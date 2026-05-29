from django.contrib import admin
from .models import Tenant, Domain, Facility, Modality, Device


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["name", "subdomain", "schema_name", "is_active", "license_activated", "created_at"]
    list_filter = ["is_active", "license_activated"]
    search_fields = ["name", "subdomain", "schema_name"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ["domain", "tenant", "is_primary", "created_at"]
    list_filter = ["is_primary"]
    search_fields = ["domain", "tenant__name"]


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ["name", "tenant", "dicom_ae_title", "is_active", "created_at"]
    list_filter = ["tenant", "is_active"]
    search_fields = ["name", "dicom_ae_title"]
    readonly_fields = ["id", "created_at"]


@admin.register(Modality)
class ModalityAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "tenant", "is_active", "created_at"]
    list_filter = ["tenant", "is_active", "code"]
    search_fields = ["code", "name", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["name", "modality", "facility", "tenant", "room_number", "is_active", "created_at"]
    list_filter = ["tenant", "modality", "is_active"]
    search_fields = ["name", "room_number"]
    readonly_fields = ["id", "created_at", "updated_at"]
