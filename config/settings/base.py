import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))
TEMPLATES = [
    {
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
    }
]
# ─────────────────────────────────────────────────────────────
# Core Django Settings
# ─────────────────────────────────────────────────────────────
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
AUDITLOG_DISABLE_REMOTE_ADDR = False
ROOT_URLCONF = "config.urls"

# ─────────────────────────────────────────────────────────────
# Authentication Settings
# ─────────────────────────────────────────────────────────────
LOGIN_URL = "users:login"
LOGIN_REDIRECT_URL = "license:home"
LOGOUT_REDIRECT_URL = "users:login"
# ─────────────────────────────────────────────────────────────
# Application Definition
# ─────────────────────────────────────────────────────────────
SHARED_APPS = [
    "django_tenants",  # MUST be first
    "tenants",  # Your tenant model app
    "license",  # License check - must be in SHARED_APPS to work across all tenants
    "core",  # Core admin registrations including Group
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "audit",  # Audit logs are shared across all tenants
    "users",  # Auth is typically shared or synced
]

TENANT_APPS = [
    "patients",
    "auditlog",
    "orders",
    "reports",
    "integrations",
    "billing",  # Financial/Billing module
    "django.contrib.staticfiles",
    "django_filters",
    "rest_framework",
    "drf_spectacular",
    "django_htmx",
    "whitenoise",
]

# django-tenants requires this exact merge
INSTALLED_APPS = list(SHARED_APPS) + [
    app for app in TENANT_APPS if app not in SHARED_APPS
]


# ─────────────────────────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "django_tenants.middleware.main.TenantMainMiddleware",  # MUST be first
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "license.middleware.LicenseMiddleware",  # License check middleware
    "django_htmx.middleware.HtmxMiddleware",
    "auditlog.middleware.AuditlogMiddleware",  # ← FIXED: correct middleware path
]

# ─────────────────────────────────────────────────────────────
# django-tenants Configuration (CRITICAL)
# ─────────────────────────────────────────────────────────────
# Tenant routing config
TENANT_MODEL = "tenants.Tenant"
TENANT_DOMAIN_MODEL = "tenants.Domain"
DATABASE_ROUTERS = ["django_tenants.routers.TenantSyncRouter"]
PUBLIC_SCHEMA_NAME = "public"  # explicit is better than implicit
TENANT_CREATION_FAKES_MIGRATIONS = False  # set True only for testing
SHOW_PUBLIC_IF_NO_TENANT_FOUND = True

# ─────────────────────────────────────────────────────────────
# Database (Docker-ready with env fallback)
# ─────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",  # ← MUST use this engine
        "NAME": env("POSTGRES_DB", default="pulsaris"),
        "USER": env("POSTGRES_USER", default="pulsaris"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="pulsaris"),
        "HOST": env("POSTGRES_HOST", default="postgres"),  # use "postgres" in Docker
        "PORT": env("POSTGRES_PORT", default="5432"),
        "ATOMIC_REQUESTS": True,
    }
}

# ─────────────────────────────────────────────────────────────
# Templates
# ─────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # ← Added global templates dir
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",  # ← Required for HTMX/i18n
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",  # ← Required for Arabic RTL
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
            ],
        },
    },
]

# ─────────────────────────────────────────────────────────────
# Static Files
# ─────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]  # ← Added source static dir
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ─────────────────────────────────────────────────────────────
# Internationalization (i18n) + RTL for Arabic
# ─────────────────────────────────────────────────────────────
LANGUAGE_CODE = env("DJANGO_LANGUAGE", default="en")
LANGUAGES = [
    ("en", "English"),
    ("ar", "Arabic"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True
USE_L10N = True
USE_TZ = True
TIME_ZONE = "Asia/Damascus"

# ─────────────────────────────────────────────────────────────
# Celery
# ─────────────────────────────────────────────────────────────
#
CELERY_BROKER_URL = "redis://redis:6379/1"  # Change 'localhost' to 'redis'
CELERY_RESULT_BACKEND = "redis://redis:6379/2"

#CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/1")
#CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/2")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes max per task

# ─────────────────────────────────────────────────────────────
# Django REST Framework + OpenAPI
# ─────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "RIS Platform API",
    "DESCRIPTION": "Radiology Information System - OpenAPI 3.0",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# ─────────────────────────────────────────────────────────────
# Audit Logging (HIPAA Compliance)
# ─────────────────────────────────────────────────────────────
# AUDITLOG_CID_GETTER = None
# AUDITLOG_CID_HEADER = None
AUDITLOG_INCLUDE_ALL_MODELS = True  # explicit is safer
# AUDITLOG_DISABLE_ON_RAW_SAVE = False
AUTH_USER_MODEL = "users.User"
# ─────────────────────────────────────────────────────────────
# Security (Production Hardening - override in prod.py)
# ─────────────────────────────────────────────────────────────
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

SESSION_SAVE_EVERY_REQUEST = True
