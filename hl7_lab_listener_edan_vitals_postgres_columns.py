#!/usr/bin/env python3
"""HL7 v2 laboratory-device receiver using python-hl7, asyncio, and PostgreSQL.

Typical deployment (instrument configured as a TCP client, sending HL7/MLLP):
    export HL7_DATABASE_URL="postgresql://hl7_user:CHANGE_ME@127.0.0.1:5432/hl7db"
    python3 hl7_lab_listener_edan_vitals_postgres_columns.py --mode listen --host 0.0.0.0 --port 2575

The default protocol is MLLP, the common transport framing for HL7 v2 over TCP.
The service stores every received payload in PostgreSQL, parses PID/ORC/OBR/OBX/SPM
segments, preserves every OBX result, adds normalized `vitals` JSON plus dedicated measurement columns, and returns
an HL7 ACK after the message has been committed to disk.
It is intentionally vendor-neutral; instrument-specific fields and workflow semantics
may require mapping after checking that instrument's interface manual and sample messages.

Dependencies: `python-hl7` and `psycopg` (PostgreSQL driver). Install with `python3 -m pip install -r requirements_hl7_listener_postgres_columns.txt`.

Security notes:
- Run this only on a trusted, firewalled laboratory network/VLAN; do not expose the
  listener to the public internet. The usual MLLP transport itself is not encrypted.
- HL7 can contain patient health information. Protect PostgreSQL access, backups,
  optional archives, and log files with appropriate access controls and retention rules.
- An ACK means that this receiver persisted the message, not that results were imported
  into an EHR/LIS or clinically validated.

Examples:
    # Listen for standard MLLP traffic using the PostgreSQL DSN from the environment
    python3 hl7_lab_listener_edan_vitals_postgres_columns.py --host 0.0.0.0 --port 2575

    # Import a prior SQLite file once (then start the PostgreSQL-backed listener)
    python3 hl7_lab_listener_edan_vitals_postgres_columns.py --migrate-sqlite ./hl7_messages.sqlite3

    # Some non-standard devices send unframed messages; complete a message after
    # the connection has been quiet for 1.5 seconds (confirm with the vendor first)
    python3 hl7_lab_listener_edan_vitals_postgres_columns.py --framing raw-idle --raw-idle-seconds 1.5

    # If the instrument is listening for a host to connect to it:
    python3 hl7_lab_listener_edan_vitals_postgres_columns.py --mode connect --device-host 192.168.10.35 \
        --device-port 2575

Inspect stored messages with psql, e.g.:
    psql "$HL7_DATABASE_URL" -c "SELECT id, received_at, message_type, status, message_control_id FROM messages ORDER BY id DESC LIMIT 20;"
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import signal
import sqlite3  # Used only by the one-time SQLite-to-PostgreSQL migration command.
import sys
import uuid

try:
    import hl7 as hl7lib  # PyPI package: `hl7` (python-hl7)
except ImportError as exc:  # fail clearly rather than silently using a home-grown parser
    raise SystemExit(
        "Missing dependency: python-hl7. Install it with: python3 -m pip install hl7"
    ) from exc
from datetime import datetime, timezone
from typing import Any, Optional

MLLP_START = b"\x0b"  # VT
MLLP_END = b"\x1c\x0d"  # FS CR
DEFAULT_DATABASE_URL = os.environ.get("HL7_DATABASE_URL") or os.environ.get("DATABASE_URL")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def configure_logging(level: str, log_file: Optional[str]) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def normalize_hl7_text(raw: str) -> str:
    # HL7 v2 segment delimiters are CR. Normalize commonly encountered alternatives.
    return raw.replace("\r\n", "\r").replace("\n", "\r").lstrip("\ufeff")


def get_segment_id(segment: str) -> str:
    return segment[:3] if len(segment) >= 3 else segment


def split_hl7_field(segment: str, field_number: int, separator: str) -> str:
    """Return HL7 field number (1-based), accounting for MSH's special indexing."""
    parts = segment.split(separator)
    if get_segment_id(segment) == "MSH":
        if field_number == 1:
            return separator
        index = field_number - 1
    else:
        index = field_number
    return parts[index] if 0 <= index < len(parts) else ""


def hl7_unescape(value: str, separator: str, encoding_chars: str) -> str:
    """Decode standard single-character HL7 escapes for display/storage."""
    component = encoding_chars[0] if len(encoding_chars) > 0 else "^"
    repetition = encoding_chars[1] if len(encoding_chars) > 1 else "~"
    escape = encoding_chars[2] if len(encoding_chars) > 2 else "\\"
    subcomponent = encoding_chars[3] if len(encoding_chars) > 3 else "&"
    mapping = {
        "F": separator,
        "S": component,
        "R": repetition,
        "E": escape,
        "T": subcomponent,
        ".br": "\n",
    }
    pattern = re.compile(re.escape(escape) + r"([^\r]*?)" + re.escape(escape))

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        return mapping.get(token, match.group(0))

    return pattern.sub(replace, value)


def components(value: str, separator: str, encoding_chars: str) -> list[str]:
    comp_sep = encoding_chars[0] if len(encoding_chars) > 0 else "^"
    return [hl7_unescape(part, separator, encoding_chars) for part in value.split(comp_sep)]


def coded_value(value: str, separator: str, encoding_chars: str) -> dict[str, str]:
    parts = components(value, separator, encoding_chars)
    keys = ("identifier", "text", "coding_system", "alternate_identifier", "alternate_text", "alternate_coding_system")
    return {keys[i]: parts[i] for i in range(min(len(parts), len(keys)))}


def parse_cx(value: str, separator: str, encoding_chars: str) -> dict[str, str]:
    parts = components(value, separator, encoding_chars)
    keys = ("id", "check_digit", "check_digit_scheme", "assigning_authority", "identifier_type_code", "assigning_facility")
    return {keys[i]: parts[i] for i in range(min(len(parts), len(keys)))}


def parse_xpn(value: str, separator: str, encoding_chars: str) -> dict[str, str]:
    parts = components(value, separator, encoding_chars)
    keys = ("family_name", "given_name", "middle_name", "suffix", "prefix", "degree", "name_type_code")
    return {keys[i]: parts[i] for i in range(min(len(parts), len(keys)))}


def parse_xcn(value: str, separator: str, encoding_chars: str) -> dict[str, str]:
    parts = components(value, separator, encoding_chars)
    keys = ("id", "family_name", "given_name", "middle_name", "suffix", "prefix", "degree", "source_table", "assigning_authority", "name_type_code")
    return {keys[i]: parts[i] for i in range(min(len(parts), len(keys)))}


def _field(segment: str, number: int, separator: str, encoding_chars: str) -> str:
    return hl7_unescape(split_hl7_field(segment, number, separator), separator, encoding_chars)


# EDAN observation identifiers seen in the supplied monitor database, plus common
# equivalent labels. Keys are matched case-insensitively against OBX-3 identifier
# and text. Vendor-specific/unrecognized observations are still retained below.
VITAL_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "24960": ("device_software_version",),
    "EHC_DEV_SW_VERSION": ("device_software_version",),
    "DEV_SW_VERSION": ("device_software_version",),
    "WEIGHT": ("weight",),
    "BODY_WEIGHT": ("weight",),
    "MDC_MASS_BODY": ("weight",),
    "HEIGHT": ("height",),
    "BODY_HEIGHT": ("height",),
    "BLOODTYPE": ("blood_type",),
    "BLOOD_TYPE": ("blood_type",),
    "150456": ("spo2",),
    "MDC_PULS_OXIM_SAT_O2": ("spo2",),
    "SPO2": ("spo2",),
    "SPO2_PERCENT": ("spo2",),
    "149546": ("pulse_rate",),
    "MDC_PULS_RATE_NON_INV": ("pulse_rate",),
    "MDC_PULS_RATE": ("pulse_rate",),
    "PULSE_RATE": ("pulse_rate",),
    "PULSE": ("pulse_rate",),
    "151562": ("respiratory_rate",),
    "MDC_RESP_RATE": ("respiratory_rate",),
    "RESP_RATE": ("respiratory_rate",),
    "RESPIRATORY_RATE": ("respiratory_rate",),
    "128": ("respiratory_rate_source",),
    "EHC_RESP_RATE_SOURCE": ("respiratory_rate_source",),
    "RESP_RATE_SOURCE": ("respiratory_rate_source",),
    "150021": ("systolic_blood_pressure",),
    "MDC_PRESS_BLD_NONINV_SYS": ("systolic_blood_pressure",),
    "SYSTOLIC_BP": ("systolic_blood_pressure",),
    "SYSTOLIC_BLOOD_PRESSURE": ("systolic_blood_pressure",),
    "150022": ("diastolic_blood_pressure",),
    "MDC_PRESS_BLD_NONINV_DIA": ("diastolic_blood_pressure",),
    "DIASTOLIC_BP": ("diastolic_blood_pressure",),
    "DIASTOLIC_BLOOD_PRESSURE": ("diastolic_blood_pressure",),
    "150023": ("mean_blood_pressure",),
    "MDC_PRESS_BLD_NONINV_MEAN": ("mean_blood_pressure",),
    "MEAN_BP": ("mean_blood_pressure",),
    "MEAN_BLOOD_PRESSURE": ("mean_blood_pressure",),
    # EDAN uses this identifier for the pulse rate measured alongside NIBP.
    # Expose it both under the source-specific name and as the general pulse rate.
    "NIBP_NIBP_PR": ("nibp_pulse_rate", "pulse_rate"),
    "MDC_TEMP_BODY": ("body_temperature",),
    "MDC_TEMP": ("body_temperature",),
    "BODY_TEMP": ("body_temperature",),
    "BODY_TEMPERATURE": ("body_temperature",),
    "TEMPERATURE": ("body_temperature",),
    "MDC_ECG_HEART_RATE": ("heart_rate",),
    "ECG_HEART_RATE": ("heart_rate",),
    "HEART_RATE": ("heart_rate",),
    "MDC_AWAY_CO2_ET": ("etco2",),
    "MDC_CO2_ET": ("etco2",),
    "ETCO2": ("etco2",),
    "FIO2": ("fio2",),
}

UNIT_LABELS = {
    "MDC_DIM_PERCENT": "%",
    "262688": "%",
    "MDC_DIM_BEAT_PER_MIN": "beats/min",
    "264864": "beats/min",
    "MDC_DIM_RESP_PER_MIN": "breaths/min",
    "264928": "breaths/min",
    "MDC_DIM_MMGH": "mmHg",
    "266016": "mmHg",
}


# Dedicated PostgreSQL columns for common clinical measurements. The full OBX
# result list remains in parsed_json.orders[*].results, while vitals_json retains
# all normalized readings (including repeats and unmapped/vendor-specific codes).
# Column names are lower-case PostgreSQL-friendly identifiers.
NUMERIC_DB_FIELDS: dict[str, str] = {
    "spo2": "spo2",
    "pulse_rate": "pulse_rate",
    "respiratory_rate": "respiratory_rate",
    "systolic_bp": "systolic_blood_pressure",
    "diastolic_bp": "diastolic_blood_pressure",
    "mean_bp": "mean_blood_pressure",
    "nibp_pulse_rate": "nibp_pulse_rate",
    "heart_rate": "heart_rate",
    "body_temperature": "body_temperature",
    "etco2": "etco2",
    "fio2": "fio2",
    "weight": "weight",
    "height": "height",
}
TEXT_DB_FIELDS: dict[str, str] = {
    "blood_type": "blood_type",
    "device_software_version": "device_software_version",
    "respiratory_rate_source": "respiratory_rate_source",
}
UNIT_DB_FIELDS: dict[str, str] = {
    f"{column}_unit": field_name for column, field_name in NUMERIC_DB_FIELDS.items()
}
VITAL_SCHEMA_COLUMNS: dict[str, str] = {
    **{column: "DOUBLE PRECISION" for column in NUMERIC_DB_FIELDS},
    **{column: "TEXT" for column in UNIT_DB_FIELDS},
    **{column: "TEXT" for column in TEXT_DB_FIELDS},
    "vitals_json": "JSONB NOT NULL DEFAULT '{}'::jsonb",
    # Rows created by older versions get backfilled exactly once on service startup.
    "vitals_schema_version": "SMALLINT NOT NULL DEFAULT 0",
}
VITAL_DB_COLUMNS = list(VITAL_SCHEMA_COLUMNS.keys())
VITAL_SCHEMA_VERSION = 1


def _finite_number(value: Any) -> Optional[float]:
    """Return a finite number when an OBX value is numeric; preserve raw text too."""
    if value is None or not str(value).strip():
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _observation_field_names(result: dict[str, Any]) -> list[str]:
    observation = result.get("observation") or {}
    candidates = [observation.get("identifier", ""), observation.get("text", "")]
    field_names: list[str] = []
    for candidate in candidates:
        key = str(candidate or "").strip().upper()
        for mapped in VITAL_FIELD_ALIASES.get(key, ()):
            if mapped not in field_names:
                field_names.append(mapped)
    return field_names


def _unit_label(units: Any) -> str:
    if not isinstance(units, dict):
        return ""
    # Prefer human-readable UCUM/vendor unit strings, but translate common MDC
    # nomenclature labels to readable units for consuming applications.
    text = str(units.get("text") or "").strip()
    identifier = str(units.get("identifier") or "").strip()
    for candidate in (text, identifier):
        if candidate in UNIT_LABELS:
            return UNIT_LABELS[candidate]
    if text and not text.startswith("MDC_DIM_"):
        return text
    return identifier or text


def normalize_vitals(parsed: dict[str, Any]) -> dict[str, Any]:
    """Create a normalized view without changing/dropping orders[*].results.

    Each normalized field exposes the latest reading at the field's top level and
    a `readings` array retaining every occurrence of that field in the message.
    `all_observations` contains every OBX result (including unknown/vendor-specific
    codes); `unmapped_observations` isolates those without an explicit mapping.
    """
    vitals: dict[str, Any] = {"all_observations": [], "unmapped_observations": []}
    orders = parsed.get("orders", [])
    if not isinstance(orders, list):
        orders = []

    for order_index, order in enumerate(orders):
        if not isinstance(order, dict):
            continue
        results = order.get("results", [])
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            fields = _observation_field_names(result)
            original_result = dict(result)
            observation = result.get("observation") or {}
            units = result.get("units") or {}
            value = result.get("value", "")
            reading = {
                "value": value,
                "numeric_value": _finite_number(value),
                "unit": _unit_label(units),
                "units": units,
                "observation": observation,
                "observation_code": str(observation.get("identifier") or ""),
                "observation_name": str(observation.get("text") or ""),
                "coding_system": str(observation.get("coding_system") or ""),
                "value_type": str(result.get("value_type") or ""),
                "reference_range": str(result.get("reference_range") or ""),
                "abnormal_flags": result.get("abnormal_flags", []),
                "result_status": str(result.get("result_status") or ""),
                "observation_datetime": str(result.get("observation_datetime") or ""),
                "observation_sub_id": str(result.get("observation_sub_id") or ""),
                "set_id": str(result.get("set_id") or ""),
                "order_index": order_index,
                "order_set_id": str(order.get("set_id") or ""),
                "order_service": order.get("service", {}),
            }
            all_observation = {
                **original_result,
                "order_index": order_index,
                "order_set_id": str(order.get("set_id") or ""),
                "order_service": order.get("service", {}),
                "normalized_fields": fields,
            }
            vitals["all_observations"].append(all_observation)
            if not fields:
                vitals["unmapped_observations"].append(all_observation)
                continue
            for field_name in fields:
                bucket = vitals.setdefault(field_name, {"readings": []})
                if not isinstance(bucket, dict):
                    bucket = {"readings": []}
                    vitals[field_name] = bucket
                bucket.setdefault("readings", []).append(reading.copy())
                # The top-level members are convenient for APIs/UIs; readings keeps
                # earlier values if an instrument reports a field more than once.
                bucket.update(reading)

    # Compose a convenience BP group while retaining the individual BP fields.
    systolic = vitals.get("systolic_blood_pressure")
    diastolic = vitals.get("diastolic_blood_pressure")
    mean = vitals.get("mean_blood_pressure")
    if systolic or diastolic or mean:
        units = (systolic or diastolic or mean or {}).get("unit", "")
        vitals["blood_pressure"] = {
            "systolic": systolic,
            "diastolic": diastolic,
            "mean": mean,
            "unit": units,
        }
    return vitals


def build_vital_storage(parsed: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild normalized vitals and produce values for all dedicated DB columns.

    One value per field is stored in the wide columns (the last occurrence in this
    HL7 message). Every occurrence, including repeated readings, remains available
    from parsed_json.orders[*].results and vitals_json.<field>.readings.
    """
    vitals = normalize_vitals(parsed)
    parsed["vitals"] = vitals
    values: dict[str, Any] = {}

    for column, field_name in NUMERIC_DB_FIELDS.items():
        reading = vitals.get(field_name)
        if not isinstance(reading, dict):
            values[column] = None
            values[f"{column}_unit"] = None
            continue
        numeric = reading.get("numeric_value")
        if numeric is None:
            numeric = _finite_number(reading.get("value"))
        values[column] = numeric
        unit = reading.get("unit")
        values[f"{column}_unit"] = str(unit) if unit not in (None, "") else None

    for column, field_name in TEXT_DB_FIELDS.items():
        reading = vitals.get(field_name)
        raw_value = reading.get("value") if isinstance(reading, dict) else None
        values[column] = None if raw_value is None or str(raw_value).strip() == "" else str(raw_value)

    values["vitals_json"] = json.dumps(vitals, ensure_ascii=False, separators=(",", ":"))
    values["vitals_schema_version"] = VITAL_SCHEMA_VERSION
    # The order is driven by VITAL_DB_COLUMNS for SQL inserts/updates.
    return vitals, values


def _json_object(value: Any) -> dict[str, Any]:
    """Normalize psycopg JSONB / SQLite JSON text without silently losing data."""
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


def _vital_sql_values(values: dict[str, Any]) -> list[Any]:
    return [values.get(column) for column in VITAL_DB_COLUMNS]


def parse_message(raw: str) -> tuple[dict[str, Any], list[str]]:
    """Parse with python-hl7, then map clinically relevant v2 fields for storage.

    python-hl7 owns HL7 message structure parsing. The explicit mapping below is
    application logic for the fields this receiver exposes; raw input is stored
    separately and never rewritten to make a non-conforming device look compliant.
    """
    normalized = normalize_hl7_text(raw)
    errors: list[str] = []
    try:
        # This is the actual HL7 v2 parser. It handles the message/segment/field
        # hierarchy; the mapping layer below retains our stable JSON schema.
        hl7lib.parse(normalized, encoding="utf-8")
    except Exception as exc:
        return {
            "message_header": {}, "patient": {}, "visit": {}, "orders": [],
            "specimens": [], "notes": [], "vitals": {"all_observations": [], "unmapped_observations": []}, "segment_types": [
                get_segment_id(s) for s in normalized.split("\r") if s
            ],
        }, [f"python-hl7 parse failure: {type(exc).__name__}: {exc}"]

    segments = [part for part in normalized.split("\r") if part]
    msh = next((segment for segment in segments if get_segment_id(segment) == "MSH"), None)
    if not msh or len(msh) < 4:
        return {
            "message_header": {}, "patient": {}, "orders": [], "specimens": [],
            "notes": [], "vitals": {"all_observations": [], "unmapped_observations": []}, "segment_types": [get_segment_id(s) for s in segments],
        }, ["Missing or invalid MSH segment"]

    separator = msh[3]
    encoding_chars = split_hl7_field(msh, 2, separator) or "^~\\&"
    header = {
        "field_separator": separator,
        "encoding_characters": encoding_chars,
        "sending_application": _field(msh, 3, separator, encoding_chars),
        "sending_facility": _field(msh, 4, separator, encoding_chars),
        "receiving_application": _field(msh, 5, separator, encoding_chars),
        "receiving_facility": _field(msh, 6, separator, encoding_chars),
        "message_datetime": _field(msh, 7, separator, encoding_chars),
        "message_type_raw": _field(msh, 9, separator, encoding_chars),
        "message_control_id": _field(msh, 10, separator, encoding_chars),
        "processing_id": _field(msh, 11, separator, encoding_chars),
        "version_id": _field(msh, 12, separator, encoding_chars),
    }
    msg_parts = components(header["message_type_raw"], separator, encoding_chars)
    header["message_type"] = msg_parts[0] if msg_parts else ""
    header["trigger_event"] = msg_parts[1] if len(msg_parts) > 1 else ""
    header["message_structure"] = msg_parts[2] if len(msg_parts) > 2 else ""
    if not header["message_type_raw"]:
        errors.append("MSH-9 message type is empty")
    if not header["message_control_id"]:
        errors.append("MSH-10 message control ID is empty")
    if not header["version_id"]:
        errors.append("MSH-12 version ID is empty")

    patient: dict[str, Any] = {}
    visit: dict[str, Any] = {}
    orders: list[dict[str, Any]] = []
    specimens: list[dict[str, Any]] = []
    notes: list[dict[str, str]] = []
    current_order: Optional[dict[str, Any]] = None
    pending_orc: dict[str, str] = {}

    for segment in segments:
        sid = get_segment_id(segment)
        if sid == "PID":
            ids_raw = _field(segment, 3, separator, encoding_chars)
            names_raw = _field(segment, 5, separator, encoding_chars)
            patient.update({
                "set_id": _field(segment, 1, separator, encoding_chars),
                "identifiers": [parse_cx(value, separator, encoding_chars) for value in ids_raw.split("~") if value],
                "names": [parse_xpn(value, separator, encoding_chars) for value in names_raw.split("~") if value],
                "date_of_birth": _field(segment, 7, separator, encoding_chars),
                "administrative_sex": _field(segment, 8, separator, encoding_chars),
                "patient_alias": _field(segment, 9, separator, encoding_chars),
                "account_number": parse_cx(_field(segment, 18, separator, encoding_chars), separator, encoding_chars) if _field(segment, 18, separator, encoding_chars) else {},
            })
            patient["patient_id"] = patient["identifiers"][0].get("id", "") if patient["identifiers"] else ""
        elif sid == "PV1":
            visit = {
                "patient_class": _field(segment, 2, separator, encoding_chars),
                "assigned_location": _field(segment, 3, separator, encoding_chars),
                "visit_number": parse_cx(_field(segment, 19, separator, encoding_chars), separator, encoding_chars) if _field(segment, 19, separator, encoding_chars) else {},
            }
        elif sid == "ORC":
            pending_orc = {
                "order_control": _field(segment, 1, separator, encoding_chars),
                "placer_order_number": _field(segment, 2, separator, encoding_chars),
                "filler_order_number": _field(segment, 3, separator, encoding_chars),
                "order_status": _field(segment, 5, separator, encoding_chars),
                "transaction_datetime": _field(segment, 9, separator, encoding_chars),
            }
            if current_order is not None and not current_order.get("order_control"):
                current_order.update({k: v for k, v in pending_orc.items() if v and not current_order.get(k)})
        elif sid == "OBR":
            current_order = {
                **{k: v for k, v in pending_orc.items() if v},
                "set_id": _field(segment, 1, separator, encoding_chars),
                "placer_order_number": _field(segment, 2, separator, encoding_chars) or pending_orc.get("placer_order_number", ""),
                "filler_order_number": _field(segment, 3, separator, encoding_chars) or pending_orc.get("filler_order_number", ""),
                "service": coded_value(_field(segment, 4, separator, encoding_chars), separator, encoding_chars),
                "observation_datetime": _field(segment, 7, separator, encoding_chars),
                "specimen_received_datetime": _field(segment, 14, separator, encoding_chars),
                "specimen_source": coded_value(_field(segment, 15, separator, encoding_chars), separator, encoding_chars),
                "result_status": _field(segment, 25, separator, encoding_chars),
                "ordering_provider": parse_xcn(_field(segment, 16, separator, encoding_chars), separator, encoding_chars) if _field(segment, 16, separator, encoding_chars) else {},
                "results": [],
                "notes": [],
            }
            orders.append(current_order)
            pending_orc = {}
        elif sid == "OBX":
            if current_order is None:
                current_order = {
                    "set_id": "", "placer_order_number": "", "filler_order_number": "",
                    "service": {}, "results": [], "notes": [], "order_created_from": "OBX without preceding OBR",
                }
                orders.append(current_order)
            raw_values = _field(segment, 5, separator, encoding_chars)
            result = {
                "set_id": _field(segment, 1, separator, encoding_chars),
                "value_type": _field(segment, 2, separator, encoding_chars),
                "observation": coded_value(_field(segment, 3, separator, encoding_chars), separator, encoding_chars),
                "observation_sub_id": _field(segment, 4, separator, encoding_chars),
                "value": raw_values,
                "value_repetitions": [hl7_unescape(v, separator, encoding_chars) for v in raw_values.split("~")] if raw_values else [],
                "units": coded_value(_field(segment, 6, separator, encoding_chars), separator, encoding_chars),
                "reference_range": _field(segment, 7, separator, encoding_chars),
                "abnormal_flags": [hl7_unescape(v, separator, encoding_chars) for v in _field(segment, 8, separator, encoding_chars).split("~") if v],
                "result_status": _field(segment, 11, separator, encoding_chars),
                "observation_datetime": _field(segment, 14, separator, encoding_chars),
                "observation_method": coded_value(_field(segment, 17, separator, encoding_chars), separator, encoding_chars),
            }
            current_order["results"].append(result)
        elif sid == "SPM":
            specimens.append({
                "set_id": _field(segment, 1, separator, encoding_chars),
                "specimen_id": _field(segment, 2, separator, encoding_chars),
                "specimen_type": coded_value(_field(segment, 4, separator, encoding_chars), separator, encoding_chars),
                "collection_datetime": _field(segment, 17, separator, encoding_chars),
                "received_datetime": _field(segment, 18, separator, encoding_chars),
            })
        elif sid == "NTE":
            note = {"set_id": _field(segment, 1, separator, encoding_chars), "source": _field(segment, 2, separator, encoding_chars), "text": _field(segment, 3, separator, encoding_chars)}
            notes.append(note)
            if current_order is not None:
                current_order["notes"].append(note)

    parsed = {
        "message_header": header,
        "patient": patient,
        "visit": visit,
        "orders": orders,
        "specimens": specimens,
        "notes": notes,
        "segment_types": [get_segment_id(s) for s in segments],
    }
    # Keep the complete original structured result list under orders[*].results;
    # this additional top-level object is only a convenience/normalization layer.
    parsed["vitals"] = normalize_vitals(parsed)
    return parsed, errors


def connect_postgres(database_url: str):
    """Create a PostgreSQL connection. Import lazily for clear startup errors."""
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: psycopg 3. Install with: "
            "python3 -m pip install -r requirements_hl7_listener_postgres_columns.txt"
        ) from exc
    return psycopg.connect(database_url, connect_timeout=10)


def initialize_database(database_url: str) -> None:
    """Create/upgrade PostgreSQL schema, then backfill columns on historical rows."""
    vital_definitions = ",\n            ".join(
        f'"{column}" {data_type}' for column, data_type in VITAL_SCHEMA_COLUMNS.items()
    )
    ddl = f"""
        CREATE TABLE IF NOT EXISTS messages (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            received_at TIMESTAMPTZ NOT NULL,
            remote_host TEXT,
            remote_port INTEGER,
            sender_identity TEXT NOT NULL DEFAULT '',
            sending_application TEXT NOT NULL DEFAULT '',
            sending_facility TEXT NOT NULL DEFAULT '',
            message_control_id TEXT NOT NULL DEFAULT '',
            message_type TEXT NOT NULL DEFAULT '',
            trigger_event TEXT NOT NULL DEFAULT '',
            payload_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '',
            duplicate_of BIGINT REFERENCES messages(id),
            raw_hl7 TEXT NOT NULL,
            parsed_json JSONB NOT NULL,
            {vital_definitions}
        )
    """
    with connect_postgres(database_url) as conn:
        conn.execute(ddl)
        # Upgrade a table created by an older receiver without deleting any records.
        for column, data_type in VITAL_SCHEMA_COLUMNS.items():
            conn.execute(
                f'ALTER TABLE messages ADD COLUMN IF NOT EXISTS "{column}" {data_type}'
            )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_received_at ON messages(received_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_control_id ON messages(sender_identity, message_control_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_payload_hash ON messages(payload_sha256)")
    updated = backfill_existing_vital_columns(database_url)
    if updated:
        logging.getLogger("hl7listener").info(
            "Backfilled dedicated vital-sign columns for %s existing PostgreSQL messages", updated
        )


def backfill_existing_vital_columns(database_url: str, batch_size: int = 500) -> int:
    """Backfill already-stored PostgreSQL rows from their preserved result lists."""
    updated = 0
    while True:
        with connect_postgres(database_url) as conn:
            with conn.transaction():
                rows = conn.execute(
                    """SELECT id, parsed_json FROM messages
                       WHERE vitals_schema_version < %s
                       ORDER BY id ASC LIMIT %s""",
                    (VITAL_SCHEMA_VERSION, batch_size),
                ).fetchall()
                if not rows:
                    return updated
                for row in rows:
                    record_id, json_value = row[0], row[1]
                    parsed = _json_object(json_value)
                    _vitals, values = build_vital_storage(parsed)
                    assignments = ["parsed_json = %s::jsonb"]
                    parameters: list[Any] = [
                        json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
                    ]
                    for column in VITAL_DB_COLUMNS:
                        assignments.append(f'"{column}" = %s' + ("::jsonb" if column == "vitals_json" else ""))
                        parameters.append(values.get(column))
                    parameters.append(record_id)
                    conn.execute(
                        f"UPDATE messages SET {', '.join(assignments)} WHERE id = %s",
                        parameters,
                    )
                    updated += 1


def migrate_sqlite_to_postgres(sqlite_path: str, database_url: str, batch_size: int = 500) -> tuple[int, int]:
    """Import SQLite rows and populate the normalized JSON plus dedicated columns.

    Existing PostgreSQL IDs are skipped. SQLite is opened read-only and is not
    modified. All original OBX entries are retained in the parsed JSON result list.
    """
    path = Path(sqlite_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"SQLite source database not found: {path}")

    required_columns = (
        "id", "received_at", "remote_host", "remote_port", "sender_identity",
        "sending_application", "sending_facility", "message_control_id", "message_type",
        "trigger_event", "payload_sha256", "status", "error", "duplicate_of", "raw_hl7",
        "parsed_json",
    )
    imported = 0
    skipped = 0
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as old:
        old.row_factory = sqlite3.Row
        old_columns = {r[1] for r in old.execute("PRAGMA table_info(messages)").fetchall()}
        if not old_columns:
            raise RuntimeError(f"No 'messages' table found in SQLite database: {path}")
        missing = [c for c in required_columns if c not in old_columns]
        if missing:
            raise RuntimeError(f"SQLite messages table is missing required columns: {', '.join(missing)}")
        cursor = old.execute(
            "SELECT " + ", ".join(required_columns) + " FROM messages ORDER BY id ASC"
        )
        base_columns = list(required_columns)
        insert_columns = base_columns + VITAL_DB_COLUMNS
        placeholder_parts = [
            "%s", "%s::timestamptz", "%s", "%s", "%s", "%s", "%s", "%s",
            "%s", "%s", "%s", "%s", "%s", "%s", "%s", "%s::jsonb",
        ]
        placeholder_parts.extend(
            "%s::jsonb" if column == "vitals_json" else "%s" for column in VITAL_DB_COLUMNS
        )
        insert_sql = f"""
            INSERT INTO messages ({', '.join(insert_columns)})
            VALUES ({', '.join(placeholder_parts)})
            ON CONFLICT (id) DO NOTHING
        """
        with connect_postgres(database_url) as pg:
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                with pg.transaction():
                    for row in rows:
                        # Validate old JSON, then retrofit the vitals layer without changing results.
                        parsed = _json_object(row["parsed_json"])
                        _vitals, vital_values = build_vital_storage(parsed)
                        parsed_json = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
                        base_vals = [row[c] for c in required_columns[:-1]] + [parsed_json]
                        vals = base_vals + _vital_sql_values(vital_values)
                        result = pg.execute(insert_sql, vals)
                        if result.rowcount == 1:
                            imported += 1
                        else:
                            skipped += 1
            pg.execute("""
                SELECT setval(
                    pg_get_serial_sequence('messages', 'id')::regclass,
                    COALESCE(MAX(id), 1),
                    COUNT(*) > 0
                ) FROM messages
            """)
    return imported, skipped


def archive_message(archive_dir: Optional[str], record_id: int, received_at: str, payload_hash: str, raw_bytes: bytes) -> None:
    if not archive_dir:
        return
    directory = Path(archive_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    safe_time = re.sub(r"[^0-9A-Za-zT_-]", "", received_at)
    target = directory / f"{safe_time}_id{record_id}_{payload_hash[:12]}.hl7"
    temporary = target.with_suffix(target.suffix + ".tmp")
    # Restrict file permissions on POSIX; Windows will use its normal ACL behavior.
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def persist_message(
    raw_bytes: bytes,
    raw_text: str,
    parsed: dict[str, Any],
    parse_errors: list[str],
    remote_host: str,
    remote_port: Optional[int],
    args: argparse.Namespace,
) -> dict[str, Any]:
    header = parsed.get("message_header", {})
    sending_app = str(header.get("sending_application", ""))
    sending_facility = str(header.get("sending_facility", ""))
    control_id = str(header.get("message_control_id", ""))
    message_type = str(header.get("message_type", ""))
    trigger_event = str(header.get("trigger_event", ""))
    sender_identity = f"{sending_app}|{sending_facility}"
    payload_hash = hashlib.sha256(raw_bytes).hexdigest()
    _vitals, vital_values = build_vital_storage(parsed)
    received_at = utc_now()
    status = "accepted"
    error = "; ".join(parse_errors)
    duplicate_of: Optional[int] = None

    conn = connect_postgres(args.database_url)
    try:
        with conn.transaction():
            # Transaction-scoped advisory locks close the SELECT/INSERT race when
            # two connections deliver the same control ID or payload simultaneously.
            if not parse_errors and args.dedupe == "control-id" and control_id:
                lock_key = f"control-id:{sender_identity}:{control_id}"
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))
            elif not parse_errors and args.dedupe == "payload":
                lock_key = f"payload:{payload_hash}"
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))

            if parse_errors:
                status = "parse_error"
            elif args.dedupe == "control-id" and control_id:
                previous = conn.execute(
                    """SELECT id, payload_sha256 FROM messages
                       WHERE sender_identity=%s AND message_control_id=%s AND status='accepted'
                       ORDER BY id DESC LIMIT 1""",
                    (sender_identity, control_id),
                ).fetchone()
                if previous:
                    duplicate_of = int(previous[0])
                    if previous[1] == payload_hash:
                        status = "duplicate"
                        error = f"Retransmission of message already stored as record {duplicate_of}"
                    else:
                        status = "rejected"
                        error = f"Message control ID {control_id!r} was reused with different contents; original record {duplicate_of}"
            elif args.dedupe == "payload":
                previous = conn.execute(
                    """SELECT id FROM messages WHERE payload_sha256=%s AND status='accepted'
                       ORDER BY id DESC LIMIT 1""",
                    (payload_hash,),
                ).fetchone()
                if previous:
                    duplicate_of = int(previous[0])
                    status = "duplicate"
                    error = f"Identical payload already stored as record {duplicate_of}"

            base_columns = [
                "received_at", "remote_host", "remote_port", "sender_identity",
                "sending_application", "sending_facility", "message_control_id",
                "message_type", "trigger_event", "payload_sha256", "status", "error",
                "duplicate_of", "raw_hl7", "parsed_json",
            ]
            column_names = base_columns + VITAL_DB_COLUMNS
            placeholders = [
                "%s::timestamptz", "%s", "%s", "%s", "%s", "%s", "%s",
                "%s", "%s", "%s", "%s", "%s", "%s", "%s", "%s::jsonb",
            ]
            placeholders.extend(
                "%s::jsonb" if column == "vitals_json" else "%s" for column in VITAL_DB_COLUMNS
            )
            insert_sql = f"""
                INSERT INTO messages ({', '.join(column_names)})
                VALUES ({', '.join(placeholders)}) RETURNING id
            """
            values = [
                received_at, remote_host, remote_port, sender_identity, sending_app,
                sending_facility, control_id, message_type, trigger_event, payload_hash,
                status, error, duplicate_of, raw_text,
                json.dumps(parsed, ensure_ascii=False, separators=(",", ":")),
            ] + _vital_sql_values(vital_values)
            record = conn.execute(insert_sql, values).fetchone()
            record_id = int(record[0])
    finally:
        conn.close()

    try:
        archive_message(args.archive_dir, record_id, received_at, payload_hash, raw_bytes)
    except Exception as exc:
        logging.getLogger("hl7listener").exception("Could not write optional archive for record %s: %s", record_id, exc)

    return {
        "id": record_id,
        "status": status,
        "error": error,
        "control_id": control_id,
        "message_type": message_type,
        "sending_application": sending_app,
        "sending_facility": sending_facility,
        "parsed": parsed,
        "payload_hash": payload_hash,
    }

def make_ack(parsed: dict[str, Any], ack_code: str, text: str, args: argparse.Namespace) -> str:
    header = parsed.get("message_header", {})
    separator = str(header.get("field_separator") or "|")
    encoding_chars = str(header.get("encoding_characters") or "^~\\&")
    component_sep = encoding_chars[0] if encoding_chars else "^"
    sender_app = str(header.get("sending_application") or "")
    sender_facility = str(header.get("sending_facility") or "")
    original_control_id = str(header.get("message_control_id") or "")
    trigger = str(header.get("trigger_event") or "")
    ack_type = f"ACK{component_sep}{trigger}{component_sep}ACK" if trigger else "ACK"
    version = str(header.get("version_id") or "2.5.1")
    processing_id = str(header.get("processing_id") or "P")
    if processing_id not in {"P", "T", "D"}:
        processing_id = "P"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S+0000")
    ack_control_id = "ACK" + uuid.uuid4().hex[:20]
    # Escape the free-text ACK detail so it cannot break the MSA fields.
    clean_text = text.replace("\\", "\\E\\").replace(separator, "\\F\\").replace("\r", " ").replace("\n", " ")
    msa = separator.join(["MSA", ack_code, original_control_id, clean_text])
    msh_fields = [
        "MSH", encoding_chars, str(args.our_app), str(args.our_facility),
        sender_app, sender_facility, timestamp, "", ack_type, ack_control_id,
        processing_id, version,
    ]
    ack_msh = separator.join(msh_fields)
    return ack_msh + "\r" + msa + "\r"


def pack_ack(ack_text: str, args: argparse.Namespace) -> bytes:
    encoding = args.encoding
    data = ack_text.encode(encoding, errors="replace")
    framing = args.ack_framing
    if framing == "same":
        framing = "mllp" if args.framing == "mllp" else "raw"
    if framing == "mllp":
        return MLLP_START + data + MLLP_END
    return data


async def send_ack(writer: asyncio.StreamWriter, parsed: dict[str, Any], code: str, detail: str, args: argparse.Namespace) -> None:
    if args.ack_mode == "never":
        return
    try:
        writer.write(pack_ack(make_ack(parsed, code, detail, args), args))
        await writer.drain()
    except (ConnectionError, OSError, asyncio.CancelledError):
        raise
    except Exception:
        logging.getLogger("hl7listener").exception("Could not send HL7 ACK")


async def handle_payload(
    payload: bytes,
    writer: asyncio.StreamWriter,
    remote_host: str,
    remote_port: Optional[int],
    args: argparse.Namespace,
) -> None:
    logger = logging.getLogger("hl7listener")
    try:
        raw_text = payload.decode(args.encoding, errors="replace")
    except LookupError:
        logger.error("Unknown character encoding %r; cannot decode message", args.encoding)
        return
    parsed, parse_errors = parse_message(raw_text)
    # Some monitor firmware emits a valid-looking ORU header but leaves MSH-10
    # blank. Permit this only when explicitly enabled by the operator. The raw
    # header remains unchanged; no synthetic control ID is written into the HL7.
    # Messages without MSH-10 cannot be safely deduplicated by control ID.
    if args.allow_empty_control_id and parsed.get("message_header", {}).get("message_control_id", "") == "":
        parse_errors = [e for e in parse_errors if e != "MSH-10 message control ID is empty"]
    try:
        outcome = persist_message(payload, raw_text, parsed, parse_errors, remote_host, remote_port, args)
    except Exception as exc:
        logger.exception("Storage failed for incoming message from %s:%s", remote_host, remote_port)
        await send_ack(writer, parsed, "AE", "Receiver storage failure; please retry", args)
        return

    status = outcome["status"]
    # Include the parser/storage disposition reason. This is especially useful for
    # vendor messages whose MSH header differs from the expected HL7 v2 layout.
    # The detail is generated from validation errors / message IDs, not the patient body.
    logger.info(
        "Received record_id=%s peer=%s:%s status=%s type=%s control_id=%s sender=%s/%s bytes=%s detail=%s",
        outcome["id"], remote_host, remote_port, status, outcome["message_type"] or "unknown",
        outcome["control_id"] or "(empty)", outcome["sending_application"] or "(unknown)",
        outcome["sending_facility"] or "(unknown)", len(payload), outcome["error"] or "(none)",
    )
    if status in {"accepted", "duplicate"}:
        await send_ack(writer, parsed, "AA", "Message stored" if status == "accepted" else "Duplicate already received", args)
    else:
        await send_ack(writer, parsed, "AE", outcome["error"] or "Message rejected", args)


async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, args: argparse.Namespace) -> None:
    logger = logging.getLogger("hl7listener")
    peer = writer.get_extra_info("peername") or ("unknown", 0)
    remote_host = str(peer[0]) if isinstance(peer, tuple) and len(peer) > 0 else "unknown"
    try:
        remote_port = int(peer[1]) if isinstance(peer, tuple) and len(peer) > 1 else None
    except (TypeError, ValueError):
        remote_port = None
    logger.info("Connection opened from %s:%s", remote_host, remote_port)
    try:
        if args.framing == "mllp":
            buffer = bytearray()
            while True:
                chunk = await reader.read(8192)
                if not chunk:
                    if buffer:
                        logger.warning("Connection closed with %s unframed bytes buffered from %s:%s", len(buffer), remote_host, remote_port)
                    break
                buffer.extend(chunk)
                while True:
                    start = buffer.find(MLLP_START)
                    if start < 0:
                        if len(buffer) > args.max_message_bytes:
                            logger.warning("Discarding oversized non-MLLP input from %s:%s", remote_host, remote_port)
                            buffer.clear()
                        elif buffer:
                            # Retain a final VT if it could be split across reads; otherwise discard noise.
                            if buffer[-1:] == MLLP_START:
                                buffer[:] = MLLP_START
                            else:
                                logger.warning("Discarding %s byte(s) outside MLLP frame from %s:%s", len(buffer), remote_host, remote_port)
                                buffer.clear()
                        break
                    if start > 0:
                        logger.warning("Discarding %s byte(s) before MLLP frame from %s:%s", start, remote_host, remote_port)
                        del buffer[:start]
                    end = buffer.find(MLLP_END, 1)
                    if end < 0:
                        if len(buffer) > args.max_message_bytes + len(MLLP_START) + len(MLLP_END):
                            logger.error("MLLP message exceeds --max-message-bytes; closing %s:%s", remote_host, remote_port)
                            return
                        break
                    payload = bytes(buffer[1:end])
                    del buffer[: end + len(MLLP_END)]
                    if not payload:
                        logger.warning("Ignoring empty MLLP frame from %s:%s", remote_host, remote_port)
                        continue
                    if len(payload) > args.max_message_bytes:
                        logger.error("Message exceeds --max-message-bytes; not processing it")
                        continue
                    await handle_payload(payload, writer, remote_host, remote_port, args)
        else:
            # For unframed feeds, message boundaries are ambiguous. This mode treats an
            # interval with no received bytes as the end of one message; only use it when
            # the analyzer's transport manual confirms this behavior.
            buffer = bytearray()
            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(8192), timeout=args.raw_idle_seconds)
                except asyncio.TimeoutError:
                    chunk = None
                if chunk:
                    buffer.extend(chunk)
                    if len(buffer) > args.max_message_bytes:
                        logger.error("Unframed message exceeds --max-message-bytes; closing %s:%s", remote_host, remote_port)
                        return
                    continue
                if buffer:
                    await handle_payload(bytes(buffer), writer, remote_host, remote_port, args)
                    buffer.clear()
                if chunk == b"":
                    break
                # `None` means the idle timeout elapsed; keep the connection open for the next message.
    except asyncio.CancelledError:
        raise
    except (ConnectionResetError, BrokenPipeError):
        logger.info("Connection reset by %s:%s", remote_host, remote_port)
    except Exception:
        logger.exception("Unhandled error on connection from %s:%s", remote_host, remote_port)
    finally:
        logger.info("Connection closed from %s:%s", remote_host, remote_port)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def run_listener(args: argparse.Namespace) -> None:
    server = await asyncio.start_server(
        lambda reader, writer: handle_connection(reader, writer, args),
        host=args.host,
        port=args.port,
        limit=args.max_message_bytes + 65536,
        reuse_address=True,
    )
    sockets = server.sockets or []
    bound = ", ".join(str(sock.getsockname()) for sock in sockets) or f"{args.host}:{args.port}"
    logging.getLogger("hl7listener").info("Listening on %s using %s framing; database=PostgreSQL", bound, args.framing)
    async with server:
        await server.serve_forever()


async def run_client(args: argparse.Namespace) -> None:
    logger = logging.getLogger("hl7listener")
    if not args.device_host:
        raise SystemExit("--device-host is required when --mode connect is selected")
    while True:
        writer: Optional[asyncio.StreamWriter] = None
        try:
            logger.info("Connecting to analyzer at %s:%s", args.device_host, args.device_port)
            reader, writer = await asyncio.open_connection(args.device_host, args.device_port, limit=args.max_message_bytes + 65536)
            await handle_connection(reader, writer, args)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Analyzer connection failed (%s); retrying in %.1f seconds", exc, args.reconnect_seconds)
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
        await asyncio.sleep(args.reconnect_seconds)


def run_self_test() -> int:
    sample = (
        "MSH|^~\\&|ANALYZER|LAB1|LIS|MAIN|20261019073000||ORU^R01^ORU_R01|MSG0001|P|2.5.1\r"
        "PID|1||PAT123^^^HOSP^MR||Doe^Jane^A||19800101|F|||\r"
        "OBR|1|ORD123|FILL456|GLU^Glucose^LN|||20261019072000||||||||SERUM\r"
        "OBX|1|NM|GLU^Glucose^LN||5.4|mmol/L^millimoles per liter^UCUM|3.9-6.1|N|||F|||20261019072500\r"
    )
    parsed, errors = parse_message(sample)
    assert not errors, errors
    assert parsed["message_header"]["message_control_id"] == "MSG0001"
    assert parsed["patient"]["patient_id"] == "PAT123"
    assert parsed["orders"][0]["results"][0]["value"] == "5.4"
    assert parsed["orders"][0]["results"][0]["units"]["identifier"] == "mmol/L"
    args = argparse.Namespace(our_app="HL7_RECEIVER", our_facility="LAB", encoding="utf-8", ack_framing="mllp", framing="mllp")
    ack = make_ack(parsed, "AA", "Message stored", args)
    assert "MSA|AA|MSG0001|Message stored" in ack
    assert ack.startswith("MSH|^~\\&|HL7_RECEIVER|LAB|ANALYZER|LAB1|")
    # EDAN-like compatibility regression: the sender leaves MSH-10 and MSH-11 blank.
    edan_sample = "MSH|^~\\&|Vital Signs Monitor||||20261019051435||ORU^R01|||2.3.1\rOBX|1|NM|SPO2^SpO2||98|%|||||F\r"
    edan_parsed, edan_errors = parse_message(edan_sample)
    assert "MSH-10 message control ID is empty" in edan_errors
    edan_errors = [e for e in edan_errors if e != "MSH-10 message control ID is empty"]
    assert not edan_errors, edan_errors
    assert edan_parsed["message_header"]["version_id"] == "2.3.1"
    assert edan_parsed["message_header"]["message_type"] == "ORU"
    assert edan_parsed["vitals"]["spo2"]["numeric_value"] == 98.0
    assert edan_parsed["vitals"]["spo2"]["unit"] == "%"
    edan_vitals, edan_columns = build_vital_storage(edan_parsed)
    assert edan_columns["spo2"] == 98.0 and edan_columns["spo2_unit"] == "%"
    assert "all_observations" in json.loads(edan_columns["vitals_json"])
    assert len(edan_parsed["orders"][0]["results"]) == 1

    edan_bp_sample = (
        "MSH|^~\\&|Vital Signs Monitor||||20261019065231+0000||ORU^R01|||2.3.1\r"
        "OBR|1||||||20261019065231+0000\r"
        "OBX|1|ST|24960^EHC_DEV_SW_VERSION^99EHC||V01.09.00.08||||||\r"
        "OBX|2|NM|WEIGHT||95.0|kg|||||\r"
        "OBX|3|NM|HEIGHT||178.0|cm|||||\r"
        "OBX|4|ST|BLOODTYPE||A||||||\r"
        "OBX|5|NM|150021^MDC_PRESS_BLD_NONINV_SYS^MDC||135|266016^MDC_DIM_MMGH^MDC|90-160||||F|||20261019065231+0000\r"
        "OBX|6|NM|150022^MDC_PRESS_BLD_NONINV_DIA^MDC||92|266016^MDC_DIM_MMGH^MDC|50-90||||F|||20261019065231+0000\r"
        "OBX|7|NM|150023^MDC_PRESS_BLD_NONINV_MEAN^MDC||104|266016^MDC_DIM_MMGH^MDC|60-110||||F|||20261019065231+0000\r"
        "OBX|8|NM|NIBP_NIBP_PR||59||50-120||||F|||20261019065231+0000\r"
        "OBX|9|NM|VENDOR_UNKNOWN_CODE||opaque value||||||\r"
    )
    bp_parsed, bp_errors = parse_message(edan_bp_sample)
    bp_errors = [e for e in bp_errors if e != "MSH-10 message control ID is empty"]
    assert not bp_errors, bp_errors
    assert len(bp_parsed["orders"][0]["results"]) == 9
    assert bp_parsed["vitals"]["systolic_blood_pressure"]["numeric_value"] == 135.0
    assert bp_parsed["vitals"]["diastolic_blood_pressure"]["numeric_value"] == 92.0
    assert bp_parsed["vitals"]["mean_blood_pressure"]["unit"] == "mmHg"
    assert bp_parsed["vitals"]["pulse_rate"]["numeric_value"] == 59.0
    assert bp_parsed["vitals"]["nibp_pulse_rate"]["numeric_value"] == 59.0
    assert bp_parsed["vitals"]["weight"]["unit"] == "kg"
    assert len(bp_parsed["vitals"]["all_observations"]) == 9
    assert len(bp_parsed["vitals"]["unmapped_observations"]) == 1
    bp_vitals, bp_columns = build_vital_storage(bp_parsed)
    assert bp_columns["systolic_bp"] == 135.0
    assert bp_columns["diastolic_bp"] == 92.0
    assert bp_columns["mean_bp"] == 104.0
    assert bp_columns["nibp_pulse_rate"] == 59.0
    assert bp_columns["weight"] == 95.0 and bp_columns["height"] == 178.0
    assert bp_columns["blood_type"] == "A"
    assert len(json.loads(bp_columns["vitals_json"])["unmapped_observations"]) == 1
    print("Self-test passed: HL7 parsing, dedicated PostgreSQL vital columns, full result retention, BP, and unknown-code retention.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Receive HL7 v2 messages with python-hl7 over TCP/MLLP and persist them in PostgreSQL.")
    parser.add_argument("--mode", choices=("listen", "connect"), default="listen", help="listen for analyzer connections (default) or connect to an analyzer")
    parser.add_argument("--host", default="0.0.0.0", help="local bind address in listen mode (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=2575, help="local TCP port in listen mode (default: 2575)")
    parser.add_argument("--device-host", default="", help="analyzer IP/DNS name when --mode connect is used")
    parser.add_argument("--device-port", type=int, default=2575, help="analyzer TCP port in connect mode (default: 2575)")
    parser.add_argument("--framing", choices=("mllp", "raw-idle"), default="mllp", help="HL7 TCP framing; use mllp unless the device manual says otherwise")
    parser.add_argument("--raw-idle-seconds", type=float, default=1.0, help="raw-idle mode: quiet time that ends a message (default: 1.0)")
    parser.add_argument("--ack-mode", choices=("always", "never"), default="always", help="send ACK/NAK after each inbound message (default: always)")
    parser.add_argument("--ack-framing", choices=("same", "mllp", "raw"), default="same", help="ACK framing; same follows --framing (default: same)")
    parser.add_argument("--dedupe", choices=("control-id", "payload", "none"), default="control-id", help="duplicate policy (default: sender + MSH-10 control ID)")
    parser.add_argument("--allow-empty-control-id", action="store_true", help="compatibility mode for devices that omit MSH-10; original message is preserved, and such messages cannot be deduplicated by control ID")
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL, help="PostgreSQL DSN; may also be set with HL7_DATABASE_URL or DATABASE_URL")
    parser.add_argument("--migrate-sqlite", default=None, metavar="PATH", help="import an existing SQLite messages database into PostgreSQL and exit; existing PostgreSQL IDs are skipped")
    parser.add_argument("--archive-dir", default=None, help="optional directory for exact raw message copies; protect as PHI")
    parser.add_argument("--encoding", default="utf-8", help="character encoding for inbound/outbound HL7 (default: utf-8)")
    parser.add_argument("--our-app", default="HL7_RECEIVER", help="application name used in ACK MSH-3")
    parser.add_argument("--our-facility", default="LAB", help="facility name used in ACK MSH-4")
    parser.add_argument("--max-message-bytes", type=int, default=10 * 1024 * 1024, help="maximum payload size per message (default: 10 MiB)")
    parser.add_argument("--reconnect-seconds", type=float, default=5.0, help="connect mode reconnect delay (default: 5 seconds)")
    parser.add_argument("--log-file", default=None, help="optional rotating log file; logs do not include patient data")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    parser.add_argument("--self-test", action="store_true", help="run parser/ACK self-test and exit")
    return parser


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if not args.database_url:
        parser.error("PostgreSQL DSN is required: set HL7_DATABASE_URL/DATABASE_URL or pass --database-url")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not 1 <= args.device_port <= 65535:
        parser.error("--device-port must be between 1 and 65535")
    if args.max_message_bytes < 1024:
        parser.error("--max-message-bytes must be at least 1024")
    if args.raw_idle_seconds <= 0:
        parser.error("--raw-idle-seconds must be positive")
    if args.reconnect_seconds < 0.2:
        parser.error("--reconnect-seconds must be at least 0.2")


async def async_main(args: argparse.Namespace) -> None:
    initialize_database(args.database_url)
    if args.mode == "listen":
        await run_listener(args)
    else:
        await run_client(args)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    validate_args(args, parser)
    configure_logging(args.log_level, args.log_file)
    try:
        if args.migrate_sqlite:
            initialize_database(args.database_url)
            imported, skipped = migrate_sqlite_to_postgres(args.migrate_sqlite, args.database_url)
            logging.getLogger("hl7listener").info(
                "SQLite migration finished: imported=%s skipped_existing_ids=%s", imported, skipped
            )
            return 0
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        logging.getLogger("hl7listener").info("Stopped by user")
    except Exception as exc:
        logging.getLogger("hl7listener").exception("Could not start/connect or persist data: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
