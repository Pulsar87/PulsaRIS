from django.apps import AppConfig


class Hl7ListenerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.hl7"
    label = "integrations_hl7"
    verbose_name = "HL7 lab/vitals receiver service"
