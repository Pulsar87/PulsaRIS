from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.http import JsonResponse

from orders.models import ExamOrder
from patients.views import get_tenant
from tenants.models import Device, Tenant


def reserve_order(request):
    """Handle order reservation page and form submission."""
    if request.method == "POST":
        # Get form data
        patient_mrn = request.POST.get("patient_mrn", "").strip()
        accession_number = request.POST.get("accession_number", "").strip()
        priority = request.POST.get("priority", "ROUTINE")
        device_id = request.POST.get("device", "")
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

        # Basic validation
        if not patient_mrn:
            messages.error(request, _("Please enter a valid MRN"))
            return redirect("orders:reserve_order")

        if not accession_number:
            messages.error(request, _("Accession number is required"))
            return redirect("orders:reserve_order")

        if not device_id:
            messages.error(request, _("Please select a device"))
            return redirect("orders:reserve_order")

        if not procedure_code or not procedure_name_en:
            messages.error(request, _("Procedure code and name are required"))
            return redirect("orders:reserve_order")

        # TODO: Add logic to create the ExamOrder
        # This would involve:
        # 1. Looking up the patient by MRN
        # 2. Getting the tenant from the request
        # 3. Creating the ExamOrder instance with device_id as room_station

        messages.success(request, _("Order reserved successfully!"))
        return redirect("orders:worklist")

    return render(request, "orders/reserve_order.html")


def get_devices(request):
    """HTMX endpoint to fetch devices for the current tenant."""
    tenant = get_tenant(request)
    
    # Debug: log tenant info
    print(f"DEBUG get_devices: tenant={tenant}")

    if not tenant:
        from django.template.loader import render_to_string
        html = render_to_string('orders/_device_options.html', {'devices': [], 'error': 'Tenant not found'})
        print(f"DEBUG get_devices: no tenant, returning error HTML")
        return html

    devices = Device.objects.filter(
        tenant=tenant,
        is_active=True
    ).select_related('modality').order_by('name')
    
    # Debug: log device count
    print(f"DEBUG get_devices: found {devices.count()} devices")

    from django.template.loader import render_to_string
    html = render_to_string('orders/_device_options.html', {'devices': devices})
    print(f"DEBUG get_devices: returning HTML with {len(html)} chars")
    return html
