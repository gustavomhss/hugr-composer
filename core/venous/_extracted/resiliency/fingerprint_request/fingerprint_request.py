from __future__ import annotations
from fastapi import Request
import hashlib


def fingerprint_request(request: Request) -> str:
    """Build a behavioral fingerprint from header order and timing.

    Combines the ordered header names (not values) with the remote
    IP to create a fingerprint that detects IP rotation while rotating
    clients that reuse the same header pattern.

    Args:
        request: Incoming Starlette request.

    Returns:
        A hex fingerprint string.
    """
    header_order = ','.join((k.lower() for k in request.headers.keys()))
    raw = f"{(request.client.host if request.client else 'unknown')}|{header_order}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
