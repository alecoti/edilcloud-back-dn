"""Websocket consumers for realtime notification and project channels."""

from __future__ import annotations

from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from edilcloud.platform.realtime.services import (
    notification_group_name,
    notification_user_group_name,
    project_group_name,
    validate_realtime_ticket,
)


class BaseRealtimeConsumer(AsyncJsonWebsocketConsumer):
    group_names: list[str]

    async def accept_with_ticket(self, *, channel: str, project_id: int | None = None) -> None:
        ticket = self._get_ticket()
        try:
            payload = await sync_to_async(validate_realtime_ticket)(
                ticket=ticket,
                expected_channel=channel,
                expected_project_id=project_id,
            )
        except ValueError:
            await self.close(code=4401)
            return

        self.group_names = self.resolve_group_names(payload)
        self.scope["realtime"] = payload
        for group_name in self.group_names:
            await self.channel_layer.group_add(group_name, self.channel_name)
        await self.accept()

    def _get_ticket(self) -> str:
        query_string = self.scope.get("query_string", b"").decode()
        query_params = parse_qs(query_string)
        return (query_params.get("ticket") or [""])[0].strip()

    def resolve_group_names(self, payload: dict) -> list[str]:
        raise NotImplementedError

    async def disconnect(self, close_code):
        for group_name in getattr(self, "group_names", []):
            await self.channel_layer.group_discard(group_name, self.channel_name)
        await super().disconnect(close_code)

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def realtime_event(self, event):
        await self.send_json(event["payload"])


class NotificationRealtimeConsumer(BaseRealtimeConsumer):
    async def connect(self):
        await self.accept_with_ticket(channel="notifications")

    def resolve_group_names(self, payload: dict) -> list[str]:
        user_id = payload.get("user_id")
        if isinstance(user_id, int) and user_id > 0:
            return [notification_user_group_name(user_id)]
        return [notification_group_name(int(payload["profile_id"]))]


class ProjectRealtimeConsumer(BaseRealtimeConsumer):
    async def connect(self):
        project_id = int(self.scope["url_route"]["kwargs"]["project_id"])
        await self.accept_with_ticket(channel="project", project_id=project_id)

    def resolve_group_names(self, payload: dict) -> list[str]:
        return [project_group_name(int(payload["project_id"]))]
