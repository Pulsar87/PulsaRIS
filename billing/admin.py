from django.contrib import admin
from .models import (
    InsurancePayer, Clearinghouse, PatientInsurance, Authorization,
    FeeSchedule, FeeScheduleItem, PatientAccount, ServiceLine,
    Claim, ClaimLine, PaymentPosting, PaymentDetail,
    PatientStatement, Payment, PaymentAllocation,
    PaymentPlan, PaymentPlanInstallment,
    DenialReason, ClaimAppeal
)


@admin.register(InsurancePayer)
class InsurancePayerAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'payer_id', 'payer_type', 'edi_enabled', 'claim_format', 'is_active']
    list_filter = ['payer_type', 'edi_enabled', 'is_active', 'claim_format']
    search_fields = ['name', 'code', 'payer_id', 'short_name']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('tenant', 'name', 'short_name', 'code', 'payer_id', 'payer_type')
        }),
        ('Contact Information', {
            'fields': (
                ('address_line1', 'address_line2'),
                ('city', 'state_province', 'postal_code', 'country'),
                ('phone', 'fax', 'email', 'website')
            )
        }),
        ('EDI Configuration', {
            'fields': (
                ('edi_enabled', 'clearinghouse'),
                ('edi_qualifier', 'edi_receiver_id'),
                ('transmitter_name', 'isa_receiver_id', 'gs_receiver_id'),
                ('billing_provider_npi', 'billing_provider_tin')
            )
        }),
        ('Claim Settings', {
            'fields': (
                ('claim_format', 'fee_schedule', 'default_copay'),
                ('require_auth', 'auth_required_for_cpt'),
                'place_of_service_restrictions'
            )
        }),
        ('ERA Settings', {
            'fields': ('era_enabled', 'era_trace_number_qualifier')
        }),
        ('Status', {
            'fields': ('is_active', 'created_at', 'updated_at')
        }),
    )


@admin.register(Clearinghouse)
class ClearinghouseAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'vendor_name', 'transmission_protocol', 'supports_837p', 'supports_835', 'is_active']
    list_filter = ['is_active', 'transmission_protocol', 'supports_837p', 'supports_837i', 'supports_835']
    search_fields = ['name', 'code', 'vendor_name']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('tenant', 'name', 'code', 'vendor_name')
        }),
        ('Support Contact', {
            'fields': (
                ('support_phone', 'support_email'),
                'website'
            )
        }),
        ('API Connection', {
            'fields': (
                ('api_endpoint', 'api_username'),
                'api_password',
                'api_key'
            )
        }),
        ('EDI Settings', {
            'fields': (
                ('sender_id', 'receiver_id'),
                'interchange_control_version',
                'trading_partner_id'
            )
        }),
        ('Supported Transactions', {
            'fields': (
                ('supports_837p', 'supports_837i'),
                ('supports_835', 'supports_270_271'),
                'supports_278'
            )
        }),
        ('Transmission Protocol', {
            'fields': (
                ('transmission_protocol', 'sftp_host', 'sftp_port'),
                'sftp_username'
            )
        }),
        ('Status', {
            'fields': ('is_active', 'created_at', 'updated_at')
        }),
    )


@admin.register(PatientInsurance)
class PatientInsuranceAdmin(admin.ModelAdmin):
    list_display = ['patient', 'payer', 'priority', 'policy_number', 'verified']
    list_filter = ['priority', 'verified']
    search_fields = ['patient__mrn', 'policy_number']


@admin.register(Authorization)
class AuthorizationAdmin(admin.ModelAdmin):
    list_display = ['auth_number', 'exam_order', 'status', 'valid_until']
    list_filter = ['status', 'auth_type']
    search_fields = ['auth_number']


@admin.register(FeeSchedule)
class FeeScheduleAdmin(admin.ModelAdmin):
    list_display = ['name', 'schedule_type', 'payer', 'is_active', 'effective_date']
    list_filter = ['schedule_type', 'is_active']
    search_fields = ['name']


@admin.register(FeeScheduleItem)
class FeeScheduleItemAdmin(admin.ModelAdmin):
    list_display = ['procedure_code', 'procedure_description', 'fee_schedule', 'global_fee']
    list_filter = ['fee_schedule']
    search_fields = ['procedure_code', 'procedure_description']


@admin.register(PatientAccount)
class PatientAccountAdmin(admin.ModelAdmin):
    list_display = ['account_number', 'patient', 'account_status', 'current_balance']
    list_filter = ['account_status', 'has_payment_plan']
    search_fields = ['account_number', 'patient__mrn']


@admin.register(ServiceLine)
class ServiceLineAdmin(admin.ModelAdmin):
    list_display = ['procedure_code', 'service_date', 'exam_order', 'total_charge', 'billing_status']
    list_filter = ['billing_status', 'service_date']
    search_fields = ['procedure_code']


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ['claim_number', 'patient_account', 'payer', 'status', 'total_charges', 'submission_date']
    list_filter = ['status', 'claim_type', 'submission_date']
    search_fields = ['claim_number']


@admin.register(ClaimLine)
class ClaimLineAdmin(admin.ModelAdmin):
    list_display = ['claim', 'line_number', 'cpt_code', 'charge_amount', 'status']
    list_filter = ['status']


@admin.register(PaymentPosting)
class PaymentPostingAdmin(admin.ModelAdmin):
    list_display = ['posting_date', 'claim', 'payment_method', 'payment_amount', 'status']
    list_filter = ['payment_method', 'status', 'posting_date']


@admin.register(PaymentDetail)
class PaymentDetailAdmin(admin.ModelAdmin):
    list_display = ['payment_posting', 'claim_line', 'paid_amount', 'is_denied']
    list_filter = ['is_denied']


@admin.register(PatientStatement)
class PatientStatementAdmin(admin.ModelAdmin):
    list_display = ['statement_number', 'patient_account', 'statement_date', 'current_balance', 'status']
    list_filter = ['status', 'delivery_method']
    search_fields = ['statement_number']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['payment_date', 'patient_account', 'amount', 'payment_method']
    list_filter = ['payment_method', 'payment_date']


@admin.register(PaymentAllocation)
class PaymentAllocationAdmin(admin.ModelAdmin):
    list_display = ['payment', 'service_line', 'allocated_amount', 'allocation_date']


@admin.register(PaymentPlan)
class PaymentPlanAdmin(admin.ModelAdmin):
    list_display = ['patient_account', 'total_amount', 'remaining_balance', 'monthly_payment', 'status']
    list_filter = ['status']


@admin.register(PaymentPlanInstallment)
class PaymentPlanInstallmentAdmin(admin.ModelAdmin):
    list_display = ['payment_plan', 'installment_number', 'due_date', 'amount_due', 'status']
    list_filter = ['status']


@admin.register(DenialReason)
class DenialReasonAdmin(admin.ModelAdmin):
    list_display = ['code_system', 'code', 'description', 'category', 'requires_appeal']
    list_filter = ['code_system', 'category', 'requires_appeal']
    search_fields = ['code', 'description']


@admin.register(ClaimAppeal)
class ClaimAppealAdmin(admin.ModelAdmin):
    list_display = ['appeal_number', 'claim', 'appeal_level', 'status', 'filed_date']
    list_filter = ['appeal_level', 'status']
    search_fields = ['appeal_number']
