"""Declarative registry of the app's feature modules (Clinic, RIS, PACS, ...).

Single source of truth for:

* **Enable / disable** – ``settings.ENABLED_MODULES`` (populated from the
  ``DJANGO_ENABLED_MODULES`` env var, comma-separated) decides which modules
  are active.  A module whose Django app is not installed can never be
  enabled; a disabled module gets no nav entry and no card in the module
  picker (its URLs additionally return 404 via ``core.middleware.ModuleGateMiddleware``).
* **Navigation & browsing** – templates read the registry through the
  ``core.context_processors.modules`` context processor, so adding a new
  module means adding one entry to ``MODULES`` below.
* **License sync** – license feature names map to module keys with
  ``MODULE_KEYS_BY_LICENSE_FEATURE``.

To add a new module:

1. Make sure its app is in ``INSTALLED_APPS`` (conditionally, e.g. driven by
   the license – see ``config/settings/base.py``).
2. Give its URLconf an ``app_name`` namespace.
3. Add an entry to ``MODULES`` with label/icon/description and either a
   namespaced landing route (``"clinic:appointment_list"``) or a plain
   top-level url name (``"worklist"``), plus optional dropdown ``items``.
"""

from django.apps import apps
from django.conf import settings
from django.urls import NoReverseMatch, reverse

# ─────────────────────────────────────────────────────────────
# Module catalogue (display metadata only – enablement is runtime)
# ─────────────────────────────────────────────────────────────
MODULES = [
    {
        "key": "ris",
        "label": "RIS",
        "icon": "bi-clipboard2-pulse",
        "description": "Radiology workflow: orders, worklist and reports.",
        "url": "worklist",            # top-level route in config/urls.py
        "always_enabled": True,       # core workflow – cannot be switched off
        "items": [
            {"label": "Worklist", "url": "worklist"},
            {"label": "Reports", "url": "reports:report_list"},
        ],
    },
    {
        "key": "patients",
        "label": "Patients",
        "icon": "bi-people",
        "description": "Patient master index.",
        "url": "patients:patient_list",
        "items": [],
    },
    {
        "key": "clinic",
        "label": "Clinic",
        "icon": "bi-hospital",
        "description": "Clinic information system: appointments, encounters, clinical records.",
        "url": "clinic:appointment_list",
        "items": [],  # clinic keeps its own rollout-gated submenu in layout.html
    },
    {
        "key": "pacs",
        "label": "PACS",
        "icon": "bi-display",
        "description": "Imaging archive: study browsing, reconciliation, Orthanc sync.",
        "url": "pacs:study_list",
        "items": [
            {"label": "Studies", "url": "pacs:study_list"},
            {"label": "Diagnostics", "url": "pacs:diagnostics"},
        ],
    },
    {
        "key": "billing",
        "label": "Billing",
        "icon": "bi-cash-stack",
        "description": "Financial module: claims, payments, fee schedules.",
        "url": "billing:fee_schedule_list",
        "items": [],
    },
    {
        "key": "inventory",
        "label": "Inventory",
        "icon": "bi-box-seam",
        "description": "Radiology consumables inventory.",
        "url": "inventory:dashboard",
        "items": [],
    },
    {
        "key": "dashboard",
        "label": "Dashboard",
        "icon": "bi-speedometer2",
        "description": "Statistics and charts across enabled modules.",
        "url": "dashboard:dashboard_stats",
        "items": [],
    },
]

# License feature names -> module keys they unlock (consumed when translating
# licensed features into app/module sets).
MODULE_KEYS_BY_LICENSE_FEATURE = {
    "RIS": ["ris", "patients", "orders", "reports", "dashboard"],
    "CLINIC": ["clinic"],
    "PACS": ["pacs"],
    "BILLING": ["billing"],
    "INVENTORY": ["inventory"],
}


# ─────────────────────────────────────────────────────────────
# Enablement
# ─────────────────────────────────────────────────────────────
def _installed_app_names():
    return {c.name.split(".")[-1] for c in apps.get_app_configs()}


def configured_enabled_keys():
    """Explicit allow-list from settings/env, or ``None`` when unset.

    ``DJANGO_ENABLED_MODULES=clinic,pacs,billing`` in .env →
    ``settings.ENABLED_MODULES``.  Unset means "every installed module is
    enabled" so existing deployments keep working unchanged.
    """
    configured = getattr(settings, "ENABLED_MODULES", None)
    if configured is None:
        return None
    return {str(k).strip().lower() for k in configured if str(k).strip()}


def enabled_keys():
    """Keys of all currently-enabled modules."""
    installed = _installed_app_names()
    explicit = configured_enabled_keys()
    keys = set()
    for meta in MODULES:
        key = meta["key"]
        if key not in installed:
            continue  # app uninstalled (e.g. not licensed) → never enabled
        if meta.get("always_enabled"):
            keys.add(key)
        elif explicit is None or key in explicit:
            keys.add(key)
    return keys


def is_enabled(key):
    return key in enabled_keys()


# ─────────────────────────────────────────────────────────────
# Resolution helpers (reverse URLs defensively)
# ─────────────────────────────────────────────────────────────
def resolve_url(target):
    """Best-effort ``reverse()``; returns '' when the route doesn't exist
    (e.g. a module whose app was removed from INSTALLED_APPS)."""
    if not target:
        return ""
    try:
        return reverse(target)
    except NoReverseMatch:
        return ""


def get_modules(request=None):
    """Full catalogue with display data, enabled flag and resolved URLs."""
    out = []
    for meta in MODULES:
        item = dict(meta)
        item["enabled"] = meta["key"] in enabled_keys()
        item["resolved_url"] = resolve_url(meta.get("url"))
        items = []
        for sub in meta.get("items", []):
            s = dict(sub)
            s["resolved_url"] = resolve_url(sub.get("url"))
            if s["resolved_url"]:  # drop dead links
                items.append(s)
        item["resolved_items"] = items
        out.append(item)
    return out


def get_enabled_modules(request=None):
    return [m for m in get_modules(request) if m["enabled"]]


def get_nav_modules(request=None):
    """Modules eligible for nav/picker UIs (enabled + routable)."""
    return [m for m in get_enabled_modules(request) if m["resolved_url"]]


def license_features_to_module_keys(features):
    """Map an iterable of license feature names to the module keys they unlock."""
    keys = set()
    for f in features or ():
        keys.update(MODULE_KEYS_BY_LICENSE_FEATURE.get(str(f).upper(), []))
    return keys
