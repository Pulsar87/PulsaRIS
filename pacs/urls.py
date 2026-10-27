"""URL routes for the PACS module (PACS plan Phase 4).

All routes are namespaced under ``pacs:`` and served from ``/pacs/`` in
``config/urls.py``. Views enforce facility scoping, login, and (for
reconciliation/diagnostics) server-side permission checks; the URL layer
intentionally adds no trust of its own beyond stable, guess-resistant
patterns (UUID pks, validated Orthanc instance ids).
"""

from django.urls import path, re_path

from pacs import viewer_views, views

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
    # Task 4.3 — embedded OHIF viewer page for one scoped study.
    path(
        "studies/<uuid:pk>/viewer/",
        viewer_views.study_viewer,
        name="study_viewer",
    ),
    # OHIF's study route must also resolve on refresh/deep-link navigation.
    path(
        "studies/<uuid:pk>/viewer/viewer/<str:study_uid>",
        viewer_views.study_viewer,
        name="study_viewer_study",
    ),
    # Standard OHIF route: routerBasename="/pacs" + /viewer/:studyInstanceUIDs.
    re_path(
        r"^viewer/(?P<study_uid>[0-9.]+)$",
        viewer_views.study_viewer_by_uid,
        name="study_viewer_uid",
    ),
    # Advanced viewer — 3D Slicer (SlicerMZ) workstation for one scoped study.
    path(
        "studies/<uuid:pk>/viewer/3d-slicer/",
        viewer_views.study_slicer3d,
        name="study_slicer3d",
    ),
    # Deep-linkable entry point for the advanced 3D Slicer viewer.
    re_path(
        r"^viewer/3d-slicer/(?P<study_uid>[0-9.]+)$",
        viewer_views.study_slicer3d_by_uid,
        name="study_slicer3d_uid",
    ),
    # Advanced viewer data feed: PHI-light volume manifest (geometry tags +
    # proxy-relative file URLs) consumed by the 3D Slicer workstation page.
    path(
        "studies/<uuid:pk>/viewer/3d-slicer/manifest/",
        viewer_views.study_slicer3d_manifest,
        name="study_slicer3d_manifest",
    ),
    # Advanced viewer data feed: every original DICOM file of the study as one
    # multipart/related body, so the workstation can open *any* image series
    # (single-slice projections included), independent of transfer syntax.
    path(
        "studies/<uuid:pk>/viewer/3d-slicer/files/",
        viewer_views.study_slicer3d_files,
        name="study_slicer3d_files",
    ),
    # Query-string entry point retained for links such as
    # /pacs/viewer?studyInstanceUIDs=<UID>; it redirects to OHIF's native route.
    re_path(
        r"^viewer/?$",
        viewer_views.study_viewer_query,
        name="study_viewer_query",
    ),
    # Task 4.3 — audited QIDO-RS/WADO-RS proxy used by the OHIF bundle.
    # ``scope_id`` pins the proxy to one Orthanc study; ``path`` is the
    # standard DICOMweb path appended by OHIF (e.g. studies/<UID>/metadata).
    re_path(
        r"^viewer/dicomweb/(?P<scope_id>[A-Za-z0-9_-]{1,64})/(?P<path>.*)$",
        viewer_views.dicomweb_proxy_view,
        name="dicomweb_proxy",
    ),
    # Task 4.1 — staff-only system diagnostics (no payloads, no secrets).
    path("diagnostics/", views.diagnostics, name="diagnostics"),
]
