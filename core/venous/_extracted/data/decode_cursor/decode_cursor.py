from __future__ import annotations
from typing import Any
import base64
import json


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode a cursor string back to ``{field, value, id?}``.

    Args:
        cursor: Opaque cursor string from a previous response.

    Returns:
        Dict with keys ``field``, ``value``, and optionally ``id``.

    Raises:
        ValueError: On bad base64, invalid JSON, wrong structure,
            oversized input, or missing required keys.
    """
    if len(cursor.encode('utf-8')) > _MAX_CURSOR_BYTES:
        raise ValueError(f'Cursor exceeds maximum size ({_MAX_CURSOR_BYTES} bytes)')
    try:
        padding_needed = (4 - len(cursor) % 4) % 4
        padded = cursor + '=' * padding_needed
        raw = base64.urlsafe_b64decode(padded.encode('ascii'))
        data = json.loads(raw)
        if not isinstance(data, dict) or 'f' not in data or 'v' not in data:
            raise ValueError("Invalid cursor structure: missing 'f' or 'v' keys")
        return {'field': data['f'], 'value': data['v'], 'id': data.get('id')}
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f'Malformed cursor: {exc}') from exc
