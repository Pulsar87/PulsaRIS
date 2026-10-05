"""Facility-scoping permission helpers for the clinic module.

Adopted decision (plan addendum B.3): a single reusable scoping layer applied
first to new clinic models, then retrofitted to patients/orders/billing/reports.

Phase 0 will implement:
- FacilityScopedPermission (DRF): request.user must have an active
  FacilityAssignment (or home User.facility) matching the record's facility.
- facility_scope_queryset(user, qs): filter helper for function-based views.
"""
