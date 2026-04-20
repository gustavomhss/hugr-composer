from __future__ import annotations
from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import UUID
import base64
import json


def encode_cursor(field: str, value: Any, tiebreaker_id: str | None=None) -> str:
    """Encode a sort key into a URL-safe base64 cursor string.

    Supports: datetime (ISO-8601 UTC), UUID (str), int, float, str.
    Includes optional tiebreaker_id (record UUID) for composite cursors.

    Args:
        field: Name of the sort column (e.g. ``"created_at"``).
        value: Value of the sort column for the last item on the page.
        tiebreaker_id: Optional record UUID to stabilise ties.

    Returns:
        URL-safe base64url string with no padding characters.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        serialized: Any = value.isoformat()
    elif isinstance(value, UUID):
        serialized = str(value)
    else:
        serialized = value
    payload: dict[str, Any] = {'f': field, 'v': serialized}
    if tiebreaker_id is not None:
        payload['id'] = tiebreaker_id
    raw = json.dumps(payload, separators=(',', ':'))
    return base64.urlsafe_b64encode(raw.encode('utf-8')).decode('ascii').rstrip('=')
