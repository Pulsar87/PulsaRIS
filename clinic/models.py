"""Clinic Information System models.

Implementation phases (see plan-clinicInformationSystem.prompt.md):
- Phase 0: FacilityAssignment, PatientFacilityIdentifier (foundations)  <-- implemented here
- Phase 1: ProviderAvailability, RoomBooking, Appointment (operations)
- Phase 2: Vitals, Problem, Allergy, Medication, Prescription,
           EncounterNote (clinical records). Encounter exists as a Phase 0
           shell (needed by billing.ServiceLine.encounter); extended in Phase 2.

Phase 0 design notes (addendum B.3 / B.5):
- ``User.facility`` stays the *home/default* facility (no breaking change).
  Multi-facility coverage is expressed through ``FacilityAssignment`` rows.
- Patients remain a single shared identity; per-site chart numbers live in
  ``PatientFacilityIdentifier`` — never duplicate demographics.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class FacilityAssignment(models.Model):
    """A staff member's active coverage at one facility under a given role.

    Addendum A.3: layered on top of ``User.facility`` (home facility); does
    not replace it. Unique per (user, facility) so history is kept by
    deactivating rows (end_date) rather than deleting them.
    """

    ROLE_CHOICES = [
        ("ADMIN", "Administrator"),
        ("PROVIDER", "Provider / Physician"),
        ("RECEPTIONIST", "Receptionist"),
        ("TECHNICIAN", "Technician"),
        ("BILLING", "Billing staff"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="facility_assignments",
    )
    facility = models.ForeignKey(
        "core.Facility", on_delete=models.PROTECT, related_name="staff_assignments"
    )
    role_at_facility = models.CharField(max_length=20, choices=ROLE_CHOICES)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)  # None = ongoing
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["facility__name", "user__email"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "facility"], name="unique_user_facility_assignment"
            ),
        ]
        indexes = [
            models.Index(fields=["facility", "is_active"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def clean(self):
        super().clean()
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError("end_date cannot precede start_date.")

    def is_current(self, on_date=None):
        """True if this assignment covers ``on_date`` (default: today)."""
        from datetime import date

        on_date = on_date or date.today()
        if not self.is_active:
            return False
        if self.start_date > on_date:
            return False
        if self.end_date and self.end_date < on_date:
            return False
        return True

    def __str__(self):
        return f"{self.user} @ {self.facility} ({self.role_at_facility})"


class PatientFacilityIdentifier(models.Model):
    """Site-specific identifier for the shared patient record (addendum B.5).

    Lets each facility keep its own MRN/chart number while ``patients.Patient``
    remains the single cross-site identity.
    """

    TYPE_CHOICES = [
        ("MRN", "Medical Record Number"),
        ("CHART", "Chart number"),
        ("NATIONAL_ID", "National ID as captured at site"),
        ("OTHER", "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="facility_identifiers"
    )
    facility = models.ForeignKey(
        "core.Facility", on_delete=models.PROTECT, related_name="patient_identifiers"
    )
    identifier = models.CharField(max_length=50)
    identifier_type = models.CharField(max_length=15, choices=TYPE_CHOICES, default="MRN")
    is_primary = models.BooleanField(
        default=True, help_text="Primary chart identifier for this patient at this site."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["facility__name", "identifier"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "identifier_type", "identifier"],
                name="unique_site_patient_identifier",
            ),
            models.UniqueConstraint(
                fields=["patient", "facility"],
                condition=models.Q(is_primary=True),
                name="unique_primary_identifier_per_site",
            ),
        ]
        indexes = [models.Index(fields=["patient", "facility"])]

    def __str__(self):
        return f"{self.patient} @ {self.facility}: {self.identifier_type} {self.identifier}"


class Appointment(models.Model):
    """Clinic appointment (Phase 1, addendum B.1/B.2).

    Part of the single availability/conflict engine: provider and room
    reservations are checked here; radiology `ExamOrder.scheduled_datetime`
    slots will reserve through the same primitives in Phase 1. The
    `Encounter.appointment` FK closes the loop visit-side; `ExamOrder` gains a
    nullable `appointment` FK on the imaging side (orders/models.py).
    """

    class Status(models.TextChoices):
        BOOKED = "BOOKED", "Booked"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CHECKED_IN = "CHECKED_IN", "Checked in"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"
        NO_SHOW = "NO_SHOW", "No show"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="appointments"
    )
    facility = models.ForeignKey(
        "core.Facility", on_delete=models.PROTECT, related_name="appointments"
    )
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="appointments_as_provider",
        null=True,
        blank=True,
    )
    department = models.CharField(max_length=100, blank=True)
    room = models.ForeignKey(
        "core.Device",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
        help_text="Room/station resource; same primitive used by exam scheduling.",
    )
    start_datetime = models.DateTimeField(db_index=True)
    duration_minutes = models.PositiveIntegerField(default=20)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.BOOKED, db_index=True
    )
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="appointments_created",
    )
    cancelled_reason = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_datetime"]
        indexes = [
            models.Index(fields=["facility", "start_datetime"]),
            models.Index(fields=["provider", "start_datetime"]),
            models.Index(fields=["status"]),
        ]

    @property
    def end_datetime(self):
        from datetime import timedelta

        return self.start_datetime + timedelta(minutes=self.duration_minutes)

    def __str__(self):
        return f"Appointment {self.pk} - {self.patient} {self.start_datetime}"


class Encounter(models.Model):
    """Minimal Phase 0 shell — full clinical lifecycle lands in Phase 2.

    Created now so `billing.ServiceLine.encounter` (addendum A.1) can be
    migrated and deployed without waiting for the rest of Phase 2. Addendum E
    open questions (required documentation set per specialty/jurisdiction) are
    resolved before extending this model with vitals/problems/notes.
    """

    class VisitStatus(models.TextChoices):
        PLANNED = "PLANNED", "Planned"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Phase 1 link: an encounter may originate from a clinic Appointment.
    # Nullable now; the reverse FK is used by the unified availability engine.
    appointment = models.ForeignKey(
        "clinic.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="encounters",
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="encounters"
    )
    facility = models.ForeignKey(
        "core.Facility", on_delete=models.PROTECT, related_name="encounters"
    )
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="encounters_as_provider",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20, choices=VisitStatus.choices, default=VisitStatus.PLANNED, db_index=True
    )
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True, help_text="Chief complaint / reason for visit.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="encounters_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["facility", "status"]),
            models.Index(fields=["patient", "started_at"]),
        ]

    def __str__(self):
        return f"Encounter {self.pk} - {self.patient} @ {self.facility} ({self.status})"
