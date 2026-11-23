from django.urls import path

from clinic import views

app_name = "clinic"

# Phase 1 (Operations): appointments, reception queue, availability.
# Phase 2 (Clinical records): encounters, vitals, notes, referrals, charges.
urlpatterns = [
    path("appointments/", views.appointment_list, name="appointment_list"),
    path(
        "appointments/calendar-events/",
        views.appointment_calendar_events,
        name="appointment_calendar_events",
    ),
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
    # ── Clinical Encounter & Documentation: structured record types ──
    path("encounters/<uuid:pk>/chief-complaint/", views.chief_complaint_add, name="chief_complaint_add"),
    path("encounters/<uuid:pk>/diagnosis/", views.diagnosis_add, name="diagnosis_add"),
    path("encounters/<uuid:pk>/orders/place/", views.clinical_order_place, name="clinical_order_place"),
    path("clinical-orders/<uuid:pk>/<str:action>/", views.clinical_order_action, name="clinical_order_action"),
    path("encounters/<uuid:pk>/follow-up/", views.follow_up_add, name="follow_up_add"),
    path("notes/<uuid:pk>/sign/", views.note_sign, name="note_sign"),
    path("notes/<uuid:pk>/amend/", views.note_amend, name="note_amend"),
    # ── Phase 4: patient-matching reconciliation (admin, manual review) ──
    path("patients/duplicates/", views.patient_duplicates, name="patient_duplicates"),
    path(
        "patients/<uuid:pk>/merge/",
        views.patient_merge,
        name="patient_merge",
    ),
]
