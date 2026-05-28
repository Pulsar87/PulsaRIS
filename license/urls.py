from django.urls import path

from . import views

app_name = "license"

urlpatterns = [
    path("", views.home, name="home"),
    path("activate/", views.activate, name="activate"),
    path("activation-required/", views.activation_required, name="activation_required"),
    path("api/calendar-events/", views.calendar_events, name="calendar_events"),
]
