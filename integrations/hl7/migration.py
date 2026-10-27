"""One-time import of the standalone receiver's SQLite database.

Reads the legacy ``messages`` table produced by
``hl7_lab_listener_edan_vitals_postgres_columns.py --sqlite`` (read-only; the
source file is never modified), rebuilds the normalized vitals layer, and
inserts rows into the Django model table. Existing destination IDs are skipped
(``ignore_conflicts`` on the primary key), so re-running is safe.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from django.db import transaction

from integrations.hl7.models import HL7VitalMessage
from integrations.hl7.parsing import build_vital_storage, normalize_vitals

logger = logging.getLogger("integrations.hl7.migration")

REQUIRED_COLUMNS = (
    "id", "received_at", "remote_host", "remote_port", "sender_identity",
    "sending_application", "sending_facility", "message_control_id", "message_type",
    "trigger_event", "payload_sha256", "status", "error", "duplicate_of", "raw_hl7",
    "parsed_json",
)


def _json_object(value: Any) -> dict[str, Any]:
    """Normalize stored JSON text without silently losing data."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("A stored parsed_json value is not valid JSON; refusing to replace it") from exc
        if isinstance(decoded, dict):
            return decoded
        raise ValueError("A stored parsed_json value is not a JSON object; refusing to replace it")
    if value is None:
        return {}
    raise ValueError(f"Unsupported parsed_json value type: {type(value).__name__}")


def migrate_sqlite(source_path: str, batch_size: int = 500) -> tuple[int, int]:
    """Import a legacy SQLite ``messages`` database. Returns (imported, skipped)."""
    path = Path(source_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"SQLite source database not found: {path}")

    imported = 0
    skipped = 0
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as old:
        old.row_factory = sqlite3.Row
        old_columns = {r[1] for r in old.execute("PRAGMA table_info(messages)").fetchall()}
        if not old_columns:
            raise RuntimeError(f"No 'messages' table found in SQLite database: {path}")
        missing = [c for c in REQUIRED_COLUMNS if c not in old_columns]
        if missing:
            raise RuntimeError(f"SQLite messages table is missing required columns: {', '.join(missing)}")
        cursor = old.execute("SELECT " + ", ".join(REQUIRED_COLUMNS) + " FROM messages ORDER BY id ASC")
        existing_ids = set(HL7VitalMessage.objects.values_list("id", flat=True))
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            with transaction.atomic():
                for row in rows:
                    record_id = int(row["id"])
                    if record_id in existing_ids:
                        skipped += 1
                        continue
                    parsed = _json_object(row["parsed_json"])
                    # Keep the legacy raw parse, then attach the normalized
                    # vitals layer (the same convenience view the live listener
                    # stores) before rebuilding the dedicated columns.
                    parsed["vitals"] = normalize_vitals({**parsed})
                    _vitals, vital_values = build_vital_storage(parsed)
                    message = HL7VitalMessage(
                        id=record_id,
                        received_at=row["received_at"],
                        remote_host=row["remote_host"] or "",
                        remote_port=row["remote_port"],
                        sender_identity=row["sender_identity"] or "",
                        sending_application=row["sending_application"] or "",
                        sending_facility=row["sending_facility"] or "",
                        message_control_id=row["message_control_id"] or "",
                        message_type=row["message_type"] or "",
                        trigger_event=row["trigger_event"] or "",
                        payload_sha256=row["payload_sha256"] or "",
                        status=row["status"] or "accepted",
                        error=row["error"] or "",
                        duplicate_of_id=row["duplicate_of"],
                        raw_hl7=row["raw_hl7"] or "",
                        parsed_json=parsed,
                    )
                    for column, value in vital_values.items():
                        setattr(message, column, value)
                    message.save()
                    existing_ids.add(record_id)
                    imported += 1
    logger.info("SQLite migration finished: imported=%s skipped_existing_ids=%s", imported, skipped)
    return imported, skipped
