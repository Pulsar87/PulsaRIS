from django.contrib import admin
from .models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = [
        'mrn',
        'first_name_en',
        'last_name_en',
        'dob',
        'gender',
        'phone',
        'email',
        'is_deceased',
        'is_deleted',
        'created_at',
    ]
    list_filter = [
        'gender',
        'is_deceased',
        'is_deleted',
        'nationality',
        'created_at',
    ]
    search_fields = [
        'mrn',
        'first_name_en',
        'last_name_en',
        'first_name_ar',
        'last_name_ar',
        'national_id',
        'email',
        'phone',
    ]
    readonly_fields = [
        'id',
        'created_at',
        'updated_at',
    ]
    fieldsets = (
        ('Personal Information', {
            'fields': (
                'mrn',
                'first_name_en',
                'last_name_en',
                'first_name_ar',
                'last_name_ar',
                'dob',
                'gender',
                'nationality',
                'national_id',
            )
        }),
        ('Contact Information', {
            'fields': (
                'phone',
                'email',
                'address',
            )
        }),
        ('Emergency Contact', {
            'fields': (
                'emergency_contact_name',
                'emergency_contact_phone',
            )
        }),
        ('Insurance', {
            'fields': (
                'insurance_provider',
                'insurance_policy_number',
            )
        }),
        ('Status & Settings', {
            'fields': (
                'is_deceased',
                'consent_data_sharing',
                'data_retention_until',
                'is_deleted',
                'deleted_at',
            )
        }),
        ('System', {
            'fields': (
                'id',
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
