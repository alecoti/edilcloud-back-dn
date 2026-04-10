from edilcloud.settings.base import *  # noqa: F403,F401

DEBUG = True

try:
    import debug_toolbar  # noqa: F401
except ImportError:
    debug_toolbar = None
else:
    INSTALLED_APPS += ["debug_toolbar", "django_extensions"]  # noqa: F405
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405
    INTERNAL_IPS = ["127.0.0.1", "localhost"]
