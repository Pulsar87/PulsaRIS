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
    list_display = ['name', 'payer_id', 'payer_type', 'is_active']
    list_filter = ['payer_type', 'is_active']
    search_fields = ['name', 'payer_id']


@admin.register(Clearinghouse)
class ClearinghouseAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at']
    list_filter = ['is_active']


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
