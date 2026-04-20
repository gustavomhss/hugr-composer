from __future__ import annotations


def record_error(method: str, path: str, status_code: int) -> None:
    """Increment the error counter for a 5xx response.

    Args:
        method: HTTP method.
        path: Request path.
        status_code: HTTP status code (expected 5xx).
    """
    _ensure_instruments()
    if _error_counter is not None:
        _error_counter.add(1, {'http.method': method, 'http.route': path, 'http.status_code': status_code})
    if status_code >= 500:
        logger.warning('5xx error recorded: %s %s → %d', method, path, status_code)
