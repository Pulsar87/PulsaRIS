from django.shortcuts import redirect
from django.urls import reverse
from .check import get_hardware_id, verify_key


class LicenseMiddleware:
    """
    Middleware that checks for a valid license on every request.
    If no valid license is found, redirects to the activation page.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        # Paths that don't require license verification
        self.exempt_paths = [
            '/license/activation-required/',
            '/license/activate/',
            '/admin/',
            '/static/',
            '/media/',
        ]
    
    def __call__(self, request):
        # Check if the path is exempt from license checking
        path = request.path_info
        
        for exempt_path in self.exempt_paths:
            if path.startswith(exempt_path):
                return self.get_response(request)
        
        # Check if license is activated in session
        if not request.session.get('license_activated'):
            # No valid license, redirect to activation page
            return redirect('license:activation_required')
        
        # Optional: Check if license has expired
        license_expiry = request.session.get('license_expiry')
        if license_expiry:
            from datetime import datetime
            try:
                expiry_date = datetime.strptime(license_expiry, '%Y-%m-%d')
                if datetime.now() > expiry_date:
                    # License expired, clear session and redirect
                    request.session.flush()
                    return redirect('license:activation_required')
            except ValueError:
                pass
        
        response = self.get_response(request)
        return response
