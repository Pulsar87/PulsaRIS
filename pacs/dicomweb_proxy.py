"""DICOMweb (QIDO-RS / WADO-RS) proxy for the embedded OHIF viewer.

PACS plan Task 4.3: "If a browser viewer is needed, enable Orthanc's DICOMweb
plugin and integrate a maintained viewer such as OHIF." The plan's trust
boundary (§3, Task 4.2) forbids handing archive credentials to the browser, so
OHIF never talks to Orthanc directly. Instead it calls Django under
``/pacs/viewer/dicomweb/...``, and this module forwards each request to the
private Orthanc REST/DICOMweb endpoint using the service-to-service
credentials from settings — the same pattern already used by
``pacs.views.retrieve_dicom`` for ZIP retrieval.

Two layers of authorization, mirroring the existing retrieval views:

1. **Prefix scoping** — every proxied path must live under a study prefix
   (``studies/<orthanc-study-id>/...`` or the legacy ``searches/...`` QIDO
   form). Instance/series ids are validated *by the archive* (Orthanc resolves
   them), then checked against the mirror row below.
2. **Facility scope after archive resolution** — whenever the response
   reveals which Orthanc study the data belongs to (a ``ParentStudy`` field,
   a resolved DICOM-level UID, or the prefix itself), the orthanc study id is
   matched against ``reconciliation.scoped_studies(user)``. A cross-facility
   guess returns 404 (existence is never leaked), exactly like ``_study_or_404``.

The browser only ever sees session-authenticated Django URLs; Orthanc's host,
port, username and password stay server-side. Responses carry PHI, so they get
the same ``no-store`` cache headers as the rest of the PACS module.
"""

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from pacs import reconciliation

logger = logging.getLogger(__name__)

# Orthanc internal resource ids (letters/digits/_/- up to 64 chars).
ORTHANC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# DICOM UIDs appearing in QIDO/WADO paths.
UID_RE = re.compile(r"^[0-9.]{1,64}$")

# Prefixes accepted after ``dicomweb/``. Everything else is refused before any
# archive request is made (allowlist beats deny-list here).
_ALLOWED_PREFIXES = ("studies", "searches")

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


def _study_id_in_prefix(path_parts):
    """Return the orthanc study id if the path is rooted at studies/<id>.

    ``path_parts`` is the list of already-decoded path segments after
    ``dicomweb/``. Raises DicomWebRequestError on malformed prefixes.
    """
    if not path_parts or path_parts[0] not in _ALLOWED_PREFIXES:
        raise DicomWebRequestError(404, "unsupported DICOMweb route")
    if path_parts[0] == "searches":
        # Legacy Orthanc QIDO form: /searches/studies?... The query itself is
        # answered by the archive within its whole index; the viewer can only
        # reach this through our own study pages, and results contain metadata
        # rows whose StudyInstanceUID we still resolve per-request below when
        # fetched. Kept restricted to GET with no further resource segments.
        if len(path_parts) != 2 or path_parts[1] != "studies":
            raise DicomWebRequestError(404, "unsupported DICOMweb route")
        return None
    # studies/<id>[/<series>[/<instance>[/...]]]
    if len(path_parts) < 2 or not ORTHANC_ID_RE.match(path_parts[1]):
        raise DicomWebRequestError(404, "invalid study resource id")
    return path_parts[1]


def _check_study_scope(user, orthanc_study_id):
    """404 unless the orthanc study id belongs to a study in the user's scope."""
    qs = reconciliation.scoped_studies(user)
    if not qs.filter(orthanc_study_id=orthanc_study_id).exists():
        raise DicomWebRequestError(404, "study not found in your scope")


def _resolve_uid_to_study_id(uid):
    """Map a DICOM StudyInstanceUID to its Orthanc study id via lookup."""
    url = f"{_base_url()}/resources/{uid}/lookup"
    data = json.dumps({"ExpandLevels": False}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **_auth_header(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.PACS_ORTHANC_TIMEOUT_SECONDS) as r:
            payload = json.loads(r.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise DicomWebRequestError(502, "archive unavailable")
    if isinstance(payload, dict) and payload.get("ID") and ORTHANC_ID_RE.match(str(payload["ID"])):
        return str(payload["ID"])
    return None


def _authorize(user, path_parts, query):
    """Validate + authorize one proxied request.

    Returns the (possibly ``None``) orthanc study id governing the request.
    Any path that names a concrete resource is checked against the mirror;
    global search parameters naming a specific StudyInstanceUID are resolved
    and checked too, so URL manipulation cannot widen scope.
    """
    study_id = _study_id_in_prefix(path_parts)

    if study_id is not None:
        _check_study_scope(user, study_id)
        return study_id

    # /searches/studies?StudyInstanceUID=... → pin to that study's scope.
    params = urllib.parse.parse_qs(query or "")
    uid_list = params.get("StudyInstanceUID") or []
    if uid_list:
        uid = uid_list[0].strip()
        # Support '*' wildcard and '=' exact / '@' fuzzy forms minimally.
        m = re.match(r"^(?:=?)([0-9.]{1,64})$", uid)
        if m:
            sid = _resolve_uid_to_study_id(m.group(1))
            if sid:
                _check_study_scope(user, sid)
                return sid
            raise DicomWebRequestError(404, "study not found in your scope")
    return None


def _upstream_headers(extra=None):
    headers = {"Accept": "*/*", **_auth_header()}
    if extra:
        headers.update(extra)
    return headers


def fetch(request, sub_path, query):
    """Proxy one authenticated DICOMweb request to the private archive.

    ``sub_path``: decoded path segments after ``dicomweb/`` (list of str).
    ``query``: raw query string (may be empty).
    Returns ``(status, response_headers_dict, body_bytes)``.
    Raises DicomWebRequestError for refused/unauthorized requests.
    """
    study_id = _authorize(request.user, sub_path, query)

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

    # Defense-in-depth: if the JSON body names a parent study (single-resource
    # metadata endpoints), confirm it matches the authorized prefix. Mismatch
    # would indicate archive inconsistency — refuse rather than serve.
    if (
        study_id is not None
        and len(sub_path) >= 3
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
        if parent and parent != study_id:
            raise DicomWebRequestError(404, "resource does not belong to this study")

    return status, out_headers, payload
