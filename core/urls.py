from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('api/facilities/search/', views.facility_search_api, name='facilities_search_api'),
    path('api/devices/search/', views.device_search_api, name='devices_search_api'),
]
