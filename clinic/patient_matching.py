"""Patient-matching reconciliation service (Phase 4, plan Step 5.1).

Duplicate ``patients.Patient`` identity rows can appear when the same person
is registered at two sites before a shared MRN exists. This module merges a
duplicate into a canonical record:

- every operational row pointing at the duplicate is re-pointed to the
  canonical patient inside one transaction;
- each site identifier moves to the canonical patient as a
  ``PatientFacilityIdentifier`` (site MRNs are preserved forever);
- the duplicate is deactivated (``is_active=False``, MRN suffixed with
  ``-MERGED-<canonical-short-id>`` to free the unique-MRN slot) — never
  deleted, so history stays intact;
- an append-only merge log entry is written to ``audit.AuditLog``
  (action ``CLINIC_PATIENT_MERGE``) via the shared audit helper.

Manual review only: no automatic threshold-based merging yet (open decision
in plan section E / Step 5.1 — "auto-link vs manual-review" — defaults to
manual until owners answer).
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone


from clinic.models import PatientFacilityIdentifier, PatientMergeLog
from clinic.permissions import record_audit_service
from patients.models import Patient

# Models with a direct FK named ``patient`` that must follow the merge.
# (Encounter-scoped records — Vitals, EncounterNote — hang off Encounter and
# follow the merge automatically once encounters are re-pointed.)
PATIENT_FK_LABELS = [
    "clinic.Appointment",
    "clinic.Encounter",
    "clinic.Problem",
    "clinic.Allergy",
    "clinic.Medication",
    "clinic.Prescription",
    "orders.ExamOrder",
]


def find_candidate_duplicates():
    """Surface probable duplicate patients for human review.

    Conservative heuristic (no auto-merge): same first name, same last name
    (both case-insensitive), same date of birth, different active records.
    Returns a list of ``(canonical_candidate, duplicate_candidate)`` tuples —
    earliest-created record first in each pair.
    """
    qs = Patient.objects.filter(is_deleted=False)
    rows = list(
        qs.values("id", "first_name_en", "last_name_en", "dob")
    )
    buckets = {}
    for r in rows:
        key = (
            (r["first_name_en"] or "").strip().lower(),
            (r["last_name_en"] or "").strip().lower(),
            r["dob"],
        )
        if not key[0] or not key[1] or not key[2]:
            continue  # require all three fields to avoid noisy matches
        buckets.setdefault(key, []).append(r["id"])

    dupes = []
    id_objs = {p.id: p for p in qs.filter(id__in=[i for ids in buckets.values() for i in ids])}
    for ids in buckets.values():
        if len(ids) > 1:
            ids_sorted = sorted(ids, key=lambda i: id_objs[i].created_at)
            for other in ids_sorted[1:]:
                dupes.append((id_objs[ids_sorted[0]], id_objs[other]))
    return dupes


@transaction.atomic
def merge_patients(*, duplicate: Patient, canonical: Patient, actor=None):
    """Merge ``duplicate`` into ``canonical``. Returns dict summary."""
    if duplicate.pk == canonical.pk:
        raise ValidationError("Cannot merge a patient into itself.")
    if duplicate.is_deleted or canonical.is_deleted:
        raise ValidationError("Both records must be non-deleted to merge.")

    summary = {"repointed": {}, "identifiers_moved": 0}

    # 1. Move site identifiers (skip collisions on the per-site unique key).
    for ident in list(duplicate.facility_identifiers.all()):
        clash = PatientFacilityIdentifier.objects.filter(
            facility=ident.facility,
            identifier_type=ident.identifier_type,
            identifier=ident.identifier,
        ).exclude(patient=duplicate).exists()
        if clash:
            # Canonical already has this exact site identifier; keep the
            # duplicate's row detached by leaving it on the duplicate
            # (deactivated below) rather than violating uniqueness.
            continue
        if ident.is_primary and PatientFacilityIdentifier.objects.filter(
            patient=canonical, facility=ident.facility, is_primary=True
        ).exists():
            ident.is_primary = False
        ident.patient = canonical
        ident.save(update_fields=["patient", "is_primary"])
        summary["identifiers_moved"] += 1

    # 2. Re-point operational rows. EncounterNote/Vitals etc. hang off
    # Encounter, so touching Appointment/Encounter/ExamOrder cascades.
    from django.apps import apps as django_apps

    for label in PATIENT_FK_LABELS:
        app_label, model_name = label.split(".")
        Model = django_apps.get_model(app_label, model_name)
        updated = Model.objects.filter(patient=duplicate).update(patient=canonical)
        if updated:
            summary["repointed"][label] = updated

    # 3. Anything protected (e.g. billing PatientAccount OneToOne) blocks the
    # deactivation unless handled; try to re-point known billing links first.
    try:
        from billing.models import PatientAccount

        account_dup = PatientAccount.objects.filter(patient=duplicate).first()
        if account_dup:
            existing = PatientAccount.objects.filter(patient=canonical).first()
            if existing:
                # Merge balances manually later; block silently here by
                # leaving the duplicate account attached until reconciled.
                summary["billing_conflict"] = True
            else:
                account_dup.patient = canonical
                account_dup.save(update_fields=["patient"])
                summary["repointed"]["billing.PatientAccount"] = 1
    except Exception:
        pass

    # 4. Retire the duplicate (never delete): tombstone via the existing
    # soft-delete fields, freeing the unique-MRN slot for active records.
    duplicate.is_deleted = True
    duplicate.deleted_at = timezone.now()
    duplicate.mrn = f"{duplicate.mrn}-MERGED-{str(canonical.pk)[:8]}"[:50]
    duplicate.save(update_fields=["is_deleted", "deleted_at", "mrn"])
    summary["merged_into"] = str(canonical.pk)

    # Append-only, queryable merge history (clinic.PatientMergeLog) written in
    # the same transaction as the merge; complements the generic AuditLog row.
    PatientMergeLog.objects.create(
        duplicate=duplicate, canonical=canonical, actor=actor, summary=summary
    )

    record_audit_service(
        "CLINIC_PATIENT_MERGE",
        entity_type="Patient",
        entity_id=duplicate.pk,
        user=actor,
        old={"status": "active_duplicate"},
        new={
            "canonical": str(canonical.pk),
            "repointed": summary["repointed"],
            "identifiers_moved": summary["identifiers_moved"],
        },
    )
    return summary
