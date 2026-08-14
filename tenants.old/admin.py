from django.contrib import admin
from .models import Facility, Modality, Device


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ["name", "dicom_ae_title", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "dicom_ae_title"]
    readonly_fields = ["id", "created_at"]


@admin.register(Modality)
class ModalityAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_active", "created_at"]
    list_filter = ["is_active", "code"]
    search_fields = ["code", "name", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["name", "modality", "facility", "room_number", "is_active", "created_at"]
    list_filter = ["modality", "is_active"]
    search_fields = ["name", "room_number"]
    readonly_fields = ["id", "created_at", "updated_at"]
