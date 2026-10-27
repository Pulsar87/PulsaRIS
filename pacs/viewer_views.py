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

import json
import logging
import re

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from clinic.permissions import record_audit
from pacs import dicomweb_proxy, reconciliation
from pacs.dicom_uid import is_valid_dicom_uid
from pacs.models import StudyStatus
from pacs.orthanc_client import OrthancClient, OrthancError
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

    The workstation is *always available*: any study already present in the
    archive can be opened here — single-slice images (CR/DX/secondary
    captures) render as a full 2D image with window/level, pan and zoom,
    multi-slice series additionally get MPR/volume reconstruction. Only
    studies that have not been archived yet fall back to the detail page.
    Images are fetched exclusively through the same audited proxy as the
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
        # Advanced-toolkit bundles (Cornerstone3D + VTK.js volume renderer)
        # are pinned and vendored under /static/slicer3d/ exactly like the
        # OHIF bundle — served same-origin, never from a CDN at runtime.
        # The template probes these and falls back to the standard viewer's
        # capabilities if the workstation bundle has not been installed yet.
        # Raw-file feed (audited, facility-scoped): one original DICOM file
        # per Orthanc instance. Works for *every* transfer syntax — the
        # browser decodes uncompressed data itself and hands compressed
        # files to WebAssembly codecs — so the workstation can open any
        # DICOM image, not only tomographic series.
        "files_url": reverse(
            "pacs:study_slicer3d_files", kwargs={"pk": study.pk}
        ),
        "vtk_url": static("slicer3d/vtk.min.js"),
        "manifest_url": reverse(
            "pacs:study_slicer3d_manifest", kwargs={"pk": study.pk}
        ),
        "standard_viewer_url": reverse(
            "pacs:study_viewer", kwargs={"pk": study.pk}
        ),
    }
    response = render(request, "pacs/viewer_3d_slicer.html", context)
    return _no_phi_cache(response)


# Tags we forward to the browser-side toolkit for each slice; anything not
# listed here never leaves the server (keeps the manifest lean and PHI-light).
_MANIFEST_NUMERIC_TAGS = {
    "PixelSpacing": ("0028,0030",),
    "SliceThickness": ("0018,0050",),
    "SpacingBetweenSlices": ("0018,0088",),
    "Rows": ("0028,0010",),
    "Columns": ("0028,0011",),
    "BitsAllocated": ("0028,0100",),
    "SamplesPerPixel": ("0028,0002",),
    "PhotometricInterpretation": ("0028,0004",),
    "RescaleSlope": ("0028,1053",),
    "RescaleIntercept": ("0028,1052",),
}
_MANIFEST_LIST_TAGS = {
    "ImagePositionPatient": ("0020,0037",),
    "ImageOrientationPatient": ("0020,0032",),
}
# Orthanc exposes the transfer syntax either as a UID or as its own name,
# depending on version/build — map both spellings we may see.
_TRANSFER_SYNTAX_NAMES = {
    "RAW": ("1.2.840.10008.1.2.1", "LittleEndianExplicit"),
    "LITTLE_ENDIAN_EXPLICIT": ("1.2.840.10008.1.2.1", "LittleEndianExplicit"),
    "LITTLE_ENDIAN_IMPLICIT": ("1.2.840.10008.1.2", "LittleEndianImplicit"),
    "JPEG_BASELINE": ("1.2.840.10008.1.24.80", "jpegBaseline"),
    "JPEG_EXTENDED": ("1.2.840.10008.1.24.80", "jpegExtended"),
    "JPEG_LOSSLESS": ("1.2.840.10008.1.24.70", "jpegLossless"),
    "JPEG2000": ("1.2.840.10008.1.2.4.90", "jpeg2000"),
    "JPEG2000_LOSSLESS": ("1.2.840.10008.1.2.4.90", "jpeg2000"),
    "MRI_DEFLATED": ("1.2.840.10008.1.2.1.99", "deflated"),
}


def _first_tag(tags, names):
    for name in names:
        value = tags.get(name)
        if value not in (None, ""):
            return value
    return None


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _series_to_manifest(series, wado_base):
    """Convert one expanded Orthanc series into a browser-loadable entry."""
    tags = series.get("SharedTags") or {}
    instances = [i for i in (series.get("Instances") or []) if isinstance(i, dict)]

    slices = []
    for idx, inst in enumerate(instances):
        itags = inst.get("MainTags") or {}
        entry = {"fileUrl": f"{wado_base}/instances/{inst.get('ID', '')}/file"}
        pos = _first_tag(itags, _MANIFEST_LIST_TAGS["ImagePositionPatient"])
        z = _as_float(pos[2]) if isinstance(pos, list) and len(pos) >= 3 else None
        if z is None:
            # No IPP (e.g. some CR/secondary captures): keep acquisition order.
            z = float(idx)
        entry["z"] = z
        for key, names in _MANIFEST_NUMERIC_TAGS.items():
            value = _first_tag(itags, names) or _first_tag(tags, names)
            if value is not None:
                entry[key] = value
        for key, names in _MANIFEST_LIST_TAGS.items():
            value = _first_tag(itags, names) or _first_tag(tags, names)
            if value is not None:
                entry[key] = value
        if inst.get("Index") is not None:
            entry["instanceNumber"] = inst["Index"]
        slices.append(entry)

    # Sort slices along the patient Z axis so the volume is coherent even if
    # Orthanc returned instances out of acquisition order.
    slices.sort(key=lambda s: s["z"])

    transfer_name = tags.get("TransferSyntax") or ""
    transfer_uid, decoder = _TRANSFER_SYNTAX_NAMES.get(transfer_name, ("", ""))

    return {
        "seriesInstanceUid": tags.get("ID", ""),
        "seriesDescription": tags.get("SeriesDescription", ""),
        "modality": tags.get("Modality", ""),
        "numberOfFrames": len(slices),
        "transferSyntaxUid": transfer_uid,
        "decoder": decoder,
        "dimensions": {
            "rows": _first_tag(tags, _MANIFEST_NUMERIC_TAGS["Rows"]),
            "columns": _first_tag(tags, _MANIFEST_NUMERIC_TAGS["Columns"]),
            "slices": len(slices),
        },
        "pixelSpacing": _first_tag(tags, _MANIFEST_NUMERIC_TAGS["PixelSpacing"]),
        "sliceThickness": (
            _first_tag(tags, _MANIFEST_NUMERIC_TAGS["SliceThickness"])
            or _first_tag(tags, _MANIFEST_NUMERIC_TAGS["SpacingBetweenSlices"])
        ),
        "imageOrientationPatient": _first_tag(
            tags, _MANIFEST_LIST_TAGS["ImageOrientationPatient"]
        ),
        "slices": slices,
    }


@require_GET
@login_required
def study_slicer3d_manifest(request, pk):
    """JSON volume manifest powering the advanced 3D Slicer workstation.

    The browser toolkit cannot talk to the archive directly, and DICOMweb
    metadata responses do not expose the per-instance Orthanc ids needed to
    stream original files through the audited proxy. This endpoint therefore
    walks the *server-side* Orthanc hierarchy (service credentials stay in
    Django), and returns only geometry/encoding tags plus proxy-relative file
    URLs — no patient identifiers, and every ``fileUrl`` still re-passes
    through the facility-scoped, audited ``dicomweb_proxy_view``.
    """
    study = _study_or_404(request, pk)
    if not study.orthanc_study_id or study.status == StudyStatus.RECEIVED:
        raise Http404

    record_audit(
        request,
        "pacs.viewer_open",
        entity_type="PACSStudy",
        entity_id=str(study.pk),
        old=None,
        new={
            "accession": study.accession_number,
            "viewer": "slicer3d-manifest",
        },
    )

    wado_base = reverse(
        "pacs:dicomweb_proxy",
        kwargs={"scope_id": study.orthanc_study_id, "path": "studies/" + study.study_instance_uid},
    ).rstrip("/")

    try:
        client = OrthancClient()
        data = client.get_study(study.orthanc_study_id, expand=True) or {}
    except OrthancError as exc:
        logger.warning("slicer3d manifest: archive error for study %s: %s", pk, exc)
        return JsonResponse(
            {"error": "archive-unreachable", "detail": str(exc)}, status=502
        )

    series_entries = []
    for s in data.get("Series") or []:
        if not isinstance(s, dict):
            continue
        shared = s.get("SharedTags") or {}
        modality = shared.get("Modality", "")
        # Skip empty series and non-image (SR) content; every *image*
        # series is listed — single-slice projections included — so the
        # workstation can open any DICOM image, not only 3D-capable ones.
        if not s.get("Instances") or modality == "SR":
            continue
        series_entries.append(_series_to_manifest(s, wado_base))

    payload = {
        "studyInstanceUid": study.study_instance_uid,
        "studyDescription": data.get("Name", "") if isinstance(data, dict) else "",
        "modalities": sorted({e["modality"] for e in series_entries if e["modality"]}),
        "maxResponseBytes": int(
            getattr(settings, "PACS_RETRIEVE_MAX_BYTES", 536870912)
        ),
        # Raw-file feed consumed by the workstation page: one original
        # DICOM file per instance, regardless of transfer syntax.
        "filesUrl": reverse("pacs:study_slicer3d_files", kwargs={"pk": study.pk}),
        "series": series_entries,
    }
    response = JsonResponse(payload, json_dumps_params={"separators": (",", ":")})
    return _no_phi_cache(response)


@require_GET
@login_required
def study_slicer3d_files(request, pk):
    """Stream every original DICOM file of one study as a multipart body.

    The advanced 3D Slicer workstation needs the *whole* study in the
    browser — including single-slice images (CR/DX/US/secondary captures),
    which have no reconstructable volume and therefore never appear in the
    geometry manifest's slice URLs in a usable form. Rather than making
    the browser issue N sequential WADO requests, this endpoint walks the
    facility-scoped Orthanc hierarchy server-side (service credentials stay
    in Django) and returns all instances as one ``multipart/related`` body
    of original ``application/dicom`` parts — exactly the format standard
    viewers parse, for *any* transfer syntax.

    Trust model unchanged from the other viewer routes: facility-scoped
    mirror lookup first (404 across facilities), audit before pixel data
    flows, and a total byte cap so a runaway archive object cannot exhaust
    web memory.
    """
    study = _study_or_404(request, pk)
    if not study.orthanc_study_id or study.status == StudyStatus.RECEIVED:
        raise Http404

    record_audit(
        request,
        "pacs.dicom_retrieve",
        entity_type="PACSStudy",
        entity_id=str(study.pk),
        old=None,
        new={"kind": "slicer3d-files"},
    )

    client = OrthancClient()
    boundary = "ris-slicer3d"

    def chunks():
        yield f"--{boundary}\r\n".encode()
        sent = 0
        cap = int(getattr(settings, "PACS_RETRIEVE_MAX_BYTES", 536870912))
        try:
            data = client.get_study(study.orthanc_study_id, expand=True) or {}
        except OrthancError as exc:
            logger.warning("slicer3d files: archive error for study %s: %s", pk, exc)
            # Mid-stream we can only signal truncation; the page detects the
            # missing terminator and shows an archive-unavailable message.
            return
        for series in data.get("Series") or []:
            if not isinstance(series, dict):
                continue
            shared = series.get("SharedTags") or {}
            if shared.get("Modality", "") == "SR":
                continue  # structured reports carry no pixels to display
            for inst in series.get("Instances") or []:
                if not isinstance(inst, dict) or not inst.get("ID"):
                    continue
                instance_id = str(inst["ID"])
                if not re.match(r"^[A-Za-z0-9_-]{1,64}$", instance_id):
                    continue
                try:
                    file_bytes = client.get_instance_file(instance_id)
                except OrthancError:
                    continue  # one unreadable instance must not sink the feed
                if not file_bytes:
                    continue
                sent += len(file_bytes)
                if sent > cap:
                    return
                yield b"Content-Type: application/dicom\r\n\r\n"
                yield file_bytes
                yield f"\r\n--{boundary}\r\n".encode()
        yield f"--{boundary}--\r\n".encode()

    response = StreamingHttpResponse(
        chunks(),
        content_type=f'multipart/related; type="application/dicom"; boundary={boundary}',
    )
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
