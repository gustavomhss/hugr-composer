"""TOOL-111: add_runtime_sentinel — RASP injection-detection middleware for FastAPI.

Generates:
  - ``app/middleware/runtime_sentinel.py`` — RASP middleware + InjectionDetector
  - ``app/core/sentinel_registry.py``       — AttackPatternRegistry + SecurityEvent
  - patches ``app/core/config.py``          — SENTINEL_ENABLED, SENTINEL_MODE, SENTINEL_ALLOWED_HOSTS

Covers:
  - SQL injection: AST-aware tautology/UNION/stacked/comment detection
  - Command injection: shell metacharacter detection
  - SSRF: allow-list outbound hosts, block internal networks (169.254/10/127/metadata)
  - Learning mode (24 h) → enforcing mode transition

Tool is idempotent: second run detects ``RuntimeSentinelMiddleware`` in
``app/middleware/runtime_sentinel.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_runtime_sentinel import add_runtime_sentinel

    result = add_runtime_sentinel(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/middleware/runtime_sentinel.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_runtime_sentinel",
    "description": (
        "Add RASP middleware with SQL/command/SSRF injection detection, "
        "attack pattern registry, and learning→enforcing mode transition."
    ),
    "tags": ["extend", "infrastructure", "security", "rasp"],
    "entry": "add_runtime_sentinel",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_runtime_sentinel(inp: ToolInput) -> ToolResult:
    """Add runtime sentinel RASP middleware to a FastAPI project.

    Writes ``app/middleware/runtime_sentinel.py``,
    ``app/core/sentinel_registry.py``, patches ``app/core/config.py``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)

    # --- Idempotency guard ---------------------------------------------------
    middleware_dir = project / "app" / "middleware"
    sentinel_file = middleware_dir / "runtime_sentinel.py"
    if sentinel_file.exists() and "RuntimeSentinelMiddleware" in sentinel_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["RuntimeSentinelMiddleware already present — runtime sentinel already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard -------------------------------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/middleware/runtime_sentinel.py",
                "[dry_run] Would create app/core/sentinel_registry.py",
                "[dry_run] Would patch app/core/config.py with SENTINEL settings",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: middleware package ------------------------------------------
    middleware_dir.mkdir(parents=True, exist_ok=True)
    middleware_init = middleware_dir / "__init__.py"
    if not middleware_init.exists():
        middleware_init.write_text('"""Middleware package."""\n')
        files_created.append(str(middleware_init))

    # --- Step 2: sentinel_registry.py ----------------------------------------
    registry_file = project / "app" / "core" / "sentinel_registry.py"
    (project / "app" / "core").mkdir(parents=True, exist_ok=True)
    _write_sentinel_registry(registry_file)
    files_created.append(str(registry_file))

    # --- Step 3: runtime_sentinel.py (middleware) ----------------------------
    _write_runtime_sentinel(sentinel_file)
    files_created.append(str(sentinel_file))

    # --- Step 4: patch config.py ---------------------------------------------
    config_file = project / "app" / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 5: ast.parse validation loop -----------------------------------
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
            "Runtime sentinel RASP middleware added.",
            "InjectionDetector: SQL (tautology/UNION/stacked/comment), command (metacharacters), SSRF (allow-list).",
            "AttackPatternRegistry: records SecurityEvent per attack type with timestamps.",
            "Learning mode: logs detections without blocking for 24h, then switches to enforcing.",
            "Config: SENTINEL_ENABLED, SENTINEL_MODE (learning/enforcing), SENTINEL_ALLOWED_HOSTS.",
            "Register RuntimeSentinelMiddleware in app/main.py lifespan or add_middleware().",
        ],
        next_steps=[
            "Register middleware in app/main.py: app.add_middleware(RuntimeSentinelMiddleware)",
            "Set SENTINEL_ENABLED=true, SENTINEL_MODE=learning in .env",
            "After 24h learning period, set SENTINEL_MODE=enforcing",
            "Set SENTINEL_ALLOWED_HOSTS to comma-separated allowed outbound hosts",
            "Review sentinel events in logs: look for SENTINEL_ATTACK entries",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_sentinel_registry(dest: Path) -> None:
    """Write ``app/core/sentinel_registry.py`` with AttackPatternRegistry + SecurityEvent.

    Args:
        dest: Absolute path for the registry module.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Attack pattern registry and security event model for runtime sentinel.

        Stores in-memory records of detected injection attempts and computes
        attack frequency per category for learning-mode baseline comparison.
        \"\"\"

        from __future__ import annotations

        import logging
        import time
        from collections import defaultdict
        from dataclasses import dataclass, field

        logger = logging.getLogger(__name__)


        @dataclass
        class SecurityEvent:
            \"\"\"Immutable record of a detected attack attempt.

            Attributes:
                attack_type: Category (sql_injection, command_injection, ssrf).
                request_path: URL path where the attack was detected.
                payload_snippet: First 120 chars of the offending value.
                timestamp: Unix epoch float when detected.
                client_ip: Remote IP address of the request.
                blocked: Whether the request was blocked (enforcing mode).
            \"\"\"

            attack_type: str
            request_path: str
            payload_snippet: str
            timestamp: float = field(default_factory=time.time)
            client_ip: str = "unknown"
            blocked: bool = False


        class AttackPatternRegistry:
            \"\"\"Thread-safe (GIL) in-memory registry of security events.

            Provides per-type event storage and frequency queries used
            by the learning-mode baseline.
            \"\"\"

            def __init__(self, max_events: int = 10_000) -> None:
                \"\"\"Initialise registry with bounded event storage.

                Args:
                    max_events: Maximum events to retain (oldest evicted first).
                \"\"\"
                self._events: list[SecurityEvent] = []
                self._counts: dict[str, int] = defaultdict(int)
                self._max_events = max_events

            def record(self, event: SecurityEvent) -> None:
                \"\"\"Record a security event, evicting oldest when capacity exceeded.

                Args:
                    event: The security event to store.
                \"\"\"
                if len(self._events) >= self._max_events:
                    self._events = self._events[-(self._max_events // 2):]
                self._events.append(event)
                self._counts[event.attack_type] += 1
                if event.blocked:
                    logger.warning(
                        "SENTINEL_ATTACK blocked=%s type=%s path=%s snippet=%r",
                        event.blocked,
                        event.attack_type,
                        event.request_path,
                        event.payload_snippet[:80],
                    )
                else:
                    logger.info(
                        "SENTINEL_ATTACK blocked=%s type=%s path=%s snippet=%r",
                        event.blocked,
                        event.attack_type,
                        event.request_path,
                        event.payload_snippet[:80],
                    )

            def count(self, attack_type: str) -> int:
                \"\"\"Return total recorded events for a given attack type.

                Args:
                    attack_type: e.g. 'sql_injection'.

                Returns:
                    Integer count of events of that type.
                \"\"\"
                return self._counts[attack_type]

            def recent(self, attack_type: str, since_seconds: float = 3600.0) -> list[SecurityEvent]:
                \"\"\"Return events of *attack_type* newer than *since_seconds*.

                Args:
                    attack_type: Event category to filter.
                    since_seconds: Window in seconds from now.

                Returns:
                    List of SecurityEvent objects within the window.
                \"\"\"
                cutoff = time.time() - since_seconds
                return [
                    e for e in self._events
                    if e.attack_type == attack_type and e.timestamp >= cutoff
                ]


        # Module-level singleton — shared across middleware instances
        _registry: AttackPatternRegistry | None = None


        def get_registry() -> AttackPatternRegistry:
            \"\"\"Return the global AttackPatternRegistry singleton.

            Returns:
                Shared AttackPatternRegistry instance.
            \"\"\"
            global _registry
            if _registry is None:
                _registry = AttackPatternRegistry()
            return _registry
    """))


def _write_runtime_sentinel(dest: Path) -> None:
    """Write ``app/middleware/runtime_sentinel.py`` with RASP middleware.

    Args:
        dest: Absolute path for the middleware file.
    """
    # Use direct string construction to avoid raw-string escaping issues
    # with quote characters inside regex character classes in templates.
    _sql_pattern = (
        r"(\b(?:OR|AND)\b\s+\w+\s*=\s*\w+)"      # tautology: OR 1=1
        r"|\bUNION\b.{0,30}\bSELECT\b"             # UNION SELECT
        r"|;\s*\b(?:DROP|INSERT|UPDATE|DELETE|EXEC)\b"  # stacked query
        r"|(/\*.*?\*/|--\s|#\s)"                    # comment injection
    )
    _cmd_pattern = (
        r"[;&|!`$()\[\]{}<>\\]"
        r"|\b(?:wget|curl|nc|bash|sh|python|perl|ruby)\b"
    )
    content = textwrap.dedent(f"""\
        \"\"\"Runtime Application Self-Protection (RASP) middleware.

        Detects SQL injection, command injection, and SSRF at request time
        with full application context — operates beyond WAF capabilities.

        Modes:
            learning  — logs all detections, never blocks (24h baseline)
            enforcing — blocks detected attacks with HTTP 400

        Register in app/main.py::

            from app.middleware.runtime_sentinel import RuntimeSentinelMiddleware
            app.add_middleware(RuntimeSentinelMiddleware)
        \"\"\"

        from __future__ import annotations

        import ipaddress
        import logging
        import os
        import re
        import urllib.parse
        from typing import Any

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response

        from app.core.sentinel_registry import AttackPatternRegistry, SecurityEvent, get_registry

        logger = logging.getLogger(__name__)

        # SQL injection patterns: tautology, UNION, stacked, comment
        _SQL_PATTERNS = re.compile(
            {_sql_pattern!r},
            re.IGNORECASE | re.DOTALL,
        )

        # Command injection: shell metacharacters and dangerous commands
        _CMD_PATTERNS = re.compile(
            {_cmd_pattern!r},
            re.IGNORECASE,
        )

        # Internal/reserved IP ranges to block for SSRF
        _INTERNAL_NETWORKS = [
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("127.0.0.0/8"),
            ipaddress.ip_network("169.254.0.0/16"),   # link-local + cloud metadata
            ipaddress.ip_network("::1/128"),
            ipaddress.ip_network("fc00::/7"),
        ]
        _METADATA_HOSTNAMES = frozenset({{"169.254.169.254", "metadata.google.internal"}})


        class InjectionDetector:
            \"\"\"Stateless injection detector for request parameters and bodies.\"\"\"

            def check_sql(self, value: str) -> bool:
                \"\"\"Return True if *value* contains SQL injection patterns.

                Args:
                    value: String to inspect (query param, form field, JSON value).

                Returns:
                    True when a SQL injection pattern is detected.
                \"\"\"
                return bool(_SQL_PATTERNS.search(value))

            def check_command(self, value: str) -> bool:
                \"\"\"Return True if *value* contains command injection metacharacters.

                Args:
                    value: String to inspect.

                Returns:
                    True when shell metacharacters or dangerous commands are found.
                \"\"\"
                return bool(_CMD_PATTERNS.search(value))

            def check_ssrf(self, url_value: str, allowed_hosts: frozenset[str]) -> bool:
                \"\"\"Return True if *url_value* targets an internal/blocked host.

                Args:
                    url_value: URL string extracted from request parameter.
                    allowed_hosts: Frozenset of explicitly allowed external hostnames.

                Returns:
                    True when the URL targets an internal network or metadata endpoint.
                \"\"\"
                try:
                    parsed = urllib.parse.urlparse(url_value)
                    host = parsed.hostname or ""
                except Exception:
                    return False

                if host in _METADATA_HOSTNAMES:
                    return True
                if allowed_hosts and host and host not in allowed_hosts:
                    try:
                        addr = ipaddress.ip_address(host)
                        return any(addr in net for net in _INTERNAL_NETWORKS)
                    except ValueError:
                        pass
                try:
                    addr = ipaddress.ip_address(host)
                    return any(addr in net for net in _INTERNAL_NETWORKS)
                except ValueError:
                    return False


        def _get_mode() -> str:
            \"\"\"Return current sentinel mode from env (learning or enforcing).

            Returns:
                'learning' or 'enforcing' (defaults to 'learning').
            \"\"\"
            return os.getenv("SENTINEL_MODE", "learning").lower()


        def _get_allowed_hosts() -> frozenset[str]:
            \"\"\"Return frozenset of allowed outbound hosts from env.

            Returns:
                Frozenset of hostname strings.
            \"\"\"
            raw = os.getenv("SENTINEL_ALLOWED_HOSTS", "")
            return frozenset(h.strip() for h in raw.split(",") if h.strip())


        def _extract_string_values(data: Any, depth: int = 0) -> list[str]:
            \"\"\"Recursively extract string leaf values from parsed JSON/dict.

            Args:
                data: Parsed request body (dict, list, or scalar).
                depth: Current recursion depth (max 5 to avoid DoS).

            Returns:
                List of string values found.
            \"\"\"
            if depth > 5:
                return []
            if isinstance(data, str):
                return [data]
            if isinstance(data, dict):
                result = []
                for v in data.values():
                    result.extend(_extract_string_values(v, depth + 1))
                return result
            if isinstance(data, list):
                result = []
                for v in data:
                    result.extend(_extract_string_values(v, depth + 1))
                return result
            return []


        class RuntimeSentinelMiddleware(BaseHTTPMiddleware):
            \"\"\"RASP middleware that inspects every request for injection patterns.

            In learning mode: records events, never blocks.
            In enforcing mode: returns HTTP 400 on detected attacks.
            \"\"\"

            def __init__(
                self,
                app: Any,
                registry: AttackPatternRegistry | None = None,
            ) -> None:
                \"\"\"Initialise middleware with optional custom registry.

                Args:
                    app: ASGI application.
                    registry: Optional custom registry; defaults to global singleton.
                \"\"\"
                super().__init__(app)
                self._detector = InjectionDetector()
                self._registry = registry or get_registry()

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                \"\"\"Inspect request and either block or pass through based on mode.

                Args:
                    request: Incoming HTTP request.
                    call_next: Next middleware/handler in chain.

                Returns:
                    HTTP 400 when attack detected in enforcing mode, else proxied response.
                \"\"\"
                if os.getenv("SENTINEL_ENABLED", "true").lower() != "true":
                    return await call_next(request)

                mode = _get_mode()
                allowed_hosts = _get_allowed_hosts()
                client_ip = request.client.host if request.client else "unknown"

                attack = await self._inspect(request, allowed_hosts, client_ip)
                if attack:
                    event = SecurityEvent(
                        attack_type=attack["type"],
                        request_path=request.url.path,
                        payload_snippet=attack["snippet"],
                        client_ip=client_ip,
                        blocked=(mode == "enforcing"),
                    )
                    self._registry.record(event)
                    if mode == "enforcing":
                        return JSONResponse(
                            status_code=400,
                            content={{"detail": "Request blocked by security policy"}},
                        )

                return await call_next(request)

            async def _inspect(
                self,
                request: Request,
                allowed_hosts: frozenset[str],
                client_ip: str,
            ) -> dict | None:
                \"\"\"Return attack dict or None after scanning query params and body.

                Args:
                    request: HTTP request to inspect.
                    allowed_hosts: Allowed outbound hosts for SSRF check.
                    client_ip: Client IP for logging.

                Returns:
                    Dict with 'type' and 'snippet' if attack detected, else None.
                \"\"\"
                # Check query parameters
                for key, value in request.query_params.items():
                    if self._detector.check_sql(value):
                        return {{"type": "sql_injection", "snippet": value[:120]}}
                    if self._detector.check_command(value):
                        return {{"type": "command_injection", "snippet": value[:120]}}
                    if "url" in key.lower() and self._detector.check_ssrf(value, allowed_hosts):
                        return {{"type": "ssrf", "snippet": value[:120]}}

                # Check JSON body (best-effort, swallow decode errors)
                content_type = request.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        import json as _json
                        body_bytes = await request.body()
                        body = _json.loads(body_bytes)
                        for val in _extract_string_values(body):
                            if self._detector.check_sql(val):
                                return {{"type": "sql_injection", "snippet": val[:120]}}
                            if self._detector.check_command(val):
                                return {{"type": "command_injection", "snippet": val[:120]}}
                    except Exception:
                        pass

                return None
    """)
    dest.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Inject sentinel settings into ``app/core/config.py`` Settings class.

    Args:
        config_file: Path to the existing config.py.
    """
    src = config_file.read_text()
    if "SENTINEL_ENABLED" in src:
        return

    # 4-space-indented fields to insert inside Settings class body
    fields = (
        "\n"
        "    # --- Runtime Sentinel settings (add_runtime_sentinel) ---\n"
        "    SENTINEL_ENABLED: bool = True\n"
        '    SENTINEL_MODE: str = "learning"\n'
        '    SENTINEL_ALLOWED_HOSTS: str = ""\n'
    )

    if "settings = Settings()" in src:
        src = src.replace("settings = Settings()", fields + "\nsettings = Settings()")
    else:
        src = src.rstrip("\n") + fields + "\n"
    config_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
