from django.contrib import admin
from django.core.exceptions import PermissionDenied

from clinic.models import (
    Allergy,
    Appointment,
    Encounter,
    EncounterNote,
    FacilityAssignment,
    IntegrationEvent,
    Medication,
    PatientFacilityIdentifier,
    Problem,
    ProviderAvailability,
    RoomBooking,
    Vitals,
)


@admin.register(FacilityAssignment)
class FacilityAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "facility", "role_at_facility", "start_date", "end_date", "is_active")
    list_filter = ("facility", "role_at_facility", "is_active")
    search_fields = ("user__email", "user__username")


@admin.register(PatientFacilityIdentifier)
class PatientFacilityIdentifierAdmin(admin.ModelAdmin):
    list_display = ("patient", "facility", "identifier_type", "identifier", "is_primary")
    list_filter = ("facility", "identifier_type")
    search_fields = ("identifier", "patient__mrn")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("patient", "facility", "provider", "start_datetime", "status",
                    "queue_position")
    list_filter = ("facility", "status")
    search_fields = ("patient__mrn", "reason")
    readonly_fields = ("cancelled_at", "checked_in_at")


@admin.register(Encounter)
class EncounterAdmin(admin.ModelAdmin):
    list_display = ("patient", "facility", "provider", "status", "started_at")
    list_filter = ("facility", "status")
    search_fields = ("patient__mrn",)


@admin.register(ProviderAvailability)
class ProviderAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("provider", "facility", "kind", "weekday", "start_time",
                    "end_time", "exception_date", "is_available")
    list_filter = ("facility", "kind")


@admin.register(RoomBooking)
class RoomBookingAdmin(admin.ModelAdmin):
    list_display = ("room", "facility", "start_datetime", "duration_minutes",
                    "appointment", "exam_order", "is_cancelled")
    list_filter = ("facility", "is_cancelled")


@admin.register(Vitals)
class VitalsAdmin(admin.ModelAdmin):
    list_display = ("encounter", "recorded_by", "recorded_at", "systolic_bp",
                    "diastolic_bp", "heart_rate", "temperature_c")
    list_filter = ("encounter__facility",)
    search_fields = ("encounter__patient__mrn",)


@admin.register(Problem)
class ProblemAdmin(admin.ModelAdmin):
    list_display = ("patient", "code", "description", "status", "recorded_by")
    list_filter = ("status",)
    search_fields = ("patient__mrn", "code", "description")


@admin.register(Allergy)
class AllergyAdmin(admin.ModelAdmin):
    list_display = ("patient", "substance", "reaction_type", "severity", "clinical_status")
    list_filter = ("severity", "clinical_status", "reaction_type")
    search_fields = ("patient__mrn", "substance")


@admin.register(Medication)
class MedicationAdmin(admin.ModelAdmin):
    list_display = ("patient", "name", "dose", "frequency", "status")
    list_filter = ("status",)
    search_fields = ("patient__mrn", "name")


@admin.register(EncounterNote)
class EncounterNoteAdmin(admin.ModelAdmin):
    """Signed notes are immutable: no editing, no deleting (addendum B.4)."""

    list_display = ("encounter", "version", "author", "signed_at", "content_hash")
    list_filter = ("encounter__facility",)
    search_fields = ("encounter__patient__mrn", "body")
    readonly_fields = ("content_hash", "prev_version_hash", "signed_at")

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.signed_at is not None:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.signed_at is not None:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(IntegrationEvent)
class IntegrationEventAdmin(admin.ModelAdmin):
    """Phase 3 outbox: read-only for humans; consumers update delivery fields."""

    list_display = ("created_at", "event_type", "facility", "entity_type", "delivered_at", "delivery_attempts")
    list_filter = ("event_type", "facility", "delivered_at")
    search_fields = ("entity_id",)
    readonly_fields = tuple(f.name for f in IntegrationEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
