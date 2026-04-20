from __future__ import annotations
from fastapi import HTTPException
import hashlib
import hmac
import json
import time


class StripeVerifier(InboundVerifier):
    """Verify Stripe webhook payloads using the ``Stripe-Signature`` header."""
    name = 'stripe'

    def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
        """Verify a Stripe-signed webhook request.

        Raises:
            HTTPException(401): If ``stripe-signature`` header is missing.
            HTTPException(400): If the timestamp is out of tolerance or the
                HMAC does not match.
        """
        sig_header = headers.get('stripe-signature')
        if not sig_header:
            raise HTTPException(401, 'Missing Stripe-Signature header')
        parts = dict((p.split('=', 1) for p in sig_header.split(',') if '=' in p))
        try:
            ts = int(parts.get('t', 0))
        except ValueError:
            raise HTTPException(400, 'Invalid Stripe signature timestamp')
        if abs(int(time.time()) - ts) > _TOLERANCE:
            raise HTTPException(400, 'Stripe signature timestamp out of tolerance')
        from app.core.config import settings as _settings
        secret = getattr(_settings, 'STRIPE_WEBHOOK_SECRET', '')
        signed_payload = f'{ts}.'.encode('ascii') + body
        expected = hmac.new(secret.encode('utf-8'), signed_payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, parts.get('v1', '')):
            raise HTTPException(400, 'Stripe signature mismatch')
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(400, 'Invalid JSON body')
        return VerifiedEvent(provider='stripe', event_id=event.get('id', ''), event_type=event.get('type', 'unknown'), payload=event)
