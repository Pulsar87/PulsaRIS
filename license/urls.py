from django.urls import path
from . import views

app_name = 'license'

urlpatterns = [
    path('activate/', views.activate, name='activate'),
    path('activation-required/', views.activation_required, name='activation_required'),
]
