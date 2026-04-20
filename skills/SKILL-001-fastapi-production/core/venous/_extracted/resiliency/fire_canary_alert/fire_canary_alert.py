from __future__ import annotations
from typing import Any
import asyncio
import json
import time


def fire_canary_alert(token_id: str, request_context: dict[str, Any], webhook_url: str) -> None:
    """Dispatch a canary alert in a background thread — never blocks.

    Args:
        token_id: The canary token that was triggered.
        request_context: Dict with method, path, headers, client_ip, etc.
        webhook_url: URL to POST the alert to.
    """
    if not webhook_url:
        logger.warning('canary_alert: CANARY_ALERT_WEBHOOK_URL not set, logging only')
        logger.critical('CANARY_TRIGGERED token_id=%s context=%s', token_id, json.dumps(request_context))
        return
    payload = {'event': 'canary_triggered', 'token_id': token_id, 'timestamp': int(time.time()), 'request': request_context}
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_post_webhook(webhook_url, payload))
        else:
            asyncio.run(_post_webhook(webhook_url, payload))
    except Exception as exc:
        logger.error('canary_alert: dispatch error: %s', exc)
