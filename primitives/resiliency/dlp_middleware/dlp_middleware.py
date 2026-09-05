"""Response middleware that detects and redacts PII/PHI/PCI in JSON."""

import re
import json
import logging
import os
from typing import Pattern
from builtins import frozenset

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

_BYPASS_PATHS: frozenset[str] = frozenset({"/health", "/healthz", "/readyz", "/metrics", "/docs", "/openapi.json"})
_JSON_CONTENT_TYPES = ("application/json", "application/vnd.api+json")

# Simplified PII patterns
_PATTERNS: dict[str, Pattern[str]] = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
    "api_key": re.compile(r"(?i)(api[_-]?key|access[_-]?token)[\"']?\s*[:=]\s*[\"']?([a-zA-Z0-9_-]{20,})"),
}


class Redactor:
    """JSON body redactor for PII/PHI/PCI."""

    def __init__(self, mode: str = "full"):
        self.mode = mode

    def redact_json_bytes(self, body: bytes) -> bytes:
        try:
            data = json.loads(body.decode("utf-8"))
            redacted = self._redact_value(data)
            return json.dumps(redacted, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        except Exception:
            return body

    def _redact_value(self, value):
        if isinstance(value, dict):
            return {k: self._redact_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._redact_value(v) for v in value]
        elif isinstance(value, str):
            return self._redact_string(value)
        return value

    def _redact_string(self, s: str) -> str:
        for name, pattern in _PATTERNS.items():
            s = pattern.sub(f"[REDACTED:{name.upper()}]", s)
        return s


class DLPMiddleware(BaseHTTPMiddleware):
    """Response middleware that detects and redacts PII/PHI/PCI in JSON.

    Attributes:
        bypass_paths: URL paths that skip DLP scanning.
    """

    def __init__(self, app: ASGIApp, bypass_paths: frozenset[str] = _BYPASS_PATHS) -> None:
        """Initialise the middleware.

        Args:
            app: ASGI application to wrap.
            bypass_paths: Paths that skip DLP scanning.
        """
        super().__init__(app)
        self.bypass_paths = bypass_paths

    async def dispatch(self, request: Request, call_next) -> Response:
        """Intercept the response and apply DLP redaction.

        Args:
            request: Incoming Starlette request.
            call_next: Next handler.

        Returns:
            Original or DLP-redacted response.
        """
        # Check DLP enabled via env
        import os
        if not os.getenv("DLP_ENABLED", "false").lower() == "true":
            return await call_next(request)
        if request.url.path in self.bypass_paths:
            return await call_next(request)
        response: Response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        is_json = any(ct in content_type for ct in _JSON_CONTENT_TYPES)
        if not is_json:
            return response
        body = b""
        async for chunk in response.body_iterator:
            body += chunk if isinstance(chunk, bytes) else chunk.encode()
        mode = os.getenv("DLP_REDACTION_MODE", "full")
        redactor = Redactor(mode=mode)
        redacted_body = redactor.redact_json_bytes(body)
        headers = dict(response.headers)
        headers["content-length"] = str(len(redacted_body))
        return Response(content=redacted_body, status_code=response.status_code, headers=headers, media_type="application/json")
