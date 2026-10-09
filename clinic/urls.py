from django.urls import path

from clinic import views

app_name = "clinic"

# Phase 1 (Operations): appointments, reception queue, availability.
# Phase 2 (Clinical records): encounters, vitals, notes, referrals, charges.
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
    # ── Phase 2: encounters & clinical records ──
    path("encounters/", views.encounter_list, name="encounter_list"),
    path("encounters/new/", views.encounter_new, name="encounter_new"),
    path("encounters/<uuid:pk>/", views.encounter_detail, name="encounter_detail"),
    path("encounters/<uuid:pk>/<str:action>/", views.encounter_action, name="encounter_action"),
    path("encounters/<uuid:pk>/vitals/", views.vitals_add, name="vitals_add"),
    path("encounters/<uuid:pk>/notes/", views.note_create, name="note_create"),
    path("encounters/<uuid:pk>/refer/", views.referral_from_encounter, name="referral_from_encounter"),
    path("encounters/<uuid:pk>/charge/", views.encounter_charge, name="encounter_charge"),
    path("notes/<uuid:pk>/sign/", views.note_sign, name="note_sign"),
    path("notes/<uuid:pk>/amend/", views.note_amend, name="note_amend"),
]
