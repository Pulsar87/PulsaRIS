"""PACS metadata mirror models (PACS plan Phase 2, Task 2.1).

These tables are a lightweight application-side mirror of the Orthanc
archive. Orthanc remains the authoritative source for actual DICOM
objects; Django never stores binary pixel data and never reads or
mutates Orthanc's private database tables (plan §1.4).

Schema strategy (Task 2.1 "review whether series/instance mirrors are
essential"): study-level rows plus per-study series/instance *counts*
are sufficient for the MVP scope (search, work queue, order linking,
study list UI). Full PACSSeries/PACSInstance expansion is deferred as
an explicit future step so we do not create a redundant schema that
mirrors every archive table. Series/instance detail remains
authoritative in the archive via Orthanc resource IDs.
"""

import uuid

from django.db import models

from pacs.dicom_uid import is_valid_dicom_uid


class StudyStatus(models.TextChoices):
    """Archive/study lifecycle states (Task 2.3).

    These describe image receipt and index/reconciliation state only.
    They NEVER imply ExamOrder completion: a CT/MR study arrives
    instance-by-instance and quiet periods are not authoritative proof
    of acquisition end (plan §1.5, Task 2.3). Order status transitions
    are a separate documented workflow (Phase 5).
    """

    RECEIVED = "RECEIVED", "Received (instances stored, metadata pending)"
    INDEXED = "INDEXED", "Indexed (metadata synced)"
    RECONCILIATION_REQUIRED = (
        "RECONCILIATION_REQUIRED",
        "Reconciliation required (unsafe or missing match)",
    )
    SYNC_ERROR = "SYNC_ERROR", "Sync error (archive exists, mirror needs attention)"
    AVAILABLE = "AVAILABLE", "Available (indexed, authorized retrieval possible)"
    INTEGRITY_CONFLICT = (
        "INTEGRITY_CONFLICT",
        "Integrity conflict (UID collision with different content)",
    )


class PACSStudy(models.Model):
    """One row per Study Instance UID held by the archive."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # --- Stable identifiers -------------------------------------------------
    study_instance_uid = models.CharField(max_length=64, unique=True)
    # Orthanc internal REST resource id for the study (e.g. "studies/...").
    orthanc_study_id = models.CharField(max_length=64, blank=True, db_index=True)

    # --- Trusted facility context -------------------------------------------
    # Ownership comes ONLY from the trusted sender→device→facility mapping
    # (plan §1.6 / Task 0.2), never from arbitrary DICOM tags. Nullable when
    # the sending device has no facility yet; such studies land in
    # reconciliation.
    facility = models.ForeignKey(
        "core.Facility",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pacs_studies",
    )
    # Device row whose calling AE title delivered the study, when known.
    sender_device = models.ForeignKey(
        "core.Device",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pacs_studies",
    )

    # --- RIS linkage ----------------------------------------------------------
    # Optional matched order. Set only through the deterministic matching
    # policy (Phase 3); manual reconciliation actions also go through the
    # service layer so conflicts are surfaced first.
    matched_order = models.ForeignKey(
        "orders.ExamOrder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pacs_studies",
    )

    # --- Patient/order identifiers AS RECEIVED (not corrected) ---------------
    patient_id_as_received = models.CharField(max_length=64, blank=True)
    accession_number = models.CharField(max_length=50, blank=True, db_index=True)
    study_date = models.DateField(null=True, blank=True)
    study_datetime = models.DateTimeField(null=True, blank=True)
    study_description = models.CharField(max_length=200, blank=True)
    referring_physician = models.CharField(max_length=150, blank=True)
    patient_name_as_received = models.CharField(max_length=200, blank=True)

    # --- Modality summary + counts (mirror; archive is authoritative) --------
    modality = models.CharField(max_length=16, blank=True)
    series_count = models.PositiveIntegerField(default=0)
    instance_count = models.PositiveIntegerField(default=0)

    # --- Workflow state --------------------------------------------------------
    status = models.CharField(
        max_length=32,
        choices=StudyStatus.choices,
        default=StudyStatus.RECEIVED,
        db_index=True,
    )
    # Machine-readable reason for RECONCILIATION_REQUIRED / SYNC_ERROR /
    # INTEGRITY_CONFLICT (no PHI beyond identifiers already mirrored here).
    status_reason = models.TextField(blank=True)

    # --- Timestamps -------------------------------------------------------------
    first_received_at = models.DateTimeField(null=True, blank=True)
    last_received_at = models.DateTimeField(null=True, blank=True)
    indexed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-study_datetime", "-created_at"]
        indexes = [
            models.Index(fields=["accession_number"], name="pacs_study_accession_idx"),
            models.Index(fields=["status", "facility"], name="pacs_study_status_facility_idx"),
            models.Index(fields=["-study_datetime"], name="pacs_study_datetime_idx"),
            models.Index(fields=["patient_id_as_received"], name="pacs_study_mrn_idx"),
        ]

    def __str__(self):
        return f"{self.study_instance_uid} [{self.status}]"

    def clean(self):
        super().clean()
        if not is_valid_dicom_uid(self.study_instance_uid):
            raise ValueError("study_instance_uid is not a valid DICOM UID")


class SyncEvent(models.Model):
    """Durable Orthanc changes-feed cursor (Task 2.2).

    A single-row-per-event log lets the worker resume after restarts at
    least-once delivery; handlers must be idempotent. Failed events keep
    their error category for operational review — exceptions are never
    silently swallowed.
    """

    class Outcome(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSED = "PROCESSED", "Processed"
        FAILED = "FAILED", "Failed"
        IGNORED = "IGNORED", "Ignored"

    # Orthanc change number (monotonic integer from /changes).
    change = models.BigIntegerField(unique=True)
    path = models.CharField(max_length=200, blank=True)
    resource_type = models.CharField(max_length=32, blank=True)
    outcome = models.CharField(
        max_length=16, choices=Outcome.choices, default=Outcome.PENDING, db_index=True
    )
    error_category = models.CharField(max_length=64, blank=True)
    error_detail = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["change"]
        indexes = [
            models.Index(fields=["outcome", "change"], name="sync_event_outcome_idx"),
        ]

    def __str__(self):
        return f"change={self.change} {self.outcome}"
