"""URLconf for the Phase 3 read-only clinic JSON API.

Included from config/urls.py at ``api/clinic/`` (no app namespace so the
main clinic HTML namespace stays untouched).
"""

from clinic import api_views
from django.urls import path

urlpatterns = [
    path("patients/", api_views.PatientSearchView.as_view(), name="api_patients"),
    path("appointments/", api_views.AppointmentListView.as_view(), name="api_appointments"),
    path(
        "appointments/<uuid:pk>/",
        api_views.AppointmentDetailView.as_view(),
        name="api_appointment_detail",
    ),
    path("encounters/", api_views.EncounterListView.as_view(), name="api_encounters"),
    path(
        "encounters/<uuid:pk>/",
        api_views.EncounterDetailView.as_view(),
        name="api_encounter_detail",
    ),
    path("notes/", api_views.EncounterNoteListView.as_view(), name="api_notes"),
]
