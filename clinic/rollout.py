"""Per-facility clinic feature flag (Phase 4, plan Step 5.3 rollback plan).

Rollback for multi-site rollout is *disable the clinic URLs for one facility*
without a redeploy. A site is "live" when it has at least one active
``FacilityAssignment`` whose role is in ``LIVE_ROLES`` (ADMIN by default) and
whose ``start_date`` has been reached — i.e. ``seed_site`` provisions a site,
but the site only opens once an ADMIN assignment goes live for it. Removing /
deactivating that assignment (or setting a future start date) closes the site
again: every clinic HTML view, the read-only API, and the outbox consumer
check this gate before doing facility work.

Superusers are never gated so operations can always reach the modules to fix
a mis-flagged site.
"""

from datetime import date

from clinic.models import FacilityAssignment

# Roles whose presence marks a facility as rolled-out. Extend via settings:
# CLINIC_ROLLOUT_LIVE_ROLES = ["ADMIN", "PROVIDER"]
DEFAULT_LIVE_ROLES = ("ADMIN",)


def live_roles():
    from django.conf import settings

    return tuple(getattr(settings, "CLINIC_ROLLOUT_LIVE_ROLES", DEFAULT_LIVE_ROLES))


def facility_clinic_enabled(facility_id):
    """True if the facility has a live (active, started) assignment in a
    rollout role."""
    if facility_id is None:
        return False
    today = date.today()
    return FacilityAssignment.objects.filter(
        facility_id=facility_id,
        is_active=True,
        role_at_facility__in=live_roles(),
        start_date__lte=today,
    ).exists()


def enabled_facility_ids():
    """All currently-live facility PKs (rollout dashboard / health output)."""
    today = date.today()
    return set(
        FacilityAssignment.objects.filter(
            is_active=True,
            role_at_facility__in=live_roles(),
            start_date__lte=today,
        ).values_list("facility_id", flat=True)
    )


def user_can_bypass_gate(user):
    """Superusers can always browse clinic pages even at disabled sites so
    they can repair flag state; everyone else is gated."""
    return bool(user and user.is_authenticated and user.is_superuser)


def request_facility_ids(request, kwargs=None):
    """Best-effort extraction of the facility id(s) a request targets:
    URL kwargs, POST/GET ``facility``, or the object's own facility FK
    resolved by the caller beforehand (passed via ``kwargs['facility_pk']``).
    Returns a list (possibly empty -> caller falls back to the user's home
    facility)."""
    kwargs = kwargs or {}
    fid = kwargs.get("facility_pk") or request.POST.get("facility") or request.GET.get("facility")
    return [fid] if fid else []


def clinic_nav_visible(user):
    """Whether the Clinic menu should appear in the global layout nav.

    Shown when the user can actually reach at least one rolled-out site:
    superusers always (ops bypass), otherwise any facility they can access
    must pass the per-facility rollout gate. Anonymous users never see it.
    Keeps disabled sites' links out of the chrome entirely (Step 5.3 flag is
    the single source of truth — no separate nav setting)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    from clinic.permissions import accessible_facility_ids

    ids = accessible_facility_ids(user)
    if ids is None:  # unrestricted (superuser handled above anyway)
        return True
    live = enabled_facility_ids()
    return bool(ids & live)
