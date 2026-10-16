"""Local test settings: dev settings with an in-memory SQLite database.

Used only for running the unit-test suite inside sandboxes/CI without a
PostgreSQL server (production/dev still use config.settings.dev/base).
"""
from config.settings.dev import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
