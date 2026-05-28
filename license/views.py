from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from datetime import datetime, timedelta
from .check import get_hardware_id, verify_key

@login_required
def home(request):
    """Home page view with calendar."""
    # Get tenant from request
    tenant = getattr(request, 'tenant', None)
    
    # Fetch scheduled orders for the calendar
    if tenant:
        from orders.models import ExamOrder
        from tenants.models import Device
        # Get orders for the next 30 days
        end_date = datetime.now() + timedelta(days=30)
        orders = ExamOrder.objects.filter(
            tenant=tenant,
            scheduled_datetime__isnull=False,
            scheduled_datetime__lte=end_date
        ).exclude(status='CANCELLED')[:100]  # Limit to 100 for performance
        
        # Get all active devices for the tenant
        devices = Device.objects.filter(tenant=tenant, is_active=True).order_by('name')
    else:
        orders = []
        devices = []
    
    return render(request, 'license/home.html', {'orders': orders, 'devices': devices})

@login_required
def calendar_events(request):
    """API endpoint to return calendar events in FullCalendar format."""
    from orders.models import ExamOrder
    from tenants.models import Device
    
    tenant = getattr(request, 'tenant', None)
    
    # Get date range from request
    start = request.GET.get('start')
    end = request.GET.get('end')
    device_ids = request.GET.getlist('devices[]')
    
    if not tenant:
        return JsonResponse([], safe=False)
    
    # Filter orders within the date range
    filters = {
        'tenant': tenant,
        'scheduled_datetime__isnull': False,
    }
    
    if start:
        filters['scheduled_datetime__gte'] = start
    if end:
        filters['scheduled_datetime__lte'] = end
    
    # Filter by selected devices if provided
    if device_ids:
        filters['room_station__in'] = device_ids
    
    orders = ExamOrder.objects.filter(**filters).exclude(status='CANCELLED')[:200]
    
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
        event = {
            'id': str(order.id),
            'title': f"{order.modality} - {order.procedure_code}",
            'start': order.scheduled_datetime.isoformat(),
            'end': (order.scheduled_datetime + timedelta(minutes=order.duration_minutes)).isoformat() if order.duration_minutes else None,
            'backgroundColor': color_map.get(order.modality, '#95a5a6'),
            'borderColor': color_map.get(order.modality, '#95a5a6'),
            'extendedProps': {
                'patient_mrn': order.patient.mrn if order.patient else 'N/A',
                'patient_name': str(order.patient) if order.patient else 'N/A',
                'accession': order.accession_number,
                'priority': order.priority,
                'status': order.status,
                'modality': order.modality,
                'device': order.room_station or 'N/A',
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
                    tenant.save(update_fields=['license_activated', 'license_expiry', 'license_signature'])
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
