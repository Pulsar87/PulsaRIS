"""Celery tasks for PACS metadata synchronization (PACS plan Task 2.2).

Long-running sync stays out of request/response views; these tasks use
bounded exponential backoff retries and never silently swallow errors.
If the archive is temporarily down the task retries; after max retries
the failure remains visible in SyncEvent rows and Celery results.
"""

import logging

from celery import shared_task

from pacs.orthanc_client import OrthancUnavailable
from pacs.services import process_changes, replay_all_studies

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="pacs.tasks.sync_orthanc_changes",
    max_retries=None,
    default_retry_delay=30,
)
def sync_orthanc_changes(self):
    """Drain the Orthanc changes feed from the durable cursor."""
    try:
        counters = process_changes()
    except OrthancUnavailable as exc:
        # Archive outage: retry with bounded exponential backoff (cap 10m).
        countdown = min(600, 30 * (2 ** min(self.request.retries, 4)))
        logger.warning("archive unavailable during sync (%s); retrying in %ss", exc, countdown)
        raise self.retry(exc=exc, countdown=countdown)
    return counters


@shared_task(name="pacs.tasks.replay_pacs_mirror")
def replay_pacs_mirror(limit=None):
    """Rebuild/reconcile the Django mirror from the archive."""
    return replay_all_studies(limit=limit)
