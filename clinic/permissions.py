"""Facility-scoping permission helpers for the clinic module.

Adopted decision (plan addendum B.3): a single reusable scoping layer applied
first to new clinic models, then retrofitted to patients/orders/billing/reports.

API:
- ``accessible_facility_ids(user)`` -> set of Facility PKs the user may act in
  (home facility via ``User.facility`` + every active, non-expired
  ``FacilityAssignment``; superusers get ``None`` = unrestricted).
- ``has_facility_access(user, facility_id)`` -> bool
- ``facility_scope_queryset(user, qs)`` -> rows whose ``facility`` FK is in the
  user's accessible set.
- ``role_required(*roles)`` / ``facility_scoped_view`` decorators — Phase 1
  Step 2.6 route enforcement for function-based views.
- ``record_audit(request, ...)`` -> custom ``audit`` app row (django-auditlog
  middleware already logs model changes; see addendum A.4 — no third path).
- ``FacilityScopedPermission`` (DRF): shared object-level check.
"""

from datetime import date
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from audit.models import AuditLog
from clinic.models import FacilityAssignment


def accessible_facility_ids(user):
    """Return a set of Facility PKs the user may access, or None for superuser
    (None means 'unrestricted' — callers should skip filtering)."""
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return None  # unrestricted

    today = date.today()
    ids = set()
    if getattr(user, "facility_id", None):
        ids.add(user.facility_id)
    ids.update(
        FacilityAssignment.objects.filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today),
            is_active=True,
            user=user,
        ).values_list("facility_id", flat=True)
    )
    return ids


def has_facility_access(user, facility_id):
    ids = accessible_facility_ids(user)
    if ids is None:  # superuser
        return True
    return facility_id in ids


def facility_scope_queryset(user, queryset):
    """Filter a queryset having a `facility` FK down to the user's sites."""
    ids = accessible_facility_ids(user)
    if ids is None:
        return queryset
    return queryset.filter(facility_id__in=ids)


# ── Route guards (Phase 1 Step 2.6: enforcement on every clinic route) ────


def role_required(*roles):
    """Restrict a view to users whose active FacilityAssignment role matches
    one of ``roles`` (e.g. "PROVIDER"). Any authenticated staff member with a
    home facility passes as RECEPTIONIST-capable; superusers always pass."""

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if user.is_superuser:
                return view_func(request, *args, **kwargs)
            user_roles = set()
            assignments = FacilityAssignment.objects.filter(
                user=user, is_active=True,
            ).filter(Q(end_date__isnull=True) | Q(end_date__gte=date.today()))
            user_roles.update(assignments.values_list("role_at_facility", flat=True))
            if getattr(user, "facility_id", None):
                user_roles.add("RECEPTIONIST")
            if user.is_staff:
                user_roles.add("ADMIN")
            if roles and not (user_roles & set(roles)):
                raise PermissionDenied("This clinic function requires a staff role.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def facility_scoped_view(view_func):
    """Decorator: resolve the target facility from kwargs/POST/GET
    (``facility`` pk) and require the user has access to it. Use together
    with ``role_required`` on routes that act on a specific site."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        fid = (
            kwargs.get("facility_id")
            or request.POST.get("facility")
            or request.GET.get("facility")
        )
        if fid and not has_facility_access(request.user, fid):
            raise PermissionDenied("No access to this facility.")
        return view_func(request, *args, **kwargs)

    return _wrapped


def record_audit(request, action, *, entity_type, entity_id, old=None, new=None):
    """Write to the custom ``audit`` app (django-auditlog middleware covers
    model changes automatically; see addendum A.4 — do not build a third path)."""
    AuditLog.objects.create(
        user=request.user
        if getattr(request, "user", None) and request.user.is_authenticated
        else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_values=old or {},
        new_values=new or {},
        ip_address=request.META.get("REMOTE_ADDR", "127.0.0.1"),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )


try:  # optional DRF integration — package already installed in requirements
    from rest_framework.permissions import BasePermission

    class FacilityScopedPermission(BasePermission):
        """DRF permission: object must expose `.facility` (or `.facility_id`)
        within the requesting user's accessible facilities."""

        def has_permission(self, request, view):
            return bool(request.user and request.user.is_authenticated)

        def has_object_permission(self, request, view, obj):
            facility_id = getattr(obj, "facility_id", None)
            if facility_id is None:
                return True  # not a facility-scoped record; other perms apply
            return has_facility_access(request.user, facility_id)

except ImportError:  # pragma: no cover - DRF absent
    FacilityScopedPermission = None
