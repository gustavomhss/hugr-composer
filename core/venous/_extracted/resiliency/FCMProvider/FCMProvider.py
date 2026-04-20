from __future__ import annotations


class FCMProvider:
    """Send push notifications via FCM."""

    async def send_to_device(self, *, token: str, title: str, body: str, data: dict | None=None) -> bool:
        """Send a notification to a single device token.

        Args:
            token: FCM registration token.
            title: Notification title.
            body: Notification body.
            data: Optional string key-value data payload.

        Returns:
            ``True`` on success, ``False`` when FCM is unavailable.
        """
        if not _init_firebase():
            return False
        try:
            from firebase_admin import messaging
            msg = messaging.Message(notification=messaging.Notification(title=title, body=body), data={k: str(v) for k, v in (data or {}).items()}, token=token)
            messaging.send(msg)
            return True
        except Exception as exc:
            logger.warning('FCM send_to_device failed: %s', exc)
            return False

    async def send_to_topic(self, *, topic: str, title: str, body: str, data: dict | None=None) -> bool:
        """Broadcast a notification to an FCM topic.

        Args:
            topic: FCM topic name (without /topics/ prefix).
            title: Notification title.
            body: Notification body.
            data: Optional string key-value data payload.

        Returns:
            ``True`` on success, ``False`` when FCM is unavailable.
        """
        if not _init_firebase():
            return False
        try:
            from firebase_admin import messaging
            msg = messaging.Message(notification=messaging.Notification(title=title, body=body), data={k: str(v) for k, v in (data or {}).items()}, topic=topic)
            messaging.send(msg)
            return True
        except Exception as exc:
            logger.warning('FCM send_to_topic failed: %s', exc)
            return False
