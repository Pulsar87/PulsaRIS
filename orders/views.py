import logging

from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from orders.models import ExamOrder


def worklist(request):
    """Display worklist of orders with advanced filtering."""
    query = request.GET.get("q", "")
    status_filter = request.GET.get("status", "")
    modality_filter = request.GET.get("modality", "")
    priority_filter = request.GET.get("priority", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")

    orders = ExamOrder.objects.filter(is_deleted=False).select_related(
        "patient", "modality", "room_station"
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

    if modality_filter:
        orders = orders.filter(modality__code=modality_filter)

    if priority_filter:
        orders = orders.filter(priority=priority_filter)

    if date_from:
        orders = orders.filter(scheduled_datetime__date__gte=date_from)

    if date_to:
        orders = orders.filter(scheduled_datetime__date__lte=date_to)


    context = {
        "orders": orders,
        "query": query,
        "status_filter": status_filter,
        "modality_filter": modality_filter,
        "priority_filter": priority_filter,
        "date_from": date_from,
        "date_to": date_to,
        "status_choices": ExamOrder.Status.choices,
        "priority_choices": ExamOrder.Priority.choices,
    }
    return render(request, "orders/worklist.html", context)


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

        # Look up patient by MRN
        from patients.models import Patient

        try:
            patient = Patient.objects.get(mrn=patient_mrn)
        except Patient.DoesNotExist:
            messages.error(
                request, _("Patient with MRN %(mrn)s not found") % {"mrn": patient_mrn}
            )
            return redirect("orders:add_order")

        # Check for duplicate accession number
        if ExamOrder.objects.filter(
            accession_number=accession_number
        ).exists():
            messages.error(
                request, _("An order with this accession number already exists")
            )
            return redirect("orders:add_order")

        # Get modality from device
        device = None
        modality = None
        if device_id:
            try:
                device = Device.objects.get(id=device_id)
                modality = device.modality
            except Device.DoesNotExist:
                messages.error(request, _("Selected device not found"))
                return redirect("orders:add_order")

        # Get facility if provided
        facility = None


        try:
            facility = Facility.objects.get(id=facility_id)
        except Facility.DoesNotExist:
            pass

        # Create order
        try:
            order = ExamOrder.objects.create(
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
                request,
                _("Order created successfully! Accession: %(acc)s")
                % {"acc": accession_number},
            )
            return redirect("orders:order_detail", pk=order.pk)
        except Exception as e:
            messages.error(
                request, _("Error creating order: %(error)s") % {"error": str(e)}
            )
            return redirect("orders:add_order")


    # Get active procedures from database
    from orders.models import Procedure

    procedures = Procedure.objects.filter(is_active=True).order_by(
        "modality_type", "code"
    )

    # Get scheduled_datetime from query parameter (from calendar click)
    datetime = request.GET.get("datetime", "")
    context = {
        "procedures": procedures,
        "priority_choices": ExamOrder.Priority.choices,
        "datetime": datetime,
    }
    return render(request, "orders/add_order.html", context)


def edit_order(request, pk):
    """Edit an existing order."""
    order = get_object_or_404(ExamOrder, pk=pk)

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
            patient = Patient.objects.get(mrn=patient_mrn)
        except Patient.DoesNotExist:
            messages.error(
                request, _("Patient with MRN %(mrn)s not found") % {"mrn": patient_mrn}
            )
            return redirect("orders:edit_order", pk=pk)

        # Check for duplicate accession number (excluding current order)
        if (
            ExamOrder.objects.filter(accession_number=accession_number)
            .exclude(pk=pk)
            .exists()
        ):
            messages.error(
                request, _("An order with this accession number already exists")
            )
            return redirect("orders:edit_order", pk=pk)

        # Get modality from device
        device = None
        modality = None
        if device_id:
            try:
                device = Device.objects.get(id=device_id)
                modality = device.modality
            except Device.DoesNotExist:
                messages.error(request, _("Selected device not found"))
                return redirect("orders:edit_order", pk=pk)

        # Get facility if provided
        facility = None

        try:
            facility = Facility.objects.get(id=facility_id)
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
            order.scheduled_datetime = (
                scheduled_datetime if scheduled_datetime else None
            )
            order.duration_minutes = int(duration_minutes)
            order.room_station = device
            order.save()

            messages.success(request, _("Order updated successfully!"))
            return redirect("orders:order_detail", pk=order.pk)
        except Exception as e:
            messages.error(
                request, _("Error updating order: %(error)s") % {"error": str(e)}
            )
            return redirect("orders:edit_order", pk=pk)

    # Get active procedures from database
    from orders.models import Procedure

    procedures = Procedure.objects.filter(is_active=True).order_by(
        "modality_type", "code"
    )

    context = {
        "order": order,
        "procedures": procedures,
        "priority_choices": ExamOrder.Priority.choices,
        "status_choices": ExamOrder.Status.choices,
    }
    return render(request, "orders/edit_order.html", context)


def delete_order(request, pk):
    """Delete an order (soft delete with audit logging)."""
    from audit.models import AuditLog

    order = get_object_or_404(ExamOrder, pk=pk)

    if request.method == "POST":
        try:
            # Store old values for audit
            old_values = {
                'accession_number': order.accession_number,
                'patient_mrn': order.patient.mrn if order.patient else None,
                'procedure_code': order.procedure_code,
                'procedure_name_en': order.procedure_name_en,
                'priority': order.priority,
                'status': order.status,
            }

            # Soft delete instead of hard delete
            order.soft_delete()

            # Create audit log entry
            AuditLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action='DELETE',
                entity_type='ExamOrder',
                entity_id=order.id,
                old_values=old_values,
                new_values={'is_deleted': True, 'deleted_at': str(order.deleted_at)},
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            )

            messages.success(request, _("Order deleted successfully!"))
            return redirect("orders:worklist")
        except Exception as e:
            messages.error(
                request, _("Error deleting order: %(error)s") % {"error": str(e)}
            )
            return redirect("orders:order_detail", pk=pk)

    context = {
        "order": order,
    }
    return render(request, "orders/delete_order.html", context)


# def reserve_order(request):
#     """Handle order reservation page and form submission."""
#     if request.method == "POST":
#         # Get form data
#         patient_mrn = request.POST.get("patient_mrn", "").strip()
#         accession_number = request.POST.get("accession_number", "").strip()
#         priority = request.POST.get("priority", "ROUTINE")
#         device_id = request.POST.get("device", "")
#         procedure_code = request.POST.get("procedure_code", "").strip()
#         procedure_name_en = request.POST.get("procedure_name_en", "").strip()
#         procedure_name_ar = request.POST.get("procedure_name_ar", "").strip()
#         referring_physician = request.POST.get("referring_physician", "").strip()
#         laterality = request.POST.get("laterality", "")
#         body_part = request.POST.get("body_part", "").strip()
#         contrast_required = request.POST.get("contrast_required") == "on"
#         clinical_indication = request.POST.get("clinical_indication", "").strip()
#         scheduled_datetime = request.POST.get("scheduled_datetime", "")
#         duration_minutes = request.POST.get("duration_minutes", 15)

#         # Basic validation
#         if not patient_mrn:
#             messages.error(request, _("Please enter a valid MRN"))
#             return redirect("orders:reserve_order")

#         if not accession_number:
#             messages.error(request, _("Accession number is required"))
#             return redirect("orders:reserve_order")

#         if not device_id:
#             messages.error(request, _("Please select a device"))
#             return redirect("orders:reserve_order")

#         if not procedure_code or not procedure_name_en:
#             messages.error(request, _("Procedure code and name are required"))
#             return redirect("orders:reserve_order")

#         # Get tenant
#         tenant = get_tenant(request)
#         if not tenant:
#             messages.error(request, _("Tenant not found. Please select a tenant."))
#             return redirect("license:home")

#         # Look up patient by MRN
#         from patients.models import Patient

#         try:
#             patient = Patient.objects.get(tenant=tenant, mrn=patient_mrn)
#         except Patient.DoesNotExist:
#             messages.error(
#                 request, _("Patient with MRN %(mrn)s not found") % {"mrn": patient_mrn}
#             )
#             return redirect("orders:reserve_order")

#         # Check for duplicate accession number within tenant
#         if ExamOrder.objects.filter(
#             tenant=tenant, accession_number=accession_number
#         ).exists():
#             messages.error(
#                 request, _("An order with this accession number already exists")
#             )
#             return redirect("orders:reserve_order")

#         # Get modality from device
#         try:
#             device = Device.objects.get(id=device_id, tenant=tenant)
#             modality = device.modality
#         except Device.DoesNotExist:
#             messages.error(request, _("Selected device not found"))
#             return redirect("orders:reserve_order")

#         # Create order
#         try:
#             order = ExamOrder.objects.create(
#                 tenant=tenant,
#                 patient=patient,
#                 accession_number=accession_number,
#                 referring_physician=referring_physician,
#                 modality=modality,
#                 procedure_code=procedure_code,
#                 procedure_name_en=procedure_name_en,
#                 procedure_name_ar=procedure_name_ar,
#                 priority=priority,
#                 clinical_indication=clinical_indication,
#                 laterality=laterality,
#                 body_part=body_part,
#                 contrast_required=contrast_required,
#                 status=ExamOrder.Status.REGISTERED,
#                 scheduled_datetime=scheduled_datetime if scheduled_datetime else None,
#                 duration_minutes=int(duration_minutes),
#                 room_station=device,
#                 created_by=request.user if request.user.is_authenticated else None,
#             )
#             messages.success(
#                 request,
#                 _("Order reserved successfully! Accession: %(acc)s")
#                 % {"acc": accession_number},
#             )
#             return redirect("orders:order_detail", pk=order.pk)
#         except Exception as e:
#             messages.error(
#                 request, _("Error creating order: %(error)s") % {"error": str(e)}
#             )
#             return redirect("orders:reserve_order")

#     # GET request - pre-fill MRN if provided
#     prefill_mrn = request.GET.get("mrn", "")
#     tenant = get_tenant(request)

#     # Get active procedures from database
#     from orders.models import Procedure

#     procedures = Procedure.objects.filter(is_active=True).order_by(
#         "modality_type", "code"
#     )

#     context = {
#         "prefill_mrn": prefill_mrn,
#         "procedures": procedures,
#         "priority_choices": ExamOrder.Priority.choices,
#     }
#     return render(request, "orders/reserve_order.html", context)


def get_devices(request):
    """HTMX endpoint to fetch devices for the current tenant."""
    from django.http import HttpResponse
    from django.template.loader import render_to_string

    # Get facility from request (if using facility-based filtering)
    facility = getattr(request, 'facility', None)

    # Debug: log facility info
    print(f"DEBUG get_devices: facility={facility}")

    if not facility:
        html = render_to_string(
            "orders/_device_options.html", {"devices": [], "error": "Facility not found"}
        )
        print(f"DEBUG get_devices: no facility, returning error HTML")
        return HttpResponse(html)

    devices = (
        Device.objects.filter(facility=facility, is_active=True)
        .select_related("modality")
        .order_by("name")
    )

    # Debug: log device count
    print(f"DEBUG get_devices: found {devices.count()} devices")

    html = render_to_string("orders/_device_options.html", {"devices": devices})
    print(f"DEBUG get_devices: returning HTML with {len(html)} chars")
    return HttpResponse(html)


def update_order_status(request, pk):
    """API endpoint to update order status via AJAX."""
    import json

    from django.http import JsonResponse
    from django.views.decorators.http import require_POST

    from orders.models import ExamOrder

    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Method not allowed"})

    try:
        data = json.loads(request.body)
        new_status = data.get("status")

        if not new_status:
            return JsonResponse({"success": False, "error": "Status is required"})

        # Validate status choice
        valid_statuses = [choice[0] for choice in ExamOrder.Status.choices]
        if new_status not in valid_statuses:
            return JsonResponse({"success": False, "error": "Invalid status"})

        # Get the order
        order = ExamOrder.objects.get(pk=pk)

        # Update status
        order.status = new_status
        order.save()

        return JsonResponse({"success": True, "status": new_status})

    except ExamOrder.DoesNotExist:
        return JsonResponse({"success": False, "error": "Order not found"})
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


def send_order_worklist(request, pk):
    """
    API endpoint to send worklist for a specific order to configured DICOM devices.

    This endpoint triggers sending the worklist entry for an order to all
    relevant DICOM modality devices.

    Args:
        pk: Primary key of the ExamOrder

    Returns:
        JSON response with success status and details
    """
    from django.http import JsonResponse

    from integrations.dicom import send_worklist_for_order

    try:
        order = ExamOrder.objects.select_related(
            "patient", "modality", "room_station"
        ).get(pk=pk)

        # Check if order has required information
        if not order.room_station or not order.room_station.dicom_host:
            return JsonResponse(
                {"success": False, "error": "No DICOM device configured for this order"}
            )

        # Send worklist to device(s)
        success, message, results = send_worklist_for_order(order)

        return JsonResponse(
            {"success": success, "message": message, "details": results}
        )

    except ExamOrder.DoesNotExist:
        return JsonResponse({"success": False, "error": "Order not found"})
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error sending worklist: {str(e)}")
        return JsonResponse({"success": False, "error": str(e)})


def test_dicom_connection(request, device_id):
    """
    API endpoint to test DICOM connection to a specific device.

    Args:
        device_id: UUID of the Device to test

    Returns:
        JSON response with connection status
    """
    from django.http import JsonResponse

    from integrations.dicom import verify_dicom_connection

    try:
        device = Device.objects.get(id=device_id)

        if not device.dicom_host:
            return JsonResponse(
                {"success": False, "error": "Device has no DICOM host configured"}
            )

        success, message = verify_dicom_connection(
            ae_title=device.dicom_ae_title,
            host=device.dicom_host,
            port=device.dicom_port,
            calling_ae_title="RIS_SYSTEM",
            timeout=10,
        )

        return JsonResponse(
            {
                "success": success,
                "message": message,
                "device": {
                    "name": device.name,
                    "ae_title": device.dicom_ae_title,
                    "host": device.dicom_host,
                    "port": device.dicom_port,
                },
            }
        )

    except Device.DoesNotExist:
        return JsonResponse({"success": False, "error": "Device not found"})
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error testing DICOM connection: {str(e)}")
        return JsonResponse({"success": False, "error": str(e)})
