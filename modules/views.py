from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core import module_registry


@login_required
def module_browser(request):
    """Modern "app launcher": grid of every enabled module."""
    context = {
        "enabled_modules": module_registry.get_enabled_modules(request),
    }
    return render(request, "modules/browser.html", context)
