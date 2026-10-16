"""Integration audit events + operational metrics (PACS plan Phase 3, Task 3.4).

Emits structured, PHI-minimal service events (event IDs, archive resource
IDs, UID references where operationally necessary, durations, results) —
never patient names, birth dates, full DICOM datasets, or credentials.
Metrics are derived from existing tables plus Orthanc statistics so no
separate time-series store is required for the MVP; a Prometheus exporter
can be layered on ``collect_metrics`` later.
"""

import logging
import time

from django.conf import settings
from django.db.models import Count, Max, Min
from django.utils import timezone

from pacs.models import PACSStudy, StudyStatus, SyncEvent
from pacs.orthanc_client import OrthancClient, OrthancUnavailable

logger = logging.getLogger("pacs.audit")


def log_event(event, **fields):
    """Emit one structured audit/metrics event line (no PHI values).

    Allowed field vocabulary: study_uid_ref (last 8 chars of a UID),
    orthanc_id, accession (order-scoped identifier already mirrored),
    outcome, reason_category, duration_ms, counts. Full UIDs are
    truncated to avoid correlating identifiers in log aggregators.
    """
    safe = {}
    for key, value in fields.items():
        if key == "study_uid_ref" and value:
            safe[key] = f"...{str(value)[-8:]}"
        elif key in ("accession", "orthanc_id", "outcome", "reason_category"):
            safe[key] = str(value)[:64]
        else:
            safe[key] = value
    parts = " ".join(f"{k}={v}" for k, v in safe.items())
    logger.info("event=%s %s", event, parts)


def timed_sync(client=None, limit=200):
    """Wrap process_changes with duration/result audit (Task 3.4)."""
    started = time.monotonic()
    try:
        counters = _run_process(client, limit)
        log_event(
            "sync_completed",
            outcome="success",
            duration_ms=int((time.monotonic() - started) * 1000),
            **counters,
        )
        return counters
    except OrthancUnavailable as exc:
        log_event(
            "sync_failed",
            outcome="archive_unavailable",
            reason_category=type(exc).__name__,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        raise


def _run_process(client, limit):
    # Imported lazily to keep this module importable without Django app
    # registry fully loaded in some tooling contexts.
    from pacs.services import process_changes

    return process_changes(client=client, limit=limit)


def log_match_result(study, outcome, reason_category=""):
    """Called by sync paths when an order match succeeds/fails."""
    log_event(
        "order_match",
        outcome=outcome,
        study_uid_ref=study.study_instance_uid,
        accession=study.accession_number,
        orthanc_id=study.orthanc_study_id,
        reason_category=reason_category,
    )


def collect_metrics(client=None):
    """Operational metric snapshot (Task 3.4 list).

    Returns plain JSON-serializable values; suitable for the diagnostics
    view and future exporters. No PHI beyond identifiers already in the
    mirror tables, and never includes credentials or DICOM payloads.
    """
    now = timezone.now()
    studies = PACSStudy.objects.all()
    status_counts = dict(
        studies.values_list("status").annotate(n=Count("id")).order_by()
    )
    unmatched_qs = studies.filter(status=StudyStatus.RECONCILIATION_REQUIRED)
    oldest = unmatched_qs.aggregate(m=Min("created_at"))["m"]
    pending_events = SyncEvent.objects.filter(
        outcome=SyncEvent.Outcome.PENDING
    ).count()
    failed_events = SyncEvent.objects.filter(
        outcome=SyncEvent.Outcome.FAILED
    ).count()
    last_processed = SyncEvent.objects.filter(
        outcome=SyncEvent.Outcome.PROCESSED
    ).aggregate(m=Max("processed_at"))["m"]
    lag_seconds = None
    if last_processed:
        lag_seconds = max(0, int((now - last_processed).total_seconds()))

    metrics = {
        "generated_at": now.isoformat(),
        "queue_depth": {
            "pending_sync_events": pending_events,
            "failed_sync_events": failed_events,
            "reconciliation_required": status_counts.get(
                StudyStatus.RECONCILIATION_REQUIRED, 0
            ),
            "integrity_conflicts": status_counts.get(
                StudyStatus.INTEGRITY_CONFLICT, 0
            ),
            "sync_errors": status_counts.get(StudyStatus.SYNC_ERROR, 0),
        },
        "study_status_counts": status_counts,
        "unmatched_oldest_age_seconds": (
            int((now - oldest).total_seconds()) if oldest else None
        ),
        "event_lag_seconds": lag_seconds,
        "archive": {"health": "unknown"},
    }

    client = client or OrthancClient()
    try:
        stats = client.get_statistics()
        if isinstance(stats, dict):
            metrics["archive"] = {
                "health": "ok",
                "dicom_files": stats.get("DicomFiles"),
                "disk_size_mb": stats.get("DiskSize"),
                "changes_count": stats.get("ChangesCount"),
                "memory_bytes": stats.get("MemoryUsed"),
            }
    except Exception as exc:  # health probe must never crash the caller
        metrics["archive"] = {"health": "error", "reason_category": type(exc).__name__}

    # Build/version metadata (GET /) — Orthanc Name/Version/API version.
    # Best-effort: a failure here must not flip an otherwise-healthy archive.
    try:
        summary = client.get_summary()
        if isinstance(summary, dict):
            metrics["archive"]["name"] = summary.get("Name")
            metrics["archive"]["version"] = summary.get("Version")
            metrics["archive"]["api_version"] = summary.get("ApiVersion")
    except Exception:  # pragma: no cover - non-critical enrichment
        pass

    # --- PACS connection identity (non-secret deployment config) ------------
    # Lets staff see exactly which archive endpoint/AE the app talks to;
    # credentials are never included.
    metrics["connection"] = {
        "api_url": settings.PACS_ORTHANC_API_URL,
        "ae_title": settings.PACS_ORTHANC_AE_TITLE,
        "dicom_port": settings.PACS_ORTHANC_DICOM_PORT,
        "rest_user_configured": bool(settings.PACS_ORTHANC_REST_USER),
    }
    return metrics
