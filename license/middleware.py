from django.shortcuts import redirect
from django.utils import timezone

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
            "/activation-required/",
            "/activate/",
            "/admin/",
            "/static/",
            "/media/",
            "/users/login",
            "/users/logout",
        ]

    def __call__(self, request):
        # Check if the path is exempt from license checking
        path = request.path_info

        for exempt_path in self.exempt_paths:
            if path.startswith(exempt_path):
                return self.get_response(request)

        # Get tenant from request (set by django_tenants middleware)
        tenant = getattr(request, 'tenant', None)
        
        if tenant and hasattr(tenant, 'license_activated'):
            # Check license status from tenant model
            if not tenant.license_activated:
                return redirect("license:activation_required")
            
            # Check if license has expired
            if tenant.license_expiry and tenant.license_expiry < timezone.now().date():
                # License expired, deactivate and redirect
                tenant.license_activated = False
                tenant.save(update_fields=['license_activated'])
                return redirect("license:activation_required")
        else:
            # Fallback to session-based check for non-tenant setups or public schema
            if not request.session.get("license_activated"):
                return redirect("license:activation_required")
            
            license_expiry = request.session.get("license_expiry")
            if license_expiry:
                try:
                    expiry_date = timezone.datetime.strptime(license_expiry, "%Y-%m-%d").date()
                    if timezone.now().date() > expiry_date:
                        request.session.flush()
                        return redirect("license:activation_required")
                except ValueError:
                    pass

        response = self.get_response(request)
        return response
