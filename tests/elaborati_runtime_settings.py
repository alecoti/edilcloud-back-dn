"""Local, disposable Elaborati integration environment; never production settings."""
import os
from pathlib import Path
import re

from edilcloud.settings.test import *  # noqa: F403

_database = os.environ.get("ELABORATI_RUNTIME_DATABASE", "")
if not re.fullmatch(r"edilcloud_elaborati_qa_[0-9a-f]{12}", _database):
    raise RuntimeError("An explicitly owned disposable Elaborati database is required.")

DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": _database,
    "USER": "edilcloud_rust_parity",
    "PASSWORD": "local-parity-only",
    "HOST": "127.0.0.1",
    "PORT": "55432",
    "CONN_MAX_AGE": 0,
}}
_runtime = Path(__file__).resolve().parents[2] / "runtime"
PRIVATE_STORAGE_ROOT = _runtime / "private"
MEDIA_ROOT = _runtime / "media"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
AI_TOKEN_QUOTA_ENFORCED = False
ELABORATI_WORKFLOW_VERSION = "v1"
ELABORATI_CHROMIUM_EXECUTABLE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OPENAI_API_KEY = ""
OPENAI_BASE_URL = "http://127.0.0.1:9/v1"
OPENAI_API_BASE_URL = "http://127.0.0.1:9/v1"
GOOGLE_WEATHER_API_KEY = ""
GOOGLE_MAPS_API_KEY = ""
CORS_ALLOW_ALL_ORIGINS = True
