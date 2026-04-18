"""TOOL-098: add_retry_budget — global retry budget to prevent retry storms.

Generates ``app/resilience/retry_budget.py`` with a ``RetryBudget`` class that
tracks retry ratio globally using a sliding window, blocks retries when the
ratio exceeds the configured limit (default 10% of total traffic), a
``@with_retry_budget("stripe")`` decorator, and a status endpoint at
``GET /resilience/retry-budget``.

The tool is idempotent: a second run detects ``RetryBudget`` in
``app/resilience/retry_budget.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_retry_budget import add_retry_budget

    result = add_retry_budget(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/resilience/retry_budget.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_retry_budget",
    "description": (
        "Add a global retry budget to limit retries to 10% of traffic, "
        "preventing retry storms from turning a blip into an outage."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_retry_budget",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_retry_budget(inp: ToolInput) -> ToolResult:
    """Add retry budget pattern to a FastAPI project.

    Writes ``app/resilience/retry_budget.py``, ``app/resilience/retry_decorator.py``,
    ``app/api/routes/retry_status.py``, patches ``app/core/config.py`` with
    ``RETRY_BUDGET_*`` settings, and registers the route in ``app/main.py``.

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
        return ToolResult(
            status="error",
            error=err,
            execution_time_ms=_elapsed_ms(start),
        )

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
    budget_file = app_dir / "resilience" / "retry_budget.py"
    if budget_file.exists() and "RetryBudget" in budget_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["RetryBudget already present — retry budget already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create retry_budget.py, retry_decorator.py, "
                "retry_status.py, and patch config.py."
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

    # --- Step 2: retry_budget.py ---------------------------------------------
    _write_retry_budget(budget_file)
    files_created.append(str(budget_file))

    # --- Step 3: retry_decorator.py ------------------------------------------
    decorator_file = resilience_dir / "retry_decorator.py"
    _write_retry_decorator(decorator_file)
    files_created.append(str(decorator_file))

    # --- Step 4: retry_status route ------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        status_route = routes_dir / "retry_status.py"
        _write_retry_status_route(status_route)
        files_created.append(str(status_route))

    # --- Step 5: Patch config.py ---------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 6: Patch main.py -----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

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
            "Retry budget added: limits retries to RETRY_BUDGET_RATIO of total traffic.",
            "Uses a sliding window (RETRY_BUDGET_WINDOW_S) to track request/retry counts.",
            "Requires MIN_REQUESTS before enforcing the budget (warm-up period).",
            "Decorator: @with_retry_budget('stripe') wraps any async function.",
            "Status endpoint: GET /resilience/retry-budget (per-service ratio).",
            "BudgetExhaustedError raised when budget exceeded — catch in callers.",
        ],
        next_steps=[
            "Set RETRY_BUDGET_RATIO=0.1 in .env (10% default).",
            "Set RETRY_BUDGET_WINDOW_S=60 in .env.",
            "Set RETRY_BUDGET_MIN_REQUESTS=10 in .env.",
            "Use @with_retry_budget('payment_service') on retry wrappers.",
            "Catch BudgetExhaustedError to return 503 instead of retrying.",
            "Wire retry_status_router into app.include_router() in main.py.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_retry_budget(dest: Path) -> None:
    """Write ``app/resilience/retry_budget.py`` with RetryBudget class.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Global retry budget — prevents retry storms.

        Tracks the ratio of retries to total requests in a sliding time window.
        When the ratio exceeds the budget threshold, retries are rejected.

        Usage::

            budget = get_retry_budget("stripe")
            if budget.can_retry():
                budget.record_retry()
                ...  # perform retry
            else:
                raise BudgetExhaustedError("stripe")
        \"\"\"

        from __future__ import annotations

        import logging
        import threading
        import time
        from collections import deque

        logger = logging.getLogger(__name__)

        _budgets: dict[str, "RetryBudget"] = {}
        _lock = threading.Lock()


        class BudgetExhaustedError(Exception):
            \"\"\"Raised when the retry budget for a service is exhausted.\"\"\"


        class RetryBudget:
            \"\"\"Sliding-window retry budget tracker.

            Tracks total requests and retries over a rolling window.
            Blocks retries when ``retries / total > ratio``.

            Args:
                service: Logical service name (e.g. ``\"stripe\"``).
                ratio: Maximum allowed retry fraction (default 0.10).
                window_s: Sliding window width in seconds (default 60).
                min_requests: Minimum requests before enforcing the budget.
            \"\"\"

            def __init__(
                self,
                service: str,
                ratio: float = 0.10,
                window_s: float = 60.0,
                min_requests: int = 10,
            ) -> None:
                \"\"\"Initialise a new retry budget for *service*.

                Args:
                    service: Service name used in logs and error messages.
                    ratio: Max retries / total requests before blocking.
                    window_s: Sliding window width in seconds.
                    min_requests: Warm-up: enforce budget only above this count.
                \"\"\"
                self.service = service
                self.ratio = ratio
                self.window_s = window_s
                self.min_requests = min_requests
                self._requests: deque[float] = deque()
                self._retries: deque[float] = deque()
                self._lock = threading.Lock()

            def record_request(self) -> None:
                \"\"\"Record a new inbound request for this service.\"\"\"
                now = time.monotonic()
                with self._lock:
                    self._requests.append(now)
                    self._evict(now)

            def record_retry(self) -> None:
                \"\"\"Record a retry attempt for this service.\"\"\"
                now = time.monotonic()
                with self._lock:
                    self._retries.append(now)
                    self._evict(now)

            def can_retry(self) -> bool:
                \"\"\"Return True if a retry is allowed under the current budget.

                Returns:
                    ``True`` when retries are within budget or warm-up not complete.
                \"\"\"
                now = time.monotonic()
                with self._lock:
                    self._evict(now)
                    total = len(self._requests)
                    if total < self.min_requests:
                        return True
                    retries = len(self._retries)
                    current_ratio = retries / total if total else 0.0
                    allowed = current_ratio < self.ratio
                    if not allowed:
                        logger.warning(
                            "Retry budget exhausted for %s: %.1f%% >= %.1f%%",
                            self.service,
                            current_ratio * 100,
                            self.ratio * 100,
                        )
                    return allowed

            def current_ratio(self) -> float:
                \"\"\"Return the current retry ratio for observability.

                Returns:
                    Float in [0.0, 1.0] representing retries / total requests.
                \"\"\"
                now = time.monotonic()
                with self._lock:
                    self._evict(now)
                    total = len(self._requests)
                    retries = len(self._retries)
                    return retries / total if total > 0 else 0.0

            def stats(self) -> dict:
                \"\"\"Return current budget statistics dict.

                Returns:
                    Dict with keys: service, total_requests, total_retries,
                    current_ratio, budget_ratio, budget_exhausted.
                \"\"\"
                now = time.monotonic()
                with self._lock:
                    self._evict(now)
                    total = len(self._requests)
                    retries = len(self._retries)
                ratio = retries / total if total > 0 else 0.0
                return {
                    "service": self.service,
                    "total_requests": total,
                    "total_retries": retries,
                    "current_ratio": round(ratio, 4),
                    "budget_ratio": self.ratio,
                    "budget_exhausted": ratio >= self.ratio and total >= self.min_requests,
                }

            def _evict(self, now: float) -> None:
                \"\"\"Remove entries outside the sliding window (call with lock held).

                Args:
                    now: Current monotonic time.
                \"\"\"
                cutoff = now - self.window_s
                while self._requests and self._requests[0] < cutoff:
                    self._requests.popleft()
                while self._retries and self._retries[0] < cutoff:
                    self._retries.popleft()


        def get_retry_budget(
            service: str,
            ratio: float = 0.10,
            window_s: float = 60.0,
            min_requests: int = 10,
        ) -> RetryBudget:
            \"\"\"Return (and lazily create) the shared RetryBudget for *service*.

            Args:
                service: Service name. Same name returns the same instance.
                ratio: Budget ratio passed on first creation.
                window_s: Window seconds passed on first creation.
                min_requests: Warm-up count passed on first creation.

            Returns:
                The global ``RetryBudget`` instance for *service*.
            \"\"\"
            with _lock:
                if service not in _budgets:
                    _budgets[service] = RetryBudget(
                        service=service,
                        ratio=ratio,
                        window_s=window_s,
                        min_requests=min_requests,
                    )
                return _budgets[service]


        def all_budget_stats() -> list[dict]:
            \"\"\"Return stats for all registered retry budgets.

            Returns:
                List of stats dicts, one per registered service.
            \"\"\"
            with _lock:
                budgets = list(_budgets.values())
            return [b.stats() for b in budgets]
    """))


def _write_retry_decorator(dest: Path) -> None:
    """Write ``app/resilience/retry_decorator.py`` with @with_retry_budget.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Retry budget decorator for async functions.

        Usage::

            @with_retry_budget("stripe")
            async def charge_card(amount: float) -> dict:
                ...  # wrapped function records requests automatically
        \"\"\"

        from __future__ import annotations

        import functools
        import logging
        from typing import Any, Callable

        from app.resilience.retry_budget import BudgetExhaustedError, get_retry_budget

        logger = logging.getLogger(__name__)


        def with_retry_budget(
            service: str,
            ratio: float = 0.10,
            window_s: float = 60.0,
            min_requests: int = 10,
        ) -> Callable:
            \"\"\"Decorator that gates retries through a global retry budget.

            Records every call as a request.  The decorated function is
            expected to only be called when a retry is intended — each
            invocation also records a retry and raises ``BudgetExhaustedError``
            if the budget is exhausted.

            Args:
                service: Logical service name (shared budget across instances).
                ratio: Maximum retry fraction before blocking (default 0.10).
                window_s: Sliding window width in seconds (default 60).
                min_requests: Warm-up count before enforcing budget.

            Returns:
                Decorator wrapping the target async function.
            \"\"\"
            def decorator(func: Callable) -> Callable:
                @functools.wraps(func)
                async def wrapper(*args: Any, **kwargs: Any) -> Any:
                    budget = get_retry_budget(
                        service,
                        ratio=ratio,
                        window_s=window_s,
                        min_requests=min_requests,
                    )
                    budget.record_request()
                    if not budget.can_retry():
                        raise BudgetExhaustedError(
                            f"Retry budget exhausted for {service!r} "
                            f"({budget.current_ratio():.1%} >= {ratio:.1%})"
                        )
                    budget.record_retry()
                    return await func(*args, **kwargs)

                return wrapper
            return decorator
    """))


def _write_retry_status_route(dest: Path) -> None:
    """Write ``app/api/routes/retry_status.py`` with status endpoint.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Status endpoint for retry budget observability.

        Endpoints:
            GET /resilience/retry-budget — current ratio per downstream service
        \"\"\"

        from __future__ import annotations

        from fastapi import APIRouter

        from app.resilience.retry_budget import all_budget_stats

        router = APIRouter(prefix="/resilience", tags=["resilience"])


        @router.get("/retry-budget", response_model=list)
        async def get_retry_budget_status() -> list:
            \"\"\"Return current retry budget statistics for all services.

            Returns:
                List of dicts, each with: service, total_requests,
                total_retries, current_ratio, budget_ratio, budget_exhausted.
            \"\"\"
            return all_budget_stats()
    """))


def _patch_config(config_file: Path) -> None:
    """Inject RETRY_BUDGET_* settings into app/core/config.py Settings class.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "RETRY_BUDGET_RATIO" in src:
        return
    fields = (
        "\n    # Retry budget (TOOL-098)\n"
        "    RETRY_BUDGET_RATIO: float = 0.10\n"
        "    RETRY_BUDGET_WINDOW_S: float = 60.0\n"
        "    RETRY_BUDGET_MIN_REQUESTS: int = 10\n"
    )
    # Insert before the closing of the Settings class (before `settings = `)
    if "settings = Settings()" in src:
        src = src.replace("settings = Settings()", fields + "\nsettings = Settings()")
    else:
        src = src.rstrip("\n") + "\n" + fields
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Inject retry budget router into main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "retry_status" in src:
        return

    import_snippet = (
        "\nfrom app.api.routes.retry_status import router as _retry_status_router"
        "  # noqa: F401 — retry budget status\n"
    )
    wire_snippet = (
        "\n# Retry budget status router — added by add_retry_budget tool\n"
        "app.include_router(_retry_status_router)\n"
    )

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + import_snippet,
        )
    else:
        src = import_snippet + src

    src = src.rstrip("\n") + "\n" + wire_snippet
    main_file.write_text(src)


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
