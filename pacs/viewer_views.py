"""OHIF viewer integration (PACS plan Task 4.3 — optional DICOMweb viewer).

Serves the pinned, prebuilt OHIF standalone bundle *same-origin* under
``/static/ohif/`` and renders it full-screen for one study at a time. Design
decisions, all traceable to the plan:

- Per-study entry point (``/pacs/studies/<uuid>/viewer/``): the viewer is
  opened from an authorized PACS study page, never as a free-standing study
  list. The StudyInstanceUID travels in the URL hash only (not logs of other
  apps), and images/metadata are fetched through the audited Django DICOMweb
  proxy — the browser never receives Orthanc credentials or internal URLs
  (plan §3 trust boundary, Task 4.2 retrieval rules).
- Access control identical to the existing retrieval views: facility-scoped
  mirror row lookup first (404 across facilities), audit record before any
  pixel data flows.
- The static bundle itself contains no PHI and no secrets; configuration is
  injected per request via ``window.config`` in the template.
"""

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from clinic.permissions import record_audit
from pacs import dicomweb_proxy, reconciliation
from pacs.models import StudyStatus
from pacs.views import _no_phi_cache, _study_or_404

logger = logging.getLogger(__name__)


@require_GET
@login_required
def study_viewer(request, pk):
    """Full-screen OHIF page bound to one facility-scoped study."""
    study = _study_or_404(request, pk)

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

    # DICOMweb roots for OHIF = our own same-origin proxy, namespaced by the
    # Orthanc study id so every viewer request is prefix-checked server-side.
    # Orthanc's DICOMweb answers ``.../studies/<id>/...`` under a per-study
    # root; appending ``/studies`` yields exactly that shape.
    proxy_root = reverse("pacs:dicomweb_proxy", args=[study.orthanc_study_id])
    qido_root = proxy_root + "/studies"
    wado_root = proxy_root + "/studies"

    context = {
        "study": study,
        "qido_root": qido_root,
        "wado_root": wado_root,
        "ohif_static_url": static("ohif/index.umd.js"),
    }
    response = render(request, "pacs/viewer.html", context)
    return _no_phi_cache(response)


@csrf_exempt  # DICOMweb clients do not send Django CSRF tokens; auth is the session.
@login_required
def dicomweb_proxy_view(request, path=""):
    """Audited QIDO-RS/WADO-RS proxy: browser ⇄ Django ⇄ private Orthanc.

    ``path`` captures everything after ``/pacs/viewer/dicomweb/``. All real
    validation/authorization happens in :mod:`pacs.dicomweb_proxy`.
    """
    segments = [s for s in path.split("/") if s]
    try:
        status, headers, body = dicomweb_proxy.fetch(request, segments, request.META.get("QUERY_STRING", ""))
    except dicomweb_proxy.DicomWebRequestError as exc:
        resp = HttpResponse(exc.detail or "", status=exc.status)
        return _no_phi_cache(resp)

    # Audit once per study-level metadata/pixel fetch group? Keep volume sane:
    # audit only WADO instance-file retrievals (bulk pixel access), not every
    # metadata call the viewer makes while scrolling.
    if len(segments) >= 4 and segments[-1] == "file":
        study = reconciliation.scoped_studies(request.user).filter(
            orthanc_study_id=segments[1]
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
