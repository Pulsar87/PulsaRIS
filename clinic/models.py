"""Clinic Information System models.

Implementation phases (see plan-clinicInformationSystem.prompt.md):
- Phase 0: FacilityAssignment, PatientFacilityIdentifier (foundations)
- Phase 1: ProviderAvailability, RoomBooking, Appointment (operations)
- Phase 2: Vitals, Problem, Allergy, Medication, Prescription,
           EncounterNote (clinical records)  <-- implemented here. The
           Phase 0 Encounter shell was extended with lifecycle helpers.

Phase 0 design notes (addendum B.3 / B.5):
- ``User.facility`` stays the *home/default* facility (no breaking change).
  Multi-facility coverage is expressed through ``FacilityAssignment`` rows.
- Patients remain a single shared identity; per-site chart numbers live in
  ``PatientFacilityIdentifier`` — never duplicate demographics.

Phase 2 design notes (addendum B.4):
- Clinical records are append-only where immutability matters:
  ``EncounterNote`` versions supersede one another and carry a SHA-256
  content hash plus ``prev_version_hash`` for tamper evidence. A signed
  note can never be edited or deleted (pre_save guard + admin lockdown;
  django-auditlog middleware logs any attempted change).
- django-auditlog registers every model automatically
  (AUDITLOG_INCLUDE_ALL_MODELS); the custom ``audit.AuditLog`` receives
  explicit business-event rows via ``clinic.permissions.record_audit``.
"""

import hashlib
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_save
from django.utils import timezone


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
    cancelled_at = models.DateTimeField(null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    queue_position = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Waiting-queue order within the facility; assigned at check-in.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_datetime"]
        indexes = [
            models.Index(fields=["facility", "start_datetime"]),
            models.Index(fields=["provider", "start_datetime"]),
            models.Index(fields=["status"]),
            models.Index(fields=["facility", "status", "checked_in_at"]),
        ]

    @property
    def end_datetime(self):
        from datetime import timedelta

        return self.start_datetime + timedelta(minutes=self.duration_minutes)

    # ── Phase 1 status machine (plan Step 2.5 / Verification item 2) ────
    # Allowed forward transitions; terminal states have no outgoing edges.
    TRANSITIONS = {
        Status.BOOKED: {Status.CONFIRMED, Status.CHECKED_IN, Status.CANCELLED, Status.NO_SHOW},
        Status.CONFIRMED: {Status.CHECKED_IN, Status.CANCELLED, Status.NO_SHOW},
        Status.CHECKED_IN: {Status.COMPLETED, Status.CANCELLED, Status.NO_SHOW},
        Status.COMPLETED: set(),
        Status.CANCELLED: set(),
        Status.NO_SHOW: set(),
    }

    def can_transition_to(self, new_status):
        return new_status in self.TRANSITIONS.get(self.status, set())

    def transition_to(self, new_status, *, reason="", when=None):
        """Move through the appointment lifecycle, recording metadata.

        Raises ``ValidationError`` on illegal transitions so views/services
        fail loudly instead of silently corrupting the schedule.
        """
        from django.utils import timezone as tz

        if not self.can_transition_to(new_status):
            raise ValidationError(
                f"Illegal appointment transition {self.status} -> {new_status}."
            )
        when = when or tz.now()
        self.status = new_status
        if new_status == self.Status.CHECKED_IN:
            self.checked_in_at = when
            if self.queue_position is None:
                last = (
                    Appointment.objects.filter(
                        facility_id=self.facility_id,
                        status=self.Status.CHECKED_IN,
                        queue_position__isnull=False,
                    )
                    .order_by("-queue_position")
                    .values_list("queue_position", flat=True)
                    .first()
                )
                self.queue_position = (last or 0) + 1
        elif new_status in (self.Status.CANCELLED, self.Status.NO_SHOW):
            self.cancelled_reason = reason or new_status.label
            self.cancelled_at = when
        elif new_status == self.Status.COMPLETED:
            # Stamp encounter close-out if this appointment spawned one.
            for enc in self.encounters.filter(status=Encounter.VisitStatus.IN_PROGRESS):
                enc.ended_at = when
                enc.status = Encounter.VisitStatus.COMPLETED
                enc.save(update_fields=["status", "ended_at", "updated_at"])
        self.save()

    def __str__(self):
        return f"Appointment {self.pk} - {self.patient} {self.start_datetime}"


class ProviderAvailability(models.Model):
    """Weekly-recurring provider schedule template (Phase 1, plan Step 2.1).

    One row = one repeating block (e.g. "Dr X, Mondays 09:00-13:00 at Site A").
    ``EXCEPTION`` rows override the template for a single date — day off or an
    extra clinic session. The conflict engine in ``clinic.scheduling`` reads
    these rows; appointments never store availability themselves.
    """

    class Kind(models.TextChoices):
        TEMPLATE = "TEMPLATE", "Weekly template"
        EXCEPTION = "EXCEPTION", "Single-date exception"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="availabilities",
    )
    facility = models.ForeignKey(
        "core.Facility", on_delete=models.PROTECT, related_name="provider_availabilities"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.TEMPLATE)
    # TEMPLATE rows use weekday + times; EXCEPTION rows use exception_date.
    weekday = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="0=Monday … 6=Sunday (Python weekday numbering), template rows only.",
    )
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    exception_date = models.DateField(null=True, blank=True)
    is_available = models.BooleanField(
        default=True,
        help_text="EXCEPTION rows with False block the whole day (day off / leave).",
    )
    slot_minutes = models.PositiveIntegerField(
        default=20, help_text="Default appointment length offered in this window."
    )
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["provider", "weekday", "start_time"]
        constraints = [
            models.CheckConstraint(
                name="provider_avail_template_fields",
                check=(
                    models.Q(kind="TEMPLATE", weekday__isnull=False, start_time__isnull=False)
                    | models.Q(kind="EXCEPTION", exception_date__isnull=False)
                ),
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "facility", "kind"]),
            models.Index(fields=["exception_date"]),
        ]

    def covers(self, dt):
        """True if datetime ``dt`` falls inside this availability row."""
        if self.kind == self.Kind.EXCEPTION:
            return self.exception_date == dt.date()
        if self.weekday != dt.weekday():
            return False
        t = dt.time()
        return self.start_time <= t < self.end_time

    def __str__(self):
        if self.kind == self.Kind.EXCEPTION:
            return f"{self.provider} {self.exception_date} ({'open' if self.is_available else 'off'})"
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        d = days[self.weekday] if self.weekday is not None else "?"
        return f"{self.provider} {d} {self.start_time}-{self.end_time}"


class RoomBooking(models.Model):
    """A room/station occupied over a time window (Phase 1, plan Step 2.1).

    Used by clinic appointments AND (via the scheduling adapter) radiology
    exam slots so both modules share one room-conflict source of truth.
    Bookings are soft-cancelled to preserve history.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(
        "core.Device", on_delete=models.PROTECT, related_name="bookings"
    )
    facility = models.ForeignKey(
        "core.Facility", on_delete=models.PROTECT, related_name="room_bookings"
    )
    start_datetime = models.DateTimeField(db_index=True)
    duration_minutes = models.PositiveIntegerField(default=20)
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="room_booking",
        help_text="Clinic appointment that holds this booking, if any.",
    )
    exam_order = models.OneToOneField(
        "orders.ExamOrder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="room_booking",
        help_text="Radiology order holding this booking via the scheduling adapter.",
    )
    purpose = models.CharField(max_length=100, blank=True)
    is_cancelled = models.BooleanField(default=False, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_datetime"]
        constraints = [
            models.CheckConstraint(
                name="room_booking_exactly_one_holder",
                check=(
                    models.Q(appointment__isnull=False, exam_order__isnull=True)
                    | models.Q(appointment__isnull=True, exam_order__isnull=False)
                ),
            ),
        ]
        indexes = [models.Index(fields=["room", "start_datetime", "is_cancelled"])]

    @property
    def end_datetime(self):
        from datetime import timedelta

        return self.start_datetime + timedelta(minutes=self.duration_minutes)

    def __str__(self):
        return f"Room {self.room} {self.start_datetime} +{self.duration_minutes}m"


class Encounter(models.Model):
    """Clinical encounter (Phase 0 shell, extended with lifecycle in Phase 2).

    Created in Phase 0 so `billing.ServiceLine.encounter` (addendum A.1) could
    be migrated and deployed early. Phase 2 added the lifecycle transitions
    below plus the clinical-record child models (Vitals, Problem, Allergy,
    Medication, Prescription, EncounterNote).
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
    cancellation_reason = models.CharField(max_length=100, blank=True)
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

    # ── Phase 2 lifecycle (plan Step 3 / Verification item 3) ──────────────

    ENCOUNTER_TRANSITIONS = {
        VisitStatus.PLANNED: {VisitStatus.IN_PROGRESS, VisitStatus.CANCELLED},
        VisitStatus.IN_PROGRESS: {VisitStatus.COMPLETED, VisitStatus.CANCELLED},
        VisitStatus.COMPLETED: set(),
        VisitStatus.CANCELLED: set(),
    }

    def can_transition_to(self, new_status):
        return new_status in self.ENCOUNTER_TRANSITIONS.get(self.status, set())

    def start(self, when=None):
        """PLANNED -> IN_PROGRESS; requires an assigned provider."""
        if not self.provider_id:
            raise ValidationError("Encounter needs a provider before it starts.")
        self._transition(
            self.VisitStatus.IN_PROGRESS, started_at=when or timezone.now()
        )

    def complete(self, when=None):
        """IN_PROGRESS -> COMPLETED; enforces the minimum documentation set
        (addendum E.1 default until per-specialty templates are confirmed)."""
        self.require_documentation()
        self._transition(self.VisitStatus.COMPLETED, ended_at=when or timezone.now())

    def cancel(self, reason="", when=None):
        self._transition(
            self.VisitStatus.CANCELLED, ended_at=when or timezone.now(),
            cancellation_reason=reason or "cancelled",
        )

    def _transition(self, new_status, **fields):
        if not self.can_transition_to(new_status):
            raise ValidationError(
                f"Illegal encounter transition {self.status} -> {new_status}."
            )
        self.status = new_status
        for k, v in fields.items():
            setattr(self, k, v)
        self.save(update_fields=list(fields) + ["status", "updated_at"])

    def require_documentation(self):
        """A completed encounter must carry at least one signed note and one
        vitals recording. Raises ValidationError listing what is missing."""
        missing = []
        if not self.notes.filter(signed_at__isnull=False).exists():
            missing.append("a signed encounter note")
        if not self.vitals.exists():
            missing.append("recorded vitals")
        if missing:
            raise ValidationError(
                "Cannot complete encounter — missing: " + ", ".join(missing) + "."
            )


# ── Phase 2: clinical records ─────────────────────────────────────────────
# All child records hang off Encounter and inherit its facility through the
# encounter FK; facility scoping on queries goes via encounter__facility_id
# (core.mixins.FacilityScopedQuerySet.for_facility covers direct-FK models).


class Vitals(models.Model):
    """Structured vital-signs recording (Phase 2). Numeric fields are
    nullable so partial sets are recordable without free-text hacks."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.ForeignKey(
        Encounter, on_delete=models.CASCADE, related_name="vitals"
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="vitals_recorded",
    )
    recorded_at = models.DateTimeField(default=timezone.now)
    systolic_bp = models.PositiveIntegerField(null=True, blank=True)
    diastolic_bp = models.PositiveIntegerField(null=True, blank=True)
    heart_rate = models.PositiveIntegerField(null=True, blank=True, help_text="bpm")
    respiratory_rate = models.PositiveIntegerField(null=True, blank=True, help_text="breaths/min")
    temperature_c = models.DecimalField(null=True, blank=True, max_digits=4, decimal_places=1)
    spo2_pct = models.DecimalField(null=True, blank=True, max_digits=4, decimal_places=1, help_text="%")
    height_cm = models.DecimalField(null=True, blank=True, max_digits=5, decimal_places=1)
    weight_kg = models.DecimalField(null=True, blank=True, max_digits=5, decimal_places=1)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["encounter", "recorded_at"])]

    def clean(self):
        if (self.systolic_bp is None) != (self.diastolic_bp is None):
            raise ValidationError("Blood pressure requires both systolic and diastolic values.")

    @property
    def bmi(self):
        if self.height_cm and self.weight_kg:
            m = float(self.height_cm) / 100.0
            return round(float(self.weight_kg) / (m * m), 1)
        return None

    def __str__(self):
        return f"Vitals {self.recorded_at:%Y-%m-%d %H:%M} — encounter {self.encounter_id}"


class Problem(models.Model):
    """Active/inactive problem-list entry with optional ICD-10 coding
    (addendum C Phase 2: 'ICD-10 coding column')."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        RESOLVED = "RESOLVED", "Resolved"
        HISTORY = "HISTORY", "History"
        ENTERED_IN_ERROR = "ENTERED_IN_ERROR", "Entered in error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="problems"
    )
    encounter = models.ForeignKey(
        Encounter, on_delete=models.SET_NULL, null=True, blank=True, related_name="problems"
    )
    code = models.CharField(max_length=10, blank=True, help_text="ICD-10-CM code")
    description = models.CharField(max_length=250)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    onset_date = models.DateField(null=True, blank=True)
    resolved_date = models.DateField(null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="problems_recorded",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(status__in=["RESOLVED", "HISTORY"], resolved_date__isnull=False)
                    | models.Q(resolved_date__isnull=True)
                ),
                name="%(app_label)s_%(class)s_resolved_needs_date",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.description} ({self.status})"


class Allergy(models.Model):
    """Patient allergy/intolerance record (shared identity => patient-level,
    not encounter-level; encounter records who documented it)."""

    class Severity(models.TextChoices):
        MILD = "MILD", "Mild"
        MODERATE = "MODERATE", "Moderate"
        SEVERE = "SEVERE", "Severe"

    class ReactionType(models.TextChoices):
        ALLERGIC = "ALLERGIC", "Allergic"
        INTOLERANCE = "INTOLERANCE", "Intolerance"
        UNKNOWN = "UNKNOWN", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="allergies"
    )
    substance = models.CharField(max_length=150, help_text="e.g., Penicillin, iodinated contrast")
    reaction_type = models.CharField(
        max_length=15, choices=ReactionType.choices, default=ReactionType.ALLERGIC
    )
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MODERATE)
    clinical_status = models.CharField(
        max_length=20,
        choices=[("ACTIVE", "Active"), ("CONFIRMED", "Confirmed"), ("ENTERED_IN_ERROR", "Entered in error")],
        default="ACTIVE",
    )
    notes = models.TextField(blank=True)
    documented_at = models.DateTimeField(default=timezone.now)
    documented_in = models.ForeignKey(
        Encounter, on_delete=models.SET_NULL, null=True, blank=True, related_name="allergies_documented"
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="allergies_recorded",
    )

    class Meta:
        ordering = ["substance"]
        constraints = [
            models.UniqueConstraint(
                fields=["patient", "substance", "reaction_type"],
                condition=models.Q(clinical_status__in=["ACTIVE", "CONFIRMED"]),
                name="unique_active_allergy_per_patient_substance",
            ),
        ]

    def __str__(self):
        return f"{self.substance} ({self.severity})"


class Medication(models.Model):
    """Medication history entry (current or past) for the shared patient."""

    class Status(models.TextChoices):
        CURRENT = "CURRENT", "Current"
        PAST = "PAST", "Past"
        STOPPED = "STOPPED", "Stopped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="medications"
    )
    encounter = models.ForeignKey(
        Encounter, on_delete=models.SET_NULL, null=True, blank=True, related_name="medications_documented"
    )
    name = models.CharField(max_length=200, help_text="Drug name (generic preferred)")
    dose = models.CharField(max_length=100, blank=True)
    frequency = models.CharField(max_length=100, blank=True, help_text="e.g., BID, TID, q6h")
    route = models.CharField(max_length=50, blank=True, help_text="e.g., PO, IV, SC")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CURRENT)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="medications_recorded",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} {self.dose} {self.frequency}".strip()


class Prescription(models.Model):
    """Prescription issued during an encounter.

    Addendum E.2 (e-prescribing mandates) remains open; this is an internal
    record only — no external e-Rx transmission yet.
    """

    class Status(models.TextChoices):
        ISSUED = "ISSUED", "Issued"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.ForeignKey(
        Encounter, on_delete=models.PROTECT, related_name="prescriptions"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="prescriptions"
    )
    prescriber = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="prescriptions_issued",
    )
    medication_name = models.CharField(max_length=200)
    dose = models.CharField(max_length=100)
    frequency = models.CharField(max_length=100)
    route = models.CharField(max_length=50, blank=True)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    days_supply = models.PositiveIntegerField(null=True, blank=True)
    refills_allowed = models.PositiveSmallIntegerField(default=0)
    instructions = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ISSUED)
    issued_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self):
        return f"Rx {self.medication_name} — {self.patient}"


class EncounterNote(models.Model):
    """Append-only, versioned, signable encounter note (addendum B.4).

    Invariants enforced here + by ``_guard_immutable`` pre_save hook:
    - version = max(existing)+1 per encounter; ``supersedes`` points at the
      previous version (None for v1);
    - ``content_hash`` = SHA-256 over body+author+signed_at+prev_version_hash;
    - once ``signed_at`` is set, the row is immutable (no edits, no deletes);
    - hash chain links versions so tampering with any row breaks verification.
    django-auditlog (AUDITLOG_INCLUDE_ALL_MODELS) captures every DB change;
    business events go to audit.AuditLog via clinic.permissions.record_audit.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.ForeignKey(
        Encounter, on_delete=models.CASCADE, related_name="notes"
    )
    version = models.PositiveIntegerField(default=1)
    supersedes = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="superseded_by"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="encounter_notes_authored",
    )
    body = models.TextField()
    signed_at = models.DateTimeField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, editable=False)
    prev_version_hash = models.CharField(max_length=64, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["encounter", "version"]
        constraints = [
            models.UniqueConstraint(
                fields=["encounter", "version"], name="unique_note_version_per_encounter"
            ),
        ]

    def compute_hash(self):
        payload = "|".join(
            str(x) if x is not None else ""
            for x in (self.body, self.author_id, self.signed_at.isoformat() if self.signed_at else "",
                      self.prev_version_hash)
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def next_version(self, *, body, author):
        """Create the append-only successor of this note (draft until signed).

        The predecessor must be signed first — you supersede finalized work,
        never edit drafts in place.

        ``select_for_update`` locks the *signed* predecessor row so concurrent
        amendments serialize (lock-then-insert works on Postgres & SQLite;
        locking the brand-new v1 row itself would deadlock on Postgres).
        """
        if self.signed_at is None:
            raise ValidationError("Only signed notes can be superseded; edit the draft instead.")
        EncounterNote.objects.filter(pk=self.pk).select_for_update().first()
        latest = self.encounter.notes.order_by("-version").first()
        if latest.pk != self.pk:
            raise ValidationError(
                f"Note v{self.version} is no longer the latest version "
                f"(v{latest.version} exists); amend the latest note instead."
            )
        note = EncounterNote.objects.create(
            encounter=self.encounter,
            version=latest.version + 1,
            supersedes=latest,
            author=author,
            body=body,
            prev_version_hash=latest.content_hash,
        )
        return note

    def sign(self, signing_user):
        """Authenticated signature: author check + timestamp + hash seal."""
        if self.signed_at is not None:
            raise ValidationError("Note is already signed and immutable.")
        if signing_user.pk != self.author_id:
            raise ValidationError("Only the note author may sign it.")
        self.signed_at = timezone.now()
        self.content_hash = self.compute_hash()
        self.save(update_fields=["signed_at", "content_hash", "updated_at"])
        return self

    def verify_integrity(self):
        """True iff this row's stored hash matches recomputation AND, when
        chained, the parent note's hash matches our prev_version_hash."""
        ok = bool(self.content_hash) and self.content_hash == self.compute_hash()
        if ok and self.supersedes_id:
            ok = self.supersedes.content_hash == self.prev_version_hash
        return ok

    def delete(self, *args, **kwargs):
        if self.signed_at is not None:
            raise ValidationError("Signed notes are immutable and cannot be deleted.")
        super().delete(*args, **kwargs)

    def __str__(self):
        state = "signed" if self.signed_at else "draft"
        return f"Note v{self.version} ({state}) — encounter {self.encounter_id}"


def _guard_note_immutable(sender, instance, **kwargs):
    """pre_save guard (addendum B.4): block edits to signed note rows at the
    ORM layer, not just the UI/API layer."""
    if instance.pk is None:
        return
    try:
        db = EncounterNote.objects.filter(pk=instance.pk).first()
    except Exception:
        return
    if db is not None and db.signed_at is not None:
        changed = (
            db.body != instance.body
            or db.author_id != instance.author_id
            or db.encounter_id != instance.encounter_id
            or db.version != instance.version
            or db.signed_at != instance.signed_at
            or db.content_hash != instance.content_hash
            or db.prev_version_hash != instance.prev_version_hash
        )
        if changed:
            raise ValidationError("Signed encounter notes are immutable.")


pre_save.connect(_guard_note_immutable, sender=EncounterNote)


class IntegrationEvent(models.Model):
    """Transactional outbox for interoperability events (Phase 3).

    Addendum C Phase 3: ORM post_save hooks in ``clinic.signals`` append one
    row per business event (appointment booked/cancelled/completed, encounter
    closed). Consumers (HL7 v2 / FHIR mappers) poll ``delivered_at IS NULL``;
    actual consumer wiring is deferred until pilot feedback. The outbox itself
    is append-only — updating only the delivery bookkeeping fields is allowed.
    """

    class EventType(models.TextChoices):
        APPOINTMENT_BOOKED = "APPT_BOOKED", "Appointment booked"
        APPOINTMENT_CANCELLED = "APPT_CANCELLED", "Appointment cancelled"
        APPOINTMENT_COMPLETED = "APPT_COMPLETED", "Appointment completed"
        ENCOUNTER_CLOSED = "ENCOUNTER_CLOSED", "Encounter closed"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        DELIVERED = "DELIVERED", "Delivered"
        FAILED = "FAILED", "Delivery failed (will retry)"
        DEAD_LETTER = "DEAD_LETTER", "Dead letter (max attempts exceeded)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=30, choices=EventType.choices, db_index=True)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    facility = models.ForeignKey(
        "core.Facility",
        on_delete=models.PROTECT,
        related_name="integration_events",
        null=True,
        blank=True,
    )
    entity_type = models.CharField(max_length=50)
    entity_id = models.UUIDField()
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivery_attempts = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["delivered_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} | {self.entity_type}:{self.entity_id}"


class PatientMergeLog(models.Model):
    """Append-only record of patient identity merges (Phase 4, plan Step 5.1).

    Written by ``clinic.patient_matching.merge_patients`` inside the same
    transaction as the merge itself; complements the generic AuditLog entry
    with a queryable duplicate->canonical history for site admins. Rows are
    immutable: save() after creation and delete raise unless flagged otherwise.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    duplicate = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="merge_log_as_duplicate"
    )
    canonical = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="merge_log_as_canonical"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    summary = models.JSONField(default=dict, help_text="Counts/ids from merge_patients().")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                name="merge_log_distinct_patients",
                check=models.Q(duplicate__pk__ne=models.OuterRef("canonical__pk")),
            ),
        ]
        indexes = [models.Index(fields=["duplicate"]), models.Index(fields=["canonical"])]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("PatientMergeLog rows are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("PatientMergeLog rows cannot be deleted.")

    def __str__(self):
        return f"Merged {self.duplicate_id} -> {self.canonical_id} @ {self.created_at}"
