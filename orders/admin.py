from django.contrib import admin

from .models import ExamOrder, Procedure


@admin.register(Procedure)
class ProcedureAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "name_en",
        "name_ar",
        "modality_type",
        "is_active",
        "updated_at",
    ]
    list_filter = ["modality_type", "is_active"]
    search_fields = ["code", "name_en", "name_ar", "description"]
    ordering = ["modality_type", "code"]
    list_editable = ["is_active"]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("code", "name_en", "name_ar", "modality_type")},
        ),
        (
            "Additional Details",
            {"fields": ("description", "is_active"), "classes": ("collapse",)},
        ),
    )


@admin.register(ExamOrder)
class ExamOrderAdmin(admin.ModelAdmin):
    list_display = [
        "accession_number",
        "patient",
        "modality",
        "procedure_code",
        "status",
        "priority",
        "created_at",
    ]
    list_filter = ["status", "priority", "modality"]
    search_fields = [
        "accession_number",
        "patient__mrn",
        "patient__first_name_en",
        "patient__last_name_en",
    ]
    ordering = ["-created_at"]
    date_hierarchy = "created_at"
