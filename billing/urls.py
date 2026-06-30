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
    
    # Fee Schedule Lookup API
    path('api/fee-lookup/', views.fee_lookup_api, name='fee_lookup_api'),
    path('api/fee-calculate/', views.fee_calculate_api, name='fee_calculate_api'),
]
