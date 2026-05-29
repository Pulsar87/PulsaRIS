from django.contrib import messages
from django.shortcuts import redirect, render, get_object_or_404
from django.utils.translation import gettext as _
from django.http import JsonResponse
from django.db.models import Q

from orders.models import ExamOrder
from patients.views import get_tenant
from tenants.models import Device, Tenant


def order_list(request):
    """Display list of orders with search functionality."""
    query = request.GET.get("q", "")
    status_filter = request.GET.get("status", "")
    tenant = get_tenant(request)

    orders = ExamOrder.objects.none()
    if tenant:
        orders = ExamOrder.objects.filter(tenant=tenant).select_related(
            'patient', 'modality', 'facility', 'room_station'
        )

        if query:
            orders = orders.filter(
                Q(accession_number__icontains=query)
                | Q(patient__mrn__icontains=query)
                | Q(patient__first_name_en__icontains=query)
                | Q(patient__last_name_en__icontains=query)
                | Q(procedure_name_en__icontains=query)
            )

        if status_filter:
            orders = orders.filter(status=status_filter)

    context = {
        "orders": orders,
        "query": query,
        "status_filter": status_filter,
        "status_choices": ExamOrder.Status.choices,
    }
    return render(request, "orders/order_list.html", context)


def order_detail(request, pk):
    """Display order details."""
    order = get_object_or_404(ExamOrder, pk=pk)
    context = {
        "order": order,
    }
    return render(request, "orders/order_detail.html", context)


def add_order(request):
    """Handle order creation page and form submission."""
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
        duration_minutes = request.POST.get("duration_minutes", 15) or 15
        facility_id = request.POST.get("facility", "")

        # Basic validation
        if not patient_mrn:
            messages.error(request, _("Please enter a valid MRN"))
            return redirect("orders:add_order")

        if not accession_number:
            messages.error(request, _("Accession number is required"))
            return redirect("orders:add_order")

        if not procedure_code or not procedure_name_en:
            messages.error(request, _("Procedure code and name are required"))
            return redirect("orders:add_order")

        # Get tenant
        tenant = get_tenant(request)
        if not tenant:
            messages.error(request, _("Tenant not found. Please select a tenant."))
            return redirect("license:home")

        # Look up patient by MRN
        from patients.models import Patient
        try:
            patient = Patient.objects.get(tenant=tenant, mrn=patient_mrn)
        except Patient.DoesNotExist:
            messages.error(request, _("Patient with MRN %(mrn)s not found") % {"mrn": patient_mrn})
            return redirect("orders:add_order")

        # Check for duplicate accession number within tenant
        if ExamOrder.objects.filter(tenant=tenant, accession_number=accession_number).exists():
            messages.error(request, _("An order with this accession number already exists"))
            return redirect("orders:add_order")

        # Get modality from device
        device = None
        modality = None
        if device_id:
            try:
                device = Device.objects.get(id=device_id, tenant=tenant)
                modality = device.modality
            except Device.DoesNotExist:
                messages.error(request, _("Selected device not found"))
                return redirect("orders:add_order")

        # Get facility if provided
        facility = None
        if facility_id:
            from tenants.models import Facility
            try:
                facility = Facility.objects.get(id=facility_id, tenant=tenant)
            except Facility.DoesNotExist:
                pass

        # Create order
        try:
            order = ExamOrder.objects.create(
                tenant=tenant,
                patient=patient,
                facility=facility,
                accession_number=accession_number,
                referring_physician=referring_physician,
                modality=modality,
                procedure_code=procedure_code,
                procedure_name_en=procedure_name_en,
                procedure_name_ar=procedure_name_ar,
                priority=priority,
                clinical_indication=clinical_indication,
                laterality=laterality,
                body_part=body_part,
                contrast_required=contrast_required,
                status=ExamOrder.Status.REGISTERED,
                scheduled_datetime=scheduled_datetime if scheduled_datetime else None,
                duration_minutes=int(duration_minutes),
                room_station=device,
                created_by=request.user if request.user.is_authenticated else None,
            )
            messages.success(
                request, _("Order created successfully! Accession: %(acc)s") % {"acc": accession_number}
            )
            return redirect("orders:order_detail", pk=order.pk)
        except Exception as e:
            messages.error(request, _("Error creating order: %(error)s") % {"error": str(e)})
            return redirect("orders:add_order")

    # GET request - render form
    tenant = get_tenant(request)
    facilities = []
    if tenant:
        from tenants.models import Facility
        facilities = Facility.objects.filter(tenant=tenant, is_active=True)

    context = {
        "facilities": facilities,
        "procedure_choices": ExamOrder._meta.get_field('procedure_code').choices,
        "priority_choices": ExamOrder.Priority.choices,
    }
    return render(request, "orders/add_order.html", context)


def edit_order(request, pk):
    """Edit an existing order."""
    order = get_object_or_404(ExamOrder, pk=pk)
    tenant = get_tenant(request)

    if not tenant:
        messages.error(request, _("Tenant not found. Please select a tenant."))
        return redirect("orders:order_list")

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
        duration_minutes = request.POST.get("duration_minutes", 15) or 15
        status = request.POST.get("status", order.status)
        facility_id = request.POST.get("facility", "")

        # Basic validation
        if not patient_mrn:
            messages.error(request, _("Please enter a valid MRN"))
            return redirect("orders:edit_order", pk=pk)

        if not accession_number:
            messages.error(request, _("Accession number is required"))
            return redirect("orders:edit_order", pk=pk)

        if not procedure_code or not procedure_name_en:
            messages.error(request, _("Procedure code and name are required"))
            return redirect("orders:edit_order", pk=pk)

        # Look up patient by MRN
        from patients.models import Patient
        try:
            patient = Patient.objects.get(tenant=tenant, mrn=patient_mrn)
        except Patient.DoesNotExist:
            messages.error(request, _("Patient with MRN %(mrn)s not found") % {"mrn": patient_mrn})
            return redirect("orders:edit_order", pk=pk)

        # Check for duplicate accession number within tenant (excluding current order)
        if ExamOrder.objects.filter(tenant=tenant, accession_number=accession_number).exclude(pk=pk).exists():
            messages.error(request, _("An order with this accession number already exists"))
            return redirect("orders:edit_order", pk=pk)

        # Get modality from device
        device = None
        modality = None
        if device_id:
            try:
                device = Device.objects.get(id=device_id, tenant=tenant)
                modality = device.modality
            except Device.DoesNotExist:
                messages.error(request, _("Selected device not found"))
                return redirect("orders:edit_order", pk=pk)

        # Get facility if provided
        facility = None
        if facility_id:
            from tenants.models import Facility
            try:
                facility = Facility.objects.get(id=facility_id, tenant=tenant)
            except Facility.DoesNotExist:
                pass

        # Update order
        try:
            order.patient = patient
            order.facility = facility
            order.accession_number = accession_number
            order.referring_physician = referring_physician
            order.modality = modality
            order.procedure_code = procedure_code
            order.procedure_name_en = procedure_name_en
            order.procedure_name_ar = procedure_name_ar
            order.priority = priority
            order.clinical_indication = clinical_indication
            order.laterality = laterality
            order.body_part = body_part
            order.contrast_required = contrast_required
            order.status = status
            order.scheduled_datetime = scheduled_datetime if scheduled_datetime else None
            order.duration_minutes = int(duration_minutes)
            order.room_station = device
            order.save()

            messages.success(request, _("Order updated successfully!"))
            return redirect("orders:order_detail", pk=order.pk)
        except Exception as e:
            messages.error(request, _("Error updating order: %(error)s") % {"error": str(e)})
            return redirect("orders:edit_order", pk=pk)

    # GET request - render form
    facilities = []
    if tenant:
        from tenants.models import Facility
        facilities = Facility.objects.filter(tenant=tenant, is_active=True)

    context = {
        "order": order,
        "facilities": facilities,
        "procedure_choices": ExamOrder._meta.get_field('procedure_code').choices,
        "priority_choices": ExamOrder.Priority.choices,
        "status_choices": ExamOrder.Status.choices,
    }
    return render(request, "orders/edit_order.html", context)


def delete_order(request, pk):
    """Delete an order."""
    order = get_object_or_404(ExamOrder, pk=pk)
    tenant = get_tenant(request)

    if not tenant:
        messages.error(request, _("Tenant not found. Please select a tenant."))
        return redirect("orders:order_list")

    if request.method == "POST":
        try:
            order.delete()
            messages.success(request, _("Order deleted successfully!"))
            return redirect("orders:order_list")
        except Exception as e:
            messages.error(request, _("Error deleting order: %(error)s") % {"error": str(e)})
            return redirect("orders:order_detail", pk=pk)

    context = {
        "order": order,
    }
    return render(request, "orders/delete_order.html", context)


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

        # Get tenant
        tenant = get_tenant(request)
        if not tenant:
            messages.error(request, _("Tenant not found. Please select a tenant."))
            return redirect("license:home")

        # Look up patient by MRN
        from patients.models import Patient
        try:
            patient = Patient.objects.get(tenant=tenant, mrn=patient_mrn)
        except Patient.DoesNotExist:
            messages.error(request, _("Patient with MRN %(mrn)s not found") % {"mrn": patient_mrn})
            return redirect("orders:reserve_order")

        # Check for duplicate accession number within tenant
        if ExamOrder.objects.filter(tenant=tenant, accession_number=accession_number).exists():
            messages.error(request, _("An order with this accession number already exists"))
            return redirect("orders:reserve_order")

        # Get modality from device
        try:
            device = Device.objects.get(id=device_id, tenant=tenant)
            modality = device.modality
        except Device.DoesNotExist:
            messages.error(request, _("Selected device not found"))
            return redirect("orders:reserve_order")

        # Create order
        try:
            order = ExamOrder.objects.create(
                tenant=tenant,
                patient=patient,
                accession_number=accession_number,
                referring_physician=referring_physician,
                modality=modality,
                procedure_code=procedure_code,
                procedure_name_en=procedure_name_en,
                procedure_name_ar=procedure_name_ar,
                priority=priority,
                clinical_indication=clinical_indication,
                laterality=laterality,
                body_part=body_part,
                contrast_required=contrast_required,
                status=ExamOrder.Status.REGISTERED,
                scheduled_datetime=scheduled_datetime if scheduled_datetime else None,
                duration_minutes=int(duration_minutes),
                room_station=device,
                created_by=request.user if request.user.is_authenticated else None,
            )
            messages.success(
                request, _("Order reserved successfully! Accession: %(acc)s") % {"acc": accession_number}
            )
            return redirect("orders:order_detail", pk=order.pk)
        except Exception as e:
            messages.error(request, _("Error creating order: %(error)s") % {"error": str(e)})
            return redirect("orders:reserve_order")

    # GET request - pre-fill MRN if provided
    prefill_mrn = request.GET.get("mrn", "")
    tenant = get_tenant(request)

    context = {
        "prefill_mrn": prefill_mrn,
        "procedure_choices": ExamOrder._meta.get_field('procedure_code').choices,
        "priority_choices": ExamOrder.Priority.choices,
    }
    return render(request, "orders/reserve_order.html", context)


def get_devices(request):
    """HTMX endpoint to fetch devices for the current tenant."""
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    
    tenant = get_tenant(request)
    
    # Debug: log tenant info
    print(f"DEBUG get_devices: tenant={tenant}")

    if not tenant:
        html = render_to_string('orders/_device_options.html', {'devices': [], 'error': 'Tenant not found'})
        print(f"DEBUG get_devices: no tenant, returning error HTML")
        return HttpResponse(html)

    devices = Device.objects.filter(
        tenant=tenant,
        is_active=True
    ).select_related('modality').order_by('name')
    
    # Debug: log device count
    print(f"DEBUG get_devices: found {devices.count()} devices")

    html = render_to_string('orders/_device_options.html', {'devices': devices})
    print(f"DEBUG get_devices: returning HTML with {len(html)} chars")
    return HttpResponse(html)
