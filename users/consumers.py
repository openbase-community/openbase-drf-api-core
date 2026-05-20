import json

import structlog
from channels.generic.websocket import AsyncWebsocketConsumer

logger = structlog.get_logger(__name__)


class UserEventsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]

        from django.contrib.auth.models import AnonymousUser  # noqa: PLC0415

        if isinstance(self.user, AnonymousUser):
            await self.close()
            return

        self.user_group_name = f"user_{self.user.id}"

        await self.channel_layer.group_add(self.user_group_name, self.channel_name)

        await self.accept()
        logger.info("WebSocket connected", user_id=self.user.id)

    async def disconnect(self, code):
        if hasattr(self, "user_group_name"):
            await self.channel_layer.group_discard(
                self.user_group_name, self.channel_name
            )
            logger.info("WebSocket disconnected", user_id=self.user.id)

    async def receive(self, text_data=None, bytes_data=None):
        pass

    async def user_event(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": event.get("event_type", "message"),
                    "data": event.get("data", {}),
                }
            )
        )
