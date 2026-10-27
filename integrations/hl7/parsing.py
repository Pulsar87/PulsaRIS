"""HL7 v2 parsing and vital-sign normalization for the lab/vitals listener.

Ported from the standalone ``hl7_lab_listener_edan_vitals_postgres_columns.py``
receiver so the same logic runs as a first-class part of the Django app. The
parsing layer is vendor-neutral: it keeps every OBX result and adds a
normalized ``vitals`` view plus dedicated wide-column values for common
clinical measurements (EDAN monitor aliases included).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

try:
    import hl7 as hl7lib  # PyPI package: `hl7` (python-hl7)
except ImportError as exc:  # fail clearly rather than silently using a home-grown parser
    raise SystemExit(
        "Missing dependency: python-hl7. Install it with: python3 -m pip install hl7"
    ) from exc

logger = logging.getLogger("integrations.hl7")

MLLP_START = b"\x0b"  # VT
MLLP_END = b"\x1c\x0d"  # FS CR


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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


# Dedicated columns for common clinical measurements. The full OBX result list
# remains in parsed_json.orders[*].results, while vitals_json retains all
# normalized readings (including repeats and unmapped/vendor-specific codes).
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

    values["vitals_json"] = vitals
    values["vitals_schema_version"] = VITAL_SCHEMA_VERSION
    return vitals, values


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
            "message_header": {}, "patient": {}, "visit": {}, "orders": [], "specimens": [],
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


def payload_hash(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
