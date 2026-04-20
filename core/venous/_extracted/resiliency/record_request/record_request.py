from __future__ import annotations


def record_request(method: str, path: str, status_code: int, duration_ms: float) -> None:
    """Record an HTTP request in the metrics counters.

    Args:
        method: HTTP method (GET, POST, etc.).
        path: Request path.
        status_code: HTTP response status code.
        duration_ms: Request duration in milliseconds.
    """
    _ensure_instruments()
    attrs = {'http.method': method, 'http.route': path, 'http.status_code': status_code}
    if _request_counter is not None:
        _request_counter.add(1, attrs)
    if _duration_histogram is not None:
        _duration_histogram.record(duration_ms, attrs)
