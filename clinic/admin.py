from django.contrib import admin

from clinic.models import FacilityAssignment, PatientFacilityIdentifier


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
