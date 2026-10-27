"""Admin registration for the HL7 lab/vitals receiver service."""

from __future__ import annotations

import json

from django.contrib import admin

from integrations.hl7.models import HL7VitalMessage


@admin.register(HL7VitalMessage)
class HL7VitalMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id", "received_at", "status", "message_type", "message_control_id",
        "sender_identity", "spo2", "pulse_rate", "systolic_bp", "diastolic_bp",
        "body_temperature",
    )
    list_filter = ("status", "message_type", "sending_application", "sending_facility")
    search_fields = ("message_control_id", "sender_identity", "payload_sha256", "raw_hl7")
    date_hierarchy = "received_at"
    ordering = ("-received_at", "-id")
    readonly_fields = tuple(field.name for field in HL7VitalMessage._meta.fields)
    list_per_page = 50

    def has_add_permission(self, request):
        # Rows are created by the listener/ingest pipeline, not manually.
        return False

    @admin.display(description="Parsed JSON")
    def parsed_pretty(self, obj):
        return json.dumps(obj.parsed_json, indent=2, ensure_ascii=False)
