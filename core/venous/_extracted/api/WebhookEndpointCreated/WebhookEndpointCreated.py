from __future__ import annotations


class WebhookEndpointCreated(WebhookEndpointPublic):
    """Extends the public schema with the signing secret.

    The ``secret`` is included exactly once — in the create response.
    Subsequent reads use ``WebhookEndpointPublic`` which omits it.

    Attributes:
        secret: HMAC signing secret for verifying delivery signatures.
    """
    secret: str
