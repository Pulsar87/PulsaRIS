from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    name = 'integrations'
    default = True

    def ready(self):
        # Import the HL7 sub-app models so admin registration and migrations
        # for `integrations.hl7` are discovered with the parent app.
        import integrations.hl7.admin  # noqa: F401
