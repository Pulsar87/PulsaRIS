from django.urls import path
from . import views

app_name = 'patients'

urlpatterns = [
    path('add/', views.add_patient, name='add_patient'),
    path('', views.patient_list, name='patient_list'),
    path('<uuid:pk>/', views.patient_detail, name='patient_detail'),
    path('search/', views.search_patient, name='search_patient'),
    path('api/lookup/', views.patient_lookup, name='patient_lookup'),
]
