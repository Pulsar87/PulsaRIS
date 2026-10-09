"""Unified availability / conflict engine (plan addendum B.1, Step 2.2).

ONE engine serves both modules:
- clinic appointments (``book_appointment``) and
- radiology exam slots on ``ExamOrder.scheduled_datetime`` (adapter:
  ``reserve_exam_slot`` / ``release_exam_slot``).

Conflict primitives:
- provider double-booking: overlapping active Appointments for the same
  provider; ExamOrders scheduled at the same time count as busy via their
  linked appointment or a direct slot reservation.
- room conflicts: every occupied window is a ``RoomBooking`` row (appointment
  OR exam order), so room contention has a single source of truth.
- provider availability: weekly templates + single-date exceptions
  (``ProviderAvailability``); a day-off exception blocks everything.

Cancelled/no-show appointments and cancelled bookings are ignored by all
checks. All booking operations run inside ``transaction.atomic`` with an
overlap re-check to fail loudly on races.
"""

from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from clinic.models import Appointment, ProviderAvailability, RoomBooking

ACTIVE_APPOINTMENT_STATUSES = [
    Appointment.Status.BOOKED,
    Appointment.Status.CONFIRMED,
    Appointment.Status.CHECKED_IN,
]


def _window(start, duration_minutes):
    return start, start + timedelta(minutes=duration_minutes)


def _overlaps(s1, e1, s2, e2):
    """Half-open interval overlap: touching edges (10:00 end, 10:00 start) OK."""
    return s1 < e2 and s2 < e1


# ── Availability checks ───────────────────────────────────────────────────


def provider_is_available(provider, facility, start, duration_minutes):
    """True if ``start..end`` falls in a template window (or an open
    EXCEPTION day) and no day-off exception applies."""
    end = start + timedelta(minutes=duration_minutes)
    day = timezone.localdate(start) if timezone.is_aware(start) else start.date()

    exceptions = {
        row.kind: row
        for row in ProviderAvailability.objects.filter(
            provider=provider,
            facility=facility,
            kind=ProviderAvailability.Kind.EXCEPTION,
            exception_date=day,
        )
    }
    # Explicit day-off blocks everything that day.
    for exc in exceptions.values():
        if not exc.is_available:
            return False

    # An "open" exception (extra session) can grant availability by itself.
    for exc in exceptions.values():
        if exc.is_available and exc.start_time and exc.end_time:
            win_start = timezone.make_aware(datetime.combine(day, exc.start_time)) \
                if timezone.is_naive(datetime.combine(day, exc.start_time)) \
                else datetime.combine(day, exc.start_time)
            win_end = win_start + (
                timedelta(hours=exc.end_time.hour - exc.start_time.hour,
                          minutes=exc.end_time.minute - exc.start_time.minute)
            )
            if win_start <= start and end <= win_end:
                return True

    templates = ProviderAvailability.objects.filter(
        provider=provider,
        facility=facility,
        kind=ProviderAvailability.Kind.TEMPLATE,
        weekday=day.weekday(),
    )
    for tpl in templates:
        win_start = _combine(day, tpl.start_time)
        win_end = _combine(day, tpl.end_time)
        if win_start <= start and end <= win_end:
            return True
    return False


def _combine(day, t):
    naive = datetime.combine(day, t)
    if timezone.is_aware(timezone.now()):
        return timezone.make_aware(naive)
    return naive


def find_provider_conflicts(provider, start, duration_minutes, exclude_pk=None):
    """Active appointments AND radiology slot reservations overlapping the
    window for this provider (excluding ``exclude_pk`` appointment)."""
    end = start + timedelta(minutes=duration_minutes)
    conflicts = []

    appts = Appointment.objects.filter(
        provider=provider, status__in=ACTIVE_APPOINTMENT_STATUSES
    ).exclude(pk=exclude_pk)
    busy_start = end - timedelta(days=365 * 5)  # bounded scan keeps queries sane
    for appt in appts.filter(start_datetime__gte=busy_start,
                             start_datetime__lte=end + timedelta(days=1)):
        if _overlaps(start, end, appt.start_datetime, appt.end_datetime):
            conflicts.append(("appointment", appt))

    # Radiology orders reserved through the adapter that share this
    # appointment's provider (ExamOrder has no provider FK; linkage runs
    # through order.appointment).
    exam_windows = RoomBooking.objects.filter(
        exam_order__isnull=False, is_cancelled=False,
        exam_order__appointment__provider=provider,
    ).exclude(appointment_id=exclude_pk)
    for rb in exam_windows.select_related("exam_order"):
        if _overlaps(start, end, rb.start_datetime, rb.end_datetime):
            conflicts.append(("exam_order", rb.exam_order))
    return conflicts


def find_room_conflicts(room, start, duration_minutes, *, exclude_appointment=None,
                        exclude_exam_order=None):
    end = start + timedelta(minutes=duration_minutes)
    rbs = RoomBooking.objects.filter(room=room, is_cancelled=False)
    if exclude_appointment:
        rbs = rbs.exclude(appointment_id=getattr(exclude_appointment, "pk", exclude_appointment))
    if exclude_exam_order:
        rbs = rbs.exclude(exam_order_id=getattr(exclude_exam_order, "pk", exclude_exam_order))
    hits = []
    for rb in rbs.filter(start_datetime__lt=end,
                         start_datetime__gt=start - timedelta(days=1)):
        if _overlaps(start, end, rb.start_datetime, rb.end_datetime):
            hits.append(rb)
    return hits


def check_slot(*, provider=None, room=None, facility, start, duration_minutes,
               exclude_appointment=None, exclude_exam_order=None):
    """Full pre-book validation. Raises ValidationError listing every problem."""
    errors = []
    if provider is not None:
        if not provider_is_available(provider, facility, start, duration_minutes):
            errors.append(
                f"Provider is not available at {timezone.localtime(start):%Y-%m-%d %H:%M}."
            )
        for kind, obj in find_provider_conflicts(
            provider, start, duration_minutes,
            exclude_pk=getattr(exclude_appointment, "pk", exclude_appointment),
        ):
            errors.append(f"Provider conflict with existing {kind} {obj.pk}.")
    if room is not None:
        for rb in find_room_conflicts(
            room, start, duration_minutes,
            exclude_appointment=exclude_appointment, exclude_exam_order=exclude_exam_order,
        ):
            errors.append(f"Room conflict with booking {rb.pk}.")
    if errors:
        raise ValidationError(errors)
    return True


def find_free_slots(*, provider, facility, day, slot_minutes=None):
    """Suggest open windows for a provider on a date (reception UI helper)."""
    free = []
    templates = ProviderAvailability.objects.filter(
        provider=provider, facility=facility,
        kind=ProviderAvailability.Kind.TEMPLATE, weekday=day.weekday(),
    )
    exceptions = list(ProviderAvailability.objects.filter(
        provider=provider, facility=facility,
        kind=ProviderAvailability.Kind.EXCEPTION, exception_date=day,
    ))
    if any(not e.is_available for e in exceptions):
        return free
    windows = [(tpl.start_time, tpl.end_time, tpl.slot_minutes) for tpl in templates]
    windows += [(e.start_time, e.end_time, e.slot_minutes) for e in exceptions
                if e.is_available and e.start_time and e.end_time]
    for st, en, sm in windows:
        step = slot_minutes or sm or 20
        cursor = _combine(day, st)
        stop = _combine(day, en)
        while cursor + timedelta(minutes=step) <= stop:
            try:
                check_slot(provider=provider, facility=facility,
                           start=cursor, duration_minutes=step)
                free.append(cursor)
            except ValidationError:
                pass
            cursor += timedelta(minutes=step)
    return free


# ── Booking operations ────────────────────────────────────────────────────


@transaction.atomic
def book_appointment(*, patient, facility, start, duration_minutes=20, provider=None,
                     room=None, department="", reason="", created_by=None,
                     provider_id=None, room_id=None):
    """Validate against the engine, then create Appointment (+ RoomBooking)."""
    if provider_id and provider is None:
        from django.contrib.auth import get_user_model

        provider = get_user_model().objects.get(pk=provider_id)
    if room_id and room is None:
        from core.models import Device

        room = Device.objects.get(pk=room_id)
    check_slot(provider=provider, room=room, facility=facility,
               start=start, duration_minutes=duration_minutes)
    appt = Appointment.objects.create(
        patient=patient, facility=facility, provider=provider, room=room,
        department=department, start_datetime=start,
        duration_minutes=duration_minutes, reason=reason, created_by=created_by,
    )
    if room is not None:
        RoomBooking.objects.create(
            room=room, facility=facility, start_datetime=start,
            duration_minutes=duration_minutes, appointment=appt,
            purpose="clinic appointment", created_by=created_by,
        )
    return appt


@transaction.atomic
def reschedule_appointment(appt, *, new_start, new_duration=None, new_room=None,
                           new_provider=None):
    """Move an appointment; re-runs the full conflict check before saving."""
    if appt.status not in ACTIVE_APPOINTMENT_STATUSES:
        raise ValidationError("Only active appointments can be rescheduled.")
    duration = new_duration or appt.duration_minutes
    provider = new_provider or appt.provider
    room = new_room if new_room is not None else appt.room
    check_slot(provider=provider, room=room, facility=appt.facility,
               start=new_start, duration_minutes=duration,
               exclude_appointment=appt,
               exclude_exam_order=None)
    appt.start_datetime = new_start
    appt.duration_minutes = duration
    appt.provider = provider
    appt.room = room
    appt.save()
    rb = getattr(appt, "room_booking", None)
    if rb:
        rb.start_datetime = new_start
        rb.duration_minutes = duration
        rb.room = room
        rb.save()
    elif room is not None:
        RoomBooking.objects.create(
            room=room, facility=appt.facility, start_datetime=new_start,
            duration_minutes=duration, appointment=appt, purpose="clinic appointment",
        )
    return appt


@transaction.atomic
def release_appointment_room(appt):
    rb = getattr(appt, "room_booking", None)
    if rb and not rb.is_cancelled:
        rb.is_cancelled = True
        rb.save(update_fields=["is_cancelled"])


def cancel_appointment(appt, *, reason=""):
    """Status-machine cancel + free the room hold."""
    appt.transition_to(Appointment.Status.CANCELLED, reason=reason)
    release_appointment_room(appt)
    return appt


def no_show_appointment(appt):
    appt.transition_to(Appointment.Status.NO_SHOW)
    release_appointment_room(appt)
    return appt


def check_in_appointment(appt):
    """Check in and open (or reuse) the encounter for this visit."""
    from clinic.models import Encounter

    appt.transition_to(Appointment.Status.CHECKED_IN)
    enc, created = Encounter.objects.get_or_create(
        appointment=appt,
        defaults={"patient": appt.patient, "facility": appt.facility,
                  "provider": appt.provider, "status": Encounter.VisitStatus.IN_PROGRESS,
                  "started_at": appt.checked_in_at, "reason": appt.reason},
    )
    if created or enc.status == Encounter.VisitStatus.PLANNED:
        enc.status = Encounter.VisitStatus.IN_PROGRESS
        enc.started_at = enc.started_at or appt.checked_in_at
        enc.save(update_fields=["status", "started_at"])
    return appt, enc


# ── Radiology adapter (addendum B.1: RIS keeps its own fields) ────────────


@transaction.atomic
def reserve_exam_slot(order, *, start, duration_minutes=None, room=None):
    """Reserve provider/room capacity for an ExamOrder through the SAME engine.

    Writes back ``scheduled_datetime`` / ``room_station`` / ``duration_minutes``
    (semantics unchanged per finding A.2) and creates a RoomBooking when a
    room is given. Called from order scheduling views; raises ValidationError
    with the conflict list on failure.
    """
    duration = duration_minutes or order.duration_minutes
    room = room or order.room_station
    # Performing provider, if the order carries a clinic appointment.
    provider = getattr(order, "appointment", None) and order.appointment.provider
    check_slot(provider=provider, room=room, facility=order.facility,
               start=start, duration_minutes=duration, exclude_exam_order=order)
    order.scheduled_datetime = start
    order.duration_minutes = duration
    if room is not None:
        order.room_station = room
    order.status = order.Status.SCHEDULED
    order.save()
    rb = getattr(order, "room_booking", None)
    if room is not None:
        if rb:
            rb.start_datetime = start
            rb.duration_minutes = duration
            rb.room = room
            rb.is_cancelled = False
            rb.save()
        else:
            RoomBooking.objects.create(
                room=room, facility=order.facility, start_datetime=start,
                duration_minutes=duration, exam_order=order, purpose="radiology exam",
                created_by=order.created_by,
            )
    return order


@transaction.atomic
def release_exam_slot(order):
    """Soft-cancel the order's room hold (on cancel/reschedule-away)."""
    rb = getattr(order, "room_booking", None)
    if rb and not rb.is_cancelled:
        rb.is_cancelled = True
        rb.save(update_fields=["is_cancelled"])


@transaction.atomic
def create_referral(*, encounter, patient, facility, modality, procedure_code,
                    procedure_name_en, clinical_indication="", priority="ROUTINE",
                    body_part="", created_by=None, book_at=None, room=None):
    """Referral capture (Step 2.3): ExamOrder linked back to the encounter's
    appointment, optionally booked into the shared engine immediately."""
    from orders.models import ExamOrder

    order = ExamOrder.objects.create(
        patient=patient, facility=facility,
        accession_number=_next_accession(facility),
        modality=modality, procedure_code=procedure_code,
        procedure_name_en=procedure_name_en,
        clinical_indication=clinical_indication or encounter.reason,
        body_part=body_part, priority=priority,
        appointment=encounter.appointment, created_by=created_by,
    )
    if book_at is not None:
        reserve_exam_slot(order, start=book_at, room=room)
    return order


def _next_accession(facility):
    from orders.models import ExamOrder

    stamp = timezone.now().strftime("%y%m%d%H%M%S%f")
    acc = f"{facility.pk.hex[:4] if hasattr(facility.pk, 'hex') else str(facility.pk)[:4]}-{stamp}"
    while ExamOrder.objects.filter(accession_number=acc).exists():
        acc += "X"
    return acc


# ── Phase 2: encounter lifecycle & clinical-record services ───────────────
# Views call these so business rules (documentation minimums, note signing,
# append-only versioning) live in ONE place; every mutation writes an
# audit.AuditLog business-event row (addendum A.4 — django-auditlog already
# captures the model-level change via middleware).


@transaction.atomic
def start_encounter(encounter, *, actor=None):
    """PLANNED -> IN_PROGRESS (requires provider)."""
    encounter.start()
    from clinic.permissions import record_audit_service

    record_audit_service(
        "CLINIC_ENC_START", entity_type="Encounter", entity_id=encounter.pk,
        user=actor, new={"status": encounter.status},
    )
    return encounter


@transaction.atomic
def complete_encounter(encounter, *, actor=None):
    """IN_PROGRESS -> COMPLETED after enforcing the documentation minimum."""
    encounter.complete()
    from clinic.permissions import record_audit_service

    record_audit_service(
        "CLINIC_ENC_COMPLETE", entity_type="Encounter", entity_id=encounter.pk,
        user=actor, new={"status": encounter.status},
    )
    return encounter


@transaction.atomic
def cancel_encounter(encounter, *, reason="", actor=None):
    encounter.cancel(reason=reason)
    from clinic.permissions import record_audit_service

    record_audit_service(
        "CLINIC_ENC_CANCEL", entity_type="Encounter", entity_id=encounter.pk,
        user=actor, old={"status": "IN_PROGRESS"}, new={"status": encounter.status, "reason": reason},
    )
    return encounter


@transaction.atomic
def sign_note(note, *, signing_user):
    """Seal a note version: author check + timestamp + SHA-256 hash (B.4)."""
    note.sign(signing_user)
    from clinic.permissions import record_audit_service

    record_audit_service(
        "CLINIC_NOTE_SIGN", entity_type="EncounterNote", entity_id=note.pk,
        user=signing_user, new={"version": note.version, "hash": note.content_hash},
    )
    return note


@transaction.atomic
def amend_note(note, *, body, author):
    """Append-only amendment: supersede a signed note with a new draft version."""
    new_note = note.next_version(body=body, author=author)
    from clinic.permissions import record_audit_service

    record_audit_service(
        "CLINIC_NOTE_AMEND", entity_type="EncounterNote", entity_id=new_note.pk,
        user=author, old={"superseded_version": note.version},
        new={"version": new_note.version, "supersedes": str(note.pk)},
    )
    return new_note


@transaction.atomic
def bill_encounter_service(encounter, *, code, name, unit_price, rendering_provider=None,
                           quantity=1, service_date=None, created_by=None):
    """Create a ServiceLine sourced from the Encounter (plan Step 4 /
    Verification item 4). Reuses the existing PatientAccount abstraction;
    does not touch the RIS exam-order billing path."""
    from datetime import date as _date

    from billing.models import PatientAccount, ServiceLine

    account, _ = PatientAccount.objects.get_or_create(
        patient=encounter.patient,
        defaults={"account_number": f"PA-{encounter.patient.mrn}"},
    )
    line = ServiceLine.objects.create(
        encounter=encounter,
        patient_account=account,
        service_date=service_date or _date.today(),
        procedure_code=code,
        procedure_name=name,
        quantity=quantity,
        unit_price=unit_price,
        total_charge=unit_price * quantity,
        rendering_provider=rendering_provider,
        facility=encounter.facility,
    )
    from clinic.permissions import record_audit_service

    record_audit_service(
        "CLINIC_ENC_CHARGE", entity_type="ServiceLine", entity_id=line.pk,
        user=created_by, new={"encounter": str(encounter.pk), "code": code,
                              "total": str(line.total_charge)},
    )
    return line
