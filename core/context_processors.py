"""Global template context for the modular UI (nav + module picker).

Exposes ``enabled_modules`` (list of enabled, routable modules with resolved
URLs) to every template rendered with a RequestContext, driven by
``core.module_registry``.  Views/templates must never hard-code module lists –
adding or disabling a module is a registry/settings change only.
"""

from core import module_registry


def modules(request):
    return {
        "enabled_modules": module_registry.get_nav_modules(request),
        "all_modules": module_registry.get_modules(request),
    }
