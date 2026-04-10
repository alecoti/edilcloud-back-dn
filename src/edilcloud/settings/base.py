from pathlib import Path

import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

from edilcloud.platform.config.env import get_bool_env, get_csv_env, get_env

BASE_DIR = Path(__file__).resolve().parents[3]

load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.local")

APP_ENV = get_env("APP_ENV", "local")
SECRET_KEY = get_env("SECRET_KEY", "change-me")
DEBUG = get_bool_env("DEBUG", False)
if APP_ENV in {"production", "prod"} and SECRET_KEY == "change-me":
    raise ImproperlyConfigured("SECRET_KEY must be configured when DEBUG is False.")

TIME_ZONE = get_env("TIME_ZONE", "Europe/Rome")
APP_VERSION = get_env("APP_VERSION", "0.1.0-dev")
ALLOWED_HOSTS = get_csv_env("ALLOWED_HOSTS", "localhost,127.0.0.1")
CORS_ALLOWED_ORIGINS = get_csv_env("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
CSRF_TRUSTED_ORIGINS = get_csv_env("CSRF_TRUSTED_ORIGINS", "http://localhost:3000")
CORS_ALLOW_CREDENTIALS = True
DATABASE_URL = get_env(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/edilcloud_dn",
)
REDIS_URL = get_env("REDIS_URL", "redis://localhost:6379/0")
SENTRY_DSN = get_env("SENTRY_DSN")
APP_FRONTEND_URL = get_env("APP_FRONTEND_URL", "http://localhost:3000").rstrip("/")
BACKEND_PUBLIC_URL = get_env("BACKEND_PUBLIC_URL", "http://localhost:8001").rstrip("/")
DEFAULT_FROM_EMAIL = get_env("DEFAULT_FROM_EMAIL", "no-reply@edilcloud.local")
SERVER_EMAIL = get_env("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
REGISTRATION_FROM_EMAIL = get_env("REGISTRATION_FROM_EMAIL", DEFAULT_FROM_EMAIL)
MARKETING_SITE_URL = get_env("MARKETING_SITE_URL", "http://localhost:3000").rstrip("/")
PAYMENTS_SITE_URL = get_env("PAYMENTS_SITE_URL", "http://localhost:3000/payments").rstrip("/")
EMAIL_BACKEND = get_env(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = get_env("EMAIL_HOST", "mail.edilcloud.io")
EMAIL_PORT = int(get_env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = get_env("EMAIL_HOST_USER", "notification@edilcloud.io")
EMAIL_HOST_PASSWORD = get_env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = get_bool_env("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = get_bool_env("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = int(get_env("EMAIL_TIMEOUT", "10"))
EMAIL_DELIVERY_MODE = get_env("EMAIL_DELIVERY_MODE", "threaded").strip().lower() or "threaded"
EMAIL_THREAD_POOL_SIZE = int(get_env("EMAIL_THREAD_POOL_SIZE", "2"))
GOOGLE_OAUTH_CLIENT_ID = get_env("GOOGLE_OAUTH_CLIENT_ID", "")
OPENAI_API_KEY = get_env("OPENAI_API_KEY", "")
OPENAI_API_BASE_URL = get_env("OPENAI_API_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_ASSISTANT_MODEL = get_env(
    "AI_ASSISTANT_MODEL",
    get_env("OPENAI_CHAT_MODEL", get_env("OPENAI_MODEL", "gpt-4o-mini")),
).strip() or "gpt-4o-mini"
AI_DRAFT_MODEL = get_env("AI_DRAFT_MODEL", AI_ASSISTANT_MODEL).strip() or AI_ASSISTANT_MODEL
PROJECT_CONTENT_TRANSLATION_MODEL = (
    get_env("PROJECT_CONTENT_TRANSLATION_MODEL", get_env("OPENAI_TRANSLATION_MODEL", "gpt-4o-mini")).strip()
    or "gpt-4o-mini"
)
AI_ASSISTANT_MONTHLY_TOKEN_LIMIT = int(get_env("AI_ASSISTANT_MONTHLY_TOKEN_LIMIT", "100000"))
AI_ASSISTANT_EMBEDDING_MODEL = get_env(
    "AI_ASSISTANT_EMBEDDING_MODEL",
    get_env("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"),
).strip() or "text-embedding-3-large"
AI_ASSISTANT_RETRIEVAL_TOP_K = int(get_env("AI_ASSISTANT_RETRIEVAL_TOP_K", "12"))
AI_ASSISTANT_CONTEXT_SOURCE_LIMIT = int(get_env("AI_ASSISTANT_CONTEXT_SOURCE_LIMIT", "8"))
AI_ASSISTANT_CHUNK_TARGET_CHARS = int(get_env("AI_ASSISTANT_CHUNK_TARGET_CHARS", "1100"))
AI_ASSISTANT_CHUNK_OVERLAP_CHARS = int(get_env("AI_ASSISTANT_CHUNK_OVERLAP_CHARS", "180"))
AI_ASSISTANT_MAX_CHUNKS_PER_SOURCE = int(get_env("AI_ASSISTANT_MAX_CHUNKS_PER_SOURCE", "24"))
AI_ASSISTANT_EMBEDDING_BATCH_SIZE = int(get_env("AI_ASSISTANT_EMBEDDING_BATCH_SIZE", "16"))
AI_ASSISTANT_EMBEDDING_CACHE_TTL_SECONDS = int(
    get_env("AI_ASSISTANT_EMBEDDING_CACHE_TTL_SECONDS", "86400")
)
AI_ASSISTANT_EMBEDDING_DIMENSIONS = int(get_env("AI_ASSISTANT_EMBEDDING_DIMENSIONS", "3072"))
if AI_ASSISTANT_EMBEDDING_DIMENSIONS <= 0:
    raise ImproperlyConfigured("AI_ASSISTANT_EMBEDDING_DIMENSIONS must be a positive integer.")
if AI_ASSISTANT_EMBEDDING_MODEL == "text-embedding-3-small" and AI_ASSISTANT_EMBEDDING_DIMENSIONS > 1536:
    raise ImproperlyConfigured(
        "AI_ASSISTANT_EMBEDDING_DIMENSIONS cannot exceed 1536 for text-embedding-3-small."
    )
if AI_ASSISTANT_EMBEDDING_MODEL == "text-embedding-3-large" and AI_ASSISTANT_EMBEDDING_DIMENSIONS > 3072:
    raise ImproperlyConfigured(
        "AI_ASSISTANT_EMBEDDING_DIMENSIONS cannot exceed 3072 for text-embedding-3-large."
    )
ASSISTANT_INDEXER_POLL_SECONDS = float(get_env("ASSISTANT_INDEXER_POLL_SECONDS", "10"))
ASSISTANT_INDEXER_BATCH_SIZE = int(get_env("ASSISTANT_INDEXER_BATCH_SIZE", "4"))
GEOCODING_PROVIDER = get_env("GEOCODING_PROVIDER", "nominatim").strip().lower() or "nominatim"
GEOCODING_TIMEOUT_SECONDS = float(get_env("GEOCODING_TIMEOUT_SECONDS", "4"))
GEOCODING_USER_AGENT = get_env("GEOCODING_USER_AGENT", f"EdilCloud/{APP_VERSION} (local-dev geocoding)").strip()
GEOCODING_NOMINATIM_URL = get_env(
    "GEOCODING_NOMINATIM_URL",
    "https://nominatim.openstreetmap.org/search",
).rstrip("/")
STRIPE_SECRET_KEY = get_env("STRIPE_SECRET_KEY", "").strip()
STRIPE_PUBLISHABLE_KEY = get_env("STRIPE_PUBLISHABLE_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = get_env("STRIPE_WEBHOOK_SECRET", "").strip()
STRIPE_API_VERSION = get_env("STRIPE_API_VERSION", "2026-02-25.clover").strip() or "2026-02-25.clover"
STRIPE_PRICE_PLAN_FONDAZIONI_MONTHLY = get_env("STRIPE_PRICE_PLAN_FONDAZIONI_MONTHLY", "").strip()
STRIPE_PRICE_PLAN_FONDAZIONI_YEARLY = get_env("STRIPE_PRICE_PLAN_FONDAZIONI_YEARLY", "").strip()
STRIPE_PRICE_PLAN_STRUTTURA_MONTHLY = get_env("STRIPE_PRICE_PLAN_STRUTTURA_MONTHLY", "").strip()
STRIPE_PRICE_PLAN_STRUTTURA_YEARLY = get_env("STRIPE_PRICE_PLAN_STRUTTURA_YEARLY", "").strip()
STRIPE_PRICE_PLAN_DIREZIONE_LAVORI_MONTHLY = get_env("STRIPE_PRICE_PLAN_DIREZIONE_LAVORI_MONTHLY", "").strip()
STRIPE_PRICE_PLAN_DIREZIONE_LAVORI_YEARLY = get_env("STRIPE_PRICE_PLAN_DIREZIONE_LAVORI_YEARLY", "").strip()
STRIPE_PRICE_ADDON_WORKSPACE_MONTHLY = get_env("STRIPE_PRICE_ADDON_WORKSPACE_MONTHLY", "").strip()
STRIPE_PRICE_ADDON_WORKSPACE_YEARLY = get_env("STRIPE_PRICE_ADDON_WORKSPACE_YEARLY", "").strip()
STRIPE_PRICE_ADDON_SEAT_MONTHLY = get_env("STRIPE_PRICE_ADDON_SEAT_MONTHLY", "").strip()
STRIPE_PRICE_ADDON_SEAT_YEARLY = get_env("STRIPE_PRICE_ADDON_SEAT_YEARLY", "").strip()
STRIPE_PRICE_ADDON_STORAGE_100GB_MONTHLY = get_env("STRIPE_PRICE_ADDON_STORAGE_100GB_MONTHLY", "").strip()
STRIPE_PRICE_ADDON_STORAGE_100GB_YEARLY = get_env("STRIPE_PRICE_ADDON_STORAGE_100GB_YEARLY", "").strip()
STRIPE_PRICE_AI_PACK_1M = get_env("STRIPE_PRICE_AI_PACK_1M", "").strip()
STRIPE_PRICE_AI_PACK_5M = get_env("STRIPE_PRICE_AI_PACK_5M", "").strip()
STRIPE_PRICE_AI_PACK_20M = get_env("STRIPE_PRICE_AI_PACK_20M", "").strip()
LOG_LEVEL = get_env("LOG_LEVEL", "INFO").strip().upper() or "INFO"
LOG_FORMAT = get_env("LOG_FORMAT", "console").strip().lower() or "console"
PROJECT_ARCHIVE_AFTER_DAYS = int(get_env("PROJECT_ARCHIVE_AFTER_DAYS", "365"))
PROJECT_PURGE_AFTER_ARCHIVE_DAYS = int(get_env("PROJECT_PURGE_AFTER_ARCHIVE_DAYS", "180"))

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "corsheaders",
    "edilcloud.modules.assistant",
    "edilcloud.modules.billing",
    "edilcloud.modules.identity",
    "edilcloud.modules.notifications",
    "edilcloud.modules.projects",
    "edilcloud.modules.workspaces",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "edilcloud.platform.middleware.request_context.RequestContextMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "edilcloud.urls"
WSGI_APPLICATION = "edilcloud.wsgi.application"
ASGI_APPLICATION = "edilcloud.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_health_checks=True,
        conn_max_age=60,
    )
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": get_env("CACHE_KEY_PREFIX", "edilcloud-dn"),
        "TIMEOUT": int(get_env("CACHE_DEFAULT_TIMEOUT_SECONDS", "300")),
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
            "capacity": int(get_env("REALTIME_CHANNEL_CAPACITY", "1500")),
            "expiry": int(get_env("REALTIME_CHANNEL_EXPIRY_SECONDS", "60")),
        },
    }
}

LANGUAGE_CODE = "it"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "identity.User"
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

AUTH_ACCESS_TOKEN_TTL_SECONDS = int(get_env("AUTH_ACCESS_TOKEN_TTL_SECONDS", str(15 * 60)))
AUTH_REFRESH_TOKEN_TTL_SECONDS = int(get_env("AUTH_REFRESH_TOKEN_TTL_SECONDS", str(60 * 60 * 24 * 30)))
AUTH_ACCESS_CODE_TTL_SECONDS = int(get_env("AUTH_ACCESS_CODE_TTL_SECONDS", str(10 * 60)))
AUTH_ONBOARDING_SESSION_TTL_SECONDS = int(get_env("AUTH_ONBOARDING_SESSION_TTL_SECONDS", str(30 * 60)))
AUTH_ACCESS_CODE_RESEND_COOLDOWN_SECONDS = int(
    get_env("AUTH_ACCESS_CODE_RESEND_COOLDOWN_SECONDS", "60")
)
AUTH_ACCESS_CODE_MAX_ATTEMPTS = int(get_env("AUTH_ACCESS_CODE_MAX_ATTEMPTS", "5"))
AUTH_PASSWORD_RESET_TTL_SECONDS = int(get_env("AUTH_PASSWORD_RESET_TTL_SECONDS", str(15 * 60)))
AUTH_PASSWORD_RESET_MAX_ATTEMPTS = int(get_env("AUTH_PASSWORD_RESET_MAX_ATTEMPTS", "5"))
AUTH_PASSWORD_RESET_RESEND_COOLDOWN_SECONDS = int(
    get_env("AUTH_PASSWORD_RESET_RESEND_COOLDOWN_SECONDS", "60")
)
AUTH_TOKEN_ISSUER = get_env("AUTH_TOKEN_ISSUER", "edilcloud-back-dn")
AUTH_TOKEN_AUDIENCE = get_env("AUTH_TOKEN_AUDIENCE", "edilcloud-web")
AUTH_REFRESH_TOKEN_AUDIENCE = get_env("AUTH_REFRESH_TOKEN_AUDIENCE", "edilcloud-web-refresh")
AUTH_INCLUDE_DEBUG_CODES = get_bool_env("AUTH_INCLUDE_DEBUG_CODES", False)
ENABLE_DEV_BOOTSTRAP_AUTH = get_bool_env("ENABLE_DEV_BOOTSTRAP_AUTH", False)
REALTIME_TICKET_TTL_SECONDS = int(get_env("REALTIME_TICKET_TTL_SECONDS", "90"))

SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_RESOURCE_POLICY = "same-site"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_NAME = "edilcloud_sessionid"
CSRF_COOKIE_NAME = "edilcloud_csrftoken"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = False

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {
            "()": "edilcloud.platform.logging.RequestIDFilter",
        }
    },
    "formatters": {
        "console": {
            "format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S%z",
        },
        "json": {
            "()": "edilcloud.platform.logging.JsonFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_id"],
            "formatter": "json" if LOG_FORMAT == "json" else "console",
        }
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "edilcloud": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
}
