"""ACK generation and MLLP framing for the HL7 v2 listener.

Ported from the standalone receiver: builds a proper MSH/MSA acknowledgement
mirroring the inbound header, with configurable framing so non-standard
devices (raw, unframed) can also be served.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from django.conf import settings

from integrations.hl7.parsing import MLLP_END, MLLP_START


def _setting(name: str, default):
    config = getattr(settings, "HL7_LISTENER", {}) or {}
    if name in config:
        return config[name]
    return getattr(settings, f"HL7_{name}", default)


def make_ack(parsed: dict[str, Any], ack_code: str, text: str) -> str:
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
    our_app = str(_setting("OUR_APP", "HL7_RECEIVER"))
    our_facility = str(_setting("OUR_FACILITY", "LAB"))
    # Escape the free-text ACK detail so it cannot break the MSA fields.
    clean_text = text.replace("\\", "\\E\\").replace(separator, "\\F\\").replace("\r", " ").replace("\n", " ")
    msa = separator.join(["MSA", ack_code, original_control_id, clean_text])
    msh_fields = [
        "MSH", encoding_chars, our_app, our_facility,
        sender_app, sender_facility, timestamp, "", ack_type, ack_control_id,
        processing_id, version,
    ]
    ack_msh = separator.join(msh_fields)
    return ack_msh + "\r" + msa + "\r"


def pack_message(data: bytes, framing: str | None = None) -> bytes:
    """Wrap raw HL7 bytes in MLLP framing (or leave them raw)."""
    framing = framing or str(_setting("FRAMING", "mllp"))
    if framing == "mllp":
        return MLLP_START + data + MLLP_END
    return data


def unpack_mode(framing: str | None = None) -> str:
    return framing or str(_setting("FRAMING", "mllp"))


def ack_framing(inbound_framing: str | None = None) -> str:
    framing = str(_setting("ACK_FRAMING", "same"))
    if framing == "same":
        return inbound_framing or str(_setting("FRAMING", "mllp"))
    return framing
