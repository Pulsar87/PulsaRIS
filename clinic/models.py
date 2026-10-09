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
