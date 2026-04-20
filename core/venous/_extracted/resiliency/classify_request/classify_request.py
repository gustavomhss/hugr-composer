from __future__ import annotations


def classify_request(path: str, method: str='GET') -> RequestPriority:
    """Classify a request into a priority tier based on path and method.

    CRITICAL paths always return CRITICAL regardless of load.
    LOW paths are shed first under high load.

    Args:
        path: URL path of the incoming request.
        method: HTTP method (unused currently, reserved for future use).

    Returns:
        ``RequestPriority`` tier for this request.
    """
    for prefix in _CRITICAL_PREFIXES:
        if path.startswith(prefix):
            return RequestPriority.CRITICAL
    for prefix in _LOW_PREFIXES:
        if path.startswith(prefix):
            return RequestPriority.LOW
    for prefix in _HIGH_PREFIXES:
        if path.startswith(prefix):
            return RequestPriority.HIGH
    return RequestPriority.NORMAL
