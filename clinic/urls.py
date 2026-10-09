from django.urls import path

from clinic import views

app_name = "clinic"

# Phase 1 (Operations): appointments, reception queue, availability.
# Phase 2 will add encounter/clinical-record routes here.
urlpatterns = [
    path("appointments/", views.appointment_list, name="appointment_list"),
    path("appointments/new/", views.appointment_new, name="appointment_new"),
    path("appointments/<uuid:pk>/", views.appointment_detail, name="appointment_detail"),
    path(
        "appointments/<uuid:pk>/<str:action>/",
        views.appointment_action,
        name="appointment_action",
    ),
    path("queue/", views.reception_queue, name="reception_queue"),
    path("availability/", views.availability_list, name="availability_list"),
    path("availability/add/", views.availability_add, name="availability_add"),
    path("api/free-slots/", views.free_slots_api, name="free_slots_api"),
]
