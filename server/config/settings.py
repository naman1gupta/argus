"""Django settings for the Argus server.

Configuration comes from environment variables (see .env.example at the repo
root). Defaults target local development against the docker-compose services.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load the repo-root .env when running on the host; inside containers the
# environment is injected by compose and this is a no-op.
load_dotenv(BASE_DIR.parent / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes"}


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-secret")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.postgres",
    "apps.accounts",
    "apps.projects",
    "apps.chat",
    "apps.telemetry",
    "apps.insights",
]

AUTH_USER_MODEL = "accounts.User"

# No GZipMiddleware: it buffers streaming responses and breaks SSE.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

SESSION_COOKIE_HTTPONLY = True
CSRF_TRUSTED_ORIGINS = os.environ.get(
    "CSRF_TRUSTED_ORIGINS", "http://localhost:3000,http://localhost:5173,http://localhost:8000"
).split(",")

ROOT_URLCONF = "config.urls"

# Minimal template engine — only used by Ninja's Swagger UI page.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {},
    }
]
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "argus"),
        "USER": os.environ.get("POSTGRES_USER", "argus"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "argus"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        # Native psycopg3 pool. Persistent connections must stay disabled
        # (CONN_MAX_AGE=0) when the pool is on; required under ASGI.
        "CONN_MAX_AGE": 0,
        "OPTIONS": {
            "pool": {"min_size": 2, "max_size": 10, "timeout": 10},
        },
    }
}

# Telemetry pipeline
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092")
KAFKA_EVENTS_TOPIC = os.environ.get("KAFKA_EVENTS_TOPIC", "inference_events")
KAFKA_DLQ_TOPIC = os.environ.get("KAFKA_DLQ_TOPIC", "inference_events.dlq")
KAFKA_EVENTS_PARTITIONS = int(os.environ.get("KAFKA_EVENTS_PARTITIONS", "8"))
KAFKA_CONSUMER_GROUP = os.environ.get("KAFKA_CONSUMER_GROUP", "argus-persister")

# Ingestion API auth (static single-project key; per-project keys are future work)
ARGUS_API_KEY = os.environ.get("ARGUS_API_KEY", "dev-argus-key")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

USE_TZ = True
TIME_ZONE = "UTC"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
