"""Gate disabled modules at the URL layer.

When ``settings.ENABLED_MODULES`` explicitly excludes a module, any request
whose resolved URL namespace matches that module's key returns 404 — the app
keeps its routes registered (so re-enabling needs no redeploy of code, just
the env/settings change) but they are unreachable while disabled.

Core/shared namespaces (auth, admin, i18n, license, users, orders, reports,
dashboard…) are never gated; only keys present in the registry catalogue can
be switched off this way.
"""

from django.http import Http404

from core import module_registry


class ModuleGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Gate *after* resolution so we know the matched namespace.
        resolver = getattr(request, "resolver_match", None)
        if resolver is None:
            return response
        ns = getattr(resolver, "namespace", None) or getattr(
            resolver, "app_name", None
        )
        root = ns.split(":")[0] if ns else None
        if (
            root
            and module_registry.configured_enabled_keys() is not None
            and root in {m["key"] for m in module_registry.MODULES}
            and not module_registry.is_enabled(root)
            and response.status_code == 200
        ):
            raise Http404("This module is disabled.")
        return response
