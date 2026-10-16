"""Orthanc REST archive adapter (PACS plan: "Use an archive adapter/service
module for Orthanc API interactions. Do not spread raw REST URLs, credential
handling, or DICOM-specific parsing throughout Django views").

All HTTP access to the archive goes through this module. Credentials come
from settings (env/secrets), never from callers. Timeouts are explicit and
bounded; connection errors raise OrthancUnavailable so callers can retry
with backoff instead of failing silently.

Uses only Python stdlib (urllib) to avoid adding a runtime dependency.
"""

import base64
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)


class OrthancError(Exception):
    """Base error for archive adapter failures."""


class OrthancUnavailable(OrthancError):
    """Archive is unreachable / timed out / 5xx. Retryable."""


class OrthancAPIError(OrthancError):
    """Archive returned a non-retryable HTTP error (4xx)."""

    def __init__(self, status, body=""):
        super().__init__(f"Orthanc REST error {status}: {body[:200]}")
        self.status = status
        self.body = body


class OrthancClient:
    """Minimal authenticated client for the private Orthanc REST API."""

    def __init__(self, base_url=None, username=None, password=None, timeout=None):
        self.base_url = (base_url or settings.PACS_ORTHANC_API_URL).rstrip("/")
        self.username = username if username is not None else settings.PACS_ORTHANC_REST_USER
        self.password = password if password is not None else settings.PACS_ORTHANC_REST_PASSWORD
        self.timeout = timeout or settings.PACS_ORTHANC_TIMEOUT_SECONDS

    # -- low level -----------------------------------------------------------

    def _request(self, path, *, method="GET", data=None, headers=None):
        url = f"{self.base_url}{path}"
        req_headers = {"Accept": "application/json"}
        if self.username:
            token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            req_headers["Authorization"] = f"Basic {token}"
        if headers:
            req_headers.update(headers)
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode(errors="replace")
            except Exception:  # pragma: no cover - defensive
                pass
            if 500 <= exc.code < 600:
                logger.warning("Orthanc 5xx on %s: %s", path, exc.code)
                raise OrthancUnavailable(f"archive returned {exc.code}") from exc
            raise OrthancAPIError(exc.code, detail) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OrthancUnavailable(f"archive unreachable: {exc}") from exc
        if not payload:
            return None
        try:
            return json.loads(payload.decode())
        except json.JSONDecodeError as exc:  # pragma: no cover
            raise OrthancError(f"invalid JSON from {path}") from exc

    # -- health --------------------------------------------------------------

    def get_statistics(self):
        return self._request("/statistics")

    def get_summary(self):
        """Orthanc build/version summary (GET /) — no PHI, safe for diagnostics."""
        return self._request("/")

    def is_alive(self):
        try:
            self.get_statistics()
            return True
        except OrthancError:
            return False

    # -- changes feed (durable cursor, Task 2.2) -------------------------------

    def get_changes(self, since=None):
        """Return list of change dicts. `since` is the last processed index."""
        path = "/changes"
        if since is not None:
            path = f"/changes/{int(since)}"
        result = self._request(path) or {}
        return result.get("Changes", []), result.get("LastChange")

    def get_global_id_of_change(self, change_index):
        """Best-effort lookup of the global (UID-derived) id recorded by
        Orthanc for a given change number, via /changes metadata."""
        changes, _ = self._get_changes_window(change_index)
        for ch in changes:
            if ch.get("Index") == change_index:
                return ch.get("Id")
        return None

    def _get_changes_window(self, around):
        start = max(0, int(around) - 100)
        result = self._request(f"/changes/{start}") or {}
        return result.get("Changes", []), result.get("LastChange")

    # -- resource inspection ----------------------------------------------------

    def lookup_resource_by_dicom_id(self, dicom_identifier):
        """Map a DICOM-level id (e.g. StudyInstanceUID) to an Orthanc id."""
        try:
            result = self._request(
                f"/resources/{dicom_identifier}/lookup",
                method="POST",
                data={"ExpandLevels": False},
            )
        except OrthancAPIError as exc:
            if exc.status == 404:
                return None
            raise
        return result

    def get_study(self, orthanc_study_id, expand=False):
        path = f"/studies/{orthanc_study_id}"
        if expand:
            path += "?expand=true"
        try:
            return self._request(path)
        except OrthancAPIError as exc:
            if exc.status == 404:
                return None
            raise

    def get_shared_path(self, orthanc_id):
        """Return the shared identifier (global DICOM-level id) for a resource."""
        info = self._request(f"/{orthanc_id}")
        return info.get("ID") if isinstance(info, dict) else None

    # -- authorized file retrieval (Phase 4, Task 4.2) -------------------------

    def get_instance_file(self, instance_id, max_bytes=None):
        """Return the original DICOM file bytes for one Orthanc instance.

        Raw (non-JSON) GET. Authorization is the caller's responsibility —
        this adapter never checks facility scope by itself. Responses are
        capped so a runaway archive object cannot exhaust web memory.
        """
        import re as _re

        if not _re.match(r"^[A-Za-z0-9_-]{1,64}$", instance_id):
            raise OrthancError("invalid instance id")
        cap = max_bytes or getattr(settings, "PACS_RETRIEVE_MAX_BYTES", 536870912)
        url = f"{self.base_url}/instances/{instance_id}/file"
        headers = {}
        if self.username:
            token = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {token}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout * 6) as resp:
                return resp.read(cap)
        except urllib.error.HTTPError as exc:
            if 500 <= exc.code < 600:
                raise OrthancUnavailable(f"archive returned {exc.code}") from exc
            raise OrthancAPIError(exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OrthancUnavailable(f"archive unreachable: {exc}") from exc

    def get_study_archive_zip(self, orthanc_study_id, max_bytes=None):
        """Return the study's original-object ZIP from Orthanc /archive."""
        import re as _re

        if not _re.match(r"^[A-Za-z0-9_-]{1,64}$", orthanc_study_id):
            raise OrthancError("invalid study resource id")
        cap = max_bytes or getattr(settings, "PACS_RETRIEVE_MAX_BYTES", 536870912)
        url = f"{self.base_url}/studies/{orthanc_study_id}/archive"
        headers = {}
        if self.username:
            token = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {token}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout * 6) as resp:
                return resp.read(cap)
        except urllib.error.HTTPError as exc:
            if 500 <= exc.code < 600:
                raise OrthancUnavailable(f"archive returned {exc.code}") from exc
            raise OrthancAPIError(exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OrthancUnavailable(f"archive unreachable: {exc}") from exc
