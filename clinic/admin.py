from django.contrib import admin

from clinic.models import (
    Appointment,
    Encounter,
    FacilityAssignment,
    PatientFacilityIdentifier,
    ProviderAvailability,
    RoomBooking,
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
