"""Clinic operations views (Phase 1): appointments, reception queue, availability.

Every route is guarded by ``role_required`` + facility scoping (Step 2.6) and
writes an ``audit.AuditLog`` row for state-changing actions (addendum A.4).
Templates follow the project's Django + Bootstrap conventions under
``clinic/templates/clinic/``.
"""

from datetime import datetime, time, timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from clinic import scheduling
from clinic.models import (
    Appointment,
    Encounter,
    ProviderAvailability,
    RoomBooking,
)
from clinic.permissions import (
    accessible_facility_ids,
    facility_scope_queryset,
    facility_scoped_view,
    record_audit,
    role_required,
)
from core.models import Device, Facility
from patients.models import Patient


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
