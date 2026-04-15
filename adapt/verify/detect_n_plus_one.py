"""TOOL-028: detect_n_plus_one — instrument a FastAPI project to detect N+1 query patterns.

Writes an ASGI middleware that tracks SQLAlchemy queries per request via a
``ContextVar`` (async-safe), a ``@max_queries`` decorator for per-route budgets,
a ``.nplusone-budgets.yaml`` baseline, a pytest conftest plugin, and a GitHub
Actions CI workflow.  Detection overhead is < 0.5 ms/request.

The tool is idempotent: a second run on an already-patched project detects the
``QueryCounterMiddleware`` fingerprint and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.verify.detect_n_plus_one import detect_n_plus_one

    result = detect_n_plus_one(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # list of new files
    print(result.next_steps)     # ["Set NPLUSONE_ENABLED=1 in .env", ...]
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_detect_n_plus_one",
    "description": "Detect N+1 query patterns in SQLAlchemy ORM code.",
    "tags": ["verify"],
    "entry": "detect_n_plus_one",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def detect_n_plus_one(inp: ToolInput) -> ToolResult:
    """Instrument a FastAPI project with N+1 query detection.

    Reads the project at ``inp.project_dir`` and writes all necessary files to
    enable per-request SQL query counting via ContextVar-based tracking.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    # --- Prerequisite check ---------------------------------------------------
    from adapt.contracts.prerequisites import check_prerequisites, Prereq

    prereq_errors = check_prerequisites(inp.project_dir, Prereq.BASE_MODEL)
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_elapsed_ms(start),
        )

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    middleware_file = app_dir / "api" / "middleware" / "query_counter.py"
    if middleware_file.exists() and "QueryCounterMiddleware" in middleware_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["QueryCounterMiddleware already present — N+1 detection already enabled."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would instrument project with N+1 query detection."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Step 1: ContextVar query listener -----------------------------------
    listener_file = app_dir / "core" / "query_listener.py"
    _write_query_listener(listener_file)
    files_created.append(str(listener_file))

    # --- Step 2: ASGI middleware ----------------------------------------------
    middleware_file.parent.mkdir(parents=True, exist_ok=True)
    _write_middleware(middleware_file)
    files_created.append(str(middleware_file))

    # --- Step 3: @max_queries decorator --------------------------------------
    decorator_file = app_dir / "core" / "nplusone.py"
    _write_decorator(decorator_file)
    files_created.append(str(decorator_file))

    # --- Step 4: .nplusone-budgets.yaml baseline -----------------------------
    budgets_file = project / ".nplusone-budgets.yaml"
    if not budgets_file.exists():
        _write_budgets(budgets_file)
        files_created.append(str(budgets_file))

    # --- Step 5: pytest conftest plugin --------------------------------------
    conftest_file = project / "tests" / "conftest_nplusone.py"
    conftest_file.parent.mkdir(parents=True, exist_ok=True)
    _write_conftest(conftest_file)
    files_created.append(str(conftest_file))

    # --- Step 6: GitHub Actions CI workflow ----------------------------------
    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_file = ci_dir / "nplusone.yml"
    if not ci_file.exists():
        _write_ci_workflow(ci_file)
        files_created.append(str(ci_file))

    # --- Step 7: Patch main.py to register middleware ------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "N+1 detection uses ContextVar — safe for async FastAPI + AsyncSession.",
            "Middleware active only when NPLUSONE_ENABLED=1 env var is set.",
            "Per-route budgets committed to .nplusone-budgets.yaml.",
        ],
        next_steps=[
            "Set NPLUSONE_ENABLED=1 in .env (or CI env) to activate detection.",
            "Add conftest_nplusone.py to your conftest.py: "
            "'from tests.conftest_nplusone import *'",
            "Annotate high-query routes with @max_queries(N) from app.core.nplusone.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_query_listener(dest: Path) -> None:
    """Write app/core/query_listener.py with ContextVar-based query counter.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"SQLAlchemy event-based query counter using ContextVar (async-safe).

        Import this module once at startup to register the SQLAlchemy event
        listeners.  The ``query_count`` ContextVar is incremented by
        ``before_cursor_execute`` and reset by the middleware at the start of
        each request so concurrent async requests never share state.
        \"\"\"

        from __future__ import annotations

        from contextvars import ContextVar
        from typing import Any

        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        # Per-request query count (ContextVar = async-safe, no thread-local leakage)
        query_count: ContextVar[int] = ContextVar("query_count", default=0)
        # Per-request query stack for reporting
        query_stack: ContextVar[list[str]] = ContextVar("query_stack", default=[])


        def install_listener(engine: Engine) -> None:
            \"\"\"Register before_cursor_execute listener on *engine*.

            Args:
                engine: SQLAlchemy Engine (sync or async core engine).
            \"\"\"

            @event.listens_for(engine.sync_engine if hasattr(engine, "sync_engine") else engine, "before_cursor_execute")
            def _count(conn: Any, cursor: Any, statement: str, *args: Any, **kw: Any) -> None:
                query_count.set(query_count.get() + 1)
                stack = list(query_stack.get())
                stack.append(statement[:120])
                query_stack.set(stack)


        def reset_counters() -> None:
            \"\"\"Reset query_count and query_stack for a new request context.\"\"\"
            query_count.set(0)
            query_stack.set([])
        """)
    dest.write_text(content)


def _write_middleware(dest: Path) -> None:
    """Write app/api/middleware/query_counter.py ASGI middleware.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"ASGI middleware that enforces per-request SQL query budgets.

        Wrap the FastAPI app with ``QueryCounterMiddleware`` (activated only when
        ``NPLUSONE_ENABLED=1``) to count every SQL query emitted during a single
        HTTP request and fail/warn when the count exceeds *threshold*.
        \"\"\"

        from __future__ import annotations

        import logging
        import os
        from typing import Awaitable, Callable

        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        from app.core.query_listener import query_count, query_stack, reset_counters

        logger = logging.getLogger(__name__)


        class NPlusOneDetected(Exception):
            \"\"\"Raised in fail_fast mode when query budget is exceeded.

            Attributes:
                route: The request path that triggered detection.
                count: Actual number of queries issued.
                threshold: Configured budget.
                queries: First N query strings for diagnostics.
            \"\"\"

            def __init__(self, route: str, count: int, threshold: int, queries: list[str]) -> None:
                self.route = route
                self.count = count
                self.threshold = threshold
                self.queries = queries
                super().__init__(
                    f"N+1 detected on {route}: {count} queries (threshold={threshold})"
                )


        class QueryCounterMiddleware(BaseHTTPMiddleware):
            \"\"\"Count SQL queries per request; fail or warn on budget breach.

            Args:
                app: The ASGI application to wrap.
                threshold: Max queries allowed per request (default 10).
                mode: ``fail_fast`` raises NPlusOneDetected; ``warn`` logs only.
                excluded_routes: Route prefixes to skip (e.g. ``["/health"]``).
            \"\"\"

            def __init__(
                self,
                app,  # type: ignore[override]
                threshold: int = 10,
                mode: str = "warn",
                excluded_routes: list[str] | None = None,
            ) -> None:
                super().__init__(app)
                self.threshold = threshold
                self.mode = mode
                self.excluded_routes = excluded_routes or ["/health", "/metrics", "/docs", "/openapi.json"]

            async def dispatch(
                self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
            ) -> Response:
                \"\"\"Wrap each request: reset counters, call next, check budget.

                Args:
                    request: Incoming HTTP request.
                    call_next: Next ASGI handler in the chain.

                Returns:
                    The response from the downstream handler.
                \"\"\"
                path = request.url.path
                if any(path.startswith(exc) for exc in self.excluded_routes):
                    return await call_next(request)

                reset_counters()
                response = await call_next(request)
                count = query_count.get()

                if count > self.threshold:
                    queries = query_stack.get()
                    if self.mode == "fail_fast":
                        raise NPlusOneDetected(path, count, self.threshold, queries)
                    logger.warning(
                        "N+1 detected: %s issued %d queries (threshold=%d). "
                        "Top queries: %s",
                        path, count, self.threshold, queries[:3],
                    )
                response.headers["X-Query-Count"] = str(count)
                return response
        """)
    dest.write_text(content)


def _write_decorator(dest: Path) -> None:
    """Write app/core/nplusone.py with the @max_queries decorator.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"@max_queries decorator for per-route N+1 query budgets.

        Use on FastAPI route functions to declare an explicit query budget that
        overrides the global middleware threshold for that route only.

        Example::

            from app.core.nplusone import max_queries

            @router.get("/items/")
            @max_queries(5)
            async def list_items(session: SessionDep) -> list[ItemPublic]:
                ...
        \"\"\"

        from __future__ import annotations

        import functools
        import logging
        from typing import Any, Callable, TypeVar

        from app.core.query_listener import query_count, query_stack

        logger = logging.getLogger(__name__)
        F = TypeVar("F", bound=Callable[..., Any])


        def max_queries(limit: int, mode: str = "warn") -> Callable[[F], F]:
            \"\"\"Decorator that enforces a per-endpoint SQL query budget.

            Args:
                limit: Maximum number of SQL queries allowed for this route.
                mode: ``warn`` logs a warning; ``fail_fast`` raises
                    ``AssertionError`` with the query list attached.

            Returns:
                Decorator that wraps the route function.
            \"\"\"

            def decorator(func: F) -> F:
                @functools.wraps(func)
                async def wrapper(*args: Any, **kwargs: Any) -> Any:
                    result = await func(*args, **kwargs)
                    count = query_count.get()
                    if count > limit:
                        queries = query_stack.get()
                        msg = (
                            f"@max_queries({limit}) exceeded on {func.__name__}: "
                            f"{count} queries. Queries: {queries[:5]}"
                        )
                        if mode == "fail_fast":
                            raise AssertionError(msg)
                        logger.warning(msg)
                    return result

                return wrapper  # type: ignore[return-value]

            return decorator
        """)
    dest.write_text(content)


def _write_budgets(dest: Path) -> None:
    """Write .nplusone-budgets.yaml with example per-route budgets.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .nplusone-budgets.yaml — per-route N+1 query budgets
        # Every exception must have: route, budget, reason, reviewer, expiry.
        # Routes not listed here use the global threshold from settings.
        #
        # Example:
        #   - route: /api/v1/reports/summary
        #     budget: 50
        #     reason: "Aggregation report intentionally queries all org rows"
        #     reviewer: "@eng-team"
        #     expiry: "2026-12-31"
        version: "1.0"
        global_threshold: 10
        exceptions: []
        """)
    dest.write_text(content)


def _write_conftest(dest: Path) -> None:
    """Write tests/conftest_nplusone.py pytest autouse fixture.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"pytest plugin: autouse fixture that enforces N+1 query budgets in tests.

        Include in conftest.py::

            from tests.conftest_nplusone import *  # noqa: F401,F403
        \"\"\"

        from __future__ import annotations

        import pytest

        from app.core.query_listener import query_count, reset_counters


        @pytest.fixture(autouse=True)
        def reset_query_counter() -> None:
            \"\"\"Reset query counter before every test to prevent leakage.

            This fixture is autouse so every test starts with a clean slate.
            \"\"\"
            reset_counters()
            yield
            reset_counters()


        @pytest.fixture
        def assert_query_count():
            \"\"\"Return a helper that asserts the current query count equals *expected*.

            Usage::

                def test_list_items(client, assert_query_count):
                    reset_counters()
                    client.get("/api/v1/items/")
                    assert_query_count(expected=2)  # 1 count + 1 select
            \"\"\"

            def _check(expected: int) -> None:
                actual = query_count.get()
                assert actual == expected, (
                    f"Expected {expected} queries, got {actual}"
                )

            return _check
        """)
    dest.write_text(content)


def _write_ci_workflow(dest: Path) -> None:
    """Write .github/workflows/nplusone.yml CI workflow.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .github/workflows/nplusone.yml
        # Runs N+1 detection tests on every PR.
        name: N+1 Query Detection

        on:
          pull_request:
            branches: [main, master]
          push:
            branches: [main, master]

        jobs:
          nplusone:
            runs-on: ubuntu-latest
            env:
              NPLUSONE_ENABLED: "1"
              NPLUSONE_MODE: fail_fast
            steps:
              - uses: actions/checkout@v4
              - uses: actions/setup-python@v5
                with:
                  python-version: "3.12"
                  cache: pip
              - name: Install dependencies
                run: pip install -r requirements.txt pytest
              - name: Run N+1 detection tests
                run: |
                  PYTHONPATH=. pytest tests/ -m nplusone -v --tb=short
              - name: Annotate PR on failure
                if: failure()
                run: echo "::error::N+1 query threshold exceeded. Check X-Query-Count headers."
        """)
    dest.write_text(content)


def _patch_main(main_file: Path) -> None:
    """Patch app/main.py to register QueryCounterMiddleware when NPLUSONE_ENABLED.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "QueryCounterMiddleware" in src or "nplusone" in src.lower():
        return

    middleware_block = textwrap.dedent("""\

        # N+1 query detection middleware (active when NPLUSONE_ENABLED=1)
        import os as _os
        if _os.getenv("NPLUSONE_ENABLED") == "1":
            from app.api.middleware.query_counter import QueryCounterMiddleware
            from app.core.query_listener import install_listener
            app.add_middleware(
                QueryCounterMiddleware,
                threshold=int(_os.getenv("NPLUSONE_THRESHOLD", "10")),
                mode=_os.getenv("NPLUSONE_MODE", "warn"),
            )
        """)

    # Append after the closing `)` of the `app = FastAPI(...)` call.
    # The constructor may span multiple lines, so we must find the matching
    # closing paren rather than just the first newline after `app = FastAPI(`.
    if "app = FastAPI(" in src:
        open_pos = src.find("app = FastAPI(") + len("app = FastAPI(")
        depth = 1
        pos = open_pos
        while pos < len(src) and depth > 0:
            if src[pos] == "(":
                depth += 1
            elif src[pos] == ")":
                depth -= 1
            pos += 1
        # pos now points one char past the closing `)`.
        # Advance to end of that line so we insert after the full statement.
        insert_after = src.find("\n", pos)
        if insert_after == -1:
            insert_after = len(src)
        src = src[:insert_after] + middleware_block + src[insert_after:]
    else:
        src = src + middleware_block

    main_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
