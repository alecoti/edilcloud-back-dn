from edilcloud.settings.base import *  # noqa: F403,F401
from edilcloud.platform.config.env import get_bool_env
from corsheaders.defaults import default_headers

DEBUG = True

# Native clients send these too; Flutter Web must be allowed to preflight them.
CORS_ALLOW_HEADERS = (
    *default_headers,
    "x-edilcloud-locale",
    "x-edilcloud-client-mutation-id",
)

# Temporarily allow local AI testing beyond the quota; usage accounting stays active.
AI_TOKEN_QUOTA_ENFORCED = get_bool_env("AI_TOKEN_QUOTA_ENFORCED", False)

try:
    import debug_toolbar  # noqa: F401
except ImportError:
    debug_toolbar = None
else:
    INSTALLED_APPS += ["debug_toolbar", "django_extensions"]  # noqa: F405
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405
    INTERNAL_IPS = ["127.0.0.1", "localhost"]
