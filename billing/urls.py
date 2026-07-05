from django.urls import path
from . import views

app_name = 'billing'

urlpatterns = [
    # Fee Schedule Management
    path('fee-schedules/', views.FeeScheduleListView.as_view(), name='fee_schedule_list'),
    path('fee-schedules/create/', views.FeeScheduleCreateView.as_view(), name='fee_schedule_create'),
    path('fee-schedules/<uuid:pk>/', views.FeeScheduleDetailView.as_view(), name='fee_schedule_detail'),
    path('fee-schedules/<uuid:pk>/update/', views.FeeScheduleUpdateView.as_view(), name='fee_schedule_update'),
    path('fee-schedules/<uuid:pk>/delete/', views.FeeScheduleDeleteView.as_view(), name='fee_schedule_delete'),
    path('fee-schedules/<uuid:pk>/items/add/', views.FeeScheduleItemCreateView.as_view(), name='fee_schedule_item_add'),
    path('fee-schedule-items/<uuid:pk>/update/', views.FeeScheduleItemUpdateView.as_view(), name='fee_schedule_item_update'),
    path('fee-schedule-items/<uuid:pk>/delete/', views.FeeScheduleItemDeleteView.as_view(), name='fee_schedule_item_delete'),
    
    # Insurance Payer Management
    path('payers/', views.InsurancePayerListView.as_view(), name='payer_list'),
    path('payers/create/', views.InsurancePayerCreateView.as_view(), name='payer_create'),
    path('payers/<uuid:pk>/', views.InsurancePayerDetailView.as_view(), name='payer_detail'),
    path('payers/<uuid:pk>/update/', views.InsurancePayerUpdateView.as_view(), name='payer_update'),
    path('payers/<uuid:pk>/delete/', views.InsurancePayerDeleteView.as_view(), name='payer_delete'),
    
    # Clearinghouse Management
    path('clearinghouses/', views.ClearinghouseListView.as_view(), name='clearinghouse_list'),
    path('clearinghouses/create/', views.ClearinghouseCreateView.as_view(), name='clearinghouse_create'),
    path('clearinghouses/<uuid:pk>/', views.ClearinghouseDetailView.as_view(), name='clearinghouse_detail'),
    path('clearinghouses/<uuid:pk>/update/', views.ClearinghouseUpdateView.as_view(), name='clearinghouse_update'),
    
    # Patient Insurance
    path('patient-insurance/add/', views.PatientInsuranceCreateView.as_view(), name='patient_insurance_add'),
    path('patient-insurance/<uuid:pk>/update/', views.PatientInsuranceUpdateView.as_view(), name='patient_insurance_update'),
    
    # Authorizations
    path('authorizations/add/', views.AuthorizationCreateView.as_view(), name='authorization_add'),
    path('authorizations/<uuid:pk>/update/', views.AuthorizationUpdateView.as_view(), name='authorization_update'),
    
    # Patient Accounts
    path('patient-accounts/<uuid:pk>/', views.PatientAccountDetailView.as_view(), name='patient_account_detail'),
    path('patient-accounts/create/', views.PatientAccountCreateView.as_view(), name='patient_account_create'),
    
    # Service Lines (Charge Capture)
    path('service-lines/', views.ServiceLineListView.as_view(), name='service_line_list'),
    path('service-lines/create/', views.ServiceLineCreateView.as_view(), name='service_line_create'),
    path('service-lines/<uuid:pk>/', views.ServiceLineDetailView.as_view(), name='service_line_detail'),
    path('service-lines/<uuid:pk>/update/', views.ServiceLineUpdateView.as_view(), name='service_line_update'),
    path('service-lines/<uuid:pk>/delete/', views.ServiceLineDeleteView.as_view(), name='service_line_delete'),
    
    # Claims Management
    path('claims/', views.ClaimListView.as_view(), name='claim_list'),
    path('claims/create/', views.ClaimCreateView.as_view(), name='claim_create'),
    path('claims/<uuid:pk>/', views.ClaimDetailView.as_view(), name='claim_detail'),
    path('claims/<uuid:pk>/update/', views.ClaimUpdateView.as_view(), name='claim_update'),
    path('claims/<uuid:pk>/delete/', views.ClaimDeleteView.as_view(), name='claim_delete'),
    
    # Claim Lines
    path('claims/<uuid:claim_pk>/lines/add/', views.ClaimLineCreateView.as_view(), name='claim_line_add'),
    path('claim-lines/<uuid:pk>/update/', views.ClaimLineUpdateView.as_view(), name='claim_line_update'),
    path('claim-lines/<uuid:pk>/delete/', views.ClaimLineDeleteView.as_view(), name='claim_line_delete'),
    
    # Payment Posting Management
    path('payment-postings/', views.PaymentPostingListView.as_view(), name='payment_posting_list'),
    path('payment-postings/create/', views.PaymentPostingCreateView.as_view(), name='payment_posting_create'),
    path('payment-postings/<uuid:pk>/', views.PaymentPostingDetailView.as_view(), name='payment_posting_detail'),
    path('payment-postings/<uuid:pk>/update/', views.PaymentPostingUpdateView.as_view(), name='payment_posting_update'),
    path('payment-postings/<uuid:pk>/delete/', views.PaymentPostingDeleteView.as_view(), name='payment_posting_delete'),

    # Payment Details (within payment postings)
    path('payment-postings/<uuid:posting_pk>/details/add/', views.PaymentDetailCreateView.as_view(), name='payment_detail_add'),
    path('payment-details/<uuid:pk>/update/', views.PaymentDetailUpdateView.as_view(), name='payment_detail_update'),
    path('payment-details/<uuid:pk>/delete/', views.PaymentDetailDeleteView.as_view(), name='payment_detail_delete'),

    # Patient Payment Management
    path('payments/', views.PaymentListView.as_view(), name='payment_list'),
    path('payments/create/', views.PaymentCreateView.as_view(), name='payment_create'),
    path('payments/<uuid:pk>/', views.PaymentDetailView.as_view(), name='payment_detail'),
    path('payments/<uuid:pk>/update/', views.PaymentUpdateView.as_view(), name='payment_update'),
    path('payments/<uuid:pk>/delete/', views.PaymentDeleteView.as_view(), name='payment_delete'),

    # Payment Allocations
    path('payments/<uuid:payment_pk>/allocations/add/', views.PaymentAllocationCreateView.as_view(), name='payment_allocation_add'),
    path('payment-allocations/<uuid:pk>/update/', views.PaymentAllocationUpdateView.as_view(), name='payment_allocation_update'),
    path('payment-allocations/<uuid:pk>/delete/', views.PaymentAllocationDeleteView.as_view(), name='payment_allocation_delete'),

    # Patient Statements
    path('statements/', views.PatientStatementListView.as_view(), name='statement_list'),
    path('statements/create/', views.PatientStatementCreateView.as_view(), name='statement_create'),
    path('statements/<uuid:pk>/', views.PatientStatementDetailView.as_view(), name='statement_detail'),
    path('statements/<uuid:pk>/update/', views.PatientStatementUpdateView.as_view(), name='statement_update'),
    path('statements/<uuid:pk>/delete/', views.PatientStatementDeleteView.as_view(), name='statement_delete'),

    # Payment Plans
    path('payment-plans/', views.PaymentPlanListView.as_view(), name='payment_plan_list'),
    path('payment-plans/create/', views.PaymentPlanCreateView.as_view(), name='payment_plan_create'),
    path('payment-plans/<uuid:pk>/', views.PaymentPlanDetailView.as_view(), name='payment_plan_detail'),
    path('payment-plans/<uuid:pk>/update/', views.PaymentPlanUpdateView.as_view(), name='payment_plan_update'),
    path('payment-plans/<uuid:pk>/delete/', views.PaymentPlanDeleteView.as_view(), name='payment_plan_delete'),
    path('payment-plan-installments/<uuid:pk>/update/', views.PaymentPlanInstallmentUpdateView.as_view(), name='payment_plan_installment_update'),

    # Denial Reasons
    path('denial-reasons/', views.DenialReasonListView.as_view(), name='denial_reason_list'),
    path('denial-reasons/<uuid:pk>/', views.DenialReasonDetailView.as_view(), name='denial_reason_detail'),
    path('denial-reasons/create/', views.DenialReasonCreateView.as_view(), name='denial_reason_create'),
    path('denial-reasons/<uuid:pk>/update/', views.DenialReasonUpdateView.as_view(), name='denial_reason_update'),
    path('denial-reasons/<uuid:pk>/delete/', views.DenialReasonDeleteView.as_view(), name='denial_reason_delete'),

    # Claim Appeals
    path('claim-appeals/', views.ClaimAppealListView.as_view(), name='claim_appeal_list'),
    path('claim-appeals/<uuid:pk>/', views.ClaimAppealDetailView.as_view(), name='claim_appeal_detail'),
    path('claim-appeals/create/', views.ClaimAppealCreateView.as_view(), name='claim_appeal_create'),
    path('claim-appeals/<uuid:pk>/update/', views.ClaimAppealUpdateView.as_view(), name='claim_appeal_update'),
    path('claim-appeals/<uuid:pk>/delete/', views.ClaimAppealDeleteView.as_view(), name='claim_appeal_delete'),

    # Fee Schedule Lookup API
    path('api/fee-lookup/', views.fee_lookup_api, name='fee_lookup_api'),
    path('api/fee-calculate/', views.fee_calculate_api, name='fee_calculate_api'),
    
    # EDI & Clearinghouse Integration
    path('claims/<uuid:claim_id>/generate-837/', views.ClaimGenerate837View.as_view(), name='claim_generate_837'),
    path('claims/<uuid:claim_id>/submit-clearinghouse/', views.ClaimSubmitToClearinghouseView.as_view(), name='claim_submit_clearinghouse'),
    path('claims/<uuid:claim_id>/status-check/', views.ClaimStatusCheckView.as_view(), name='claim_status_check'),
    path('era/upload/', views.ERAUploadView.as_view(), name='era_upload'),
    path('era/fetch/', views.FetchERAFilesView.as_view(), name='era_fetch'),
    
    # Reports & Analytics
    path('reports/charge-capture/', views.ChargeCaptureReportView.as_view(), name='report_charge_capture'),
    path('reports/claim-submission/', views.ClaimSubmissionReportView.as_view(), name='report_claim_submission'),
    path('reports/payment-posting/', views.PaymentPostingReportView.as_view(), name='report_payment_posting'),
    path('reports/ar-aging/', views.ARAgingReportView.as_view(), name='report_ar_aging'),
    path('reports/denial-management/', views.DenialManagementReportView.as_view(), name='report_denial_management'),
    path('reports/revenue-analysis/', views.RevenueAnalysisReportView.as_view(), name='report_revenue_analysis'),
    path('reports/collection-metrics/', views.CollectionMetricsReportView.as_view(), name='report_collection_metrics'),
]
