"""ASGI websocket routes for the realtime layer."""

from django.urls import path

from edilcloud.platform.realtime.consumers import (
    NotificationRealtimeConsumer,
    ProjectRealtimeConsumer,
)


websocket_urlpatterns = [
    path("ws/realtime/notifications/", NotificationRealtimeConsumer.as_asgi()),
    path("ws/realtime/projects/<int:project_id>/", ProjectRealtimeConsumer.as_asgi()),
]
