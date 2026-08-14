from django.contrib import admin

from .models import Facility, Modality, Device


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ["name", "dicom_ae_title", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "dicom_ae_title", "hl7_facility_id"]


@admin.register(Modality)
class ModalityAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["code", "name"]


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["name", "modality", "facility", "dicom_host", "dicom_port", "is_active"]
    list_filter = ["modality", "facility", "is_active"]
    search_fields = ["name", "dicom_ae_title", "dicom_host"]
