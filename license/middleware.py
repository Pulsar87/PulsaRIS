from django.shortcuts import redirect

from .check import is_license_valid
from .models import LicenseActivation


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
            "/users/login/",
            "/users/logout/",
        ]

    def __call__(self, request):
        # Check if the path is exempt from license checking
        path = request.path_info

        for exempt_path in self.exempt_paths:
            if path.startswith(exempt_path):
                return self.get_response(request)

        license_activation = LicenseActivation.objects.filter(pk=1).first()
        if license_activation is None:
            return redirect("license:activation_required")

        license_expiry = license_activation.expiry_date.isoformat()
        license_max_orders = license_activation.max_orders
        
        if license_expiry or license_max_orders is not None:
            # Get current orders count to check against usage limit
            from orders.models import ExamOrder
            current_orders_count = ExamOrder.objects.count()
            
            # Use the unified license validation function
            if not is_license_valid(license_expiry, license_max_orders, current_orders_count):
                request.session.flush()
                return redirect("license:activation_required")

        response = self.get_response(request)
        return response
