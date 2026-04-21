"""TOOL-096: add_adaptive_timeouts — TimeoutBudget-based request deadlines.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy the framework-agnostic primitive
   ``core.venous.resiliency.TimeoutBudget`` into the generated project.
2. Emit a thin ``app/resilience/timeouts.py`` (≤ 20 logic lines) glue file
   that instantiates a ``MonotonicTimeoutBudget`` per request and runs the
   handler inside ``asyncio.wait_for(..., timeout=budget.remaining_ms/1000)``.
3. Emit a per-dependency ``AdaptiveTimeout`` / ``TimeoutRegistry`` helper
   that records observed latency and auto-adjusts to p99 * 1.5 — this is
   an application-level policy layered on top of the primitive.

No shipped FastAPI adapter exists for ``TimeoutBudget`` in
``core/venous/_adapters/fastapi/``; the ASGI middleware is emitted by this
tool because it is framework-specific wiring, not primitive logic.

The tool is idempotent: a second run detects the primitive's
``MonotonicTimeoutBudget`` import in ``app/resilience/timeouts.py`` and
returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_adaptive_timeouts import add_adaptive_timeouts

    result = add_adaptive_timeouts(ToolInput(project_dir="/path/to/project"))
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
        "Copy TimeoutBudget primitive into the project and wire a thin "
        "app/resilience/timeouts.py + ASGI middleware that runs requests "
        "inside asyncio.wait_for(..., timeout=budget.remaining_ms/1000)."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_adaptive_timeouts",
    "imports_primitives": [
        "core.venous.resiliency.TimeoutBudget",
    ],
    "imports_adapters": (),
}


# ---------------------------------------------------------------------------
# Glue templates (thin wiring over core.venous.resiliency.TimeoutBudget)
# ---------------------------------------------------------------------------

_TIMEOUTS_GLUE = '''\
"""Thin glue that wires the TimeoutBudget primitive into a FastAPI app.

Delegates to the primitive copied under
`core/venous/resiliency/TimeoutBudget/` by the `add_adaptive_timeouts`
tool. Re-emitted idempotently on subsequent runs. This file contains NO
business logic — deadline monotonicity, hierarchical derivation, and
context propagation (TB-INV-01..05) all live in
``core.venous.resiliency.TimeoutBudget``.

The ASGI middleware opens a fresh ``MonotonicTimeoutBudget`` per request
and executes the downstream handler via
``asyncio.wait_for(..., timeout=budget.remaining_ms()/1000)``.
"""

from __future__ import annotations

import asyncio
import os

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.venous.resiliency.TimeoutBudget import (
    MonotonicTimeoutBudget,
    TimeoutBudget,
    TimeoutBudgetExpired,
    bind,
)


def budget_for_request(request: Request) -> MonotonicTimeoutBudget:
    """Open a root TimeoutBudget for *request* using env-configured ceiling."""
    ceiling_ms = int(os.getenv("ADAPTIVE_TIMEOUT_CEILING_MS", "10000"))
    return MonotonicTimeoutBudget.from_ms(ceiling_ms, origin=request.url.path)


class TimeoutBudgetMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that binds a TimeoutBudget + enforces asyncio.wait_for."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if os.getenv("ADAPTIVE_TIMEOUT_ENABLED", "false").lower() != "true":
            return await call_next(request)
        budget = budget_for_request(request)
        timeout_s = max(0.001, budget.remaining_ms() / 1000.0)
        try:
            with bind(budget):
                return await asyncio.wait_for(call_next(request), timeout=timeout_s)
        except (asyncio.TimeoutError, TimeoutBudgetExpired):
            return JSONResponse(
                status_code=504,
                content={"detail": "Gateway timeout: request exceeded budget."},
            )


def install_adaptive_timeouts(app) -> None:
    """Attach the TimeoutBudget middleware to *app*."""
    app.add_middleware(TimeoutBudgetMiddleware)


__all__ = [
    "MonotonicTimeoutBudget",
    "TimeoutBudget",
    "TimeoutBudgetMiddleware",
    "budget_for_request",
    "install_adaptive_timeouts",
]
'''


_ADAPTIVE_TIMEOUT_GLUE = '''\
"""AdaptiveTimeout: per-dependency p99-based timeout helper (application layer).

This is a thin application-level helper that LAYERS on top of the copied
``core.venous.resiliency.TimeoutBudget`` primitive. The primitive owns the
monotonic deadline; this helper owns the observed-latency statistics used
to compute per-dependency timeouts.

Usage::

    @adaptive_timeout("stripe_api")
    async def charge_card(amount: float) -> dict:
        ...
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import time
from typing import Any, Callable

from app.resilience.timeout_registry import TimeoutRegistry, get_timeout_registry
from core.venous.resiliency.TimeoutBudget import MonotonicTimeoutBudget

logger = logging.getLogger(__name__)

_DEFAULT_FLOOR_MS = 100.0
_DEFAULT_CEILING_MS = 10_000.0


class AdaptiveTimeout:
    """Tracks latency statistics for a single downstream dependency.

    Maintains a sliding window of latency samples and computes p50/p95/p99.
    The computed timeout is ``p99 * 1.5`` clamped between floor and ceiling.
    """

    def __init__(
        self,
        name: str,
        window_size: int = 100,
        multiplier: float = 1.5,
        floor_ms: float = _DEFAULT_FLOOR_MS,
        ceiling_ms: float = _DEFAULT_CEILING_MS,
    ) -> None:
        self.name = name
        self._window_size = window_size
        self._multiplier = multiplier
        self._floor_ms = floor_ms
        self._ceiling_ms = ceiling_ms
        self._samples: list[float] = []

    def record(self, latency_ms: float) -> None:
        self._samples.append(latency_ms)
        if len(self._samples) > self._window_size:
            self._samples = self._samples[-self._window_size:]

    def get_timeout_s(self) -> float:
        if not self._samples:
            return self._ceiling_ms / 1000.0
        p99 = self._percentile(0.99)
        raw_ms = p99 * self._multiplier
        clamped_ms = max(self._floor_ms, min(self._ceiling_ms, raw_ms))
        return clamped_ms / 1000.0

    def get_stats(self) -> dict[str, float]:
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
        sorted_s = sorted(self._samples)
        idx = max(0, int(len(sorted_s) * p) - 1)
        return sorted_s[idx]

    def open_budget(self, origin: str) -> MonotonicTimeoutBudget:
        """Delegate budget creation to the primitive (TB-INV-02)."""
        return MonotonicTimeoutBudget.from_ms(
            max(1, int(self.get_timeout_s() * 1000)), origin=origin,
        )


def adaptive_timeout(
    dependency: str,
    registry: TimeoutRegistry | None = None,
) -> Callable:
    """Decorator that wraps an async function with an adaptive timeout."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if os.getenv("ADAPTIVE_TIMEOUT_ENABLED", "false").lower() != "true":
                return await func(*args, **kwargs)
            reg = registry or get_timeout_registry()
            tracker = reg.get_or_create(dependency)
            timeout_s = tracker.get_timeout_s()
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    func(*args, **kwargs), timeout=timeout_s,
                )
                tracker.record((time.monotonic() - t0) * 1000.0)
                return result
            except asyncio.TimeoutError:
                tracker.record(timeout_s * 1000.0)
                logger.warning(
                    "Adaptive timeout fired for %s after %.0fms",
                    dependency, timeout_s * 1000.0,
                )
                raise

        return wrapper
    return decorator
'''


_TIMEOUT_REGISTRY_GLUE = '''\
"""TimeoutRegistry: per-dependency AdaptiveTimeout instances.

Holds one AdaptiveTimeout per downstream dependency. Pure application-layer
bookkeeping — the deadline primitive that fires the actual timeouts lives
in ``core.venous.resiliency.TimeoutBudget``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.resilience.adaptive_timeout import AdaptiveTimeout


class TimeoutRegistry:
    """Registry that holds one AdaptiveTimeout per downstream dependency."""

    def __init__(
        self,
        window_size: int = 100,
        floor_ms: float = 100.0,
        ceiling_ms: float = 10_000.0,
    ) -> None:
        self._window_size = window_size
        self._floor_ms = floor_ms
        self._ceiling_ms = ceiling_ms
        self._trackers: dict[str, "AdaptiveTimeout"] = {}

    def get_or_create(self, name: str) -> "AdaptiveTimeout":
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
        return {name: t.get_stats() for name, t in self._trackers.items()}

    def names(self) -> list[str]:
        return sorted(self._trackers)


_default_registry: TimeoutRegistry | None = None


def get_timeout_registry() -> TimeoutRegistry:
    """Return the process-global TimeoutRegistry (lazy init from env)."""
    global _default_registry
    if _default_registry is None:
        _default_registry = TimeoutRegistry(
            window_size=int(os.getenv("ADAPTIVE_TIMEOUT_WINDOW_SIZE", "100")),
            floor_ms=float(os.getenv("ADAPTIVE_TIMEOUT_FLOOR_MS", "100")),
            ceiling_ms=float(os.getenv("ADAPTIVE_TIMEOUT_CEILING_MS", "10000")),
        )
    return _default_registry
'''


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_adaptive_timeouts(inp: ToolInput) -> ToolResult:
    """Add adaptive timeouts by delegating to the shipped TimeoutBudget primitive."""
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
            notes=["Generate a base project first via fastapi_generate_project(...)."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    resilience_dir = app_dir / "resilience"
    timeouts_glue = resilience_dir / "timeouts.py"
    adaptive_file = resilience_dir / "adaptive_timeout.py"

    # --- Idempotency guard (check for the primitive's class name) ------------
    if timeouts_glue.exists() and "MonotonicTimeoutBudget" in timeouts_glue.read_text():
        return ToolResult(
            status="no_op",
            notes=["TimeoutBudget primitive already wired via app/resilience/timeouts.py."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy TimeoutBudget primitive and write "
                "app/resilience/timeouts.py + adaptive_timeout.py + timeout_registry.py."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Copy primitive ------------------------------------------------------
    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.resiliency.TimeoutBudget"],
        adapters=[],
    )
    files_created.append(manifest.path)

    files_modified: list[str] = []

    # --- Primary glue --------------------------------------------------------
    resilience_dir.mkdir(parents=True, exist_ok=True)
    resilience_init = resilience_dir / "__init__.py"
    if not resilience_init.exists():
        resilience_init.write_text('"""Resilience patterns package."""\n')
        files_created.append(str(resilience_init))

    timeouts_glue.write_text(_TIMEOUTS_GLUE)
    files_created.append(str(timeouts_glue))

    registry_file = resilience_dir / "timeout_registry.py"
    registry_file.write_text(_TIMEOUT_REGISTRY_GLUE)
    files_created.append(str(registry_file))

    adaptive_file.write_text(_ADAPTIVE_TIMEOUT_GLUE)
    files_created.append(str(adaptive_file))

    # --- Config patch --------------------------------------------------------
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

    # --- Enforce ≤20 logic lines in the primary glue -------------------------
    glue_loc = _count_logic_lines(timeouts_glue.read_text())
    if glue_loc > 20:
        return ToolResult(
            status="error",
            error=f"Primary glue {timeouts_glue} has {glue_loc} logic lines (> 20).",
            execution_time_ms=_elapsed_ms(start),
        )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Shipped primitive: core.venous.resiliency.TimeoutBudget.",
            "Glue: app/resilience/timeouts.py wires MonotonicTimeoutBudget + asyncio.wait_for.",
            "app/resilience/adaptive_timeout.py adds per-dependency p99*1.5 stats "
            "(application layer — delegates deadlines to the primitive).",
            "TimeoutRegistry tracks each dependency independently (DB, Redis, Stripe, etc.).",
            "Config: ADAPTIVE_TIMEOUT_ENABLED, FLOOR_MS=100, CEILING_MS=10000, WINDOW_SIZE=100.",
        ],
        next_steps=[
            "Set ADAPTIVE_TIMEOUT_ENABLED=true in .env to activate.",
            "Install middleware: install_adaptive_timeouts(app) in main.py.",
            "Decorate downstream calls: @adaptive_timeout('payment_service')",
            "Catch asyncio.TimeoutError / TimeoutBudgetExpired for graceful degradation.",
            "Monitor TimeoutRegistry.get_stats() for per-service timeout values.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_config(config_file: Path) -> None:
    """Add ADAPTIVE_TIMEOUT_* fields to ``app/core/config.py`` Settings class."""
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


def _count_logic_lines(source: str) -> int:
    """Count executable logic lines — imports, class/func defs, and decorators
    do NOT count (per CONTRACT §B1.0.1).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    loc = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body:
                start = node.body[0].lineno
                end = node.end_lineno or start
                loc += end - start + 1
    return loc


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)


_ = textwrap
