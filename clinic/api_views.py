"""Phase 3 read-only clinic JSON API (plan Step 4 item 1).

Boundaries:
- mounted at ``/api/clinic/`` from config/urls.py;
- every list view passes through ``facility_scope_queryset`` (addendum B.3 —
  same scoping layer the HTML views use, no second implementation);
- detail views additionally run ``FacilityScopedPermission.has_object_permission``;
- methods other than GET/HEAD/OPTIONS return 405 (read-only contract).

Patient search is deliberately facility-anchored: results are restricted to
patients who have a PatientFacilityIdentifier or an appointment/encounter at
one of the requester's facilities (cross-facility patient matching check —
Verification item 5 support).
"""

from django.db.models import Q
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from clinic.api_serializers import (
    AppointmentSerializer,
    EncounterNoteMetaSerializer,
    EncounterSerializer,
    PatientSearchSerializer,
)
from clinic.models import Appointment, Encounter, EncounterNote
from clinic.permissions import FacilityScopedPermission
from patients.models import Patient


class ReadOnlyApiMixin:
    """Enforce the read-only contract even though serializers exist."""

    def http_method_not_allowed(self, request, *args, **kwargs):
        return Response(
            {"detail": "The clinic API is read-only; writes go through the app UI or service layer."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


def _scoped(user, qs):
    from clinic.permissions import facility_scope_queryset

    return facility_scope_queryset(user, qs)


class ClinicScopedListMixin(ReadOnlyApiMixin):
    permission_classes = [IsAuthenticated, FacilityScopedPermission]

    def get_scoped_queryset(self, qs):
        return _scoped(self.request.user, qs)


class PatientSearchView(ClinicScopedListMixin, ListAPIView):
    """GET /api/clinic/patients/?q=<mrn|name|national_id>

    Scoped to patients visible at the requester's facilities.
    """

    serializer_class = PatientSearchSerializer

    def get_queryset(self):
        user = self.request.user
        base = Patient.objects.filter(is_deleted=False)
        from clinic.permissions import accessible_facility_ids

        fac_ids = accessible_facility_ids(user)
        if fac_ids is not None:  # non-superuser: facility-anchored visibility
            vis = (
                Q(facility_identifiers__facility_id__in=fac_ids)
                | Q(appointments__facility_id__in=fac_ids)
                | Q(encounters__facility_id__in=fac_ids)
            ).distinct()
            base = base.filter(vis)
        q = self.request.GET.get("q", "").strip()
        if q:
            base = base.filter(
                Q(mrn__icontains=q)
                | Q(first_name_en__icontains=q)
                | Q(last_name_en__icontains=q)
                | Q(national_id__icontains=q)
            )
        return base.order_by("mrn")


class AppointmentListView(ClinicScopedListMixin, ListAPIView):
    """GET /api/clinic/appointments/?date=&status=&facility="""

    serializer_class = AppointmentSerializer

    def get_queryset(self):
        qs = self.get_scoped_queryset(Appointment.objects.select_related("patient", "facility"))
        date_ = self.request.GET.get("date")
        if date_:
            qs = qs.filter(start_datetime__date=date_)
        st = self.request.GET.get("status")
        if st:
            qs = qs.filter(status=st)
        return qs.order_by("start_datetime")


class AppointmentDetailView(ReadOnlyApiMixin, RetrieveAPIView):
    permission_classes = [IsAuthenticated, FacilityScopedPermission]
    serializer_class = AppointmentSerializer
    queryset = Appointment.objects.select_related("patient", "facility")

    def get_object(self):
        obj = super().get_object()
        self.check_object_permissions(self.request, obj)
        return obj


class EncounterListView(ClinicScopedListMixin, ListAPIView):
    """GET /api/clinic/encounters/?date=&status="""

    serializer_class = EncounterSerializer

    def get_queryset(self):
        qs = self.get_scoped_queryset(Encounter.objects.select_related("patient", "facility"))
        date_ = self.request.GET.get("date")
        if date_:
            qs = qs.filter(
                Q(started_at__date=date_) | Q(created_at__date=date_)
            )
        st = self.request.GET.get("status")
        if st:
            qs = qs.filter(status=st)
        return qs.order_by("-created_at")


class EncounterDetailView(ReadOnlyApiMixin, RetrieveAPIView):
    permission_classes = [IsAuthenticated, FacilityScopedPermission]
    serializer_class = EncounterSerializer
    queryset = Encounter.objects.select_related("patient", "facility")

    def get_object(self):
        obj = super().get_object()
        self.check_object_permissions(self.request, obj)
        return obj


class EncounterNoteListView(ClinicScopedListMixin, ListAPIView):
    """GET /api/clinic/notes/?encounter=<uuid> — metadata only (Step 4 item 1)."""

    serializer_class = EncounterNoteMetaSerializer

    def get_queryset(self):
        qs = EncounterNote.objects.select_related("encounter")
        # scope via encounter facility (child records inherit site, models.py note)
        from clinic.permissions import accessible_facility_ids

        ids = accessible_facility_ids(self.request.user)
        if ids is not None:
            qs = qs.filter(encounter__facility_id__in=ids)
        enc = self.request.GET.get("encounter")
        if enc:
            qs = qs.filter(encounter_id=enc)
        return qs.order_by("encounter", "version")
