"""DICOMweb (QIDO-RS / WADO-RS) proxy for the embedded OHIF viewer.

PACS plan Task 4.3: "If a browser viewer is needed, enable Orthanc's DICOMweb
plugin and integrate a maintained viewer such as OHIF." The plan's trust
boundary (§3, Task 4.2) forbids handing archive credentials to the browser, so
OHIF never talks to Orthanc directly. Instead it calls Django under
``/pacs/viewer/dicomweb/...``, and this module forwards each request to the
private Orthanc REST/DICOMweb endpoint using the service-to-service
credentials from settings — the same pattern already used by
``pacs.views.retrieve_dicom`` for ZIP retrieval.

Every proxy URL carries the opaque Orthanc study id as a separate scope
segment. The id must belong to a study in the user's facility scope, and each
standard DICOMweb request is constrained to that study's DICOM Study Instance
UID. Responses carry PHI, so they get the same ``no-store`` cache headers as
the rest of the PACS module.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from pacs import reconciliation
from pacs.dicom_uid import is_valid_dicom_uid

logger = logging.getLogger(__name__)

_MAX_RESPONSE_BYTES = getattr(settings, "PACS_RETRIEVE_MAX_BYTES", 536870912)

# Hop-by-hop / transport headers that must not be copied between the client
# and the upstream (RFC 9110 §7.7, plus framing headers we regenerate).
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "content-encoding",
    "host",
    "authorization",
}


class DicomWebRequestError(Exception):
    """Bad or unauthorized viewer request; carries an HTTP status to return."""

    def __init__(self, status=404, detail=""):
        super().__init__(detail or f"DICOMweb request refused ({status})")
        self.status = status
        self.detail = detail


def _base_url():
    return settings.PACS_ORTHANC_API_URL.rstrip("/")


def _auth_header():
    user = settings.PACS_ORTHANC_REST_USER
    if not user:
        raise DicomWebRequestError(502, "archive credentials are not configured")
    import base64

    token = base64.b64encode(
        f"{user}:{settings.PACS_ORTHANC_REST_PASSWORD}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


def _authorize(user, scope_id, path_parts, query):
    """Validate one DICOMweb request and constrain it to its viewer's study."""
    study_uid = reconciliation.scoped_studies(user).filter(
        orthanc_study_id=scope_id
    ).values_list("study_instance_uid", flat=True).first()
    if not study_uid:
        raise DicomWebRequestError(404, "study not found in your scope")
    if not path_parts or path_parts[0] != "studies":
        raise DicomWebRequestError(404, "unsupported DICOMweb route")
    if any(part in (".", "..") or "\\" in part for part in path_parts):
        raise DicomWebRequestError(404, "invalid DICOMweb path")

    params = urllib.parse.parse_qsl(query or "", keep_blank_values=True)
    requested_uids = [
        value for key, value in params if key.lower() == "studyinstanceuid"
    ]
    if any(value != study_uid for value in requested_uids):
        raise DicomWebRequestError(404, "study not found in your scope")

    if len(path_parts) == 1:
        # QIDO-RS collection queries are always pinned to this one UID.
        if not requested_uids:
            params.append(("StudyInstanceUID", study_uid))
        query = urllib.parse.urlencode(params, doseq=True)
    elif path_parts[1] != study_uid or not is_valid_dicom_uid(path_parts[1]):
        raise DicomWebRequestError(404, "study not found in your scope")
    return query


def _upstream_headers(extra=None):
    headers = {"Accept": "*/*", **_auth_header()}
    if extra:
        headers.update(extra)
    return headers


def fetch(request, scope_id, sub_path, query):
    """Proxy one authenticated DICOMweb request to the private archive.

    ``scope_id``: opaque Orthanc id for the authorized viewer study.
    ``sub_path``: decoded standard DICOMweb segments after the scope id.
    ``query``: raw query string (may be empty).
    Returns ``(status, response_headers_dict, body_bytes)``.
    Raises DicomWebRequestError for refused/unauthorized requests.
    """
    query = _authorize(request.user, scope_id, sub_path, query)

    # Rebuild the upstream path with safe re-quoting of each segment.
    encoded = "/".join(urllib.parse.quote(p, safe="") for p in sub_path)
    url = f"{_base_url()}/dicom-web/{encoded}"
    if query:
        url += f"?{query}"

    body = None
    ctype = request.content_type or ""
    headers = {}
    if request.method == "POST":
        if ctype.startswith("application/dicom"):
            # STOW-RS is deliberately NOT proxied: uploads happen over DICOM
            # C-STORE from modalities, never from the browser.
            raise DicomWebRequestError(405, "STOW-RS is not enabled for the viewer")
        body = request.body or None
        if body:
            headers["Content-Type"] = ctype or "application/json"
    elif request.method not in ("GET", "HEAD"):
        raise DicomWebRequestError(405, "method not allowed for the viewer")

    req = urllib.request.Request(url, data=body, method=request.method,
                                 headers=_upstream_headers(headers))
    cap = _MAX_RESPONSE_BYTES
    timeout = int(getattr(settings, "PACS_RETRIEVE_TIMEOUT_SECONDS", 60))
    try:
        with urllib.request.urlopen(req, timeout=max(timeout, 10)) as resp:
            status = resp.status if hasattr(resp, "status") else resp.code
            raw_headers = dict(resp.headers.items())
            payload = resp.read(cap)
    except urllib.error.HTTPError as exc:
        if 500 <= exc.code < 600:
            logger.warning("viewer proxy: archive %s on %s", exc.code, url.split("?")[0])
            raise DicomWebRequestError(502, "archive unavailable")
        # 4xx from Orthanc (e.g. unknown instance) → surface as 404-ish.
        status, raw_headers, payload = exc.code, dict(exc.headers.items() or {}), exc.read(65536)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("viewer proxy: archive unreachable: %s", exc)
        raise DicomWebRequestError(502, "archive unavailable")

    out_headers = {
        k: v
        for k, v in raw_headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    out_headers.setdefault("Content-Type", "application/octet-stream")

    # Defense-in-depth: confirm any returned parent-study id matches the
    # authorized Orthanc scope.
    if (
        len(sub_path) >= 3
        and "json" in out_headers.get("Content-Type", "").lower()
        and payload
    ):
        try:
            parsed = json.loads(payload.decode())
        except (ValueError, UnicodeDecodeError):
            parsed = None
        parent = None
        if isinstance(parsed, dict):
            parent = parsed.get("ParentStudy")
        if parent and parent != scope_id:
            raise DicomWebRequestError(404, "resource does not belong to this study")

    return status, out_headers, payload
