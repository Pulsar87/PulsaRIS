"""Facility-scoping permission helpers for the clinic module.

Adopted decision (plan addendum B.3): a single reusable scoping layer applied
first to new clinic models, then retrofitted to patients/orders/billing/reports.

API:
- ``accessible_facilities(user)`` -> set of Facility ids the user may act in
  (home facility via ``User.facility`` + every active, non-expired
  ``FacilityAssignment``; superusers get all active facilities).
- ``has_facility_access(user, facility_id)`` -> bool
- ``facility_scope_queryset(user, qs)`` -> rows whose ``facility`` FK is in the
  user's accessible set (qs must have a ``facility`` field, e.g. any
  ``core.mixins.FacilityScopedModel`` subclass or existing models with a
  ``facility`` column).
- ``FacilityScopedPermission`` (DRF base_permission stub): enforced once DRF
  views are added in Phase 1; logic lives in ``has_facility_access`` so both
  FBV and DRF paths share one implementation.
"""

from datetime import date

from django.db.models import Q

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
