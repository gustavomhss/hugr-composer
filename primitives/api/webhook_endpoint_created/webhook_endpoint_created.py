"""Webhook endpoint created event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import uuid

@dataclass
class WebhookEndpointCreated:
    """Event fired when a webhook endpoint is created."""
    endpoint_id: uuid.UUID
    url: str
    events: list[str]
    created_at: datetime = None
