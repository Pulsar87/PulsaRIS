"""Lightweight operational health helpers (Phase 4, plan Step 5.2 observability).

Used by the ``clinic_health`` JSON view (staff-only, GET): reports outbox
backlog depth and oldest-pending age so rollout soak periods (Step 5.3) can
be monitored without external tooling.
"""

from clinic.outbox import backlog_depth, oldest_pending_age


def health_snapshot():
    age = oldest_pending_age()
    return {
        "outbox": {
            "pending_backlog": backlog_depth(),
            "oldest_pending_seconds": age.total_seconds(),
        },
        "note_chain_integrity": note_chain_check(),
    }


def note_chain_check():
    """Run EncounterNote.verify_chain() across facilities; report failures.

    Returns {"checked_facilities": N, "broken_chains": [encounter ids...]}.
    Scheduled during soak (Step 5.3 item 3); cheap enough to run per flush.
    """
    from django.db.models import Count

    from clinic.models import EncounterNote

    broken = []
    facility_ids = list(
        EncounterNote.objects.values_list("encounter__facility_id", flat=True)
        .annotate(c=Count("id"))
        .distinct()
    )
    # Verify per encounter chain (notes are chained within an encounter).
    for enc_id in (
        EncounterNote.objects.values_list("encounter_id", flat=True).distinct()
    ):
        notes = EncounterNote.objects.filter(encounter_id=enc_id).order_by("version")
        for n in notes:
            if not n.verify_integrity():
                broken.append(str(enc_id))
                break
    return {"checked_facilities": len(facility_ids), "broken_chains": broken}
