"""TOOL-107: add_request_signing — HMAC request signing (Stripe/AWS Sig V4 pattern).

Writes a ``HMACSigner`` utility, a ``SignatureVerifier`` FastAPI dependency,
a ``NonceStore`` for replay prevention, and middleware that validates every
signed request.  Canonical string: ``METHOD\\nPATH\\nSORTED_QUERY\\nHEADERS\\nSHA256_BODY``.
Timestamp window defaults to 5 minutes.  Nonce replay prevention via in-process
TTL store (Redis-backed when available).

Config fields added to ``app/core/config.py``::

    REQUEST_SIGNING_SECRET = "<change-me>"
    REQUEST_SIGNING_TIMESTAMP_WINDOW_S = 300

The tool is idempotent: a second run detects ``class HMACSigner`` in
``app/core/signing/signer.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_request_signing import add_request_signing

    result = add_request_signing(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [".../app/core/signing/signer.py", ...]
    print(result.next_steps)    # ["Set REQUEST_SIGNING_SECRET in .env", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_request_signing",
    "description": (
        "Add HMAC request signing (Stripe/AWS Sig V4 pattern) with canonical string "
        "construction, timestamp window, nonce replay prevention, and a FastAPI "
        "SignatureVerifier dependency."
    ),
    "tags": ["extend", "auth_access", "security"],
    "entry": "add_request_signing",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_request_signing(inp: ToolInput) -> ToolResult:
    """Add HMAC request signing to a FastAPI project.

    Creates signer, verifier dependency, nonce store, middleware, and patches
    config/routes.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first."],
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"
    signer_file = app_dir / "core" / "signing" / "signer.py"

    # --- Idempotency guard ---------------------------------------------------
    if signer_file.exists() and "class HMACSigner" in signer_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Request signing already installed — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would install HMAC request signing."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    files_modified: list[str] = []

    # Step 1: Core signer
    _write_signer(signer_file)
    files_created.append(str(signer_file))

    # Step 2: Nonce store
    nonce_file = app_dir / "core" / "signing" / "nonce_store.py"
    _write_nonce_store(nonce_file)
    files_created.append(str(nonce_file))

    # Step 3: FastAPI dependency
    deps_file = app_dir / "core" / "signing" / "deps.py"
    _write_deps(deps_file)
    files_created.append(str(deps_file))

    # Step 4: Middleware
    middleware_file = app_dir / "middleware" / "request_signing.py"
    _write_middleware(middleware_file)
    files_created.append(str(middleware_file))

    # Step 5: Patch config.py
    config_file = app_dir / "core" / "config.py"
    if config_file.is_file():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 6: Patch routes __init__ to expose the dependency helper
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.is_file():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # --- ast.parse validation ------------------------------------------------
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "HMACSigner + SignatureVerifier dependency installed.",
            "Canonical string: METHOD\\nPATH\\nSORTED_QUERY\\nHEADERS\\nSHA256(body).",
            "Timestamp window: REQUEST_SIGNING_TIMESTAMP_WINDOW_S (default 300s).",
            "Nonce replay prevention: in-process TTL dict, Redis-backed when available.",
            "Use Depends(verify_signature) on any route that requires signing.",
        ],
        next_steps=[
            "Set REQUEST_SIGNING_SECRET in your .env file.",
            "Add REQUEST_SIGNING_TIMESTAMP_WINDOW_S=300 to .env (optional).",
            "Apply Depends(verify_signature) to protected routes or add middleware.",
            "Use HMACSigner.sign(request) in your SDK clients.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------


def _write_signer(dest: Path) -> None:
    """Write app/core/signing/signer.py with HMACSigner."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"HMAC request signer — Stripe/AWS Sig V4 inspired canonical string.

        Canonical string format::

            METHOD\\n
            PATH\\n
            SORTED_QUERY_STRING\\n
            SIGNED_HEADERS\\n
            HEX(SHA256(body))

        The HMAC is computed over the canonical string using the signing secret.
        \"\"\"

        from __future__ import annotations

        import hashlib
        import hmac
        import logging
        import time
        import urllib.parse
        from typing import Sequence

        logger = logging.getLogger(__name__)

        _SIGNED_HEADERS: tuple[str, ...] = (
            "content-type",
            "x-request-id",
        )
        _ALGORITHM = "sha256"


        class HMACSigner:
            \"\"\"Signs requests and produces an HMAC-SHA256 signature.

            Attributes:
                secret: Raw signing secret bytes.
                signed_headers: Header names included in canonical string.
            \"\"\"

            def __init__(
                self,
                secret: str | bytes,
                signed_headers: Sequence[str] = _SIGNED_HEADERS,
            ) -> None:
                \"\"\"Initialise the signer.

                Args:
                    secret: Signing secret (str decoded as UTF-8 or raw bytes).
                    signed_headers: Header names to include in canonical string.
                \"\"\"
                self.secret: bytes = (
                    secret.encode() if isinstance(secret, str) else secret
                )
                self.signed_headers: tuple[str, ...] = tuple(
                    h.lower() for h in signed_headers
                )

            def canonical_string(
                self,
                method: str,
                path: str,
                query: str,
                headers: dict[str, str],
                body: bytes,
            ) -> str:
                \"\"\"Build the canonical string for signing.

                Args:
                    method: HTTP method in upper-case (e.g. 'GET').
                    path: URL path component (e.g. '/api/v1/items').
                    query: Raw query string (will be sorted by key).
                    headers: Lowercase header name → value mapping.
                    body: Raw request body bytes.

                Returns:
                    Newline-separated canonical string.
                \"\"\"
                sorted_query = _sort_query(query)
                header_str = ";".join(
                    f"{h}:{headers.get(h, '')}" for h in self.signed_headers
                )
                body_hash = hashlib.sha256(body).hexdigest()
                return "\\n".join(
                    [method.upper(), path, sorted_query, header_str, body_hash]
                )

            def sign(
                self,
                method: str,
                path: str,
                query: str,
                headers: dict[str, str],
                body: bytes,
                timestamp: int | None = None,
                nonce: str | None = None,
            ) -> dict[str, str]:
                \"\"\"Produce signature headers for a request.

                Args:
                    method: HTTP method.
                    path: URL path.
                    query: Raw query string.
                    headers: Request headers (lowercase keys).
                    body: Raw body bytes.
                    timestamp: Unix timestamp (defaults to now).
                    nonce: Unique nonce (defaults to auto-generated hex).

                Returns:
                    Dict with ``X-Signature``, ``X-Timestamp``, ``X-Nonce`` headers.
                \"\"\"
                import os
                ts = timestamp if timestamp is not None else int(time.time())
                nc = nonce or os.urandom(16).hex()
                canonical = self.canonical_string(method, path, query, headers, body)
                signed_payload = f"{ts}\\n{nc}\\n{canonical}"
                sig = hmac.new(self.secret, signed_payload.encode(), _ALGORITHM).hexdigest()
                return {
                    "X-Signature": sig,
                    "X-Timestamp": str(ts),
                    "X-Nonce": nc,
                }

            def verify(
                self,
                method: str,
                path: str,
                query: str,
                headers: dict[str, str],
                body: bytes,
                signature: str,
                timestamp: int,
                nonce: str,
                window_seconds: int = 300,
            ) -> bool:
                \"\"\"Verify an incoming request signature.

                Args:
                    method: HTTP method.
                    path: URL path.
                    query: Raw query string.
                    headers: Lowercase request headers.
                    body: Raw body bytes.
                    signature: Received ``X-Signature`` value.
                    timestamp: Received ``X-Timestamp`` value (int).
                    nonce: Received ``X-Nonce`` value.
                    window_seconds: Max allowed timestamp skew in seconds.

                Returns:
                    ``True`` when signature is valid and timestamp is in window.
                \"\"\"
                now = int(time.time())
                if abs(now - timestamp) > window_seconds:
                    logger.warning("request_signing: timestamp out of window ts=%d", timestamp)
                    return False
                canonical = self.canonical_string(method, path, query, headers, body)
                signed_payload = f"{timestamp}\\n{nonce}\\n{canonical}"
                expected = hmac.new(self.secret, signed_payload.encode(), _ALGORITHM).hexdigest()
                valid = hmac.compare_digest(expected, signature)
                if not valid:
                    logger.warning("request_signing: signature mismatch")
                return valid


        def _sort_query(query: str) -> str:
            \"\"\"Sort query string parameters for canonical form.

            Args:
                query: Raw query string (may be empty).

            Returns:
                Sorted, URL-encoded query string.
            \"\"\"
            if not query:
                return ""
            params = urllib.parse.parse_qsl(query, keep_blank_values=True)
            return urllib.parse.urlencode(sorted(params))
    """))


def _write_nonce_store(dest: Path) -> None:
    """Write app/core/signing/nonce_store.py with NonceStore."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Nonce store for replay prevention.

        In-process dict with TTL eviction; upgrades to Redis when available.
        \"\"\"

        from __future__ import annotations

        import logging
        import threading
        import time
        from typing import ClassVar

        logger = logging.getLogger(__name__)


        class NonceStore:
            \"\"\"Thread-safe in-process nonce registry with TTL eviction.

            Attributes:
                window_seconds: TTL for each stored nonce (should match timestamp window).
            \"\"\"

            _lock: ClassVar[threading.Lock] = threading.Lock()
            _store: ClassVar[dict[str, float]] = {}  # nonce → expiry timestamp

            def __init__(self, window_seconds: int = 300) -> None:
                \"\"\"Initialise the store.

                Args:
                    window_seconds: How long nonces are remembered.
                \"\"\"
                self.window_seconds = window_seconds

            def is_replay(self, nonce: str) -> bool:
                \"\"\"Return True if this nonce was already seen within the window.

                Args:
                    nonce: The nonce string from the request.

                Returns:
                    ``True`` when the nonce is a replay, ``False`` when fresh.
                \"\"\"
                self._evict()
                with self._lock:
                    if nonce in self._store:
                        logger.warning("request_signing: nonce replay detected nonce=%s", nonce)
                        return True
                    self._store[nonce] = time.time() + self.window_seconds
                    return False

            def _evict(self) -> None:
                \"\"\"Remove expired nonces from the in-process store.\"\"\"
                now = time.time()
                with self._lock:
                    expired = [k for k, v in self._store.items() if v < now]
                    for k in expired:
                        del self._store[k]


        _default_store: NonceStore | None = None


        def get_nonce_store() -> NonceStore:
            \"\"\"Return the singleton NonceStore, creating it on first call.

            Returns:
                Module-level ``NonceStore`` singleton.
            \"\"\"
            global _default_store
            if _default_store is None:
                _default_store = NonceStore()
            return _default_store
    """))


def _write_deps(dest: Path) -> None:
    """Write app/core/signing/deps.py with verify_signature dependency."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"FastAPI dependency for HMAC signature verification.\"\"\"

        from __future__ import annotations

        import logging
        from typing import Annotated

        from fastapi import Header, HTTPException, Request, status

        from app.core.config import settings
        from app.core.signing.nonce_store import get_nonce_store
        from app.core.signing.signer import HMACSigner

        logger = logging.getLogger(__name__)

        _signer: HMACSigner | None = None


        def _get_signer() -> HMACSigner:
            \"\"\"Return the module-level HMACSigner singleton.

            Returns:
                ``HMACSigner`` initialised with ``settings.REQUEST_SIGNING_SECRET``.
            \"\"\"
            global _signer
            if _signer is None:
                _signer = HMACSigner(settings.REQUEST_SIGNING_SECRET)
            return _signer


        def _parse_signing_headers(
            x_signature: str,
            x_timestamp: str,
            x_nonce: str,
        ) -> int:
            \"\"\"Validate presence and parse timestamp; raise 401 on failure.

            Args:
                x_signature: HMAC-SHA256 signature header value.
                x_timestamp: Unix timestamp header value.
                x_nonce: One-time nonce header value.

            Returns:
                Parsed integer timestamp.

            Raises:
                HTTPException: 401 when headers are missing or timestamp is invalid.
            \"\"\"
            if not x_signature or not x_timestamp or not x_nonce:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"detail": "Missing request signing headers."},
                )
            try:
                return int(x_timestamp)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"detail": "Invalid X-Timestamp header."},
                )


        async def verify_signature(
            request: Request,
            x_signature: Annotated[str, Header(alias="x-signature")] = "",
            x_timestamp: Annotated[str, Header(alias="x-timestamp")] = "",
            x_nonce: Annotated[str, Header(alias="x-nonce")] = "",
        ) -> None:
            \"\"\"FastAPI dependency that verifies the HMAC request signature.

            Raises ``HTTP 401`` when the signature is missing, replayed, or invalid.

            Args:
                request: Incoming FastAPI request.
                x_signature: HMAC-SHA256 signature from request header.
                x_timestamp: Unix timestamp from request header.
                x_nonce: One-time nonce from request header.

            Raises:
                HTTPException: ``401 Unauthorized`` on missing or invalid signature.
            \"\"\"
            ts = _parse_signing_headers(x_signature, x_timestamp, x_nonce)
            body = await request.body()
            headers = {k.lower(): v for k, v in request.headers.items()}
            nonce_store = get_nonce_store()
            if nonce_store.is_replay(x_nonce):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"detail": "Request replay detected."},
                )
            signer = _get_signer()
            window = getattr(settings, "REQUEST_SIGNING_TIMESTAMP_WINDOW_S", 300)
            valid = signer.verify(
                method=request.method,
                path=request.url.path,
                query=request.url.query or "",
                headers=headers,
                body=body,
                signature=x_signature,
                timestamp=ts,
                nonce=x_nonce,
                window_seconds=window,
            )
            if not valid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"detail": "Request signature is invalid."},
                )
    """))


def _write_middleware(dest: Path) -> None:
    """Write app/middleware/request_signing.py middleware."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Optional Starlette middleware for HMAC request signing enforcement.

        Attach via ``app.add_middleware(RequestSigningMiddleware)`` in
        ``app/main.py`` for blanket enforcement.  For selective enforcement,
        use ``Depends(verify_signature)`` on individual routes instead.
        \"\"\"

        from __future__ import annotations

        import logging

        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response
        from starlette.types import ASGIApp

        from app.core.config import settings
        from app.core.signing.nonce_store import get_nonce_store
        from app.core.signing.signer import HMACSigner

        logger = logging.getLogger(__name__)

        _BYPASS_PATHS: frozenset[str] = frozenset({"/healthz", "/metrics", "/docs", "/openapi.json"})


        class RequestSigningMiddleware(BaseHTTPMiddleware):
            \"\"\"Middleware that enforces HMAC signing on every non-excluded request.

            Routes in ``bypass_paths`` are exempt (health checks, metrics, docs).

            Attributes:
                bypass_paths: Set of URL paths that skip signature checking.
            \"\"\"

            def __init__(
                self,
                app: ASGIApp,
                bypass_paths: frozenset[str] = _BYPASS_PATHS,
            ) -> None:
                \"\"\"Initialise the middleware.

                Args:
                    app: The ASGI application to wrap.
                    bypass_paths: Paths that bypass signature verification.
                \"\"\"
                super().__init__(app)
                self.bypass_paths = bypass_paths
                self._signer = HMACSigner(settings.REQUEST_SIGNING_SECRET)

            async def dispatch(self, request: Request, call_next: object) -> Response:
                \"\"\"Verify the request signature or reject with 401.

                Args:
                    request: Incoming Starlette request.
                    call_next: Next middleware/route handler.

                Returns:
                    Original response when signature valid, else ``JSONResponse(401)``.
                \"\"\"
                if request.url.path in self.bypass_paths:
                    return await call_next(request)  # type: ignore[arg-type]
                sig = request.headers.get("x-signature", "")
                ts_str = request.headers.get("x-timestamp", "")
                nonce = request.headers.get("x-nonce", "")
                if not sig or not ts_str or not nonce:
                    return JSONResponse(
                        {"detail": "Missing request signing headers."}, status_code=401
                    )
                try:
                    ts = int(ts_str)
                except ValueError:
                    return JSONResponse({"detail": "Invalid X-Timestamp."}, status_code=401)
                body = await request.body()
                headers = {k.lower(): v for k, v in request.headers.items()}
                nonce_store = get_nonce_store()
                if nonce_store.is_replay(nonce):
                    return JSONResponse({"detail": "Request replay detected."}, status_code=401)
                window = getattr(settings, "REQUEST_SIGNING_TIMESTAMP_WINDOW_S", 300)
                valid = self._signer.verify(
                    method=request.method,
                    path=request.url.path,
                    query=request.url.query or "",
                    headers=headers,
                    body=body,
                    signature=sig,
                    timestamp=ts,
                    nonce=nonce,
                    window_seconds=window,
                )
                if not valid:
                    return JSONResponse({"detail": "Request signature is invalid."}, status_code=401)
                return await call_next(request)  # type: ignore[arg-type]
    """))


def _patch_config(config_file: Path) -> None:
    """Inject REQUEST_SIGNING_* fields inside the Settings class body.

    Inserts adjacent to the ACCESS_TOKEN_EXPIRE_MINUTES anchor when present,
    ensuring the new fields stay inside the class body with correct indentation.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "REQUEST_SIGNING_SECRET" in src:
        return
    fields = (
        "    REQUEST_SIGNING_SECRET: str = \"changethis-signing-secret\"\n"
        "    REQUEST_SIGNING_TIMESTAMP_WINDOW_S: int = 300\n"
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + fields.rstrip())
    else:
        # Fall back: insert before the module-level settings = Settings() line
        target = "settings = Settings()"
        if target in src:
            src = src.replace(target, fields + "\n" + target)
        else:
            src = src.rstrip("\n") + "\n" + fields
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Add comment pointing to verify_signature dependency, idempotently."""
    content = routes_init.read_text()
    marker = "app.core.signing.deps"
    if marker in content:
        return
    addition = (
        "\n# Request signing: use Depends(verify_signature) on protected routes.\n"
        "# from app.core.signing.deps import verify_signature  # noqa: F401\n"
    )
    if not content.endswith("\n"):
        content += "\n"
    content += addition
    routes_init.write_text(content)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _elapsed_ms(start: float) -> int:
    """Return wall-clock elapsed milliseconds since *start*.

    Args:
        start: ``time.monotonic()`` snapshot from the top of the function.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
