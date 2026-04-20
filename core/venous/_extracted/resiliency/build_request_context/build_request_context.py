from __future__ import annotations
from typing import Any


def build_request_context(method: str, path: str, client_ip: str, headers: dict[str, str], query: str='') -> dict[str, Any]:
    """Build a sanitised request context dict for the alert payload.

    Args:
        method: HTTP method.
        path: Request path.
        client_ip: Client IP address.
        headers: Lowercase request headers (sensitive values masked).
        query: Query string.

    Returns:
        Sanitised context dict suitable for JSON serialisation.
    """
    _MASK_HEADERS = frozenset({'authorization', 'cookie', 'x-api-key'})
    safe_headers = {k: '***' if k in _MASK_HEADERS else v for k, v in headers.items()}
    return {'method': method, 'path': path, 'query': query, 'client_ip': client_ip, 'headers': safe_headers}
