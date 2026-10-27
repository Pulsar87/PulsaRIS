"""Storage service for the HL7 lab/vitals receiver (Django ORM edition).

Replaces the raw-psycopg persistence of the standalone script with the app's
own database connection, so received messages live in the same PostgreSQL
database as the rest of the RIS. Deduplication mirrors the original behaviour:

* ``control-id`` (default): advisory lock + lookup on sender identity + MSH-10;
  identical retransmission -> ``duplicate``, reused control ID with different
  contents -> ``rejected``.
* ``payload``: advisory lock + SHA-256 of the exact bytes.
* ``none``: store everything.

PostgreSQL-only features (advisory locks) are skipped gracefully on other
backends (dev/test SQLite), where a plain locked transaction is used instead.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import timezone
from pathlib import Path
from typing import Any, Optional

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from integrations.hl7.models import HL7VitalMessage, MessageStatus
from integrations.hl7.parsing import (
    VITAL_SCHEMA_VERSION,
    parse_message,
    payload_hash,
)

logger = logging.getLogger("integrations.hl7")


# --------------------------------------------------------------------- config
def hl7_setting(name: str, default=None):
    """Read ``settings.HL7_LISTENER[name]`` falling back to ``HL7_<name>`` attr."""
    config = getattr(settings, "HL7_LISTENER", {}) or {}
    if name in config:
        return config[name]
    return getattr(settings, f"HL7_{name}", default)


def get_database_url() -> str:
    """DSN of the *same* database Django uses (for the migration importer)."""
    url = hl7_setting("DATABASE_URL")
    if url:
        return url
    db = settings.DATABASES["default"]
    engine = db.get("ENGINE", "")
    if "sqlite" in engine:
        return f"sqlite://{db['NAME']}"
    from urllib.parse import quote_plus

    user = quote_plus(str(db.get("USER", "")))
    password = quote_plus(str(db.get("PASSWORD", "")))
    host = db.get("HOST", "localhost")
    port = db.get("PORT", 5432)
    name = db.get("NAME", "")
    scheme = "postgresql" if "postgres" in engine else engine.split(".")[-2]
    return f"{scheme}://{user}:{password}@{host}:{port}/{name}"


# ------------------------------------------------------------------- ingest
def persist_payload(
    raw_bytes: bytes,
    remote_host: str = "",
    remote_port: Optional[int] = None,
    *,
    dedupe: Optional[str] = None,
    allow_empty_control_id: Optional[bool] = None,
    archive_dir: Optional[str] = None,
) -> dict[str, Any]:
    """Parse one HL7 payload and store it in the app database.

    Returns a dict describing the stored record and its disposition
    (``status`` ∈ accepted / duplicate / rejected / parse_error).
    """
    if dedupe is None:
        dedupe = str(hl7_setting("DEDUPE", "control-id"))
    if allow_empty_control_id is None:
        allow_empty_control_id = bool(hl7_setting("ALLOW_EMPTY_CONTROL_ID", False))
    if archive_dir is None:
        archive_dir = hl7_setting("ARCHIVE_DIR")

    raw_text = raw_bytes.decode(str(hl7_setting("ENCODING", "utf-8")), errors="replace")
    parsed, parse_errors = parse_message(raw_text)
    # Some monitor firmware emits a valid-looking ORU header but leaves MSH-10
    # blank. Permit this only when explicitly enabled by the operator; such
    # messages cannot be safely deduplicated by control ID.
    if allow_empty_control_id:
        parse_errors = [e for e in parse_errors if e != "MSH-10 message control ID is empty"]

    header = parsed.get("message_header", {})
    sending_app = str(header.get("sending_application", ""))
    sending_facility = str(header.get("sending_facility", ""))
    control_id = str(header.get("message_control_id", ""))
    sender_identity = f"{sending_app}|{sending_facility}"
    digest = payload_hash(raw_bytes)

    with transaction.atomic():
        _acquire_advisory_lock(dedupe, sender_identity, control_id, digest, parse_errors)

        status = MessageStatus.ACCEPTED
        error = "; ".join(parse_errors)
        duplicate_of: Optional[HL7VitalMessage] = None

        if parse_errors:
            status = MessageStatus.PARSE_ERROR
        elif dedupe == "control-id" and control_id:
            previous = (
                HL7VitalMessage.objects.filter(
                    sender_identity=sender_identity,
                    message_control_id=control_id,
                    status=MessageStatus.ACCEPTED,
                )
                .order_by("-id")
                .first()
            )
            if previous:
                duplicate_of = previous
                if previous.payload_sha256 == digest:
                    status = MessageStatus.DUPLICATE
                    error = f"Retransmission of message already stored as record {previous.pk}"
                else:
                    status = MessageStatus.REJECTED
                    error = (
                        f"Message control ID {control_id!r} was reused with different "
                        f"contents; original record {previous.pk}"
                    )
        elif dedupe == "payload":
            previous = (
                HL7VitalMessage.objects.filter(payload_sha256=digest, status=MessageStatus.ACCEPTED)
                .order_by("-id")
                .first()
            )
            if previous:
                duplicate_of = previous
                status = MessageStatus.DUPLICATE
                error = f"Identical payload already stored as record {previous.pk}"

        message = HL7VitalMessage(
            received_at=dj_timezone.now(),
            remote_host=remote_host,
            remote_port=remote_port,
            sender_identity=sender_identity,
            sending_application=sending_app,
            sending_facility=sending_facility,
            message_control_id=control_id,
            message_type=str(header.get("message_type", "")),
            trigger_event=str(header.get("trigger_event", "")),
            payload_sha256=digest,
            status=status,
            error=error,
            duplicate_of=duplicate_of,
            raw_hl7=raw_text,
            parsed_json=parsed,
        )
        message.apply_vitals()
        message.save()

    try:
        archive_message(archive_dir, message.pk, message.received_at, digest, raw_bytes)
    except Exception as exc:  # archiving must never fail the ingestion
        logger.exception("Could not write optional archive for record %s: %s", message.pk, exc)

    logger.info(
        "Received record_id=%s peer=%s:%s status=%s type=%s control_id=%s sender=%s detail=%s",
        message.pk, remote_host, remote_port, status,
        message.message_type or "unknown", message.message_control_id or "(empty)",
        sender_identity, error or "(none)",
    )
    return {
        "id": message.pk,
        "status": status,
        "error": error,
        "control_id": control_id,
        "message_type": message.message_type,
        "sending_application": sending_app,
        "sending_facility": sending_facility,
        "parsed": parsed,
        "payload_hash": digest,
        "object": message,
    }


def _acquire_advisory_lock(dedupe: str, sender_identity: str, control_id: str, digest: str, parse_errors: list[str]) -> None:
    """Transaction-scoped advisory locks close the SELECT/INSERT race window.

    Only meaningful on PostgreSQL; silently no-ops elsewhere (the surrounding
    atomic block still keeps the check-and-insert consistent per process).
    """
    if connection.vendor != "postgresql" or parse_errors:
        return
    if dedupe == "control-id" and control_id:
        lock_key = f"control-id:{sender_identity}:{control_id}"
    elif dedupe == "payload":
        lock_key = f"payload:{digest}"
    else:
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))


# ------------------------------------------------------------------ archive
def archive_message(archive_dir: Optional[str | os.PathLike], record_id: int, received_at, payload_sha256: str, raw_bytes: bytes) -> None:
    """Optional exact raw-message copies on disk (protect as PHI)."""
    if not archive_dir:
        return
    directory = Path(str(archive_dir)).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = received_at.isoformat() if hasattr(received_at, "isoformat") else str(received_at)
    safe_time = re.sub(r"[^0-9A-Za-zT_-]", "", stamp)
    target = directory / f"{safe_time}_id{record_id}_{payload_sha256[:12]}.hl7"
    fd, temporary = tempfile.mkstemp(dir=directory, suffix=".hl7.tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


# ----------------------------------------------------------- backfill helper
def backfill_existing_vital_columns(batch_size: int = 500) -> int:
    """Rebuild vitals columns for rows written by older schema versions."""
    updated = 0
    while True:
        rows = list(
            HL7VitalMessage.objects.filter(vitals_schema_version__lt=VITAL_SCHEMA_VERSION)
            .order_by("id")
            .values_list("pk", flat=True)[:batch_size]
        )
        if not rows:
            return updated
        for pk in rows:
            with transaction.atomic():
                message = HL7VitalMessage.objects.get(pk=pk)
                message.apply_vitals()
                message.save(update_fields=["parsed_json", *vital_update_fields()])
            updated += 1


def vital_update_fields() -> list[str]:
    from integrations.hl7.parsing import NUMERIC_DB_FIELDS, TEXT_DB_FIELDS

    fields: list[str] = []
    for column in NUMERIC_DB_FIELDS:
        fields.extend([column, f"{column}_unit"])
    fields.extend(TEXT_DB_FIELDS)
    fields.extend(["vitals_json", "vitals_schema_version"])
    return fields
