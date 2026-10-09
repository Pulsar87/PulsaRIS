from django.apps import AppConfig


class ClinicConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "clinic"

    def ready(self):
        # Phase 3: register the IntegrationEvent outbox post_save hooks.
        from clinic import signals  # noqa: F401
