"""CI database matches production PostgreSQL, with test-only credentials."""
from edilcloud.settings.test import *  # noqa: F403,F401

DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "edilcloud_ci",
    "USER": "edilcloud_ci",
    "PASSWORD": "ci-only-disposable",
    "HOST": "127.0.0.1",
    "PORT": "5432",
    "CONN_MAX_AGE": 0,
}}
