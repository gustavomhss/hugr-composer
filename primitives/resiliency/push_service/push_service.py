"""Pure Python primitive: PushService."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class PushService:
    """Deliver push notifications to individual devices or FCM topics."""

    async def send_to_device(self, *, token: str, platform: str, title: str, body: str, data: dict | None=None) -> bool:
        """Send a push notification to a single device token.

        Args:
            token: Platform-specific device push token.
            platform: ``"ios"`` (uses APNs) or ``"android"`` (uses FCM).
            title: Notification title.
            body: Notification body text.
            data: Optional key-value data payload.

        Returns:
            ``True`` when the provider accepted the message.
        """
        if platform == 'ios':
            from app.push.providers.apns import APNsProvider
            provider = APNsProvider()
            return await provider.send(token=token, title=title, body=body, data=data)
        if platform == 'android':
            from app.push.providers.fcm import FCMProvider
            provider = FCMProvider()
            return await provider.send_to_device(token=token, title=title, body=body, data=data)
        logger.warning('PushService: unknown platform %r — skipping.', platform)
        return False

    async def send_to_topic(self, *, topic: str, title: str, body: str, data: dict | None=None) -> bool:
        """Broadcast a push notification to an FCM topic.

        Args:
            topic: FCM topic name (without the ``/topics/`` prefix).
            title: Notification title.
            body: Notification body text.
            data: Optional key-value data payload.

        Returns:
            ``True`` when FCM accepted the message.
        """
        from app.push.providers.fcm import FCMProvider
        provider = FCMProvider()
        return await provider.send_to_topic(topic=topic, title=title, body=body, data=data)
