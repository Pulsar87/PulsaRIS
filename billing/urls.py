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
    
    # Fee Schedule Lookup API
    path('api/fee-lookup/', views.fee_lookup_api, name='fee_lookup_api'),
    path('api/fee-calculate/', views.fee_calculate_api, name='fee_calculate_api'),
]
