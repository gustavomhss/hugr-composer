from __future__ import annotations
from typing import Any


class FuzzResult:
    """Container for a single fuzz attempt result.

    Attributes:
        method: HTTP method used.
        path: Endpoint path tested.
        payload: The adversarial payload sent.
        status_code: HTTP response status code.
        is_json: Whether the response body was valid JSON.
        elapsed_ms: Round-trip latency in milliseconds.
        error: Exception message if the request itself failed.
    """

    def __init__(self, method: str, path: str, payload: dict, status_code: int, is_json: bool, elapsed_ms: int, error: str | None=None) -> None:
        self.method = method
        self.path = path
        self.payload = payload
        self.status_code = status_code
        self.is_json = is_json
        self.elapsed_ms = elapsed_ms
        self.error = error

    def is_finding(self) -> bool:
        """Return True when this result represents a fuzz finding.

        A finding is a non-JSON 5xx, a request timeout, or a crash.
        """
        if self.error:
            return True
        if self.status_code >= 500 and (not self.is_json):
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        """Serialise this result to a plain dict."""
        return {'method': self.method, 'path': self.path, 'status_code': self.status_code, 'is_json': self.is_json, 'elapsed_ms': self.elapsed_ms, 'is_finding': self.is_finding(), 'error': self.error}
