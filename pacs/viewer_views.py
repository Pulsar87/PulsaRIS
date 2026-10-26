"""OHIF viewer integration (PACS plan Task 4.3 — optional DICOMweb viewer).

Serves the pinned, prebuilt OHIF standalone bundle *same-origin* under
``/static/ohif/`` and renders it full-screen for one study at a time. Design
decisions, all traceable to the plan:

- Per-study entry point: the StudyInstanceUID is resolved only through the
  user's facility-scoped studies, and images/metadata are fetched through
  the audited Django DICOMweb proxy — the browser never receives Orthanc
  credentials or internal URLs (plan §3 trust boundary, Task 4.2 retrieval
  rules).
- Access control identical to the existing retrieval views: facility-scoped
  mirror row lookup first (404 across facilities), audit record before any
  pixel data flows.
- The static bundle itself contains no PHI and no secrets; configuration is
  injected per request via ``window.config`` in the template.
"""

import logging

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from clinic.permissions import record_audit
from pacs import dicomweb_proxy, reconciliation
from pacs.dicom_uid import is_valid_dicom_uid
from pacs.models import StudyStatus
from pacs.views import _no_phi_cache, _study_or_404

logger = logging.getLogger(__name__)


@require_GET
@login_required
def study_viewer(request, pk, study_uid=None):
    """Full-screen OHIF page bound to one facility-scoped study."""
    study = _study_or_404(request, pk)

    if study_uid is not None and study_uid != study.study_instance_uid:
        raise Http404

    return _render_study_viewer(request, study)


@require_GET
@login_required
def study_viewer_by_uid(request, study_uid):
    """Serve OHIF's native ``/viewer/:studyInstanceUIDs`` route safely."""
    if not is_valid_dicom_uid(study_uid):
        raise Http404
    study = reconciliation.scoped_studies(request.user).filter(
        study_instance_uid=study_uid
    ).first()
    if study is None:
        raise Http404
    return _render_study_viewer(request, study)


@require_GET
@login_required
def study_viewer_query(request):
    """Accept a query-string study link and redirect to OHIF's native route."""
    uid_values = (
        request.GET.getlist("studyInstanceUIDs")
        + request.GET.getlist("StudyInstanceUIDs")
    )
    study_uid = uid_values[0].strip() if len(uid_values) == 1 else ""
    if not is_valid_dicom_uid(study_uid):
        return HttpResponse(
            "A single valid StudyInstanceUIDs value is required.",
            status=400,
        )

    study = reconciliation.scoped_studies(request.user).filter(
        study_instance_uid=study_uid
    ).first()
    if study is None:
        raise Http404
    return redirect("pacs:study_viewer_uid", study_uid=study.study_instance_uid)


@require_GET
@login_required
def study_slicer3d(request, pk):
    """Advanced 3D Slicer / SlicerMZ page for one facility-scoped study.

    Loads the *entire* study (all series) into the browser-side medical
    imaging toolkit and enables the advanced "3D Slicer" workflows
    (volume rendering, multi-planar reconstruction, segment editor) via the
    Slicer/Medical Imaging Interaction extension. Same trust model as the
    OHIF route: facility-scoped study lookup, audit before any pixel data
    flows, and all image traffic through the audited DICOMweb proxy.
    """
    study = _study_or_404(request, pk)
    return _render_slicer3d(request, study)


@require_GET
@login_required
def study_slicer3d_by_uid(request, study_uid):
    """Deep-linkable entry point for the 3D Slicer advanced viewer."""
    if not is_valid_dicom_uid(study_uid):
        raise Http404
    study = reconciliation.scoped_studies(request.user).filter(
        study_instance_uid=study_uid
    ).first()
    if study is None:
        raise Http404
    return _render_slicer3d(request, study)


def _render_study_viewer(request, study):
    """Render the configured OHIF application for an authorized study."""
    if not study.orthanc_study_id or study.status == StudyStatus.RECEIVED:
        # Not synced into the archive yet — nothing for the viewer to show.
        return redirect("pacs:study_detail", pk=study.pk)

    record_audit(
        request,
        "pacs.viewer_open",
        entity_type="PACSStudy",
        entity_id=str(study.pk),
        old=None,
        new={"accession": study.accession_number, "viewer": "ohif"},
    )

    # OHIF expects roots at the DICOMweb service level and appends
    # /studies[/<StudyInstanceUID>...]. The opaque Orthanc id is a separate
    # scope segment consumed by Django, not forwarded to Orthanc.
    proxy_root = reverse(
        "pacs:dicomweb_proxy",
        kwargs={"scope_id": study.orthanc_study_id, "path": ""},
    ).rstrip("/")
    router_basename = reverse("pacs:study_list").rstrip("/")

    context = {
        "study": study,
        "qido_root": proxy_root,
        "wado_root": proxy_root,
        "router_basename": router_basename,
        "ohif_static_url": static("ohif/index.umd.js"),
    }
    response = render(request, "pacs/viewer.html", context)
    return _no_phi_cache(response)


def _render_slicer3d(request, study):
    """Render the advanced 3D Slicer (SlicerMZ) page for an authorized study.

    Reuses the pinned OHIF bundle (which ships the VTK.js-backed 3D Slicer /
    volume-rendering extension) but configures it with the TMTV/3D-Slicer
    mode so the whole study loads into the advanced workstation. Images are
    fetched exclusively through the same audited DICOMweb proxy as the
    standard viewer — no archive credentials reach the browser.
    """
    if not study.orthanc_study_id or study.status == StudyStatus.RECEIVED:
        # Not synced into the archive yet — nothing for the viewer to show.
        return redirect("pacs:study_detail", pk=study.pk)

    record_audit(
        request,
        "pacs.viewer_open",
        entity_type="PACSStudy",
        entity_id=str(study.pk),
        old=None,
        new={"accession": study.accession_number, "viewer": "slicer3d"},
    )

    proxy_root = reverse(
        "pacs:dicomweb_proxy",
        kwargs={"scope_id": study.orthanc_study_id, "path": ""},
    ).rstrip("/")
    router_basename = reverse("pacs:study_list").rstrip("/")

    context = {
        "study": study,
        "qido_root": proxy_root,
        "wado_root": proxy_root,
        "router_basename": router_basename,
        "ohif_static_url": static("ohif/index.umd.js"),
        "slicer_viewer_url": reverse(
            "pacs:study_viewer", kwargs={"pk": study.pk}
        ),
    }
    response = render(request, "pacs/viewer_3d_slicer.html", context)
    return _no_phi_cache(response)


@csrf_exempt  # DICOMweb clients do not send Django CSRF tokens; auth is the session.
@login_required
def dicomweb_proxy_view(request, scope_id, path=""):
    """Audited QIDO-RS/WADO-RS proxy: browser ⇄ Django ⇄ private Orthanc.

    ``scope_id`` pins every request to the Orthanc study that opened this
    viewer; ``path`` contains the standard DICOMweb route from OHIF.
    """
    segments = [s for s in path.split("/") if s]
    try:
        status, headers, body = dicomweb_proxy.fetch(
            request,
            scope_id,
            segments,
            request.META.get("QUERY_STRING", ""),
        )
    except dicomweb_proxy.DicomWebRequestError as exc:
        resp = HttpResponse(exc.detail or "", status=exc.status)
        return _no_phi_cache(resp)

    # Audit once per study-level metadata/pixel fetch group? Keep volume sane:
    # audit only WADO instance-file retrievals (bulk pixel access), not every
    # metadata call the viewer makes while scrolling.
    if len(segments) >= 4 and segments[-1] == "file":
        study = reconciliation.scoped_studies(request.user).filter(
            orthanc_study_id=scope_id
        ).first()
        if study is not None:
            record_audit(
                request,
                "pacs.dicom_retrieve",
                entity_type="PACSStudy",
                entity_id=str(study.pk),
                old=None,
                new={"kind": "dicomweb-wado", "instance_path": "/".join(segments)[:200]},
            )

    resp = HttpResponse(body, status=status, content_type=headers.get("Content-Type"))
    for k, v in headers.items():
        if k.lower() != "content-type":
            resp[k] = v
    return _no_phi_cache(resp)
