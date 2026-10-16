"""Reconciliation work queue service (PACS plan Phase 3, Task 3.3).

All actions are facility-scoped server-side and audited with the acting
user, timestamp, before/after order link, reason, and any conflicting
identifiers. Destructive "delete" is deliberately NOT offered as a
resolution — studies live in the authoritative archive; this queue only
manages the RIS linkage decision.

Role policy:
- PROVIDER / ADMIN / superuser: may link/unlink, mark incorrectly
  received, move between authorized facilities, escalate.
- Any facility-scoped staff user may VIEW the queue for their sites.
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction

from clinic.permissions import accessible_facility_ids, record_audit_service
from pacs.models import PACSStudy, StudyStatus
from pacs.services import MatchOutcome, apply_matching_policy

# Actions that change study linkage/ownership state.
REASON_MAX_LEN = 500


def can_reconcile(user):
    """Server-side role check for reconciliation actions (Task 3.3)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    from clinic.models import FacilityAssignment

    roles = set(
        FacilityAssignment.objects.filter(user=user, is_active=True).values_list(
            "role_at_facility", flat=True
        )
    )
    return bool(roles & {"PROVIDER", "ADMIN"})


def scoped_studies(user, queryset=None):
    """Restrict a PACSStudy queryset to the user's accessible facilities.

    Studies without a trusted facility yet (unknown sender) are visible
    only to superusers — they have no owner site to scope against yet.
    URL-ID manipulation is blocked because every detail/action view must
    fetch through this helper.
    """
    qs = queryset if queryset is not None else PACSStudy.objects.all()
    ids = accessible_facility_ids(user)
    if ids is None:  # superuser: unrestricted
        return qs
    if not ids:
        return qs.none()
    return qs.filter(facility_id__in=ids)


def reconciliation_queue(user, statuses=None):
    """Facility-scoped list of unmatched/conflicting studies (Task 3.3)."""
    statuses = statuses or [
        StudyStatus.RECONCILIATION_REQUIRED,
        StudyStatus.INTEGRITY_CONFLICT,
        StudyStatus.SYNC_ERROR,
    ]
    return scoped_studies(user).filter(status__in=statuses).select_related(
        "facility", "sender_device", "matched_order"
    )


def _require_access(user, study_pk):
    study = scoped_studies(user).filter(pk=study_pk).first()
    if study is None:
        # Same error for "does not exist" and "not your facility" so the
        # queue does not leak cross-facility existence through ID probing.
        raise PermissionDenied("Study not found in your permitted scope.")
    if not can_reconcile(user):
        raise PermissionDenied("Your role cannot perform reconciliation actions.")
    return study


def _audit(user, action, study, old, new):
    record_audit_service(
        action,
        entity_type="PACSStudy",
        entity_id=str(study.pk),
        user=user,
        old=old,
        new=new,
    )


def _snapshot(study):
    return {
        "status": study.status,
        "matched_order": str(study.matched_order_id) if study.matched_order_id else "",
        "facility": str(study.facility_id) if study.facility_id else "",
        "reason": study.status_reason,
    }


def preview_link(study, order):
    """Return the DICOM-vs-RIS differences an authorized user must see
    BEFORE confirming a manual link (Task 3.3 requirement)."""
    diffs = []
    if (study.accession_number or "") != (order.accession_number or ""):
        diffs.append(
            {
                "field": "accession_number",
                "dicom": study.accession_number,
                "ris": order.accession_number,
            }
        )
    if (study.patient_id_as_received or "") != (order.patient.mrn or ""):
        diffs.append(
            {
                "field": "patient_id/MRN",
                "dicom": study.patient_id_as_received,
                "ris": order.patient.mrn,
            }
        )
    order_uid = study.study_instance_uid  # linking candidate UID
    if order.dicom_study_instance_uid and order.dicom_study_instance_uid != order_uid:
        diffs.append(
            {
                "field": "study_instance_uid",
                "dicom": order_uid,
                "ris": order.dicom_study_instance_uid,
            }
        )
    return diffs


@transaction.atomic
def manual_link(user, study_pk, order_pk, reason):
    """Link a queued study to an existing order after explicit review.

    Conflicts (different existing UID on the order, foreign facility) are
    refused here rather than silently resolved; the caller must show
    ``preview_link`` differences and pass an explicit reason which is
    persisted in the audit record.
    """
    from orders.models import ExamOrder

    study = _require_access(user, study_pk)
    order_qs = ExamOrder.objects.filter(pk=order_pk, is_deleted=False)
    ids = accessible_facility_ids(user)
    if ids is not None:
        order_qs = order_qs.filter(facility_id__in=ids)
    order = order_qs.first()
    if order is None:
        raise PermissionDenied("Order not found in your permitted scope.")

    before = _snapshot(study)

    # Facility guard: never link across facilities the study is owned by.
    if study.facility_id and order.facility_id != study.facility_id:
        raise ValueError("order facility does not match the study's trusted facility")

    # Never overwrite an existing different Study UID (Task 3.2).
    if (
        order.dicom_study_instance_uid
        and order.dicom_study_instance_uid != study.study_instance_uid
    ):
        raise ValueError("order already carries a different Study Instance UID")

    study.matched_order = order
    study.status = StudyStatus.AVAILABLE
    study.status_reason = ""
    study.save(update_fields=["matched_order", "status", "status_reason", "updated_at"])

    if not order.dicom_study_instance_uid:
        ExamOrder.objects.filter(pk=order.pk).update(
            dicom_study_instance_uid=study.study_instance_uid
        )

    after = _snapshot(study)
    _audit(
        user,
        "pacs.manual_link",
        study,
        {**before, "conflicting_identifiers": _diffs_serializable(study, order)},
        {**after, "reason": (reason or "")[:REASON_MAX_LEN]},
    )
    return study


@transaction.atomic
def manual_unlink(user, study_pk, reason):
    """Remove an automatic/manual order link (keeps the study archived)."""
    study = _require_access(user, study_pk)
    if study.matched_order_id is None:
        raise ValueError("study is not linked to an order")
    before = _snapshot(study)
    order = study.matched_order
    study.matched_order = None
    study.status = StudyStatus.RECONCILIATION_REQUIRED
    study.status_reason = f"manually unlinked: {(reason or '')[:200]}"
    study.save(update_fields=["matched_order", "status", "status_reason", "updated_at"])
    if order is not None and order.dicom_study_instance_uid == study.study_instance_uid:
        from orders.models import ExamOrder

        ExamOrder.objects.filter(pk=order.pk).update(dicom_study_instance_uid="")
    _audit(
        user,
        "pacs.manual_unlink",
        study,
        before,
        {**_snapshot(study), "reason": (reason or "")[:REASON_MAX_LEN]},
    )
    return study


@transaction.atomic
def mark_incorrectly_received(user, study_pk, reason):
    """Non-destructive resolution: keep the object in the archive but take
    it out of the clinical workflow with an audited reason."""
    study = _require_access(user, study_pk)
    before = _snapshot(study)
    order = study.matched_order
    study.matched_order = None
    study.status = StudyStatus.RECONCILIATION_REQUIRED
    study.status_reason = f"marked incorrectly received: {(reason or '')[:200]}"
    study.save(update_fields=["matched_order", "status", "status_reason", "updated_at"])
    if order is not None and order.dicom_study_instance_uid == study.study_instance_uid:
        from orders.models import ExamOrder

        ExamOrder.objects.filter(pk=order.pk).update(dicom_study_instance_uid="")
    _audit(
        user,
        "pacs.mark_incorrectly_received",
        study,
        before,
        {**_snapshot(study), "reason": (reason or "")[:REASON_MAX_LEN]},
    )
    return study


@transaction.atomic
def move_facility(user, study_pk, target_facility_id, reason):
    """Move a study to another facility ONLY under an audited policy:
    actor must be able to access BOTH the current and target facility,
    and both before/after facility ids are recorded."""
    from core.models import Facility

    study = _require_access(user, study_pk)
    ids = accessible_facility_ids(user)
    if ids is not None:
        if study.facility_id and study.facility_id not in ids:
            raise PermissionDenied("current facility outside your scope")
        if target_facility_id not in ids:
            raise PermissionDenied("target facility outside your scope")
    target = Facility.objects.filter(pk=target_facility_id).first()
    if target is None:
        raise ValueError("target facility does not exist")
    before = _snapshot(study)
    # Moving ownership invalidates any automatic match until re-matched.
    study.facility = target
    study.sender_device = None
    study.matched_order = None
    study.status = StudyStatus.RECONCILIATION_REQUIRED
    study.status_reason = f"moved between facilities: {(reason or '')[:200]}"
    study.save(
        update_fields=[
            "facility",
            "sender_device",
            "matched_order",
            "status",
            "status_reason",
            "updated_at",
        ]
    )
    _audit(
        user,
        "pacs.move_facility",
        study,
        before,
        {**_snapshot(study), "reason": (reason or "")[:REASON_MAX_LEN]},
    )
    return study


@transaction.atomic
def escalate(user, study_pk, reason):
    """Flag for supervisor attention without changing linkage."""
    study = _require_access(user, study_pk)
    before = _snapshot(study)
    note = f"escalated to supervisor: {(reason or '')[:200]}"
    study.status_reason = f"{study.status_reason}; {note}" if study.status_reason else note
    study.save(update_fields=["status_reason", "updated_at"])
    _audit(
        user,
        "pacs.escalate",
        study,
        before,
        {**_snapshot(study), "reason": (reason or "")[:REASON_MAX_LEN]},
    )
    return study


@transaction.atomic
def rematch(user, study_pk):
    """Re-run the deterministic matching policy after data corrections."""
    study = _require_access(user, study_pk)
    before = _snapshot(study)
    outcome, order, reason = apply_matching_policy(study)
    if outcome == MatchOutcome.LINKED and study.facility_id is not None:
        study.matched_order = order
        study.status = StudyStatus.AVAILABLE
        study.status_reason = ""
        if not order.dicom_study_instance_uid:
            from orders.models import ExamOrder

            ExamOrder.objects.filter(pk=order.pk).update(
                dicom_study_instance_uid=study.study_instance_uid
            )
    elif outcome == MatchOutcome.CONFLICT:
        study.status = StudyStatus.RECONCILIATION_REQUIRED
        study.status_reason = reason
    else:
        study.status = StudyStatus.RECONCILIATION_REQUIRED
        study.status_reason = reason
    study.save(update_fields=["matched_order", "status", "status_reason", "updated_at"])
    _audit(user, "pacs.rematch", study, before, _snapshot(study))
    return study


def _diffs_serializable(study, order):
    return preview_link(study, order)
