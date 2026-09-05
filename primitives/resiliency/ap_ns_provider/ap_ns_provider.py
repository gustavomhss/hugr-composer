"""Pure Python primitive: ApNsProvider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class APNsProvider:
    """Send push notifications via APNs (Apple Push Notification service)."""

    async def send(self, *, token: str, title: str, body: str, data: dict | None=None) -> bool:
        """Send a notification to a single iOS device token.

        Args:
            token: APNs device token (hex string).
            title: Notification title.
            body: Notification body.
            data: Optional custom data dict merged into the APNs payload.

        Returns:
            ``True`` on success, ``False`` when APNs is unavailable.
        """
        try:
            from apns2.client import APNsClient
            from apns2.payload import Payload, PayloadAlert
        except ImportError:
            logger.warning('apns2 not installed — APNs unavailable. pip install apns2')
            return False
        try:
            from app.core.config import settings
            if not settings.APNS_KEY_PATH:
                logger.warning('APNS_KEY_PATH not set — APNs unavailable.')
                return False
            client = APNsClient(credentials=settings.APNS_KEY_PATH, use_sandbox=settings.ENVIRONMENT != 'production', use_alternative_port=False)
            alert = PayloadAlert(title=title, body=body)
            payload = Payload(alert=alert, custom=data or {})
            client.send_notification(token_hex=token, notification=payload, topic=settings.APNS_BUNDLE_ID)
            return True
        except Exception as exc:
            logger.warning('APNs send failed: %s', exc)
            return False
