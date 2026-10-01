from django.contrib import messages
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

    @staticmethod
    def _license_blocks(license_activation, current_orders_count):
        """Return (blocks, reason) for the given license state."""
        from datetime import datetime

        from .check import is_license_valid

        license_expiry = license_activation.expiry_date.isoformat()
        license_max_orders = license_activation.max_orders

        if not is_license_valid(
            license_expiry, license_max_orders, current_orders_count
        ):
            try:
                expiry_date = datetime.strptime(
                    license_expiry, "%Y-%m-%d"
                ).date()
            except (TypeError, ValueError):
                return True, "invalid"
            if datetime.now().date() > expiry_date:
                return True, "expired"
            return True, "order-limit"
        return False, None

    def __call__(self, request):
        # Check if the path is exempt from license checking
        path = request.path_info

        for exempt_path in self.exempt_paths:
            if path.startswith(exempt_path):
                return self.get_response(request)

        license_activation = LicenseActivation.objects.filter(pk=1).first()
        if license_activation is None:
            return redirect("license:activation_required")

        # Get current orders count to check against usage limit
        from orders.models import ExamOrder

        current_orders_count = ExamOrder.objects.count()

        blocks, reason = self._license_blocks(
            license_activation, current_orders_count
        )
        if blocks:
            if reason == "order-limit":
                # The order-volume cap only restricts creating new exams;
                # unrelated modules such as inventory must keep working.
                response = self.get_response(request)
                if (
                    request.method == "POST"
                    and response.status_code in (301, 302, 303, 307, 308)
                    and "/activation-required" in response.url
                ):
                    # A view (e.g. @login_required) tried to bounce the user
                    # to the activation page because of a flushed session;
                    # make that dead-end explicit instead of silent.
                    messages.error(
                        request,
                        "Your session was closed because the license order "
                        "limit was reached. Please activate a new license "
                        "and retry your last action.",
                    )
                return response
            # Expired or invalid licenses lock the whole system.
            request.session.flush()
            messages.error(
                request,
                "Your license has expired or is no longer valid. Stock "
                "movements could not be saved until the system is "
                "re-activated.",
            )
            return redirect("license:activation_required")

        response = self.get_response(request)
        return response
