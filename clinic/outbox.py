"""IntegrationEvent outbox consumer (Phase 4, plan Step 5.2).

Polls undelivered ``clinic.models.IntegrationEvent`` rows and exports them as
HL7 v2 ADT-style messages to a configurable drop target. Two transports:

- FILE DROP (default): appends one serialized message per event to
  ``CLINIC_OUTBOX_DIR/hl7-out.jsonl`` (JSON envelope wrapping the HL7-ish
  payload; easy to tail in a pilot, no network dependency).
- TCP: if ``CLINIC_OUTBOX_TCP_HOST``/``PORT`` settings exist, sends the same
  JSON line with a short timeout.

Delivery bookkeeping lives on the event row (append-only business payload is
never modified): ``delivered_at``, ``delivery_attempts``. Events that exceed
``CLINIC_OUTBOX_MAX_ATTEMPTS`` (default 5) become DEAD_LETTER via the
``status`` field added here — status transitions only, payload immutable.

Run from cron/celery beat, never on the request path:

    python manage.py flush_outbox --limit 100
"""

import json
import logging
import socket
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from clinic.models import IntegrationEvent

logger = logging.getLogger("clinic.outbox")

MAX_ATTEMPTS = getattr(settings, "CLINIC_OUTBOX_MAX_ATTEMPTS", 5)


def _hl7_envelope(event: IntegrationEvent) -> dict:
    """Map an internal event to an ADT-style export envelope.

    Deliberately a *stable internal contract* (v1), not raw HL7 — the FHIR/
    HL7 true mapping freezes after section-E answers land (plan gate 5.4).
    """
    trigger_map = {
        IntegrationEvent.EventType.APPOINTMENT_BOOKED: "A31/A32 (schedule)",
        IntegrationEvent.EventType.APPOINTMENT_CANCELLED: "A35/A36 (cancel)",
        IntegrationEvent.EventType.APPOINTMENT_COMPLETED: "A08 update (completed)",
        IntegrationEvent.EventType.ENCOUNTER_CLOSED: "A03 (discharge/close)",
    }
    return {
        "version": 1,
        "event_id": str(event.pk),
        "event_type": event.event_type,
        "trigger_event": trigger_map.get(event.event_type, event.event_type),
        "facility_id": str(event.facility_id) if event.facility_id else None,
        "entity_type": event.entity_type,
        "entity_id": str(event.entity_id),
        "created_at": event.created_at.isoformat(),
        "payload": event.payload,
    }


def _deliver(line: str) -> None:
    host = getattr(settings, "CLINIC_OUTBOX_TCP_HOST", None)
    port = getattr(settings, "CLINIC_OUTBOX_TCP_PORT", None)
    if host and port:
        timeout = getattr(settings, "CLINIC_OUTBOX_TCP_TIMEOUT", 5)
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.sendall((line + "\r\n").encode())
        return
    import os

    out_dir = getattr(settings, "CLINIC_OUTBOX_DIR", os.path.join(settings.BASE_DIR, "outbox"))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "hl7-out.jsonl"), "a") as fh:
        fh.write(line + "\n")


def deliver_pending(limit=100):
    """Attempt delivery for up to ``limit`` pending events.

    Returns ``(delivered_count, dead_lettered_count)``. Uses select_for_update
    on backends that support it (Postgres) so concurrent consumers don't
    double-send; SQLite falls back to plain ordering (single-process dev).
    """
    qs = IntegrationEvent.objects.filter(delivered_at__isnull=True).order_by("created_at")
    if connection_supports_select_for_update():
        qs = qs.select_for_update(skip_locked=True)
    events = list(qs[:limit])
    delivered = dead = 0
    now = timezone.now()
    for ev in events:
        ev.delivery_attempts += 1
        try:
            _deliver(json.dumps(_hl7_envelope(ev), default=str))
            ev.delivered_at = now
            ev.status = IntegrationEvent.Status.DELIVERED
            delivered += 1
        except OSError as exc:
            ev.status = (
                IntegrationEvent.Status.DEAD_LETTER
                if ev.delivery_attempts >= MAX_ATTEMPTS
                else IntegrationEvent.Status.FAILED
            )
            dead += 1 if ev.status == IntegrationEvent.Status.DEAD_LETTER else 0
            logger.warning("outbox delivery failed for %s (attempt %d): %s",
                           ev.pk, ev.delivery_attempts, exc)
        ev.save(update_fields=["delivered_at", "delivery_attempts", "status"])
    if delivered or dead:
        logger.info("outbox flush: %d delivered, %d dead-lettered", delivered, dead)
    return delivered, dead


def connection_supports_select_for_update():
    from django.db import connections

    return connections["default"].vendor == "postgresql"


def backlog_depth():
    """Pending (undelivered, not dead-lettered) event count — health metric."""
    return IntegrationEvent.objects.filter(
        delivered_at__isnull=True,
        status__in=[IntegrationEvent.Status.PENDING, IntegrationEvent.Status.FAILED],
    ).count()


def oldest_pending_age():
    ev = IntegrationEvent.objects.filter(
        delivered_at__isnull=True, status=IntegrationEvent.Status.PENDING
    ).order_by("created_at").first()
    return timezone.now() - ev.created_at if ev else timedelta(0)
