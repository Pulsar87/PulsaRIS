from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_stats, name='dashboard_stats'),
    path('api/stats/', views.dashboard_stats_api, name='dashboard_stats_api'),
    path('api/chart/orders-by-modality/', views.orders_by_modality_chart, name='orders_by_modality_chart'),
    path('api/chart/orders-trend/', views.orders_trend_chart, name='orders_trend_chart'),
    path('api/chart/revenue-by-payer/', views.revenue_by_payer_chart, name='revenue_by_payer_chart'),
    path('api/chart/claims-status/', views.claims_status_chart, name='claims_status_chart'),
]
