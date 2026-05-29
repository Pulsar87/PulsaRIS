from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from orders.models import ExamOrder
from patients.views import get_tenant
from tenants.models import Modality, Device


def reserve_order(request):
    """Handle order reservation page and form submission."""
    tenant = get_tenant(request)
    
    # Get active modalities and devices for this tenant
    modalities = []
    devices = []
    
    if tenant:
        modalities = Modality.objects.filter(tenant=tenant, is_active=True).order_by('code')
        devices = Device.objects.filter(tenant=tenant, is_active=True).select_related('modality').order_by('name')
    
    context = {
        'modalities': modalities,
        'devices': devices,
    }
    
    if request.method == "POST":
        # Get form data
        patient_mrn = request.POST.get("patient_mrn", "").strip()
        accession_number = request.POST.get("accession_number", "").strip()
        priority = request.POST.get("priority", "ROUTINE")
        modality_id = request.POST.get("modality", "")
        procedure_code = request.POST.get("procedure_code", "").strip()
        procedure_name_en = request.POST.get("procedure_name_en", "").strip()
        procedure_name_ar = request.POST.get("procedure_name_ar", "").strip()
        referring_physician = request.POST.get("referring_physician", "").strip()
        laterality = request.POST.get("laterality", "")
        body_part = request.POST.get("body_part", "").strip()
        contrast_required = request.POST.get("contrast_required") == "on"
        clinical_indication = request.POST.get("clinical_indication", "").strip()
        scheduled_datetime = request.POST.get("scheduled_datetime", "")
        duration_minutes = request.POST.get("duration_minutes", 15)
        room_station_id = request.POST.get("room_station", "")

        # Basic validation
        if not patient_mrn:
            messages.error(request, _("Please enter a valid MRN"))
            return redirect("orders:reserve_order")

        if not accession_number:
            messages.error(request, _("Accession number is required"))
            return redirect("orders:reserve_order")

        if not modality_id:
            messages.error(request, _("Please select a modality"))
            return redirect("orders:reserve_order")

        if not procedure_code or not procedure_name_en:
            messages.error(request, _("Procedure code and name are required"))
            return redirect("orders:reserve_order")

        # TODO: Add logic to create the ExamOrder
        # This would involve:
        # 1. Looking up the patient by MRN
        # 2. Getting the tenant from the request
        # 3. Creating the ExamOrder instance

        messages.success(request, _("Order reserved successfully!"))
        return redirect("orders:worklist")

    return render(request, "orders/reserve_order.html", context)
