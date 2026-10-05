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

        Default policy: staff see their home facility (``user.facility``);
        multi-facility coverage via ``clinic.FacilityAssignment`` will be
        layered on in Phase 0 without changing this call signature.
        Superusers see everything.
        """
        if getattr(user, "is_superuser", False):
            return self.all()
        facility = getattr(user, "facility", None)
        if facility is None:
            return self.none()
        return self.filter(facility=facility)


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
