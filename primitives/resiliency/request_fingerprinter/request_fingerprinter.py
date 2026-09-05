"""Pure Python primitive: RequestFingerprinter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class RequestFingerprinter:
    """Compute a deterministic SHA-256 fingerprint for an HTTP request.

    The fingerprint is designed to be:
    - Deterministic: same input always produces same hash.
    - Collision-resistant: body key order does not matter.
    - User-isolated: different users always get different fingerprints.
    """

    def compute(self, user_id: str | None, method: str, path: str, body: bytes | str) -> str:
        """Compute a 64-char hex fingerprint.

        Args:
            user_id: Authenticated user identifier, or "anonymous".
            method: HTTP method (uppercase, e.g. "POST").
            path: Full request path including query string.
            body: Raw request body bytes or string.

        Returns:
            64-character lowercase hex SHA-256 digest.
        """
        uid = user_id or 'anonymous'
        norm_body = self._normalize_body(body)
        raw = f'{uid}:{method.upper()}:{path}:{norm_body}'
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def _normalize_body(self, body: bytes | str) -> str:
        """Normalize body to a canonical string for hashing.

        JSON bodies are parsed and re-serialised with sorted keys so that
        ``{"b":1,"a":2}`` and ``{"a":2,"b":1}`` produce the same hash.

        Args:
            body: Raw body bytes or string.

        Returns:
            Canonical string representation.
        """
        if isinstance(body, bytes):
            text = body.decode('utf-8', errors='replace')
        else:
            text = body
        if not text:
            return ''
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return json.dumps(obj, sort_keys=True, separators=(',', ':'))
            return json.dumps(obj, separators=(',', ':'))
        except Exception:
            return text
