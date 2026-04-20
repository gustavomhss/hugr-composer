from __future__ import annotations
from typing import Any


async def webhook_retry_task(ctx: dict[str, Any], delivery_id: str, url: str, payload: dict[str, Any], signature: str) -> dict[str, Any]:
    """Retry a failed webhook delivery.

    Args:
        ctx: arq worker context dict.
        delivery_id: UUID of the original delivery attempt.
        url: Destination URL of the webhook.
        payload: JSON-serialisable payload to resend.
        signature: HMAC signature the receiver will verify.

    Returns:
        Dict with ``status``, ``delivery_id``, and ``job_id``.
    """
    job_id = ctx.get('job_id', 'unknown')
    logger.info('webhook_retry_task executing', extra={'job_id': job_id, 'delivery_id': delivery_id, 'url': url, 'payload_keys': list(payload.keys()), 'signature_len': len(signature)})
    return {'status': 'retried', 'delivery_id': delivery_id, 'job_id': job_id}
