"""Phase 3 read-only JSON API serializers (plan Step 4 item 1).

Internal-stable contract first; full FHIR R4 resource mapping deferred until
pilot feedback. Field names deliberately mirror the eventual FHIR resources:
Appointment -> schedulingslot-style flat snapshot, Encounter -> Encounter,
EncounterNote -> DocumentReference metadata (body only for encounter
providers/readers — see view-level gating).
"""

from rest_framework import serializers

from clinic.models import Appointment, Encounter, EncounterNote, IntegrationEvent
from patients.models import Patient


class PatientSearchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = [
            "id", "mrn", "first_name_en", "last_name_en",
            "dob", "gender", "phone", "is_deceased",
        ]
        read_only_fields = fields


class AppointmentSerializer(serializers.ModelSerializer):
    patient = serializers.SerializerMethodField()
    facility_id = serializers.UUIDField(read_only=True)
    end_datetime = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id", "patient", "facility_id", "provider", "department", "room",
            "start_datetime", "end_datetime", "duration_minutes", "status",
            "reason", "queue_position", "cancelled_reason", "cancelled_at",
            "checked_in_at", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_patient(self, obj):
        return {
            "id": str(obj.patient_id),
            "mrn": obj.patient.mrn,
            "name": f"{obj.patient.first_name_en} {obj.patient.last_name_en}".strip(),
        }


class EncounterSerializer(serializers.ModelSerializer):
    patient = serializers.SerializerMethodField()

    class Meta:
        model = Encounter
        fields = [
            "id", "appointment", "patient", "facility", "provider", "status",
            "started_at", "ended_at", "reason", "cancellation_reason",
            "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_patient(self, obj):
        return {
            "id": str(obj.patient_id),
            "mrn": obj.patient.mrn,
            "name": f"{obj.patient.first_name_en} {obj.patient.last_name_en}".strip(),
        }


class EncounterNoteMetaSerializer(serializers.ModelSerializer):
    """Notes *metadata* per plan Step 4 item 1; body exposed only through the
    detail endpoint where facility scoping is object-checked."""

    class Meta:
        model = EncounterNote
        fields = [
            "id", "encounter", "version", "supersedes", "author",
            "signed_at", "content_hash", "prev_version_hash", "created_at",
        ]
        read_only_fields = fields


class IntegrationEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationEvent
        fields = [
            "id", "event_type", "facility", "entity_type", "entity_id",
            "payload", "created_at", "delivered_at", "delivery_attempts",
        ]
        read_only_fields = fields
