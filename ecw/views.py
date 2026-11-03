"""Preview views for the eClinicalWorks-style UI template family.

These are *template previews only*: they reuse existing app URLs from the
shared chrome (ecw/layout.html) and render a handful of representative
screens (dashboard, patient search/chart, encounter form, worklist,
schedule, claims).  No business logic is duplicated — data comes from the
same models used by the production views where available; otherwise the
templates degrade gracefully to empty states.

Wire-up: include ``ecw.urls`` under a path prefix, e.g. in config/urls.py:

    path("ecw/", include("ecw.urls")),

Then open /ecw/dashboard/ etc. to review the look & feel before porting
the chrome into the main templates.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render


def _dash_context(request):
    """Real dashboard numbers via the production context builder."""
    from dashboard.views import get_dashboard_context

    return get_dashboard_context()


@login_required
def dashboard(request):
    """eCW 'Trends Overview' style dashboard preview."""
    return render(request, "ecw/dashboard.html", _dash_context(request))


@login_required
def patient_list(request):
    """Patient Search screen (top-bar search target)."""
    from django.db.models import Q

    from patients.models import Patient

    q = request.GET.get("q", "").strip()
    patients = Patient.objects.filter(is_deleted=False)
    if q:
        patients = patients.filter(
            Q(mrn__icontains=q)
            | Q(first_name_en__icontains=q)
            | Q(last_name_en__icontains=q)
            | Q(national_id__icontains=q)
            | Q(phone__icontains=q)
        )
    return render(
        request,
        "ecw/patient_list.html",
        {"patients": patients.order_by("last_name_en")[:100], "query": q},
    )


@login_required
def patient_chart(request, pk):
    """Patient chart banner + field groups (demographics/orders/vitals)."""
    from orders.models import ExamOrder
    from patients.models import Patient

    patient = get_object_or_404(Patient, pk=pk)
    context = {
        "patient": patient,
        "orders": ExamOrder.objects.filter(patient=patient).order_by("-created_at")[:10],
    }
    return render(request, "ecw/patient_chart.html", context)


@login_required
def encounter_form(request):
    """New Encounter / Patient Info dialog preview (static form shell)."""
    context = {"payers": []}
    try:
        from billing.models import InsurancePayer

        context["payers"] = InsurancePayer.objects.all()[:50]
    except Exception:
        pass
    return render(request, "ecw/encounter_form.html", context)


@login_required
def worklist(request):
    """Orders worklist preview reusing the production filtering logic."""
    from django.utils.dateparse import parse_date

    from orders.models import ExamOrder
    from orders.views import _orders_for_user

    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "")
    modality_filter = request.GET.get("modality", "")
    priority_filter = request.GET.get("priority", "")

    orders = _orders_for_user(request)
    if q:
        from django.db.models import Q

        orders = orders.filter(
            Q(accession_number__icontains=q)
            | Q(patient__mrn__icontains=q)
            | Q(patient__first_name_en__icontains=q)
            | Q(patient__last_name_en__icontains=q)
            | Q(procedure_name_en__icontains=q)
        )
    if status_filter:
        orders = orders.filter(status=status_filter)
    if modality_filter:
        orders = orders.filter(modality__code=modality_filter)
    if priority_filter:
        orders = orders.filter(priority=priority_filter)

    modalities = []
    try:
        from core.models import Modality

        modalities = Modality.objects.all()
    except Exception:
        pass

    context = {
        "orders": orders.select_related("patient", "modality")[:200],
        "query": q,
        "status_filter": status_filter,
        "modality_filter": modality_filter,
        "priority_filter": priority_filter,
        "status_choices": ExamOrder.Status.choices,
        "modalities": modalities,
    }
    return render(request, "ecw/worklist.html", context)


@login_required
def schedule(request):
    """Schedule tab preview: calendar + today's appointment grid."""
    from django.utils import timezone

    from clinic.models import Appointment

    today = timezone.localdate()
    appointments = (
        Appointment.objects.filter(start_datetime__date=today)
        .select_related("patient", "provider")
        .order_by("start_datetime")[:50]
    )
    return render(
        request, "ecw/schedule.html", {"appointments": appointments}
    )


@login_required
def claim_list(request):
    """Billing claims management preview."""
    from billing.models import Claim

    claims = Claim.objects.select_related(
        "patient_account", "payer"
    ).order_by("-created_at")[:100]
    return render(request, "ecw/claim_list.html", {"claims": claims})
