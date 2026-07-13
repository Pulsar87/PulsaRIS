from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from datetime import datetime, timedelta
from django.utils import timezone
from .check import get_hardware_id, verify_key

@login_required
def home(request):
    """Home page view with calendar."""
    from orders.models import ExamOrder

    # Get tenant from request
    tenant = getattr(request, 'tenant', None)

    # Fetch scheduled orders for the calendar
    if tenant:
        from tenants.models import Device
        # Get orders for the next 30 days
        end_date = timezone.now() + timedelta(days=30)
        orders = ExamOrder.objects.filter(
            tenant=tenant,
            scheduled_datetime__isnull=False,
            scheduled_datetime__lte=end_date
        ).exclude(status='CANCELLED')[:100]  # Limit to 100 for performance

        # Get all active devices for the tenant with modality info
        devices = Device.objects.filter(tenant=tenant, is_active=True).select_related('modality').order_by('name')
    else:
        orders = []
        devices = []

        return render(request, 'license/home.html', {'orders': orders, 'devices': devices, 'tenant': tenant})

@login_required
def calendar_events(request):
    """API endpoint to return calendar events in FullCalendar format."""
    from orders.models import ExamOrder
    from tenants.models import Device
    import logging

    logger = logging.getLogger(__name__)
    tenant = getattr(request, 'tenant', None)

    # Get date range from request
    start = request.GET.get('start')
    end = request.GET.get('end')
    device_ids = request.GET.getlist('devices[]')

    logger.info(f"calendar_events called: start={start}, end={end}, devices={device_ids}, tenant={tenant}")

    if not tenant:
        logger.warning("No tenant found")
        return JsonResponse([], safe=False)

    # Filter orders within the date range
    filters = {
        'tenant': tenant,
        'scheduled_datetime__isnull': False,
    }

    if start:
        # Parse the start date - FullCalendar sends ISO format with timezone
        try:
            from dateutil import parser
            start_dt = parser.parse(start)
            filters['scheduled_datetime__gte'] = start_dt
            logger.info(f"Parsed start date: {start_dt}")
        except (ValueError, ImportError) as e:
            logger.error(f"Error parsing start date: {e}")
            filters['scheduled_datetime__gte'] = start
    if end:
        # Parse the end date - FullCalendar sends ISO format with timezone
        try:
            from dateutil import parser
            end_dt = parser.parse(end)
            filters['scheduled_datetime__lte'] = end_dt
            logger.info(f"Parsed end date: {end_dt}")
        except (ValueError, ImportError) as e:
            logger.error(f"Error parsing end date: {e}")
            filters['scheduled_datetime__lte'] = end

    # Filter by selected devices if provided
    if device_ids:
        # Convert device IDs to UUIDs if needed
        from uuid import UUID
        valid_device_ids = []
        for device_id in device_ids:
            try:
                # Try to convert to UUID
                valid_device_ids.append(str(UUID(device_id)))
            except (ValueError, AttributeError):
                # If not a valid UUID, keep as string
                valid_device_ids.append(device_id)
        filters['room_station_id__in'] = valid_device_ids
        logger.info(f"Filtering by device IDs: {valid_device_ids}")

    logger.info(f"Final filters: {filters}")

    orders = ExamOrder.objects.filter(**filters).exclude(status='CANCELLED').select_related('room_station', 'modality', 'patient')[:200]

    logger.info(f"Found {orders.count()} orders")
    for order in orders:
        logger.info(f"Order: {order.id}, scheduled={order.scheduled_datetime}, device={order.room_station_id}, status={order.status}")

    events = []
    color_map = {
        'CT': '#3498db',      # Blue
        'MR': '#9b59b6',      # Purple
        'XR': '#2ecc71',      # Green
        'US': '#f39c12',      # Orange
        'NM': '#e74c3c',      # Red
        'DX': '#1abc9c',      # Teal
    }

    for order in orders:
        modality_code = order.modality.code if hasattr(order.modality, 'code') else str(order.modality)
        device_name = order.room_station.name if order.room_station else 'N/A'

        # Ensure scheduled_datetime is timezone-aware
        scheduled_dt = order.scheduled_datetime
        if scheduled_dt and timezone.is_naive(scheduled_dt):
            scheduled_dt = timezone.make_aware(scheduled_dt)

        end_dt = None
        if order.duration_minutes:
            end_dt = scheduled_dt + timedelta(minutes=order.duration_minutes)

        # Set color based on status
        status_color_map = {
            'COMPLETED': '#22c55e',
            'REPORTED': '#22c55e',
            'FINALIZED': '#22c55e',
            'REGISTERED': '#eab308',
            'SCHEDULED': '#eab308',
            'IN_PROGRESS': '#f97316',
            'CANCELLED': '#ef4444',
        }
        default_color = color_map.get(modality_code, '#95a5a6')
        event_color = status_color_map.get(order.status, default_color)

        event = {
            'id': str(order.id),
            'title': f"{modality_code} - {order.procedure_code}",
            'start': scheduled_dt.isoformat(),
            'end': end_dt.isoformat() if end_dt else None,
            'backgroundColor': event_color,
            'borderColor': event_color,
            'extendedProps': {
                'patient_mrn': order.patient.mrn if order.patient else 'N/A',
                'patient_name': str(order.patient) if order.patient else 'N/A',
                'accession': order.accession_number,
                'priority': order.priority,
                'status': order.status,
                'modality': modality_code,
                'device': device_name,
            }
        }
        events.append(event)

    return JsonResponse(events, safe=False)

def activation_required(request):
    """Display the activation page when no valid license is found."""
    hwid = get_hardware_id()
    return render(request, 'license/activation.html', {'hwid': hwid})

def activate(request):
    """Handle license activation."""
    if request.method == 'POST':
        expiry_date = request.POST.get('expiry_date')
        signature = request.POST.get('signature')
        max_orders = request.POST.get('max_orders')

        # Convert date from YYYY-MM-DD to DDMMYY format
        try:
            from datetime import datetime
            date_obj = datetime.strptime(expiry_date, '%Y-%m-%d')
            expiry_str = date_obj.strftime('%d%m%y')
            provided_key = f"{expiry_str}-{signature.upper()}"

            if verify_key(provided_key):
                # Get tenant from request
                tenant = getattr(request, 'tenant', None)

                if tenant:
                    # Store license in tenant model (persists across sessions/logouts)
                    tenant.license_activated = True
                    tenant.license_expiry = expiry_date
                    tenant.license_signature = signature.upper()
                    # Set max orders limit (None means unlimited)
                    tenant.license_max_orders = int(max_orders) if max_orders and max_orders.strip() else None
                    tenant.save(update_fields=['license_activated', 'license_expiry', 'license_signature', 'license_max_orders'])
                else:
                    # Fallback to session for non-tenant setups
                    request.session['license_activated'] = True
                    request.session['license_expiry'] = expiry_date

                messages.success(request, 'System activated successfully!')
                return redirect('license:home')
            else:
                messages.error(request, 'Invalid license key. Please check your information.')
        except Exception as e:
            messages.error(request, f'Activation failed: {str(e)}')

    hwid = get_hardware_id()
    return render(request, 'license/activation.html', {'hwid': hwid})
