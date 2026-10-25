"""Disposable, loopback-only PostgreSQL settings for the signature tests.

The test runner creates and destroys exactly the unique database supplied by
this task. No existing application database or production settings are read.
"""
import os
import re

from edilcloud.settings.test import *  # noqa: F403

_database = os.environ.get("ELABORATI_SIGNATURE_TEST_DATABASE", "")
if not re.fullmatch(r"edilcloud_rust_native_sig_[0-9a-f]{12}", _database):
    raise RuntimeError("A unique disposable signature test database is required.")

DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": _database,
    "USER": "edilcloud_rust_parity",
    "PASSWORD": "local-parity-only",
    "HOST": "127.0.0.1",
    "PORT": "55432",
    "CONN_MAX_AGE": 0,
    "TEST": {"NAME": _database},
}}
