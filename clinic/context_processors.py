"""Template context for the global layout nav.

Exposes ``clinic_nav`` to every template rendered with a RequestContext so
``templates/layout.html`` can show/hide the Clinic dropdown using the same
per-facility rollout flag that gates the views themselves (Step 5.3) — one
source of truth, no separate nav setting.
"""


def clinic_nav(request):
    from clinic import rollout

    return {
        "clinic_nav": {
            "visible": rollout.clinic_nav_visible(getattr(request, "user", None)),
        }
    }
