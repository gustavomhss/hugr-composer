"""TOOL-095: add_load_shedding — graceful degradation under load.

Generates a LoadShedder that monitors p99 latency via sliding window and
triggers degradation tiers, a RequestPriority enum (CRITICAL/HIGH/NORMAL/LOW),
a DegradationManager that disables non-critical features, and
LoadSheddingMiddleware that rejects LOW-priority requests with 429 + Retry-After
while always passing CRITICAL traffic through.

The tool is idempotent: a second run detects ``LoadShedder`` in
``app/resilience/load_shedder.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_load_shedding import add_load_shedding

    result = add_load_shedding(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/resilience/load_shedder.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_load_shedding",
    "description": (
        "Add graceful load shedding with p99 latency monitoring, request priority "
        "tiers, and automatic degradation under sustained load."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_load_shedding",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_load_shedding(inp: ToolInput) -> ToolResult:
    """Add load shedding pattern to a FastAPI project.

    Writes ``app/resilience/load_shedder.py``, ``app/resilience/priority.py``,
    ``app/resilience/degradation.py``, ``app/middleware/load_shedding.py``,
    and patches ``app/core/config.py`` with the required env vars.

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

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    shedder_file = app_dir / "resilience" / "load_shedder.py"
    if shedder_file.exists() and "LoadShedder" in shedder_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["LoadShedder already present — load shedding already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create load_shedder.py, priority.py, degradation.py, "
                "load_shedding middleware, and patch config.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: resilience package ------------------------------------------
    resilience_dir = app_dir / "resilience"
    resilience_dir.mkdir(parents=True, exist_ok=True)
    resilience_init = resilience_dir / "__init__.py"
    if not resilience_init.exists():
        resilience_init.write_text('"""Resilience patterns package."""\n')
        files_created.append(str(resilience_init))

    _write_load_shedder(shedder_file)
    files_created.append(str(shedder_file))

    priority_file = resilience_dir / "priority.py"
    _write_priority(priority_file)
    files_created.append(str(priority_file))

    degradation_file = resilience_dir / "degradation.py"
    _write_degradation(degradation_file)
    files_created.append(str(degradation_file))

    # --- Step 2: middleware ---------------------------------------------------
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    middleware_init = middleware_dir / "__init__.py"
    if not middleware_init.exists():
        middleware_init.write_text('"""Middleware package."""\n')
        files_created.append(str(middleware_init))

    mw_file = middleware_dir / "load_shedding.py"
    _write_middleware(mw_file)
    files_created.append(str(mw_file))

    # --- Step 3: patch config.py ---------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 4: patch main.py -----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- AST validation ------------------------------------------------------
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
            "Load shedding added: p99 sliding window → degradation tiers.",
            "RequestPriority: CRITICAL always passes, LOW rejected with 429.",
            "DegradationManager disables analytics, verbose logging, low-priority webhooks.",
            "LoadSheddingMiddleware adds Retry-After header on 429 responses.",
            "Config fields: LOAD_SHEDDING_ENABLED, LOAD_SHEDDING_P99_THRESHOLD_MS, "
            "LOAD_SHEDDING_RECOVERY_WINDOW_S.",
        ],
        next_steps=[
            "Set LOAD_SHEDDING_ENABLED=true in .env to activate.",
            "Tune LOAD_SHEDDING_P99_THRESHOLD_MS (default 500ms) for your SLA.",
            "Tag CRITICAL routes (health checks, payments) in priority.py.",
            "Add LoadSheddingMiddleware to app.add_middleware() in main.py.",
            "Monitor DegradationManager.is_feature_enabled() in feature code.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_load_shedder(dest: Path) -> None:
    """Write ``app/resilience/load_shedder.py`` with p99 sliding window monitor.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"LoadShedder: p99 latency monitor with sliding window and degradation tiers.

        Usage::

            shedder = LoadShedder()
            shedder.record_latency(142.5)
            if shedder.is_shedding():
                # service is under load — shed non-critical requests
                pass
        \"\"\"

        from __future__ import annotations

        import collections
        import logging
        import time
        from enum import Enum

        logger = logging.getLogger(__name__)


        class DegradationTier(str, Enum):
            \"\"\"Load shedding degradation tiers from least to most severe.\"\"\"

            NORMAL = "normal"
            TIER_1 = "tier_1"
            TIER_2 = "tier_2"
            TIER_3 = "tier_3"


        class LoadShedder:
            \"\"\"Monitors p99 latency and decides when to shed load.

            Maintains a sliding window of recent latency samples and computes
            the p99. When p99 exceeds the threshold the shedder enters
            degradation tiers; it exits when the window clears below the threshold.

            Args:
                p99_threshold_ms: p99 latency in ms above which shedding starts.
                window_size: Number of samples to keep in the sliding window.
                recovery_window_s: Seconds of clean window before recovering.
            \"\"\"

            def __init__(
                self,
                p99_threshold_ms: float = 500.0,
                window_size: int = 100,
                recovery_window_s: float = 30.0,
            ) -> None:
                \"\"\"Initialise the LoadShedder with configurable thresholds.\"\"\"
                self._threshold_ms = p99_threshold_ms
                self._window_size = window_size
                self._recovery_s = recovery_window_s
                self._samples: collections.deque[float] = collections.deque(
                    maxlen=window_size
                )
                self._shed_since: float | None = None
                self._tier = DegradationTier.NORMAL

            def record_latency(self, latency_ms: float) -> None:
                \"\"\"Record a new latency sample and update the degradation tier.

                Args:
                    latency_ms: Request latency in milliseconds.
                \"\"\"
                self._samples.append(latency_ms)
                self._update_tier()

            def get_p99(self) -> float:
                \"\"\"Return the current p99 latency from the sliding window.

                Returns:
                    p99 latency in milliseconds, or 0.0 if no samples.
                \"\"\"
                if not self._samples:
                    return 0.0
                sorted_samples = sorted(self._samples)
                idx = max(0, int(len(sorted_samples) * 0.99) - 1)
                return sorted_samples[idx]

            def is_shedding(self) -> bool:
                \"\"\"Return True when the service is currently shedding load.\"\"\"
                return self._tier != DegradationTier.NORMAL

            def get_tier(self) -> DegradationTier:
                \"\"\"Return the current degradation tier.\"\"\"
                return self._tier

            def _update_tier(self) -> None:
                \"\"\"Recompute degradation tier based on current p99.\"\"\"
                p99 = self.get_p99()
                now = time.monotonic()

                if p99 >= self._threshold_ms * 2.0:
                    new_tier = DegradationTier.TIER_3
                elif p99 >= self._threshold_ms * 1.5:
                    new_tier = DegradationTier.TIER_2
                elif p99 >= self._threshold_ms:
                    new_tier = DegradationTier.TIER_1
                else:
                    new_tier = DegradationTier.NORMAL

                if new_tier != DegradationTier.NORMAL and self._shed_since is None:
                    self._shed_since = now
                    logger.warning(
                        "Load shedding activated: p99=%.1fms tier=%s",
                        p99, new_tier.value,
                    )
                elif new_tier == DegradationTier.NORMAL and self._shed_since is not None:
                    elapsed = now - self._shed_since
                    if elapsed >= self._recovery_s:
                        self._shed_since = None
                        logger.info("Load shedding deactivated after %.1fs recovery", elapsed)

                self._tier = new_tier


        _default_shedder: LoadShedder | None = None


        def get_load_shedder() -> LoadShedder:
            \"\"\"Return the process-global LoadShedder instance (lazy init).\"\"\"
            global _default_shedder
            if _default_shedder is None:
                _default_shedder = LoadShedder()
            return _default_shedder


        def set_load_shedder(shedder: LoadShedder) -> None:
            \"\"\"Replace the global LoadShedder (for testing and startup config).

            Args:
                shedder: New LoadShedder instance to use globally.
            \"\"\"
            global _default_shedder
            _default_shedder = shedder
    """))


def _write_priority(dest: Path) -> None:
    """Write ``app/resilience/priority.py`` with RequestPriority enum + classifier.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"RequestPriority enum and path-based priority classifier.

        Priority tiers:
            CRITICAL — health checks, payments, auth (always pass)
            HIGH     — authenticated user actions
            NORMAL   — standard API requests
            LOW      — analytics, webhooks, batch jobs (shed first)
        \"\"\"

        from __future__ import annotations

        from enum import Enum


        class RequestPriority(str, Enum):
            \"\"\"Request priority tiers for load shedding decisions.\"\"\"

            CRITICAL = "critical"
            HIGH = "high"
            NORMAL = "normal"
            LOW = "low"


        _CRITICAL_PREFIXES = ("/healthz", "/health/", "/metrics", "/payments", "/auth/")
        _HIGH_PREFIXES = ("/api/v", "/users/me")
        _LOW_PREFIXES = ("/analytics", "/webhooks/outbound", "/batch", "/exports")


        def classify_request(path: str, method: str = "GET") -> RequestPriority:
            \"\"\"Classify a request into a priority tier based on path and method.

            CRITICAL paths always return CRITICAL regardless of load.
            LOW paths are shed first under high load.

            Args:
                path: URL path of the incoming request.
                method: HTTP method (unused currently, reserved for future use).

            Returns:
                ``RequestPriority`` tier for this request.
            \"\"\"
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
    """))


def _write_degradation(dest: Path) -> None:
    """Write ``app/resilience/degradation.py`` with DegradationManager.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"DegradationManager: disable non-critical features under load.

        Usage::

            manager = DegradationManager()
            manager.set_tier(DegradationTier.TIER_1)

            if manager.is_feature_enabled("analytics_events"):
                fire_analytics()
        \"\"\"

        from __future__ import annotations

        import logging

        from app.resilience.load_shedder import DegradationTier

        logger = logging.getLogger(__name__)

        # Features disabled per tier (cumulative: higher tier disables more)
        _TIER_DISABLED: dict[DegradationTier, frozenset[str]] = {
            DegradationTier.NORMAL: frozenset(),
            DegradationTier.TIER_1: frozenset({
                "analytics_events",
                "verbose_logging",
                "non_critical_webhooks",
            }),
            DegradationTier.TIER_2: frozenset({
                "analytics_events",
                "verbose_logging",
                "non_critical_webhooks",
                "background_jobs",
                "email_notifications",
            }),
            DegradationTier.TIER_3: frozenset({
                "analytics_events",
                "verbose_logging",
                "non_critical_webhooks",
                "background_jobs",
                "email_notifications",
                "search_indexing",
                "audit_logging",
                "low_priority_reads",
            }),
        }


        class DegradationManager:
            \"\"\"Manages which features are enabled based on the current degradation tier.

            Thread-safe for read access; writes are single-threaded (from middleware).
            \"\"\"

            def __init__(self) -> None:
                \"\"\"Initialise with NORMAL tier (all features enabled).\"\"\"
                self._tier = DegradationTier.NORMAL
                self._disabled: frozenset[str] = frozenset()

            def set_tier(self, tier: DegradationTier) -> None:
                \"\"\"Update the active degradation tier.

                Args:
                    tier: New degradation tier from LoadShedder.
                \"\"\"
                if tier != self._tier:
                    logger.info(
                        "Degradation tier changed: %s → %s",
                        self._tier.value, tier.value,
                    )
                self._tier = tier
                self._disabled = _TIER_DISABLED[tier]

            def is_feature_enabled(self, feature: str) -> bool:
                \"\"\"Return True if *feature* is currently available.

                Args:
                    feature: Feature name (e.g. 'analytics_events').

                Returns:
                    True when the feature should run, False when degraded away.
                \"\"\"
                return feature not in self._disabled

            def get_tier(self) -> DegradationTier:
                \"\"\"Return the current degradation tier.\"\"\"
                return self._tier

            def disabled_features(self) -> list[str]:
                \"\"\"Return sorted list of currently disabled feature names.\"\"\"
                return sorted(self._disabled)


        _default_manager: DegradationManager | None = None


        def get_degradation_manager() -> DegradationManager:
            \"\"\"Return the process-global DegradationManager (lazy init).\"\"\"
            global _default_manager
            if _default_manager is None:
                _default_manager = DegradationManager()
            return _default_manager
    """))


def _write_middleware(dest: Path) -> None:
    """Write ``app/middleware/load_shedding.py`` with ASGI middleware.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"LoadSheddingMiddleware: reject low-priority requests under load.

        Behaviour:
        - Records response latency into the global LoadShedder.
        - When shedding is active, rejects LOW priority with 429 + Retry-After.
        - CRITICAL requests always pass through regardless of load.
        - Updates the global DegradationManager tier on every request.
        \"\"\"

        from __future__ import annotations

        import logging
        import os
        import time

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response

        from app.resilience.degradation import get_degradation_manager
        from app.resilience.load_shedder import get_load_shedder
        from app.resilience.priority import RequestPriority, classify_request

        logger = logging.getLogger(__name__)

        _RETRY_AFTER_SECONDS = 5


        class LoadSheddingMiddleware(BaseHTTPMiddleware):
            \"\"\"Middleware that enforces load shedding based on p99 latency.\"\"\"

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                \"\"\"Process the request, shed load if necessary.

                Args:
                    request: Incoming HTTP request.
                    call_next: Next middleware / route handler.

                Returns:
                    HTTP response (429 if shed, else upstream response).
                \"\"\"
                if not _is_enabled():
                    return await call_next(request)

                priority = classify_request(request.url.path, request.method)
                shedder = get_load_shedder()

                if shedder.is_shedding() and priority == RequestPriority.LOW:
                    logger.debug(
                        "Shedding LOW priority request: %s %s",
                        request.method, request.url.path,
                    )
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Service under load — low priority request shed."},
                        headers={"Retry-After": str(_RETRY_AFTER_SECONDS)},
                    )

                start = time.monotonic()
                response = await call_next(request)
                latency_ms = (time.monotonic() - start) * 1000.0

                shedder.record_latency(latency_ms)
                manager = get_degradation_manager()
                manager.set_tier(shedder.get_tier())

                return response


        def _is_enabled() -> bool:
            \"\"\"Return True if load shedding is enabled via environment variable.\"\"\"
            return os.getenv("LOAD_SHEDDING_ENABLED", "false").lower() == "true"
    """))


def _patch_config(config_file: Path) -> None:
    """Add LOAD_SHEDDING_* fields to ``app/core/config.py`` Settings class.

    Args:
        config_file: Path to the existing config.py.
    """
    src = config_file.read_text()
    if "LOAD_SHEDDING_ENABLED" in src:
        return

    fields = (
        "\n    # Load shedding\n"
        "    LOAD_SHEDDING_ENABLED: bool = False\n"
        "    LOAD_SHEDDING_P99_THRESHOLD_MS: float = 500.0\n"
        "    LOAD_SHEDDING_RECOVERY_WINDOW_S: float = 30.0\n"
    )

    # Insert before 'settings = Settings()' or at end of class body
    if "settings = Settings()" in src:
        src = src.replace("settings = Settings()", fields + "\nsettings = Settings()")
    else:
        src = src.rstrip("\n") + "\n" + fields + "\n"

    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Add LoadSheddingMiddleware comment to main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "load_shedding" in src:
        return

    note = (
        "\n# Load shedding middleware — added by add_load_shedding tool\n"
        "# from app.middleware.load_shedding import LoadSheddingMiddleware\n"
        "# app.add_middleware(LoadSheddingMiddleware)\n"
    )
    main_file.write_text(src.rstrip("\n") + "\n" + note)


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
