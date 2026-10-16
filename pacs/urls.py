"""URL routes for the PACS module (PACS plan Phase 4).

All routes are namespaced under ``pacs:`` and served from ``/pacs/`` in
``config/urls.py``. Views enforce facility scoping, login, and (for
reconciliation/diagnostics) server-side permission checks; the URL layer
intentionally adds no trust of its own beyond stable, guess-resistant
patterns (UUID pks, validated Orthanc instance ids).
"""

from django.urls import path

from pacs import views

app_name = "pacs"

urlpatterns = [
    # Task 4.1 — facility-scoped study list (searchable, paginated).
    path("", views.study_list, name="study_list"),
    # Task 4.1 — study detail page (linkage, counts, archive state).
    path("studies/<uuid:pk>/", views.study_detail, name="study_detail"),
    # Task 3.3/4.1 — gated reconciliation actions (POST only).
    path(
        "studies/<uuid:pk>/action/",
        views.study_action,
        name="study_action",
    ),
    # Task 4.2 — authorized DICOM retrieval proxy (study ZIP).
    path(
        "studies/<uuid:pk>/retrieve/",
        views.retrieve_dicom,
        name="retrieve_dicom",
    ),
    # Task 4.2 — single-instance retrieval; id validated by the view.
    path(
        "studies/<uuid:pk>/instances/<str:instance_id>/file/",
        views.instance_file,
        name="instance_file",
    ),
    # Task 4.1 — staff-only system diagnostics (no payloads, no secrets).
    path("diagnostics/", views.diagnostics, name="diagnostics"),
]
