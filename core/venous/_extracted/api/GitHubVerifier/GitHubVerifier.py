from __future__ import annotations
from fastapi import HTTPException
import hashlib
import hmac
import json


class GitHubVerifier(InboundVerifier):
    """Verify GitHub webhook payloads using ``X-Hub-Signature-256``."""
    name = 'github'

    def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
        """Verify a GitHub-signed webhook request.

        Args:
            body: Raw request body bytes.
            headers: Lowercased request headers dict.

        Returns:
            A ``VerifiedEvent`` containing the parsed GitHub event.

        Raises:
            HTTPException(401): If the signature or delivery-id header is absent.
            HTTPException(400): If the HMAC does not match or the body is invalid JSON.
        """
        sig_header = headers.get('x-hub-signature-256', '')
        if not sig_header or not sig_header.startswith('sha256='):
            raise HTTPException(401, 'Missing X-Hub-Signature-256 header')
        from app.core.config import settings as _settings
        secret = getattr(_settings, 'GITHUB_WEBHOOK_SECRET', '')
        expected = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(f'sha256={expected}', sig_header):
            raise HTTPException(400, 'GitHub signature mismatch')
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(400, 'Invalid JSON body')
        delivery_id = headers.get('x-github-delivery')
        if not delivery_id:
            raise HTTPException(400, 'Missing X-GitHub-Delivery header')
        event_type = headers.get('x-github-event', 'unknown')
        return VerifiedEvent(provider='github', event_id=delivery_id, event_type=event_type, payload=event)
