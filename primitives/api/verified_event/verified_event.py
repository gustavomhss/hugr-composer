from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class VerifiedEvent:
    """Value object returned by a successful verification.

    Attributes:
        provider: Provider name string (e.g. ``"stripe"``).
        event_id: Provider-assigned event identifier.
        event_type: Provider event type string.
        payload: Parsed JSON event payload dict.
    """
    provider: str
    event_id: str
    event_type: str
    payload: dict
