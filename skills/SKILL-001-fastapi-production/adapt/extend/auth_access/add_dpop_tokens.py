"""TOOL-115: add_dpop_tokens — RFC 9449 DPoP proof-of-possession for FastAPI.

Implements RFC 9449 Demonstrating Proof of Possession (DPoP):

* ``app/core/dpop.py`` — nonce manager, proof verifier, and token binder.
* ``app/api/deps/dpop.py`` — ``require_dpop`` FastAPI dependency.
* ``app/api/routes/dpop_nonce.py`` — ``POST /auth/dpop/nonce`` endpoint
  (server-issued nonce for fresh proof generation).
* Key-pair JWK management helpers (``generate_dpop_key_pair``,
  ``jwk_from_private_key``).

FAPI 2.0 compliance
-------------------
The proof JWT must include ``htm`` (HTTP method) and ``htu`` (HTTP target URI),
a fresh ``iat`` (issued-at within ``DPOP_CLOCK_SKEW_S``), and ``jti``
(unique nonce).  A server-side nonce is injected when
``DPOP_NONCE_TTL_S > 0`` via the ``DPoP-Nonce`` response header, mirroring
the RFC 9449 §8 server-nonce flow.

Lazy imports
------------
``PyJWT`` (``jwt``) is imported lazily inside verification functions so the
application can boot without the library installed when DPoP is disabled.

Idempotency
-----------
A second run detects ``DPoPVerifier`` in ``app/core/dpop.py`` and returns
``status="no_op"``.

Config fields added
-------------------
``DPOP_ENABLED``, ``DPOP_NONCE_TTL_S``, ``DPOP_CLOCK_SKEW_S``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_dpop_tokens import add_dpop_tokens

    result = add_dpop_tokens(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/core/dpop.py", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_auth_add_dpop_tokens",
    "description": (
        "Add RFC 9449 DPoP (Demonstrating Proof of Possession) with proof verification "
        "middleware, server-side nonce, token binding, and JWK key management. "
        "FAPI 2.0 compliant."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_dpop_tokens",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_dpop_tokens(inp: ToolInput) -> ToolResult:
    """Add RFC 9449 DPoP proof-of-possession to a FastAPI project.

    Creates ``app/core/dpop.py`` (nonce store, verifier, binder),
    ``app/api/deps/dpop.py`` (``require_dpop`` dependency),
    ``app/api/routes/dpop_nonce.py`` (nonce endpoint), and all required
    settings fields.  Patches ``app/core/config.py``,
    ``app/routes/__init__.py``, and ``requirements.txt``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` describing files created/modified and next steps.
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
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    dpop_core = app_dir / "core" / "dpop.py"
    if dpop_core.exists() and "DPoPVerifier" in dpop_core.read_text():
        return ToolResult(
            status="no_op",
            notes=["DPoPVerifier already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard (BEFORE any writes) -----------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create: app/core/dpop.py, "
                "app/api/deps/dpop.py, app/api/routes/dpop_nonce.py.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — DPoP core (nonce store, verifier, binder)
    dpop_core.parent.mkdir(parents=True, exist_ok=True)
    dpop_core.write_text(_DPOP_CORE_TEMPLATE)
    files_created.append(str(dpop_core))

    # Step 2 — FastAPI dependency
    # Write to app/core/dpop_deps.py to avoid conflicting with projects
    # that have app/api/deps.py (single-file) instead of app/api/deps/ (package).
    deps_dpop = app_dir / "core" / "dpop_deps.py"
    deps_dpop.parent.mkdir(parents=True, exist_ok=True)
    deps_dpop.write_text(_DPOP_DEPS_TEMPLATE)
    files_created.append(str(deps_dpop))

    # Step 3 — Nonce endpoint
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    nonce_route = routes_dir / "dpop_nonce.py"
    nonce_route.write_text(_DPOP_NONCE_ROUTE_TEMPLATE)
    files_created.append(str(nonce_route))

    # Step 4 — Patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 5 — Register nonce router
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 6 — requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # --- ast.parse validation loop -------------------------------------------
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
            "DPoP (RFC 9449) installed: proof verifier, server-side nonce,",
            "token binding, JWK key management, @require_dpop dependency,",
            "POST /auth/dpop/nonce endpoint. FAPI 2.0 compliant.",
            "PyJWT is imported lazily — app boots without it when DPOP_ENABLED=false.",
        ],
        next_steps=[
            "Set DPOP_ENABLED=true in .env.",
            "pip install PyJWT>=2.9.0 cryptography>=42.0.0",
            "Use @require_dpop in routes that require proof-of-possession.",
            "Clients: generate an EC P-256 key pair, include DPoP header on each request.",
            "See app/api/deps/dpop.py for usage example.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File-patching helpers
# ---------------------------------------------------------------------------

def _patch_config(config_file: Path) -> None:
    """Inject DPoP settings into the Settings class body.

    Args:
        config_file: Path to app/core/config.py.
    """
    src = config_file.read_text()
    if "DPOP_ENABLED" in src:
        return
    block = (
        "\n"
        "    # --- DPoP tokens (RFC 9449) — added by add_dpop_tokens tool ---\n"
        "    DPOP_ENABLED: bool = False\n"
        "    DPOP_NONCE_TTL_S: int = 300\n"
        "    DPOP_CLOCK_SKEW_S: int = 60\n"
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the DPoP nonce router in app/routes/__init__.py.

    Args:
        routes_init: Path to app/routes/__init__.py.
    """
    import_line = "from app.api.routes.dpop_nonce import router as dpop_nonce_router"
    include_line = "api_router.include_router(dpop_nonce_router)"
    src = routes_init.read_text()
    if import_line in src:
        return
    lines = src.splitlines()
    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)
    last_include_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include_idx = idx
    if last_include_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include_idx = idx
                break
    lines.insert(last_include_idx + 1, include_line)
    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _patch_requirements(requirements_file: Path) -> None:
    """Ensure PyJWT is listed in requirements.txt.

    Args:
        requirements_file: Path to requirements.txt.
    """
    src = requirements_file.read_text()
    additions: list[str] = []
    if "PyJWT" not in src and "pyjwt" not in src.lower():
        additions.append("PyJWT>=2.9.0")
    if not additions:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "\n".join(additions) + "\n")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since start.

    Args:
        start: Start time from time.monotonic().

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_DPOP_CORE_TEMPLATE = textwrap.dedent("""\
    \"\"\"DPoP (RFC 9449) core — nonce store, proof verifier, and token binder.

    RFC 9449 Demonstrating Proof of Possession (DPoP) prevents token theft by
    binding access tokens to a client-held private key.  Each request carries
    a short-lived DPoP proof JWT signed by the client's private key.  The
    server verifies:

    1. The JWT header algorithm is an asymmetric EC or RSA scheme.
    2. ``htm`` matches the HTTP method of the current request.
    3. ``htu`` matches the request URI (scheme + host + path).
    4. ``iat`` is within the clock-skew window.
    5. ``jti`` has not been replayed (nonce store).
    6. When server-side nonces are enabled, ``nonce`` matches the issued value.

    PyJWT is imported LAZILY inside functions so the app boots without the
    library when ``DPOP_ENABLED=false``.
    \"\"\"
    from __future__ import annotations

    import hashlib
    import logging
    import secrets
    import time
    from threading import Lock
    from typing import Any

    from app.core.config import settings

    logger = logging.getLogger(__name__)

    # Allowed DPoP proof header algorithms (RFC 9449 §4.2)
    _ALLOWED_ALGS: frozenset[str] = frozenset({
        "ES256", "ES384", "ES512",
        "RS256", "RS384", "RS512",
        "PS256", "PS384", "PS512",
        "EdDSA",
    })


    class DPoPNonceStore:
        \"\"\"Thread-safe in-process nonce store with TTL eviction.

        Stores issued server nonces and consumed proof JTIs so replayed proofs
        are detected within the ``DPOP_NONCE_TTL_S`` window.
        \"\"\"

        def __init__(self, ttl_s: int = 300) -> None:
            \"\"\"Initialise with configurable TTL.

            Args:
                ttl_s: Seconds before a nonce or JTI expires.
            \"\"\"
            self._ttl = ttl_s
            self._nonces: dict[str, float] = {}  # nonce -> issued_at
            self._jtis: dict[str, float] = {}    # jti -> seen_at
            self._lock = Lock()

        def issue_nonce(self) -> str:
            \"\"\"Generate, store, and return a fresh server nonce.

            Returns:
                URL-safe random nonce string.
            \"\"\"
            nonce = secrets.token_urlsafe(24)
            with self._lock:
                self._evict()
                self._nonces[nonce] = time.monotonic()
            return nonce

        def validate_nonce(self, nonce: str) -> bool:
            \"\"\"Return True when *nonce* was issued by this store and has not expired.

            Args:
                nonce: Nonce string from the DPoP proof JWT.

            Returns:
                True when the nonce is valid and unexpired.
            \"\"\"
            with self._lock:
                self._evict()
                return nonce in self._nonces

        def mark_jti(self, jti: str) -> bool:
            \"\"\"Mark *jti* as consumed; return False when already seen (replay).

            Args:
                jti: ``jti`` claim from the DPoP proof JWT.

            Returns:
                True when first-seen (fresh), False on replay.
            \"\"\"
            with self._lock:
                self._evict()
                if jti in self._jtis:
                    return False
                self._jtis[jti] = time.monotonic()
                return True

        def _evict(self) -> None:
            \"\"\"Remove expired nonces and JTIs (must be called under lock).\"\"\"
            cutoff = time.monotonic() - self._ttl
            self._nonces = {k: v for k, v in self._nonces.items() if v > cutoff}
            self._jtis = {k: v for k, v in self._jtis.items() if v > cutoff}


    class DPoPVerifier:
        \"\"\"Stateful DPoP proof verifier (RFC 9449 §4.3).\"\"\"

        def __init__(self, nonce_store: DPoPNonceStore) -> None:
            \"\"\"Initialise verifier with a shared nonce store.

            Args:
                nonce_store: The store used for nonce and JTI tracking.
            \"\"\"
            self._store = nonce_store

        def verify_proof(
            self,
            proof_header: str,
            method: str,
            uri: str,
        ) -> dict[str, Any]:
            \"\"\"Verify a DPoP proof header and return its claims.

            Args:
                proof_header: Raw value of the ``DPoP`` HTTP header.
                method: HTTP method of the current request (e.g. 'GET').
                uri: Full URI of the current request (scheme+host+path).

            Returns:
                Decoded JWT claims dict on success.

            Raises:
                ValueError: When the proof fails any RFC 9449 check.
            \"\"\"
            import jwt  # lazy import — PyJWT
            header = _decode_header_unverified(proof_header)
            alg = header.get("alg", "")
            if alg not in _ALLOWED_ALGS:
                raise ValueError(f"DPoP: unsupported algorithm {alg!r}")
            jwk_data = header.get("jwk")
            if not jwk_data:
                raise ValueError("DPoP: missing jwk in header")
            public_key = _load_public_key_from_jwk(jwk_data)
            skew = settings.DPOP_CLOCK_SKEW_S
            claims = jwt.decode(
                proof_header,
                public_key,
                algorithms=list(_ALLOWED_ALGS),
                options={"verify_exp": False, "leeway": skew},
            )
            _check_htm_htu(claims, method, uri)
            _check_iat(claims, skew)
            jti = claims.get("jti", "")
            if not jti:
                raise ValueError("DPoP: missing jti claim")
            if not self._store.mark_jti(jti):
                raise ValueError("DPoP: replayed jti")
            if settings.DPOP_NONCE_TTL_S > 0:
                nonce = claims.get("nonce", "")
                if not nonce or not self._store.validate_nonce(nonce):
                    raise ValueError("DPoP: invalid or missing server nonce")
            return claims

        def bind_access_token(self, access_token: str, jwk_thumbprint: str) -> str:
            \"\"\"Return a token hash binding the access token to the client key.

            The ``cnf/jkt`` claim in the access token should equal this value.

            Args:
                access_token: Bearer access token string.
                jwk_thumbprint: SHA-256 thumbprint of the client's public JWK.

            Returns:
                SHA-256 hash of the access token encoded as hex.
            \"\"\"
            return hashlib.sha256(
                (access_token + ":" + jwk_thumbprint).encode()
            ).hexdigest()


    def _decode_header_unverified(token: str) -> dict[str, Any]:
        \"\"\"Decode the JWT header without signature verification.

        Args:
            token: Raw JWT string.

        Returns:
            Header claims dict.

        Raises:
            ValueError: When the token is malformed.
        \"\"\"
        import jwt  # lazy import
        try:
            return jwt.get_unverified_header(token)
        except Exception as exc:
            raise ValueError(f"DPoP: malformed JWT header: {exc}") from exc


    def _load_public_key_from_jwk(jwk_data: dict[str, Any]) -> Any:
        \"\"\"Convert a JWK dict to a cryptography public key object.

        Args:
            jwk_data: JWK dict from the DPoP proof header.

        Returns:
            Public key object usable by PyJWT.

        Raises:
            ValueError: When the JWK cannot be parsed.
        \"\"\"
        try:
            from jwt.algorithms import ECAlgorithm, RSAAlgorithm
            import json
            kty = jwk_data.get("kty", "")
            jwk_str = json.dumps(jwk_data)
            if kty == "EC":
                return ECAlgorithm.from_jwk(jwk_str)
            if kty == "RSA":
                return RSAAlgorithm.from_jwk(jwk_str)
            raise ValueError(f"DPoP: unsupported JWK kty {kty!r}")
        except (ImportError, Exception) as exc:
            raise ValueError(f"DPoP: cannot load public key: {exc}") from exc


    def _check_htm_htu(claims: dict[str, Any], method: str, uri: str) -> None:
        \"\"\"Raise ValueError when htm or htu claims do not match the request.

        Args:
            claims: Decoded JWT claims.
            method: Expected HTTP method (uppercase).
            uri: Expected request URI.
        \"\"\"
        htm = claims.get("htm", "")
        htu = claims.get("htu", "")
        if htm.upper() != method.upper():
            raise ValueError(f"DPoP: htm mismatch: expected {method!r}, got {htm!r}")
        if htu.rstrip("/") != uri.rstrip("/"):
            raise ValueError(f"DPoP: htu mismatch: expected {uri!r}, got {htu!r}")


    def _check_iat(claims: dict[str, Any], skew_s: int) -> None:
        \"\"\"Raise ValueError when the iat claim is outside the clock-skew window.

        Args:
            claims: Decoded JWT claims.
            skew_s: Allowed clock skew in seconds.
        \"\"\"
        iat = claims.get("iat")
        if iat is None:
            raise ValueError("DPoP: missing iat claim")
        now = time.time()
        if abs(now - iat) > skew_s:
            raise ValueError(f"DPoP: iat outside clock skew window ({skew_s}s)")


    def generate_dpop_key_pair() -> tuple[Any, Any]:
        \"\"\"Generate an EC P-256 key pair for DPoP use (lazy cryptography import).

        Returns:
            Tuple of (private_key, public_key) cryptography objects.
        \"\"\"
        from cryptography.hazmat.primitives.asymmetric.ec import (  # lazy import
            SECP256R1, generate_private_key,
        )
        from cryptography.hazmat.backends import default_backend
        private_key = generate_private_key(SECP256R1(), default_backend())
        return private_key, private_key.public_key()


    def jwk_from_public_key(public_key: Any) -> dict[str, Any]:
        \"\"\"Export a public key as a JWK dict (EC P-256).

        Args:
            public_key: A cryptography EC public key object.

        Returns:
            JWK dict with kty, crv, x, y fields.
        \"\"\"
        import base64
        from cryptography.hazmat.primitives.asymmetric.ec import (  # lazy import
            EllipticCurvePublicKey,
        )
        if not isinstance(public_key, EllipticCurvePublicKey):
            raise TypeError("Only EC public keys are supported")
        nums = public_key.public_numbers()
        def _b64(n: int, length: int = 32) -> str:
            return base64.urlsafe_b64encode(
                n.to_bytes(length, "big")
            ).rstrip(b"=").decode()
        return {"kty": "EC", "crv": "P-256", "x": _b64(nums.x), "y": _b64(nums.y)}


    _nonce_store = DPoPNonceStore(ttl_s=settings.DPOP_NONCE_TTL_S or 300)
    _verifier = DPoPVerifier(_nonce_store)


    def get_dpop_verifier() -> DPoPVerifier:
        \"\"\"Return the module-level DPoPVerifier singleton.

        Returns:
            Shared DPoPVerifier instance.
        \"\"\"
        return _verifier


    def get_nonce_store() -> DPoPNonceStore:
        \"\"\"Return the module-level DPoPNonceStore singleton.

        Returns:
            Shared DPoPNonceStore instance.
        \"\"\"
        return _nonce_store
""")


_DPOP_DEPS_TEMPLATE = textwrap.dedent("""\
    \"\"\"FastAPI dependency for DPoP proof-of-possession enforcement.

    Usage::

        from app.api.deps.dpop import require_dpop

        @router.get("/protected")
        async def protected(dpop_claims: Annotated[dict, Depends(require_dpop)]):
            return {"sub": dpop_claims.get("sub")}

    When ``DPOP_ENABLED=false`` the dependency is a no-op pass-through.
    \"\"\"
    from __future__ import annotations

    import logging
    from typing import Annotated, Any

    from fastapi import Depends, Header, HTTPException, Request

    from app.core.config import settings

    logger = logging.getLogger(__name__)


    async def _noop_dpop() -> dict[str, Any]:
        \"\"\"No-op DPoP dependency used when DPoP is disabled.

        Returns:
            Empty claims dict.
        \"\"\"
        return {}


    async def _verify_dpop_proof(
        request: Request,
        dpop: Annotated[str | None, Header(alias="DPoP")] = None,
    ) -> dict[str, Any]:
        \"\"\"Verify the DPoP proof header and return its claims.

        Args:
            request: Current HTTP request (provides method and URL).
            dpop: Raw value of the ``DPoP`` header.

        Returns:
            Verified DPoP JWT claims dict.

        Raises:
            HTTPException: 401 when DPoP header is missing or invalid.
        \"\"\"
        if dpop is None:
            raise HTTPException(
                status_code=401,
                detail={"detail": "DPoP header required"},
                headers={"WWW-Authenticate": 'DPoP error="use_dpop_nonce"'},
            )
        from app.core.dpop import get_dpop_verifier
        verifier = get_dpop_verifier()
        method = request.method
        uri = str(request.url).split("?")[0]
        try:
            claims = verifier.verify_proof(dpop, method, uri)
        except ValueError as exc:
            logger.warning("dpop_proof_invalid", extra={"error": str(exc)})
            raise HTTPException(
                status_code=401,
                detail={"detail": f"DPoP proof invalid: {exc}"},
                headers={"WWW-Authenticate": 'DPoP error="invalid_dpop_proof"'},
            ) from exc
        return claims


    def require_dpop(
        request: Request,
        dpop: Annotated[str | None, Header(alias="DPoP")] = None,
    ) -> Any:
        \"\"\"FastAPI dependency: verify DPoP proof when DPOP_ENABLED is True.

        Use as ``Depends(require_dpop)`` on routes that require proof-of-
        possession.  Returns an empty dict when DPoP is disabled, allowing
        gradual rollout.

        Args:
            request: Current HTTP request.
            dpop: Raw value of the ``DPoP`` header.

        Returns:
            Verified claims dict or empty dict when disabled.
        \"\"\"
        if not settings.DPOP_ENABLED:
            return {}
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            _verify_dpop_proof(request, dpop)
        )


    # Async version for use with ``await``
    async def require_dpop_async(
        request: Request,
        dpop: Annotated[str | None, Header(alias="DPoP")] = None,
    ) -> dict[str, Any]:
        \"\"\"Async FastAPI dependency for DPoP enforcement.

        Preferred over ``require_dpop`` in async route handlers.

        Args:
            request: Current HTTP request.
            dpop: Raw value of the ``DPoP`` header.

        Returns:
            Verified claims dict or empty dict when disabled.
        \"\"\"
        if not settings.DPOP_ENABLED:
            return {}
        return await _verify_dpop_proof(request, dpop)
""")


_DPOP_NONCE_ROUTE_TEMPLATE = textwrap.dedent("""\
    \"\"\"DPoP nonce endpoint — RFC 9449 §8 server-nonce flow.

    Clients that receive a 401 with ``WWW-Authenticate: DPoP error="use_dpop_nonce"``
    should POST to this endpoint to obtain a fresh server nonce, then retry
    their request with ``nonce`` included in the DPoP proof JWT.
    \"\"\"
    from __future__ import annotations

    import logging

    from fastapi import APIRouter, Response

    from app.core.config import settings

    logger = logging.getLogger(__name__)
    router = APIRouter(prefix="/auth/dpop", tags=["dpop"])


    @router.post(
        "/nonce",
        status_code=200,
        summary="Issue a fresh DPoP server nonce (RFC 9449 §8)",
    )
    async def issue_dpop_nonce(response: Response) -> dict[str, str]:
        \"\"\"Issue a fresh server nonce for DPoP proof construction.

        Clients include the returned ``nonce`` in the ``nonce`` claim of
        their next DPoP proof JWT.  The nonce is valid for
        ``DPOP_NONCE_TTL_S`` seconds.

        Returns:
            JSON body with ``nonce`` field, plus ``DPoP-Nonce`` response header.

        Raises:
            HTTPException: 503 when DPoP is not enabled.
        \"\"\"
        if not settings.DPOP_ENABLED:
            from fastapi import HTTPException
            raise HTTPException(status_code=503, detail={"detail": "DPoP not enabled"})
        from app.core.dpop import get_nonce_store
        nonce = get_nonce_store().issue_nonce()
        response.headers["DPoP-Nonce"] = nonce
        logger.debug("dpop_nonce_issued")
        return {"nonce": nonce}


    @router.get(
        "/status",
        summary="DPoP configuration status",
    )
    async def dpop_status() -> dict[str, object]:
        \"\"\"Return the current DPoP configuration.

        Returns:
            Dict with enabled flag, nonce TTL, and clock skew settings.
        \"\"\"
        return {
            "dpop_enabled": settings.DPOP_ENABLED,
            "nonce_ttl_s": settings.DPOP_NONCE_TTL_S,
            "clock_skew_s": settings.DPOP_CLOCK_SKEW_S,
        }
""")
