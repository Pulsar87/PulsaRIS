"""Django ORM models for the HL7 lab/vitals receiver service.

These tables replace the standalone ``messages`` PostgreSQL table used by
``hl7_lab_listener_edan_vitals_postgres_columns.py`` and live in the *same*
database the Django app already uses (``DATABASES["default"]``). Column layout
is preserved 1:1 so existing operational queries keep working; data is managed
through standard Django migrations instead of runtime DDL.
"""

from __future__ import annotations

from typing import Any

from django.db import models

from integrations.hl7.parsing import (
    NUMERIC_DB_FIELDS,
    TEXT_DB_FIELDS,
    UNIT_DB_FIELDS,
    VITAL_SCHEMA_VERSION,
    build_vital_storage,
)


class MessageStatus(models.TextChoices):
    ACCEPTED = "accepted", "Accepted"
    DUPLICATE = "duplicate", "Duplicate (retransmission)"
    REJECTED = "rejected", "Rejected"
    PARSE_ERROR = "parse_error", "Parse error"


class HL7VitalMessage(models.Model):
    """One inbound HL7 v2 message with parsed payload and dedicated vital columns.

    The complete structured parse stays in ``parsed_json`` (every OBX result is
    preserved under ``orders[*].results``); the wide numeric/text columns are a
    normalized convenience view rebuilt from ``vitals_json`` on every save.
    """

    id = models.BigAutoField(primary_key=True)

    received_at = models.DateTimeField(db_index=True)
    remote_host = models.CharField(max_length=100, blank=True, default="")
    remote_port = models.IntegerField(null=True, blank=True)

    sender_identity = models.CharField(max_length=255, blank=True, default="")
    sending_application = models.CharField(max_length=255, blank=True, default="")
    sending_facility = models.CharField(max_length=255, blank=True, default="")
    message_control_id = models.CharField(max_length=255, blank=True, default="")
    message_type = models.CharField(max_length=50, blank=True, default="")
    trigger_event = models.CharField(max_length=50, blank=True, default="")

    payload_sha256 = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=20, choices=MessageStatus.choices, default=MessageStatus.ACCEPTED, db_index=True)
    error = models.TextField(blank=True, default="")
    duplicate_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="duplicates",
    )

    raw_hl7 = models.TextField()
    parsed_json = models.JSONField(default=dict, blank=True)

    # --- Dedicated vital-sign measurement columns (numeric + unit pairs) -----
    spo2 = models.FloatField(null=True, blank=True)
    spo2_unit = models.CharField(max_length=50, blank=True, null=True)
    pulse_rate = models.FloatField(null=True, blank=True)
    pulse_rate_unit = models.CharField(max_length=50, blank=True, null=True)
    respiratory_rate = models.FloatField(null=True, blank=True)
    respiratory_rate_unit = models.CharField(max_length=50, blank=True, null=True)
    systolic_bp = models.FloatField(null=True, blank=True)
    systolic_bp_unit = models.CharField(max_length=50, blank=True, null=True)
    diastolic_bp = models.FloatField(null=True, blank=True)
    diastolic_bp_unit = models.CharField(max_length=50, blank=True, null=True)
    mean_bp = models.FloatField(null=True, blank=True)
    mean_bp_unit = models.CharField(max_length=50, blank=True, null=True)
    nibp_pulse_rate = models.FloatField(null=True, blank=True)
    nibp_pulse_rate_unit = models.CharField(max_length=50, blank=True, null=True)
    heart_rate = models.FloatField(null=True, blank=True)
    heart_rate_unit = models.CharField(max_length=50, blank=True, null=True)
    body_temperature = models.FloatField(null=True, blank=True)
    body_temperature_unit = models.CharField(max_length=50, blank=True, null=True)
    etco2 = models.FloatField(null=True, blank=True)
    etco2_unit = models.CharField(max_length=50, blank=True, null=True)
    fio2 = models.FloatField(null=True, blank=True)
    fio2_unit = models.CharField(max_length=50, blank=True, null=True)
    weight = models.FloatField(null=True, blank=True)
    weight_unit = models.CharField(max_length=50, blank=True, null=True)
    height = models.FloatField(null=True, blank=True)
    height_unit = models.CharField(max_length=50, blank=True, null=True)

    # --- Text measurements ----------------------------------------------------
    blood_type = models.CharField(max_length=100, blank=True, null=True)
    device_software_version = models.CharField(max_length=100, blank=True, null=True)
    respiratory_rate_source = models.CharField(max_length=100, blank=True, null=True)

    # Full normalized vitals document plus the schema version used to build it.
    vitals_json = models.JSONField(default=dict, blank=True)
    vitals_schema_version = models.SmallIntegerField(default=0)

    class Meta:
        ordering = ["-received_at", "-id"]
        indexes = [
            models.Index(fields=["sender_identity", "message_control_id"], name="hl7msg_sender_ctrl_idx"),
            models.Index(fields=["payload_sha256"], name="hl7msg_payload_hash_idx"),
            models.Index(fields=["status", "received_at"], name="hl7msg_status_recv_idx"),
        ]
        verbose_name = "HL7 vital-sign message"
        verbose_name_plural = "HL7 vital-sign messages"

    def __str__(self) -> str:
        return f"#{self.pk} {self.message_type or 'unknown'} {self.message_control_id or '(no ctrl id)'} [{self.status}]"

    # ------------------------------------------------------------------ utils
    @property
    def patient_id(self) -> str:
        return str((self.parsed_json or {}).get("patient", {}).get("patient_id", ""))

    @property
    def patient_name(self) -> str:
        names = (self.parsed_json or {}).get("patient", {}).get("names") or []
        if not names:
            return ""
        first = names[0]
        return ", ".join(part for part in (first.get("family_name", ""), first.get("given_name", "")) if part)

    def apply_vitals(self) -> dict[str, Any]:
        """Rebuild the normalized vitals JSON + wide columns from ``parsed_json``.

        Returns the values dict (also assigned onto ``self``) so callers can use
        it without another round-trip.
        """
        parsed = self.parsed_json if isinstance(self.parsed_json, dict) else {}
        _vitals, values = build_vital_storage(parsed)
        for column, value in values.items():
            setattr(self, column, value)
        return values

    def to_api_dict(self, include_raw: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "remote_host": self.remote_host,
            "remote_port": self.remote_port,
            "sender_identity": self.sender_identity,
            "sending_application": self.sending_application,
            "sending_facility": self.sending_facility,
            "message_control_id": self.message_control_id,
            "message_type": self.message_type,
            "trigger_event": self.trigger_event,
            "status": self.status,
            "error": self.error,
            "duplicate_of_id": self.duplicate_of_id,
            "payload_sha256": self.payload_sha256,
            "patient_id": self.patient_id,
            "measurements": {
                column: getattr(self, column)
                for column in list(NUMERIC_DB_FIELDS) + list(TEXT_DB_FIELDS)
            },
            "units": {column: getattr(self, column) for column in UNIT_DB_FIELDS},
            "vitals": self.vitals_json or {},
        }
        if include_raw:
            data["raw_hl7"] = self.raw_hl7
            data["parsed"] = self.parsed_json or {}
        return data


def vital_column_names() -> list[str]:
    """All dedicated vital storage columns (mirrors the standalone script)."""
    return list(NUMERIC_DB_FIELDS) + [f"{c}_unit" for c in NUMERIC_DB_FIELDS] + list(TEXT_DB_FIELDS) + [
        "vitals_json",
        "vitals_schema_version",
    ]
