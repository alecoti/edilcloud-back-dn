from pathlib import Path

from edilcloud.settings.base import *  # noqa: F403,F401

DEBUG = False
SECRET_KEY = "test-secret-key-with-at-least-thirty-two-characters"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(Path(BASE_DIR) / "test.sqlite3"),  # noqa: F405
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
EMAIL_DELIVERY_MODE = "sync"
# Existing localization tests assert deterministic synchronous translation.
# Background delivery has separate tests with this overridden to True.
PROJECT_CONTENT_TRANSLATION_ASYNC = False
# Tests must explicitly opt in and mock providers; a developer .env must never
# turn regression tests into billable network calls.
OPENAI_API_KEY = ""
GOOGLE_WEATHER_API_KEY = ""

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "edilcloud-back-dn-test-cache",
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}
