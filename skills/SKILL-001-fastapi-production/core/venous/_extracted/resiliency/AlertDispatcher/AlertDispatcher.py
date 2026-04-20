from __future__ import annotations
import json


class AlertDispatcher:
    """Dispatch anomaly alerts to configured channels.

    Args:
        webhook_url: Optional HTTP webhook URL for POST alerts.
    """

    def __init__(self, webhook_url: str | None=None) -> None:
        self.webhook_url = webhook_url

    async def dispatch(self, anomaly: dict) -> None:
        """Dispatch a single anomaly alert.

        Logs at WARNING level always.  If ``webhook_url`` is configured,
        also POSTs the anomaly JSON via httpx (lazy import).

        Args:
            anomaly: Anomaly dict with metric, value, z_score, ts.
        """
        logger.warning('Anomaly detected: metric=%s value=%s z_score=%s', anomaly.get('metric'), anomaly.get('value'), anomaly.get('z_score'))
        if not self.webhook_url:
            return
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.post(self.webhook_url, content=json.dumps(anomaly).encode(), headers={'Content-Type': 'application/json'})
        except Exception:
            logger.warning('AlertDispatcher webhook failed: url=%s', self.webhook_url, exc_info=True)
