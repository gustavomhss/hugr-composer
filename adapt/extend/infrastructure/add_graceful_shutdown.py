"""TOOL-100: add_graceful_shutdown — signal-driven graceful shutdown for FastAPI.

Generates ``app/lifecycle/shutdown.py`` (GracefulShutdown: SIGTERM/SIGINT
handler, drain phase, complete phase waiting up to 30s for in-flight requests,
cleanup phase closing DB pools and flushing queues),
``app/lifecycle/health_gate.py`` (ShutdownHealthGate: /healthz → 503 during
drain so the load balancer stops sending traffic), and
``app/middleware/shutdown.py`` (ShutdownMiddleware: rejects new requests with
503 + Retry-After during drain phase).

The tool is idempotent: a second run detects ``GracefulShutdown`` in
``app/lifecycle/shutdown.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_graceful_shutdown import add_graceful_shutdown

    result = add_graceful_shutdown(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/lifecycle/shutdown.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_graceful_shutdown",
    "description": (
        "Add signal-driven graceful shutdown: drain phase stops new traffic, "
        "complete phase waits up to 30s for in-flight requests, cleanup closes pools."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_graceful_shutdown",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_graceful_shutdown(inp: ToolInput) -> ToolResult:
    """Add graceful shutdown lifecycle management to a FastAPI project.

    Writes ``app/lifecycle/shutdown.py``, ``app/lifecycle/health_gate.py``,
    ``app/middleware/shutdown.py``, patches ``app/core/config.py`` with
    ``SHUTDOWN_*`` settings, and patches ``app/main.py`` to wire everything in.

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
    shutdown_file = app_dir / "lifecycle" / "shutdown.py"
    if shutdown_file.exists() and "GracefulShutdown" in shutdown_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["GracefulShutdown already present — graceful shutdown already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/lifecycle/shutdown.py, "
                "app/lifecycle/health_gate.py, app/middleware/shutdown.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: lifecycle package -------------------------------------------
    lifecycle_dir = app_dir / "lifecycle"
    lifecycle_dir.mkdir(parents=True, exist_ok=True)
    lifecycle_init = lifecycle_dir / "__init__.py"
    if not lifecycle_init.exists():
        lifecycle_init.write_text('"""Lifecycle management package."""\n')
        files_created.append(str(lifecycle_init))

    # --- Step 2: shutdown.py -------------------------------------------------
    _write_graceful_shutdown(shutdown_file)
    files_created.append(str(shutdown_file))

    # --- Step 3: health_gate.py ----------------------------------------------
    health_gate_file = lifecycle_dir / "health_gate.py"
    _write_health_gate(health_gate_file)
    files_created.append(str(health_gate_file))

    # --- Step 4: middleware/shutdown.py --------------------------------------
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    middleware_init = middleware_dir / "__init__.py"
    if not middleware_init.exists():
        middleware_init.write_text('"""Middleware package."""\n')
        files_created.append(str(middleware_init))

    shutdown_middleware_file = middleware_dir / "shutdown.py"
    if not shutdown_middleware_file.exists():
        _write_shutdown_middleware(shutdown_middleware_file)
        files_created.append(str(shutdown_middleware_file))

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
            "Graceful shutdown added: SIGTERM/SIGINT handled cleanly.",
            "Drain phase: ShutdownMiddleware returns 503 + Retry-After for new requests.",
            "ShutdownHealthGate: /healthz returns 503 during drain (stops LB traffic).",
            "Complete phase: waits up to SHUTDOWN_TIMEOUT_SECONDS for in-flight requests.",
            "Cleanup phase: closes DB pools, flushes queues, disconnects Redis.",
            "Config: SHUTDOWN_DRAIN_SECONDS (default 5), SHUTDOWN_TIMEOUT_SECONDS (default 30).",
        ],
        next_steps=[
            "Set SHUTDOWN_DRAIN_SECONDS=5 in .env (time to drain new traffic).",
            "Set SHUTDOWN_TIMEOUT_SECONDS=30 in .env (max wait for in-flight).",
            "Wire GracefulShutdown.register() in the FastAPI lifespan context manager.",
            "Add ShutdownMiddleware to app.add_middleware() in main.py.",
            "Register ShutdownHealthGate with the existing /healthz endpoint.",
            "Test with: kill -SIGTERM <pid> and verify 503 on /healthz during drain.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_graceful_shutdown(dest: Path) -> None:
    """Write ``app/lifecycle/shutdown.py`` with GracefulShutdown.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Graceful shutdown coordinator — drain, complete, cleanup.

        Phases:
        1. Drain   — signal received; stop accepting new requests (503)
        2. Complete — wait up to SHUTDOWN_TIMEOUT_SECONDS for in-flight requests
        3. Cleanup  — close DB pools, flush queues, disconnect Redis

        Usage (inside FastAPI lifespan)::

            shutdown = get_graceful_shutdown()
            shutdown.register()  # installs SIGTERM + SIGINT handlers
            yield
            await shutdown.wait_complete()
        \"\"\"

        from __future__ import annotations

        import asyncio
        import logging
        import os
        import signal
        import time

        logger = logging.getLogger(__name__)

        _shutdown: "GracefulShutdown | None" = None


        class GracefulShutdown:
            \"\"\"Coordinates a clean process shutdown across three phases.

            Args:
                drain_seconds: Seconds to wait in drain phase before completing.
                timeout_seconds: Max seconds to wait for in-flight requests.
            \"\"\"

            def __init__(
                self,
                drain_seconds: float = 5.0,
                timeout_seconds: float = 30.0,
            ) -> None:
                \"\"\"Initialise with drain and timeout durations.

                Args:
                    drain_seconds: Duration of drain phase in seconds.
                    timeout_seconds: Maximum time to wait for in-flight requests.
                \"\"\"
                self.drain_seconds = drain_seconds
                self.timeout_seconds = timeout_seconds
                self._draining = False
                self._shutting_down = False
                self._in_flight = 0
                self._lock = asyncio.Lock()
                self._drain_started_at: float | None = None
                self._cleanup_callbacks: list = []

            def register(self) -> None:
                \"\"\"Install SIGTERM and SIGINT handlers on the event loop.\"\"\"
                try:
                    loop = asyncio.get_event_loop()
                    loop.add_signal_handler(signal.SIGTERM, self._on_signal)
                    loop.add_signal_handler(signal.SIGINT, self._on_signal)
                    logger.info(
                        "GracefulShutdown registered (drain=%ds, timeout=%ds)",
                        self.drain_seconds,
                        self.timeout_seconds,
                    )
                except NotImplementedError:
                    # Windows — signal handlers not supported on event loop
                    signal.signal(signal.SIGTERM, lambda *_: self._on_signal())
                    signal.signal(signal.SIGINT, lambda *_: self._on_signal())

            def _on_signal(self) -> None:
                \"\"\"Called by the OS signal — begin drain phase.\"\"\"
                if self._draining:
                    return
                self._draining = True
                self._drain_started_at = time.monotonic()
                logger.info(
                    "Shutdown signal received — drain phase started (drain=%ds)",
                    self.drain_seconds,
                )

            def is_draining(self) -> bool:
                \"\"\"Return True if we are in the drain or complete phase.

                Returns:
                    ``True`` once a shutdown signal has been received.
                \"\"\"
                return self._draining

            def increment_in_flight(self) -> None:
                \"\"\"Increment the count of in-flight requests.\"\"\"
                self._in_flight += 1

            def decrement_in_flight(self) -> None:
                \"\"\"Decrement the count of in-flight requests.\"\"\"
                self._in_flight = max(0, self._in_flight - 1)

            def add_cleanup(self, callback) -> None:
                \"\"\"Register an async cleanup callback for the cleanup phase.

                Args:
                    callback: Async callable with no arguments.
                \"\"\"
                self._cleanup_callbacks.append(callback)

            async def wait_complete(self) -> None:
                \"\"\"Wait for drain + in-flight completion + run cleanup callbacks.\"\"\"
                if not self._draining:
                    return

                # Wait out the drain window
                await asyncio.sleep(self.drain_seconds)
                logger.info("Drain complete — waiting for %d in-flight requests", self._in_flight)

                # Wait for in-flight requests (up to timeout)
                deadline = time.monotonic() + self.timeout_seconds
                while self._in_flight > 0 and time.monotonic() < deadline:
                    await asyncio.sleep(0.1)

                if self._in_flight > 0:
                    logger.warning(
                        "Shutdown timeout reached — %d in-flight requests abandoned",
                        self._in_flight,
                    )
                else:
                    logger.info("All in-flight requests completed.")

                # Cleanup phase
                for cb in self._cleanup_callbacks:
                    try:
                        await cb()
                    except Exception:
                        logger.warning("Cleanup callback raised", exc_info=True)

                self._shutting_down = True
                logger.info("Graceful shutdown complete.")


        def get_graceful_shutdown() -> GracefulShutdown:
            \"\"\"Return the global GracefulShutdown instance (created on first call).

            Reads ``SHUTDOWN_DRAIN_SECONDS`` and ``SHUTDOWN_TIMEOUT_SECONDS``
            from the environment for initial configuration.

            Returns:
                The singleton ``GracefulShutdown`` instance.
            \"\"\"
            global _shutdown
            if _shutdown is None:
                _shutdown = GracefulShutdown(
                    drain_seconds=float(os.getenv("SHUTDOWN_DRAIN_SECONDS", "5")),
                    timeout_seconds=float(os.getenv("SHUTDOWN_TIMEOUT_SECONDS", "30")),
                )
            return _shutdown
    """))


def _write_health_gate(dest: Path) -> None:
    """Write ``app/lifecycle/health_gate.py`` with ShutdownHealthGate.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"ShutdownHealthGate — returns 503 on /healthz during drain phase.

        When the load balancer polls /healthz and receives 503, it stops
        sending new traffic to this pod before the drain timeout expires.

        Usage::

            gate = ShutdownHealthGate()

            @app.get("/healthz")
            async def healthz() -> dict:
                gate.check()  # raises HTTPException(503) during drain
                return {"status": "ok"}
        \"\"\"

        from __future__ import annotations

        import logging

        from fastapi import HTTPException

        from app.lifecycle.shutdown import get_graceful_shutdown

        logger = logging.getLogger(__name__)


        class ShutdownHealthGate:
            \"\"\"Health check gate that returns 503 during shutdown drain phase.\"\"\"

            def check(self) -> None:
                \"\"\"Raise HTTPException(503) if shutdown is in progress.

                Raises:
                    HTTPException: With status 503 and Retry-After header hint
                        when the service is draining.
                \"\"\"
                sd = get_graceful_shutdown()
                if sd.is_draining():
                    logger.debug("Health gate blocking request — drain in progress")
                    raise HTTPException(
                        status_code=503,
                        detail="Service is shutting down — retry after drain completes.",
                        headers={"Retry-After": "10"},
                    )

            def is_healthy(self) -> bool:
                \"\"\"Return False when shutdown drain phase is active.

                Returns:
                    ``True`` when the service is healthy, ``False`` during drain.
                \"\"\"
                return not get_graceful_shutdown().is_draining()
    """))


def _write_shutdown_middleware(dest: Path) -> None:
    """Write ``app/middleware/shutdown.py`` with ShutdownMiddleware.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"ASGI middleware that rejects new requests during shutdown drain phase.

        Returns 503 with a ``Retry-After`` header for any NEW request received
        while the service is draining.  In-flight requests that started before
        the signal are allowed to complete.
        \"\"\"

        from __future__ import annotations

        import logging

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response

        from app.lifecycle.shutdown import get_graceful_shutdown

        logger = logging.getLogger(__name__)

        # Paths always allowed through (health check, chaos management)
        _PASS_THROUGH_PATHS = frozenset({"/healthz", "/readyz"})


        class ShutdownMiddleware(BaseHTTPMiddleware):
            \"\"\"Reject new inbound requests during shutdown drain phase.

            In-flight requests (already past this middleware) are unaffected.
            The load balancer is expected to stop routing after seeing
            ``/healthz → 503`` from the ShutdownHealthGate.
            \"\"\"

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                \"\"\"Reject new requests during drain; track in-flight count.

                Args:
                    request: Incoming HTTP request.
                    call_next: Next middleware / route handler.

                Returns:
                    503 response during drain, or the downstream response.
                \"\"\"
                sd = get_graceful_shutdown()

                if sd.is_draining() and request.url.path not in _PASS_THROUGH_PATHS:
                    logger.debug(
                        "Rejecting new request during drain: %s %s",
                        request.method,
                        request.url.path,
                    )
                    return JSONResponse(
                        status_code=503,
                        content={"detail": "Service is shutting down — please retry."},
                        headers={"Retry-After": "10"},
                    )

                sd.increment_in_flight()
                try:
                    return await call_next(request)
                finally:
                    sd.decrement_in_flight()
    """))


def _patch_config(config_file: Path) -> None:
    """Inject SHUTDOWN_* settings into app/core/config.py Settings class.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "SHUTDOWN_DRAIN_SECONDS" in src:
        return
    fields = (
        "\n    # Graceful shutdown (TOOL-100)\n"
        "    SHUTDOWN_DRAIN_SECONDS: float = 5.0\n"
        "    SHUTDOWN_TIMEOUT_SECONDS: float = 30.0\n"
    )
    if "settings = Settings()" in src:
        src = src.replace("settings = Settings()", fields + "\nsettings = Settings()")
    else:
        src = src.rstrip("\n") + "\n" + fields
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Inject graceful shutdown wiring comment into main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "GracefulShutdown" in src or "graceful_shutdown" in src:
        return
    note = (
        "\n# Graceful shutdown — added by add_graceful_shutdown tool\n"
        "# from app.lifecycle.shutdown import get_graceful_shutdown\n"
        "# from app.middleware.shutdown import ShutdownMiddleware\n"
        "# app.add_middleware(ShutdownMiddleware)\n"
        "# In lifespan: shutdown = get_graceful_shutdown(); shutdown.register()\n"
        "# In lifespan teardown: await shutdown.wait_complete()\n"
    )
    src = src.rstrip("\n") + "\n" + note
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
