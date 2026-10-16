"""Idempotent PACS synchronization service (PACS plan Phase 2, Tasks 2.2–2.4).

Flow:
1. Poll Orthanc's changes feed from a durable cursor stored in SyncEvent.
2. For each change touching an instance/series/study, resolve the parent
   study via the archive REST API (trusted metadata source — we never
   trust client-posted ids, and never read Orthanc's private tables).
3. Validate required UIDs before writing the mirror; invalid data becomes
   a visible SYNC_ERROR/integrity event, not a silent success.
4. update_or_create-style idempotent writes guarded by DB uniqueness.
5. Apply the deterministic matching policy (Phase 3, Task 3.1) to link
   to ExamOrder when unambiguous; otherwise RECONCILIATION_REQUIRED.

Duplicate retransmissions are no-ops. A UID collision with materially
different content raises INTEGRITY_CONFLICT and never overwrites the
existing match automatically (Task 2.4).
"""

import hashlib
import logging
from datetime import datetime

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from orders.models import ExamOrder
from pacs.dicom_uid import clean_dicom_uid, is_valid_dicom_uid
from pacs.models import PACSStudy, StudyStatus, SyncEvent
from pacs.orthanc_client import OrthancClient, OrthancError, OrthancUnavailable

logger = logging.getLogger(__name__)

# Tags that must agree for a re-notification to be considered equivalent.
_IDENTITY_TAGS = (
    "PatientID",
    "AccessionNumber",
    "StudyInstanceUID",
)


class MatchOutcome:
    LINKED = "linked"
    UNMATCHED = "unmatched"
    CONFLICT = "conflict"


def _parse_study_datetime(study_date, study_time):
    """Parse DICOM DA (YYYYMMDD) / TM (HHMMSS[.ffffff]) defensively."""
    if not study_date:
        return None, None
    try:
        dt_date = datetime.strptime(study_date.strip(), "%Y%m%d").date()
    except ValueError:
        return None, None
    dt_time = None
    if study_time:
        tm = study_time.strip().split(".")[0]
        for fmt in ("%H%M%S", "%H%M"):
            try:
                dt_time = datetime.strptime(tm, fmt).time()
                break
            except ValueError:
                continue
    combined = None
    if dt_time is not None:
        try:
            combined = timezone.make_aware(datetime.combine(dt_date, dt_time))
        except Exception:
            combined = None
    elif timezone.get_current_timezone():
        try:
            combined = timezone.make_aware(
                datetime.combine(dt_date, datetime.min.time())
            )
        except Exception:
            combined = None
    return dt_date, combined


def resolve_facility_for_sender(calling_ae_title):
    """Trusted sender→facility mapping (plan §1.6 / Task 0.2).

    Ownership derives exclusively from the Device registry (AE title +
    active flag), never from DICOM demographic tags. Returns
    (device, facility) or (None, None) for unknown senders.
    """
    from core.models import Device

    if not calling_ae_title:
        return None, None
    device = (
        Device.objects.filter(dicom_ae_title=calling_ae_title, is_active=True)
        .select_related("facility")
        .first()
    )
    if device is None:
        return None, None
    return device, device.facility


def apply_matching_policy(study):
    """Deterministic ordered matching (Phase 3, Task 3.1).

    1. Exact StudyInstanceUID on an ExamOrder (valid patient/facility
       context) → link.
    2. Exact accession + Patient ID/MRN within the trusted facility → link.
    3. Anything else → RECONCILIATION_REQUIRED. Never match on name/DOB
       or free text. Returns (outcome, order_or_none, reason).
    """
    uid = study.study_instance_uid
    accession = (study.accession_number or "").strip()
    patient_id = (study.patient_id_as_received or "").strip()

    # Rule 1: exact Study Instance UID.
    candidates = ExamOrder.objects.filter(
        dicom_study_instance_uid=uid, is_deleted=False
    )
    if candidates.exists():
        order = candidates.first()
        if candidates.count() > 1:
            return (
                MatchOutcome.CONFLICT,
                None,
                f"{candidates.count()} orders already carry Study UID {uid}",
            )
        if study.facility_id and order.facility_id != study.facility_id:
            return (
                MatchOutcome.CONFLICT,
                None,
                "sender facility does not match order facility",
            )
        if accession and order.accession_number != accession:
            return (
                MatchOutcome.CONFLICT,
                None,
                "accession on study conflicts with order matched by UID",
            )
        if patient_id and order.patient.mrn != patient_id:
            return (
                MatchOutcome.CONFLICT,
                None,
                "PatientID on study conflicts with order MRN matched by UID",
            )
        return MatchOutcome.LINKED, order, "exact StudyInstanceUID match"

    # Rule 2: accession + MRN + facility (only when UID not already linked).
    if accession and patient_id:
        orders = ExamOrder.objects.filter(
            accession_number=accession, patient__mrn=patient_id, is_deleted=False
        )
        if study.facility_id:
            orders = orders.filter(facility_id=study.facility_id)
        if orders.count() == 1:
            order = orders.first()
            existing_uid = clean_dicom_uid(order.dicom_study_instance_uid)
            if existing_uid and existing_uid != uid:
                # Task 3.2: never overwrite an existing different UID.
                return (
                    MatchOutcome.CONFLICT,
                    None,
                    f"order already has a different Study UID ({existing_uid})",
                )
            if order.patient.mrn != patient_id:
                return (
                    MatchOutcome.CONFLICT,
                    None,
                    "MRN conflict for accession match",
                )
            return (
                MatchOutcome.LINKED,
                order,
                "accession + PatientID + facility match",
            )
        if orders.count() > 1:
            return (
                MatchOutcome.CONFLICT,
                None,
                f"{orders.count()} candidate orders for accession+MRN",
            )

    return MatchOutcome.UNMATCHED, None, "no safe deterministic match"


def sync_study_from_archive(client, orthanc_study_id, calling_ae_title=""):
    """Fetch trusted study metadata from the archive and upsert the mirror.

    Idempotent: safe under duplicate notifications, out-of-order arrival,
    and concurrent execution (guarded by unique constraint + row lock).
    """
    raw = client.get_study(orthanc_study_id, expand=False)
    if raw is None:
        logger.info("study %s no longer present in archive; skipping", orthanc_study_id)
        return None
    meta = raw.get("MainDicomTags", {}) or {}
    series_ids = raw.get("Series", []) or []

    uid = clean_dicom_uid(meta.get("StudyInstanceUID"))
    if not is_valid_dicom_uid(uid):
        # Required UID missing/invalid: record a visible integrity problem,
        # do not fabricate identity (Task 2.1 rule).
        logger.warning(
            "orthanc study %s has invalid StudyInstanceUID %r", orthanc_study_id, uid
        )
        _record_invalid_study(orthanc_study_id, uid)
        return None

    device, facility = resolve_facility_for_sender(calling_ae_title)
    accession = (meta.get("AccessionNumber") or "").strip()
    patient_id = (meta.get("PatientID") or "").strip()
    study_date, study_datetime = _parse_study_datetime(
        meta.get("StudyDate", ""), meta.get("StudyTime", "")
    )
    now = timezone.now()

    with transaction.atomic():
        study = (
            PACSStudy.objects.select_for_update()
            .filter(study_instance_uid=uid)
            .first()
        )
        created = study is None
        if created:
            study = PACSStudy(study_instance_uid=uid)

        # Duplicate/conflict handling (Task 2.4): compare identity tags.
        conflict_reason = ""
        if not created:
            old_identity = {
                "PatientID": study.patient_id_as_received,
                "AccessionNumber": study.accession_number,
                "StudyInstanceUID": study.study_instance_uid,
            }
            new_identity = {
                "PatientID": patient_id,
                "AccessionNumber": accession,
                "StudyInstanceUID": uid,
            }
            diffs = [
                tag
                for tag in _IDENTITY_TAGS
                if (old_identity[tag] or "") != (new_identity[tag] or "")
                and (old_identity[tag] or new_identity[tag])
            ]
            if diffs:
                conflict_reason = (
                    "UID collision with different content for: "
                    + ", ".join(sorted(diffs))
                )

        fields = {
            "orthanc_study_id": raw.get("ID", orthanc_study_id),
            "patient_id_as_received": patient_id,
            "accession_number": accession,
            "study_date": study_date,
            "study_datetime": study_datetime,
            "study_description": (meta.get("StudyDescription") or "")[:200],
            "referring_physician": (meta.get("ReferringPhysicianName") or "")[:150],
            "patient_name_as_received": (meta.get("PatientName") or "")[:200],
            "series_count": len(series_ids),
        }
        for key, value in fields.items():
            setattr(study, key, value)

        # Trusted ownership context only ever set from sender mapping.
        facility_conflict = ""
        if facility is not None and study.facility_id != facility.id:
            if study.facility_id is None:
                study.facility = facility
                study.sender_device = device
            else:
                facility_conflict = (
                    "cross-facility UID collision detected (mirror keeps original owner)"
                )
        elif study.facility_id is None and device is None and calling_ae_title:
            # Unknown sender: no trusted facility context yet — this is a
            # reconciliation condition, not an archive integrity conflict.
            pass

        # Counts come from the archive view; instance count requires one
        # lightweight expanded lookup of series when changed.
        instance_total = study.instance_count
        if created or study.series_count != len(series_ids) or study.status in (
            StudyStatus.RECEIVED,
            StudyStatus.INDEXED,
        ):
            instance_total = _count_instances(client, series_ids)
        study.instance_count = instance_total or study.instance_count

        if study.first_received_at is None:
            study.first_received_at = now
        study.last_received_at = now

        if conflict_reason or facility_conflict:
            study.status = StudyStatus.INTEGRITY_CONFLICT
            study.status_reason = "; ".join(
                r for r in (conflict_reason, facility_conflict) if r
            )
        elif study.matched_order_id:
            study.status = StudyStatus.AVAILABLE
            study.status_reason = ""
            study.indexed_at = study.indexed_at or now
        else:
            outcome, order, reason = apply_matching_policy(study)
            if outcome == MatchOutcome.LINKED and study.facility_id is None:
                # Unknown sender: never auto-assign facility/tenant from
                # DICOM tags (plan §1.6). Park for reconciliation even if
                # an accession+MRN candidate exists.
                study.status = StudyStatus.RECONCILIATION_REQUIRED
                study.status_reason = (
                    f"unknown sender AE title '{calling_ae_title}'; "
                    "no trusted facility context"
                )
            elif outcome == MatchOutcome.LINKED:
                study.matched_order = order
                study.status = StudyStatus.AVAILABLE
                study.status_reason = ""
                study.indexed_at = now
                # Task 3.2: assign Study UID back to the order only when
                # the field is empty and the match is confirmed. Never
                # overwrite an existing different UID (conflict path above).
                if not clean_dicom_uid(order.dicom_study_instance_uid):
                    ExamOrder.objects.filter(pk=order.pk).update(
                        dicom_study_instance_uid=uid
                    )
            elif outcome == MatchOutcome.CONFLICT:
                study.status = StudyStatus.RECONCILIATION_REQUIRED
                study.status_reason = reason
            else:
                study.status = StudyStatus.RECONCILIATION_REQUIRED
                study.status_reason = reason

        study.save()

    logger.info(
        "pacs sync study=%s orthanc=%s status=%s series=%s instances=%s",
        uid,
        study.orthanc_study_id,
        study.status,
        study.series_count,
        study.instance_count,
    )
    return study


def _count_instances(client, series_ids):
    total = 0
    for sid in series_ids:
        try:
            series = client._request(f"/series/{sid}")
        except OrthancUnavailable:
            raise
        except OrthancError:
            logger.warning("could not inspect series %s", sid)
            continue
        if isinstance(series, dict):
            total += len(series.get("Instances", []) or [])
    return total


def _record_invalid_study(orthanc_study_id, uid):
    """Persist a visible SYNC_ERROR marker for a study whose UID is invalid.

    We cannot key PACSStudy without a valid UID, so the failure lives in
    SyncEvent/operational logs; the replay command will re-attempt once
    the archive data is corrected. The synthetic change number is derived
    deterministically from (orthanc id, bad uid) so repeated sightings of
    the same defect do not pile up duplicate rows.
    """
    digest = hashlib.sha256(f"{orthanc_study_id}|{uid}".encode()).hexdigest()
    synthetic_change = -(int(digest[:15], 16) + 1)  # negative => synthetic marker
    SyncEvent.objects.update_or_create(
        change=synthetic_change,
        defaults={
            "path": f"studies/{orthanc_study_id}"[:200],
            "resource_type": "Study",
            "outcome": SyncEvent.Outcome.FAILED,
            "error_category": "invalid_study_uid",
            "error_detail": f"StudyInstanceUID invalid: {uid!r}"[:2000],
        },
    )


def process_changes(client=None, limit=200):
    """Consume the Orthanc changes feed from the durable cursor.

    Returns dict of counters for observability. Raises OrthancUnavailable
    to the caller (Celery task) so retry/backoff applies; individual bad
    events are recorded as FAILED and processing continues.
    """
    client = client or OrthancClient()
    # Durable cursor: resume strictly after the last event we finished
    # handling (processed OR recorded-failed). PENDING events (archive was
    # down) are re-delivered on the next poll; PACSStudy upserts are
    # idempotent so replaying them is safe.
    done_through = SyncEvent.objects.filter(
        outcome__in=(SyncEvent.Outcome.PROCESSED, SyncEvent.Outcome.FAILED)
    ).filter(change__gte=0).aggregate(m=Max("change"))["m"]
    since = done_through if done_through is not None else -1

    counters = {"fetched": 0, "processed": 0, "failed": 0, "ignored": 0}
    changes, _last_change = client.get_changes(since=since)
    for change in changes[:limit]:
        counters["fetched"] += 1
        index = change.get("Index")
        path = change.get("Path", "") or ""
        rtype = change.get("Type", "") or ""
        if index is None:
            counters["ignored"] += 1
            continue
        event, created = SyncEvent.objects.get_or_create(
            change=index,
            defaults={"path": path[:200], "resource_type": rtype[:32]},
        )
        if not created and event.outcome == SyncEvent.Outcome.PROCESSED:
            counters["ignored"] += 1
            continue
        event.attempts += 1
        event.save(update_fields=["attempts"])
        try:
            _handle_change(client, change)
            event.outcome = SyncEvent.Outcome.PROCESSED
            event.processed_at = timezone.now()
            event.error_category = ""
            event.error_detail = ""
            counters["processed"] += 1
        except OrthancUnavailable:
            event.outcome = SyncEvent.Outcome.PENDING
            event.error_category = "archive_unavailable"
            event.save()
            raise  # let the worker retry with backoff; cursor stays put
        except Exception as exc:  # recorded, bounded, never silent
            event.outcome = SyncEvent.Outcome.FAILED
            event.error_category = type(exc).__name__[:64]
            event.error_detail = str(exc)[:2000]
            counters["failed"] += 1
            logger.warning("sync event %s failed: %s", index, exc)
        event.save()
    return counters


def replay_all_studies(client=None, limit=None):
    """Rebuild/reconcile the mirror from the archive (Task 2.2 replay path).

    Iterates every study known to Orthanc via /studies and re-runs the
    idempotent sync for each. Used after missed events, deployment
    failure, or as a periodic integrity sweep.
    """
    client = client or OrthancClient()
    study_ids = client._request("/studies") or []
    if isinstance(study_ids, dict):  # paginated responses
        study_ids = study_ids.get("Results", [])
    if limit:
        study_ids = study_ids[:limit]
    synced = errors = 0
    for sid in study_ids:
        try:
            if sync_study_from_archive(client, sid) is not None:
                synced += 1
        except OrthancUnavailable:
            raise
        except Exception as exc:
            errors += 1
            logger.warning("replay failed for orthanc study %s: %s", sid, exc)
    return {"total": len(study_ids), "synced": synced, "errors": errors}


def resolve_parent_study(client, orthanc_id):
    """Walk a resource's ParentResources chain up to the owning study.

    Returns an Orthanc study id (e.g. "abc/def") or None if unresolvable.
    """
    current = orthanc_id
    for _ in range(4):  # instance -> series -> study; bounded walk
        try:
            info = client._request(f"/{current}")
        except OrthancAPIError as exc:
            if exc.status == 404:
                return None
            raise
        parents = (info or {}).get("ParentResources", []) or []
        for parent in parents:
            if parent.startswith("studies/"):
                return parent
        if not parents:
            return None
        current = parents[-1]
    return None


def _handle_change(client, change):
    """Resolve a single Orthanc change to its parent study and sync it."""
    path = change.get("Path", "") or ""
    # Paths look like: instances/<id>, series/<id>/instances/..., studies/<id>/...
    parts = path.split("/")
    if "studies" in parts:
        idx = parts.index("studies")
        if idx + 1 < len(parts):
            study_orthanc_id = f"studies/{parts[idx + 1]}"
        else:
            return
    elif parts and parts[0] in ("instances", "series") and len(parts) >= 2:
        study_orthanc_id = resolve_parent_study(client, "/".join(parts[:2]))
        if study_orthanc_id is None:
            raise OrthancError(f"cannot resolve parent study for path {path}")
    else:
        return  # non-resource change (e.g. label updates) — ignore safely
    calling_ae = change.get("SourceAETitle", "") or ""
    sync_study_from_archive(client, study_orthanc_id, calling_ae_title=calling_ae)
