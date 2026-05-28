from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .check import get_hardware_id, verify_key

@login_required
def home(request):
    """Home page view."""
    return render(request, 'license/home.html')

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
