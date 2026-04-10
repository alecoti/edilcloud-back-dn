import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "edilcloud.settings.local")

django_asgi_application = get_asgi_application()

# Import websocket routes only after Django app loading is complete.
from edilcloud.platform.realtime.routing import websocket_urlpatterns

application = ProtocolTypeRouter(
    {
        "http": django_asgi_application,
        "websocket": URLRouter(websocket_urlpatterns),
    }
)
