"""Clinic operations views (Phase 1): appointments, reception queue, availability.

Every route is guarded by ``role_required`` + facility scoping (Step 2.6) and
writes an ``audit.AuditLog`` row for state-changing actions (addendum A.4).
Templates follow the project's Django + Bootstrap conventions under
``clinic/templates/clinic/``.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from clinic import scheduling
from clinic.models import (
    Allergy,
    Appointment,
    Encounter,
    EncounterNote,
    FacilityAssignment,
    Medication,
    Problem,
    ProviderAvailability,
    RoomBooking,
    Vitals,
)
from clinic.permissions import (
    accessible_facility_ids,
    facility_scope_queryset,
    facility_scoped_view,
    gated_detail_view,
    gated_note_view,
    has_facility_access,
    record_audit,
    role_required,
)
from core.models import Device, Facility
from orders.models import ExamOrder
from patients.models import Patient
from reports.models import Report


def _facility_choices(user):
    ids = accessible_facility_ids(user)
    qs = Facility.objects.all()
    if ids is not None:
        qs = qs.filter(pk__in=ids)
    return qs


# ── Appointments ───────────────────────────────────────────────────────────


@role_required("RECEPTIONIST", "PROVIDER", "ADMIN")
def appointment_list(request):
    """Day board of appointments scoped to the user's facilities."""
    date_str = request.GET.get("date") or timezone.localdate().isoformat()
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        day = timezone.localdate()
    start = timezone.make_aware(datetime.combine(day, time.min))
    end = start + timedelta(days=1)
    appts = facility_scope_queryset(
        request.user,
        Appointment.objects.select_related("patient", "provider", "room", "facility"),
    ).filter(start_datetime__gte=start, start_datetime__lt=end)
    return render(
        request,
        "clinic/appointment_list.html",
        {"appointments": appts, "day": day, "facilities": _facility_choices(request.user)},
    )


@role_required("RECEPTIONIST", "ADMIN")
@facility_scoped_view
def appointment_new(request):
    """Book form + conflict-checked creation through the shared engine."""
    facilities = _facility_choices(request.user)
    if request.method == "POST":
        fid = request.POST.get("facility")
        patient_id = request.POST.get("patient")
        provider_id = request.POST.get("provider") or None
        room_id = request.POST.get("room") or None
        start_str = request.POST.get("start_datetime")  # "YYYY-MM-DD HH:MM"
        duration = int(request.POST.get("duration_minutes") or 20)
        facility = get_object_or_404(facilities, pk=fid)
        patient = get_object_or_404(Patient, pk=patient_id)
        try:
            naive = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
            start = timezone.make_aware(naive)
        except (ValueError, TypeError):
            messages.error(request, "Provide start time as YYYY-MM-DD HH:MM.")
            return redirect("clinic:appointment_new")
        try:
            provider = None
            if provider_id:
                from django.contrib.auth import get_user_model
                provider = get_object_or_404(get_user_model(), pk=provider_id)
            room = get_object_or_404(Device, pk=room_id) if room_id else None
            appt = scheduling.book_appointment(
                patient=patient, facility=facility, start=start,
                duration_minutes=duration, provider=provider,
                room=room, department=request.POST.get("department", ""),
                reason=request.POST.get("reason", ""), created_by=request.user,
            )
        except ValidationError as exc:
            for e in exc.messages:
                messages.error(request, e)
            return redirect("clinic:appointment_new")
        record_audit(request, "CLINIC_APPT_BOOK", entity_type="Appointment",
                     entity_id=appt.pk, new={"start": str(start), "patient": str(patient.pk)})
        messages.success(request, f"Appointment booked for {patient.full_name_display if hasattr(patient, 'full_name_display') else patient}.")
        return redirect("clinic:appointment_detail", pk=appt.pk)
    return render(
        request,
        "clinic/appointment_form.html",
        {
            "facilities": facilities,
            "patients": Patient.objects.filter(is_deleted=False)[:500],
            "devices": Device.objects.filter(is_active=True),
        },
    )


@role_required("RECEPTIONIST", "PROVIDER", "ADMIN")
@gated_detail_view(Appointment)
def appointment_detail(request, pk):
    appt = get_object_or_404(
        facility_scope_queryset(
            request.user,
            Appointment.objects.select_related("patient", "provider", "room", "facility"),
        ),
        pk=pk,
    )
    return render(request, "clinic/appointment_detail.html", {"appointment": appt})


@role_required("RECEPTIONIST", "ADMIN")
@gated_detail_view(Appointment)
def appointment_action(request, pk, action):
    """Status transitions + reschedule via the engine (Step 2.5 / Verification 2)."""
    appt = get_object_or_404(
        facility_scope_queryset(request.user, Appointment.objects.all()), pk=pk
    )
    old_status = appt.status
    try:
        if action == "confirm":
            appt.transition_to(Appointment.Status.CONFIRMED)
        elif action == "checkin":
            appt, enc = scheduling.check_in_appointment(appt)
            record_audit(request, "CLINIC_ENCOUNTER_OPEN", entity_type="Encounter",
                         entity_id=enc.pk, new={"status": enc.status})
        elif action == "cancel":
            scheduling.cancel_appointment(
                appt, reason=request.POST.get("reason", "") or "cancelled"
            )
        elif action == "noshow":
            scheduling.no_show_appointment(appt)
        elif action == "complete":
            appt.transition_to(Appointment.Status.COMPLETED)
        elif action == "reschedule":
            start_str = request.POST.get("start_datetime")
            naive = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
            scheduling.reschedule_appointment(appt, new_start=timezone.make_aware(naive))
        else:
            messages.error(request, "Unknown action.")
            return redirect("clinic:appointment_detail", pk=appt.pk)
    except (ValidationError, TypeError, ValueError) as exc:
        errs = getattr(exc, "messages", None) or [str(exc)]
        for e in errs:
            messages.error(request, e)
        return redirect("clinic:appointment_detail", pk=appt.pk)
    record_audit(request, f"CLINIC_APPT_{action.upper()}", entity_type="Appointment",
                 entity_id=appt.pk, old={"status": old_status}, new={"status": appt.status})
    messages.success(request, f"Appointment {action}ed." if not action.endswith("e") else f"Appointment {action}d.")
    return redirect("clinic:appointment_detail", pk=appt.pk)


# ── Reception queue (Step 2.4) ─────────────────────────────────────────────


@role_required("RECEPTIONIST", "PROVIDER", "ADMIN")
def reception_queue(request):
    """Waiting list: checked-in appointments ordered by queue_position."""
    appts = facility_scope_queryset(
        request.user,
        Appointment.objects.select_related("patient", "provider", "room"),
    ).filter(status=Appointment.Status.CHECKED_IN).order_by("queue_position")
    encounters = facility_scope_queryset(
        request.user,
        Encounter.objects.select_related("patient", "provider"),
    ).filter(status=Encounter.VisitStatus.IN_PROGRESS)
    return render(
        request,
        "clinic/reception_queue.html",
        {"queue": appts, "in_progress": encounters},
    )


# ── Availability management (Step 2.1 UI) ──────────────────────────────────


@role_required("PROVIDER", "ADMIN")
def availability_list(request):
    rows = facility_scope_queryset(
        request.user,
        ProviderAvailability.objects.select_related("provider", "facility"),
    )
    return render(
        request,
        "clinic/availability_list.html",
        {"rows": rows, "facilities": _facility_choices(request.user),
         "weekday_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]},
    )


@role_required("PROVIDER", "ADMIN")
@facility_scoped_view
def availability_add(request):
    if request.method == "POST":
        kind = request.POST.get("kind", "TEMPLATE")
        provider_id = request.POST.get("provider")
        facility = get_object_or_404(_facility_choices(request.user),
                                     pk=request.POST.get("facility"))
        row = ProviderAvailability(
            provider_id=provider_id or request.user.pk,
            facility=facility, kind=kind,
            slot_minutes=int(request.POST.get("slot_minutes") or 20),
            note=request.POST.get("note", ""),
        )
        if kind == ProviderAvailability.Kind.EXCEPTION:
            row.exception_date = datetime.strptime(
                request.POST.get("exception_date"), "%Y-%m-%d"
            ).date()
            row.is_available = request.POST.get("is_available") == "on"
            if request.POST.get("start_time"):
                row.start_time = datetime.strptime(
                    request.POST["start_time"], "%H:%M").time()
                row.end_time = datetime.strptime(
                    request.POST["end_time"], "%H:%M").time()
        else:
            row.weekday = int(request.POST.get("weekday"))
            row.start_time = datetime.strptime(
                request.POST["start_time"], "%H:%M").time()
            row.end_time = datetime.strptime(
                request.POST["end_time"], "%H:%M").time()
        row.save()
        record_audit(request, "CLINIC_AVAIL_ADD", entity_type="ProviderAvailability",
                     entity_id=row.pk, new={"kind": kind})
        messages.success(request, "Availability saved.")
        return redirect("clinic:availability_list")
    return render(
        request,
        "clinic/availability_form.html",
        {"facilities": _facility_choices(request.user),
         "weekday_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]},
    )


# ── JSON API used by forms (free-slot suggestions) ─────────────────────────


@role_required("RECEPTIONIST", "PROVIDER", "ADMIN")
def free_slots_api(request):
    from django.http import JsonResponse

    provider_id = request.GET.get("provider")
    date_str = request.GET.get("date")
    facility_id = request.GET.get("facility")
    if not (provider_id and date_str and facility_id):
        return JsonResponse({"error": "provider, date, facility required"}, status=400)
    if not accessible_facility_ids(request.user) is None and \
       facility_id not in {str(x) for x in accessible_facility_ids(request.user)}:
        return JsonResponse({"error": "no access"}, status=403)
    day = datetime.strptime(date_str, "%Y-%m-%d").date()
    from django.contrib.auth import get_user_model
    from core.models import Facility as F

    provider = get_object_or_404(get_user_model(), pk=provider_id)
    facility = get_object_or_404(F, pk=facility_id)
    slots = scheduling.find_free_slots(provider=provider, facility=facility, day=day)
    return JsonResponse({"slots": [timezone.localtime(s).strftime("%Y-%m-%d %H:%M")
                                   for s in slots]})


# ── Phase 2: encounters & clinical records ────────────────────────────────


@role_required("PROVIDER", "RECEPTIONIST", "ADMIN")
def encounter_list(request):
    encs = facility_scope_queryset(
        request.user,
        Encounter.objects.select_related("patient", "facility", "provider"),
    )
    status = request.GET.get("status")
    if status:
        encs = encs.filter(status=status)
    fid = request.GET.get("facility")
    if fid:
        encs = encs.filter(facility_id=fid)
    return render(
        request, "clinic/encounter_list.html",
        {"encounters": encs[:200], "statuses": Encounter.VisitStatus.choices,
         "facilities": _facility_choices(request.user)},
    )


@role_required("PROVIDER", "RECEPTIONIST", "ADMIN")
@gated_detail_view(Encounter)
def encounter_detail(request, pk):
    enc = get_object_or_404(
        facility_scope_queryset(request.user, Encounter.objects.all()), pk=pk,
    )
    notes = enc.notes.select_related("author", "supersedes").order_by("-version")
    context = {
        "encounter": enc,
        "vitals": enc.vitals.all(),
        "problems": Problem.objects.filter(patient=enc.patient),
        "allergies": Allergy.objects.filter(patient=enc.patient),
        "medications": Medication.objects.filter(patient=enc.patient),
        "prescriptions": enc.prescriptions.all(),
        "notes": notes,
        "service_lines": enc.service_lines.all(),
        "exam_orders": ExamOrder.objects.filter(appointment=enc.appointment)
        if enc.appointment_id else ExamOrder.objects.none(),
        "reports": Report.objects.filter(order__in=ExamOrder.objects.filter(
            appointment=enc.appointment)) if enc.appointment_id else Report.objects.none(),
    }
    return render(request, "clinic/encounter_detail.html", context)


@role_required("PROVIDER", "RECEPTIONIST", "ADMIN")
@facility_scoped_view
def encounter_new(request):
    """Open an encounter directly (walk-in / no-appointment path).

    Addendum E.3 default: receptionists may create PLANNED encounters without
    a provider; only providers/admins can start one (enforced by the model).
    """
    facilities = _facility_choices(request.user)
    if request.method == "POST":
        patient = get_object_or_404(Patient, pk=request.POST.get("patient"))
        facility = get_object_or_404(facilities, pk=request.POST.get("facility"))
        provider_id = request.POST.get("provider")
        provider = None
        if provider_id:
            from django.contrib.auth import get_user_model

            provider = get_object_or_404(get_user_model(), pk=provider_id)
        enc = Encounter.objects.create(
            patient=patient, facility=facility, provider=provider,
            reason=request.POST.get("reason", ""), created_by=request.user,
        )
        record_audit(request, "CLINIC_ENC_CREATE", entity_type="Encounter",
                     entity_id=enc.pk, new={"patient": str(patient.pk),
                                            "facility": str(facility.pk)})
        messages.success(request, "Encounter created.")
        return redirect("clinic:encounter_detail", pk=enc.pk)
    return render(
        request, "clinic/encounter_form.html",
        {"facilities": facilities,
         "patients": Patient.objects.filter(is_deleted=False)[:500]},
    )


@role_required("PROVIDER", "ADMIN")
@gated_detail_view(Encounter)
def encounter_action(request, pk, action):
    """Lifecycle actions: start / complete / cancel (Phase 2 services)."""
    enc = get_object_or_404(facility_scope_queryset(request.user, Encounter.objects.all()), pk=pk)
    try:
        if action == "start":
            scheduling.start_encounter(enc, actor=request.user)
        elif action == "complete":
            scheduling.complete_encounter(enc, actor=request.user)
        elif action == "cancel":
            scheduling.cancel_encounter(
                enc, reason=request.POST.get("reason", ""), actor=request.user)
        else:
            messages.error(request, "Unknown action.")
            return redirect("clinic:encounter_detail", pk=enc.pk)
        messages.success(request, f"Encounter {action} succeeded.")
    except ValidationError as exc:
        for e in exc.messages:
            messages.error(request, e)
    return redirect("clinic:encounter_detail", pk=enc.pk)


@role_required("PROVIDER", "ADMIN")
@gated_detail_view(Encounter)
def vitals_add(request, pk):
    enc = get_object_or_404(facility_scope_queryset(request.user, Encounter.objects.all()), pk=pk)
    if request.method == "POST":
        def num(name):
            v = request.POST.get(name)
            return v if v not in (None, "") else None
        try:
            v = Vitals.objects.create(
                encounter=enc, recorded_by=request.user,
                systolic_bp=num("systolic_bp"), diastolic_bp=num("diastolic_bp"),
                heart_rate=num("heart_rate"), respiratory_rate=num("respiratory_rate"),
                temperature_c=num("temperature_c"), spo2_pct=num("spo2_pct"),
                height_cm=num("height_cm"), weight_kg=num("weight_kg"),
                notes=request.POST.get("notes", ""),
            )
            v.clean()
            record_audit(request, "CLINIC_VITALS_ADD", entity_type="Vitals",
                         entity_id=v.pk, new={"encounter": str(enc.pk)})
            messages.success(request, "Vitals recorded.")
        except (ValidationError, ValueError) as exc:
            msgs = getattr(exc, "messages", [str(exc)])
            for e in msgs:
                messages.error(request, e)
    return redirect("clinic:encounter_detail", pk=enc.pk)


@role_required("PROVIDER", "ADMIN")
@gated_detail_view(Encounter)
def note_create(request, pk):
    """Draft a new note version. Editing an *unsigned* draft happens here too
    (newest draft is replaced); signed notes are amended via note_amend."""
    enc = get_object_or_404(facility_scope_queryset(request.user, Encounter.objects.all()), pk=pk)
    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        if not body:
            messages.error(request, "Note body is required.")
        else:
            latest = enc.notes.order_by("-version").first()
            if latest and latest.signed_at is None:
                # still a draft — edit in place (drafts are mutable)
                latest.body = body
                latest.save(update_fields=["body", "updated_at"])
                note = latest
            else:
                next_v = (latest.version + 1) if latest else 1
                note = EncounterNote.objects.create(
                    encounter=enc, version=next_v, supersedes=latest,
                    author=request.user, body=body,
                    prev_version_hash=latest.content_hash if latest else "",
                )
            record_audit(request, "CLINIC_NOTE_SAVE", entity_type="EncounterNote",
                         entity_id=note.pk, new={"version": note.version})
            messages.success(request, "Note draft saved.")
    return redirect("clinic:encounter_detail", pk=enc.pk)


@role_required("PROVIDER", "ADMIN")
@gated_note_view(EncounterNote)
def note_sign(request, pk):
    note = get_object_or_404(EncounterNote.objects.select_related("encounter"), pk=pk)
    if not has_facility_access(request.user, note.encounter.facility_id):
        raise PermissionDenied
    try:
        scheduling.sign_note(note, signing_user=request.user)
        messages.success(request, "Note signed and sealed.")
    except ValidationError as exc:
        for e in exc.messages:
            messages.error(request, e)
    return redirect("clinic:encounter_detail", pk=note.encounter_id)


@role_required("PROVIDER", "ADMIN")
@gated_note_view(EncounterNote)
def note_amend(request, pk):
    """Append-only amendment of a signed note (Verification item 3)."""
    note = get_object_or_404(EncounterNote.objects.select_related("encounter"), pk=pk)
    if not has_facility_access(request.user, note.encounter.facility_id):
        raise PermissionDenied
    if request.method == "POST":
        try:
            new_note = scheduling.amend_note(
                note, body=request.POST.get("body", "").strip(), author=request.user)
            messages.success(request, f"Amendment v{new_note.version} drafted — sign it to finalize.")
        except ValidationError as exc:
            for e in exc.messages:
                messages.error(request, e)
    return redirect("clinic:encounter_detail", pk=note.encounter_id)


@role_required("PROVIDER", "ADMIN")
@gated_detail_view(Encounter)
def referral_from_encounter(request, pk):
    """Create an imaging ExamOrder from the encounter (plan Step 4 / original
    Step 3 referral capture) through the shared engine."""
    enc = get_object_or_404(facility_scope_queryset(request.user, Encounter.objects.all()), pk=pk)
    if request.method == "POST":
        from core.models import Modality

        try:
            modality = get_object_or_404(Modality, code=request.POST.get("modality"))
            order = scheduling.create_referral(
                encounter=enc, patient=enc.patient, facility=enc.facility,
                modality=modality,
                procedure_code=request.POST.get("procedure_code", ""),
                procedure_name_en=request.POST.get("procedure_name", ""),
                clinical_indication=request.POST.get("clinical_indication", ""),
                priority=request.POST.get("priority", "ROUTINE"),
                body_part=request.POST.get("body_part", ""),
                created_by=request.user,
            )
            record_audit(request, "CLINIC_REFERRAL", entity_type="ExamOrder",
                         entity_id=order.pk, new={"encounter": str(enc.pk),
                                                  "accession": order.accession_number})
            messages.success(request, f"Referral {order.accession_number} created.")
        except ValidationError as exc:
            for e in exc.messages:
                messages.error(request, e)
    return redirect("clinic:encounter_detail", pk=enc.pk)


@role_required("PROVIDER", "ADMIN")
@gated_detail_view(Encounter)
def encounter_charge(request, pk):
    """Bill a clinic service on the encounter (encounter -> ServiceLine)."""
    enc = get_object_or_404(facility_scope_queryset(request.user, Encounter.objects.all()), pk=pk)
    if request.method == "POST":
        try:
            line = scheduling.bill_encounter_service(
                enc,
                code=request.POST.get("procedure_code", ""),
                name=request.POST.get("procedure_name", ""),
                unit_price=Decimal(request.POST.get("unit_price", "0")),
                rendering_provider=enc.provider,
                created_by=request.user,
            )
            messages.success(request, f"Charge {line.procedure_code} added to account.")
        except (ValidationError, ValueError) as exc:
            msgs = getattr(exc, "messages", [str(exc)])
            for e in msgs:
                messages.error(request, e)
    return redirect("clinic:encounter_detail", pk=enc.pk)
