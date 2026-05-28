from __future__ import annotations
from fastapi import HTTPException
import json


class InternalVerifier(InboundVerifier):
    """Verify internal (sister-service) webhook payloads."""
    name = 'internal'

    @staticmethod
    def _check_hmac_signature(secret: str, body: bytes, sig: str) -> None:
        """Verify an inline HMAC-SHA256 ``t=<ts>,v1=<hex>`` signature.

        Args:
            secret: Shared HMAC secret string.
            body: Raw request body bytes.
            sig: Raw ``X-Signature`` header value.

        Raises:
            HTTPException(400): Invalid timestamp, timestamp drift > 300 s, or mismatch.
        """
        import hashlib
        import hmac
        import time
        parts = dict((p.split('=', 1) for p in sig.split(',') if '=' in p))
        try:
            ts = int(parts.get('t', 0))
        except ValueError:
            raise HTTPException(400, 'Invalid X-Signature timestamp')
        if abs(int(time.time()) - ts) > 300:
            raise HTTPException(400, 'X-Signature timestamp out of tolerance')
        expected = hmac.new(secret.encode('utf-8'), f'{ts}.'.encode('utf-8') + body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, parts.get('v1', '')):
            raise HTTPException(400, 'Internal signature mismatch')

    def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
        """Verify an internally-signed webhook request.

        Args:
            body: Raw request body bytes.
            headers: Lowercased request headers dict.

        Returns:
            A ``VerifiedEvent`` with the parsed payload.

        Raises:
            HTTPException(401): If the ``x-signature`` header is missing.
            HTTPException(400): If signature invalid or body is invalid JSON.
        """
        sig = headers.get('x-signature')
        if not sig:
            raise HTTPException(401, 'Missing X-Signature header')
        from app.core.config import settings as _settings
        secret = getattr(_settings, 'INTERNAL_WEBHOOK_SECRET', '')
        try:
            from app.core.webhooks.signer import verify_signature
            if not verify_signature(secret, body, sig):
                raise HTTPException(400, 'Internal signature mismatch')
        except ImportError:
            self._check_hmac_signature(secret, body, sig)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(400, 'Invalid JSON body')
        event_id = headers.get('x-event-id')
        if not event_id:
            raise HTTPException(400, 'Missing X-Event-Id header')
        return VerifiedEvent(provider='internal', event_id=event_id, event_type=headers.get('x-event-type', 'unknown'), payload=payload)
