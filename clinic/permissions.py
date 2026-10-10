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
from django.shortcuts import get_object_or_404

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
    with ``role_required`` on routes that act on a specific site.

    Phase 4 (plan Step 5.3 rollback): also enforces the per-facility clinic
    feature flag — requests targeting a site that is not rolled out yet are
    denied for non-superusers."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        fid = (
            kwargs.get("facility_id")
            or request.POST.get("facility")
            or request.GET.get("facility")
        )
        if fid and not has_facility_access(request.user, fid):
            raise PermissionDenied("No access to this facility.")
        enforce_rollout_gate(request, kwargs, explicit_facility_id=fid)
        return view_func(request, *args, **kwargs)

    return _wrapped


def gated_detail_view(model):
    """Phase 4 (Step 5.3): rollout gate for object-resolving detail/action
    views that look a record up by ``pk`` from a facility-scoped queryset.

    Applies the per-facility clinic feature flag against the resolved
    object's own ``facility_id`` before the view body runs — one shared
    implementation layered on top of ``facility_scope_queryset``
    (addendum B.3), never a second scoping system::

        @role_required("PROVIDER", "ADMIN")
        @gated_detail_view(Encounter)
        def encounter_detail(request, pk): ...

    Records without a ``facility`` FK are not gated here; other permissions
    still apply.
    """

    def resolve(request, pk):
        return get_object_or_404(facility_scope_queryset(request.user, model.objects.all()), pk=pk)

    return _gate_on_resolved_object(resolve)


def gated_note_view(note_model):
    """Variant of :func:`gated_detail_view` for versioned note rows whose
    site lives on the parent encounter (``note.encounter.facility``)."""

    def resolve(request, pk):
        note = get_object_or_404(note_model.objects.select_related("encounter"), pk=pk)
        return note.encounter

    return _gate_on_resolved_object(resolve)


def _gate_on_resolved_object(resolve):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            obj = resolve(request, **kwargs)
            enforce_rollout_gate(request, kwargs, obj=obj)
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def enforce_rollout_gate(request, kwargs=None, *, explicit_facility_id=None,
                         obj=None):
    """Phase 4 per-facility feature flag check (Step 5.3 rollback plan).

    Denies access when every facility implicated by the request belongs to a
    site whose clinic module is not rolled out. If no facility can be inferred
    (e.g. a global list view), fall back to the user's home facility so the
    flag still bites for single-site staff; superusers bypass entirely so ops
    can always repair flag state."""
    from clinic import rollout

    if rollout.user_can_bypass_gate(getattr(request, "user", None)):
        return
    ids = [
        f for f in (
            [explicit_facility_id]
            + rollout.request_facility_ids(request, kwargs)
            + ([obj.facility_id] if obj is not None and getattr(obj, "facility_id", None) else [])
        ) if f
    ]
    if not ids and getattr(request.user, "facility_id", None):
        ids = [request.user.facility_id]
    if ids and not any(rollout.facility_clinic_enabled(f) for f in ids):
        raise PermissionDenied("Clinic module is not enabled at this facility yet.")


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


def record_audit_service(action, *, entity_type, entity_id, user=None, old=None, new=None):
    """Service-layer variant of ``record_audit`` for calls outside a request
    (Phase 2 encounter/note services in clinic/scheduling.py)."""
    AuditLog.objects.create(
        user=user if getattr(user, "pk", None) else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_values=old or {},
        new_values=new or {},
        ip_address="127.0.0.1",
        user_agent="service",
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
