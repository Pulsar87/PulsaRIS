from django.urls import path
from . import views

app_name = 'patients'

urlpatterns = [
    path('add/', views.add_patient, name='add_patient'),
    path('', views.patient_list, name='patient_list'),
    path('<uuid:pk>/', views.patient_detail, name='patient_detail'),
    path('<uuid:pk>/edit/', views.edit_patient, name='edit_patient'),
    path('<uuid:pk>/delete/', views.delete_patient, name='delete_patient'),
    path('search/', views.search_patient, name='search_patient'),
    path('api/lookup/', views.patient_lookup, name='patient_lookup'),
    path('api/search/', views.patient_search_api, name='patient_search_api'),
]
