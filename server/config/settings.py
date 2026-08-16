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
    "django.contrib.postgres",
    "apps.chat",
    "apps.telemetry",
    "apps.insights",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    # NOTE: no GZipMiddleware — it buffers streaming responses and would
    # silently break the SSE endpoints (chat streaming + live tail).
]

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
