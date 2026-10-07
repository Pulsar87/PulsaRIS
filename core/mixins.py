"""Shared mixins for facility-scoped models.

Adopted decision (plan-clinicInformationSystem.prompt.md, addendum B.3):
one reusable scoping layer for both the new clinic module and a later
retrofit of existing patient/order/billing/report querysets.
"""

from django.db import models


class FacilityScopedQuerySet(models.QuerySet):
    """QuerySet with an explicit facility filter helper."""

    def for_facility(self, facility):
        return self.filter(facility=facility)

    def for_user(self, user):
        """Return rows visible to ``user``.

        Policy (Phase 0, addendum B.3): home facility (``user.facility``) plus
        every site with an active, non-expired ``clinic.FacilityAssignment``.
        Delegates to ``clinic.permissions.accessible_facility_ids`` so FBV,
        DRF and ORM paths share one implementation. Superusers are unrestricted.
        """
        from clinic.permissions import accessible_facility_ids

        ids = accessible_facility_ids(user)
        if ids is None:  # superuser: unrestricted
            return self.all()
        if not ids:
            return self.none()
        return self.filter(facility_id__in=ids)


class FacilityScopedModel(models.Model):
    """Abstract base: every operational record belongs to one Facility.

    Patients remain shared identity records (see patients/models.py) and
    deliberately do NOT use this mixin.
    """

    facility = models.ForeignKey(
        "core.Facility",
        on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s_set",
    )

    objects = FacilityScopedQuerySet.as_manager()

    class Meta:
        abstract = True
        indexes = [models.Index(fields=["facility"])]
