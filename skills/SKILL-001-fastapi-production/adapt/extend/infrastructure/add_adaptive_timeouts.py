"""TOOL-096: add_adaptive_timeouts — self-adjusting timeouts based on observed latency.

Generates an AdaptiveTimeout that tracks p50/p95/p99 per downstream dependency
and auto-adjusts the timeout to ``p99 * 1.5`` with a configurable floor/ceiling,
a TimeoutRegistry for per-dependency tracking, and an
``@adaptive_timeout("stripe_api")`` decorator for any async function.

The tool is idempotent: a second run detects ``AdaptiveTimeout`` in
``app/resilience/adaptive_timeout.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_adaptive_timeouts import add_adaptive_timeouts

    result = add_adaptive_timeouts(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/resilience/adaptive_timeout.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_add_adaptive_timeouts",
    "description": (
        "Add self-adjusting timeouts that learn from observed downstream latency, "
        "auto-calibrating to p99 * 1.5 with configurable floor and ceiling."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_adaptive_timeouts",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_adaptive_timeouts(inp: ToolInput) -> ToolResult:
    """Add adaptive timeouts to a FastAPI project.

    Writes ``app/resilience/adaptive_timeout.py``,
    ``app/resilience/timeout_registry.py``, and patches
    ``app/core/config.py`` with the required env vars.

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
    timeout_file = app_dir / "resilience" / "adaptive_timeout.py"
    if timeout_file.exists() and "AdaptiveTimeout" in timeout_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["AdaptiveTimeout already present — adaptive timeouts already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create adaptive_timeout.py, timeout_registry.py, "
                "and patch config.py with ADAPTIVE_TIMEOUT_* fields."
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

    _write_adaptive_timeout(timeout_file)
    files_created.append(str(timeout_file))

    registry_file = resilience_dir / "timeout_registry.py"
    _write_timeout_registry(registry_file)
    files_created.append(str(registry_file))

    # --- Step 2: patch config.py ---------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

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
            "Adaptive timeouts added: p50/p95/p99 per downstream, auto-adjusts to p99*1.5.",
            "TimeoutRegistry tracks each dependency independently (DB, Redis, Stripe, etc.).",
            "Use @adaptive_timeout('stripe_api') on any async function.",
            "Config: ADAPTIVE_TIMEOUT_ENABLED, FLOOR_MS=100, CEILING_MS=10000, WINDOW_SIZE=100.",
            "Implements Google 'Tail at Scale' paper principles — prevents cascade failures.",
        ],
        next_steps=[
            "Set ADAPTIVE_TIMEOUT_ENABLED=true in .env to activate.",
            "Decorate downstream calls: @adaptive_timeout('payment_service')",
            "Catch asyncio.TimeoutError in callers for graceful degradation.",
            "Monitor TimeoutRegistry.get_stats() for per-service timeout values.",
            "Tune ADAPTIVE_TIMEOUT_FLOOR_MS and ADAPTIVE_TIMEOUT_CEILING_MS per SLA.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_adaptive_timeout(dest: Path) -> None:
    """Write ``app/resilience/adaptive_timeout.py`` with decorator + tracker.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"AdaptiveTimeout: self-adjusting timeouts based on observed latency.

        Implements the Google 'Tail at Scale' principle: timeouts LEARN from
        the actual p99 of each downstream dependency rather than using static
        values that are always either too high or too low.

        Usage::

            @adaptive_timeout("stripe_api")
            async def charge_card(amount: float) -> dict:
                async with httpx.AsyncClient() as c:
                    return await c.post(url, ...)
        \"\"\"

        from __future__ import annotations

        import asyncio
        import functools
        import logging
        import os
        import time
        from typing import Any, Callable

        from app.resilience.timeout_registry import TimeoutRegistry, get_timeout_registry

        logger = logging.getLogger(__name__)

        _DEFAULT_FLOOR_MS = 100.0
        _DEFAULT_CEILING_MS = 10_000.0


        class AdaptiveTimeout:
            \"\"\"Tracks latency statistics for a single downstream dependency.

            Maintains a sliding window of latency samples and computes p50/p95/p99.
            The computed timeout is ``p99 * 1.5`` clamped between floor and ceiling.

            Args:
                name: Logical name of the downstream dependency.
                window_size: Number of samples in the sliding window.
                multiplier: p99 multiplier for timeout calculation.
                floor_ms: Minimum timeout in milliseconds.
                ceiling_ms: Maximum timeout in milliseconds.
            \"\"\"

            def __init__(
                self,
                name: str,
                window_size: int = 100,
                multiplier: float = 1.5,
                floor_ms: float = _DEFAULT_FLOOR_MS,
                ceiling_ms: float = _DEFAULT_CEILING_MS,
            ) -> None:
                \"\"\"Initialise AdaptiveTimeout with configurable parameters.\"\"\"
                self.name = name
                self._window_size = window_size
                self._multiplier = multiplier
                self._floor_ms = floor_ms
                self._ceiling_ms = ceiling_ms
                self._samples: list[float] = []

            def record(self, latency_ms: float) -> None:
                \"\"\"Record a latency sample and trim the window.

                Args:
                    latency_ms: Observed latency in milliseconds.
                \"\"\"
                self._samples.append(latency_ms)
                if len(self._samples) > self._window_size:
                    self._samples = self._samples[-self._window_size:]

            def get_timeout_s(self) -> float:
                \"\"\"Return the current adaptive timeout in seconds.

                Returns:
                    Timeout in seconds, clamped between floor and ceiling.
                \"\"\"
                if not self._samples:
                    return self._ceiling_ms / 1000.0
                p99 = self._percentile(0.99)
                raw_ms = p99 * self._multiplier
                clamped_ms = max(self._floor_ms, min(self._ceiling_ms, raw_ms))
                return clamped_ms / 1000.0

            def get_stats(self) -> dict[str, float]:
                \"\"\"Return current percentile statistics.

                Returns:
                    Dict with p50, p95, p99 in milliseconds and current_timeout_s.
                \"\"\"
                if not self._samples:
                    return {
                        "p50": 0.0, "p95": 0.0, "p99": 0.0,
                        "current_timeout_s": self._ceiling_ms / 1000.0,
                        "sample_count": 0,
                    }
                return {
                    "p50": self._percentile(0.50),
                    "p95": self._percentile(0.95),
                    "p99": self._percentile(0.99),
                    "current_timeout_s": self.get_timeout_s(),
                    "sample_count": len(self._samples),
                }

            def _percentile(self, p: float) -> float:
                \"\"\"Compute the *p*-th percentile of current samples.

                Args:
                    p: Percentile as a fraction (e.g. 0.99 for p99).
                \"\"\"
                sorted_s = sorted(self._samples)
                idx = max(0, int(len(sorted_s) * p) - 1)
                return sorted_s[idx]


        def adaptive_timeout(
            dependency: str,
            registry: TimeoutRegistry | None = None,
        ) -> Callable:
            \"\"\"Decorator that wraps an async function with an adaptive timeout.

            The timeout is auto-adjusted based on observed latency of *dependency*.
            Each call records its latency so future calls benefit from the data.

            Args:
                dependency: Logical name of the downstream dependency.
                registry: Optional custom TimeoutRegistry (uses global if None).

            Returns:
                Decorator wrapping the async function with timeout + latency recording.
            \"\"\"
            def decorator(func: Callable) -> Callable:
                @functools.wraps(func)
                async def wrapper(*args: Any, **kwargs: Any) -> Any:
                    if not _is_enabled():
                        return await func(*args, **kwargs)

                    reg = registry or get_timeout_registry()
                    tracker = reg.get_or_create(dependency)
                    timeout_s = tracker.get_timeout_s()

                    t0 = time.monotonic()
                    try:
                        result = await asyncio.wait_for(
                            func(*args, **kwargs), timeout=timeout_s
                        )
                        latency_ms = (time.monotonic() - t0) * 1000.0
                        tracker.record(latency_ms)
                        return result
                    except asyncio.TimeoutError:
                        latency_ms = timeout_s * 1000.0
                        tracker.record(latency_ms)
                        logger.warning(
                            "Adaptive timeout fired for %s after %.0fms",
                            dependency, latency_ms,
                        )
                        raise

                return wrapper
            return decorator


        def _is_enabled() -> bool:
            \"\"\"Return True if adaptive timeouts are enabled via environment variable.\"\"\"
            return os.getenv("ADAPTIVE_TIMEOUT_ENABLED", "false").lower() == "true"
    """))


def _write_timeout_registry(dest: Path) -> None:
    """Write ``app/resilience/timeout_registry.py`` with per-dependency registry.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"TimeoutRegistry: per-dependency AdaptiveTimeout instances.

        Usage::

            registry = get_timeout_registry()
            tracker = registry.get_or_create("stripe_api")
            print(tracker.get_stats())
        \"\"\"

        from __future__ import annotations

        import os
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from app.resilience.adaptive_timeout import AdaptiveTimeout


        class TimeoutRegistry:
            \"\"\"Registry that holds one AdaptiveTimeout per downstream dependency.

            Thread-safe for read; concurrent writes are idempotent (same key
            returns the same tracker once created).
            \"\"\"

            def __init__(
                self,
                window_size: int = 100,
                floor_ms: float = 100.0,
                ceiling_ms: float = 10_000.0,
            ) -> None:
                \"\"\"Initialise an empty registry with shared defaults.

                Args:
                    window_size: Sliding window size for all trackers.
                    floor_ms: Minimum timeout in ms for all trackers.
                    ceiling_ms: Maximum timeout in ms for all trackers.
                \"\"\"
                self._window_size = window_size
                self._floor_ms = floor_ms
                self._ceiling_ms = ceiling_ms
                self._trackers: dict[str, "AdaptiveTimeout"] = {}

            def get_or_create(self, name: str) -> "AdaptiveTimeout":
                \"\"\"Return the AdaptiveTimeout for *name*, creating it if absent.

                Args:
                    name: Downstream dependency name (e.g. 'stripe_api').

                Returns:
                    ``AdaptiveTimeout`` instance for this dependency.
                \"\"\"
                if name not in self._trackers:
                    from app.resilience.adaptive_timeout import AdaptiveTimeout
                    self._trackers[name] = AdaptiveTimeout(
                        name=name,
                        window_size=self._window_size,
                        floor_ms=self._floor_ms,
                        ceiling_ms=self._ceiling_ms,
                    )
                return self._trackers[name]

            def all_stats(self) -> dict[str, dict[str, float]]:
                \"\"\"Return stats for every registered dependency.

                Returns:
                    Dict mapping dependency name → stats dict from
                    ``AdaptiveTimeout.get_stats()``.
                \"\"\"
                return {name: t.get_stats() for name, t in self._trackers.items()}

            def names(self) -> list[str]:
                \"\"\"Return sorted list of registered dependency names.\"\"\"
                return sorted(self._trackers)


        _default_registry: TimeoutRegistry | None = None


        def get_timeout_registry() -> TimeoutRegistry:
            \"\"\"Return the process-global TimeoutRegistry (lazy init from env).\"\"\"
            global _default_registry
            if _default_registry is None:
                _default_registry = TimeoutRegistry(
                    window_size=int(os.getenv("ADAPTIVE_TIMEOUT_WINDOW_SIZE", "100")),
                    floor_ms=float(os.getenv("ADAPTIVE_TIMEOUT_FLOOR_MS", "100")),
                    ceiling_ms=float(os.getenv("ADAPTIVE_TIMEOUT_CEILING_MS", "10000")),
                )
            return _default_registry
    """))


def _patch_config(config_file: Path) -> None:
    """Add ADAPTIVE_TIMEOUT_* fields to ``app/core/config.py`` Settings class.

    Args:
        config_file: Path to the existing config.py.
    """
    src = config_file.read_text()
    if "ADAPTIVE_TIMEOUT_ENABLED" in src:
        return

    fields = (
        "\n    # Adaptive timeouts\n"
        "    ADAPTIVE_TIMEOUT_ENABLED: bool = False\n"
        "    ADAPTIVE_TIMEOUT_FLOOR_MS: float = 100.0\n"
        "    ADAPTIVE_TIMEOUT_CEILING_MS: float = 10000.0\n"
        "    ADAPTIVE_TIMEOUT_WINDOW_SIZE: int = 100\n"
    )

    if "settings = Settings()" in src:
        src = src.replace("settings = Settings()", fields + "\nsettings = Settings()")
    else:
        src = src.rstrip("\n") + "\n" + fields + "\n"

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
