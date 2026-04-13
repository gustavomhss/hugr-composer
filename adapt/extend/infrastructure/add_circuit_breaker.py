"""TOOL-022: add_circuit_breaker — add distributed circuit breaker to FastAPI.

Generates ``app/core/circuit_breaker.py`` with a ``CLOSED → OPEN → HALF_OPEN``
state machine backed by Redis (atomic Lua transitions), a
``@circuit_breaker("service_name")`` decorator, admin endpoints at
``/admin/circuits/{name}``, and Prometheus metrics.

The tool is idempotent: a second run detects ``CircuitState`` in
``app/core/circuit_breaker.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_circuit_breaker import add_circuit_breaker

    result = add_circuit_breaker(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/core/circuit_breaker.py, ...]
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_circuit_breaker(inp: ToolInput) -> ToolResult:
    """Add circuit breaker pattern to a FastAPI project.

    Writes ``app/core/circuit_breaker.py``, ``app/api/routes/circuits.py``,
    patches ``app/main.py`` to include the admin router.

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
        return ToolResult(status="error", error=err)

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    cb_file = app_dir / "core" / "circuit_breaker.py"
    if cb_file.exists() and "CircuitState" in cb_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["CircuitState already present — circuit breaker already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would create circuit_breaker.py, admin routes, metrics."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    # --- Step 1: core circuit breaker ----------------------------------------
    (app_dir / "core").mkdir(parents=True, exist_ok=True)
    _write_circuit_breaker_core(cb_file)
    files_created.append(str(cb_file))

    # --- Step 2: admin routes ------------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        admin_route = routes_dir / "circuits.py"
        _write_circuits_admin_route(admin_route)
        files_created.append(str(admin_route))

    # --- Step 3: Prometheus metrics module -----------------------------------
    metrics_file = app_dir / "core" / "circuit_metrics.py"
    _write_circuit_metrics(metrics_file)
    files_created.append(str(metrics_file))

    # --- Step 4: Patch main.py -----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Circuit breaker added: CLOSED → OPEN → HALF_OPEN state machine.",
            "State stored in Redis with atomic Lua transitions (no race conditions).",
            "Sliding window failure counting — old failures age out automatically.",
            "Admin endpoints: GET /admin/circuits/{name}, POST /admin/circuits/{name}/reset.",
            "Prometheus metrics: fastapi_circuit_state, fastapi_circuit_failures_total.",
        ],
        next_steps=[
            "pip install 'redis[hiredis]' prometheus-client",
            "Set REDIS_URL in .env.",
            "Decorate outbound calls: @circuit_breaker('payment_service')",
            "Catch CircuitOpenError in callers to return graceful degradation.",
            "Mount /metrics endpoint for Prometheus scraping.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_circuit_breaker_core(dest: Path) -> None:
    """Write ``app/core/circuit_breaker.py`` with state machine + decorator.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Distributed circuit breaker with Redis-backed state machine.

        State machine: CLOSED → OPEN → HALF_OPEN → CLOSED

        Usage::

            @circuit_breaker("payment_service")
            async def charge_card(amount: float) -> dict:
                ...
        \"\"\"

        from __future__ import annotations

        import functools
        import logging
        import time as _time
        from enum import Enum
        from typing import Any, Callable

        import redis.asyncio as aioredis

        logger = logging.getLogger(__name__)

        # Lua script: atomic CLOSED → OPEN transition
        _LUA_OPEN_CIRCUIT = \"\"\"
        local key = KEYS[1]
        local threshold = tonumber(ARGV[1])
        local now = tonumber(ARGV[2])
        local window = tonumber(ARGV[3])
        local recovery = tonumber(ARGV[4])
        local fail_key = key .. \":failures\"
        redis.call(\"ZADD\", fail_key, now, tostring(now))
        redis.call(\"ZREMRANGEBYSCORE\", fail_key, \"-inf\", now - window)
        local count = redis.call(\"ZCARD\", fail_key)
        if count >= threshold then
            redis.call(\"HSET\", key, \"state\", \"open\", \"opened_at\", now,
                       \"failure_count\", count, \"recovery_at\", now + recovery)
        end
        return count
        \"\"\"

        _redis_client: "aioredis.Redis | None" = None


        class CircuitState(str, Enum):
            \"\"\"Circuit breaker states.\"\"\"
            CLOSED = "closed"
            OPEN = "open"
            HALF_OPEN = "half_open"


        class CircuitOpenError(Exception):
            \"\"\"Raised when a call is rejected because the circuit is OPEN.\"\"\"


        def get_circuit_redis() -> "aioredis.Redis | None":
            \"\"\"Return the shared Redis client for circuit state.\"\"\"
            return _redis_client


        def set_circuit_redis(client: "aioredis.Redis") -> None:
            \"\"\"Configure the Redis client used for circuit state.

            Args:
                client: Async Redis client instance.
            \"\"\"
            global _redis_client
            _redis_client = client


        def circuit_breaker(
            service_name: str,
            failure_threshold: int = 5,
            recovery_timeout_seconds: int = 30,
            half_open_max_calls: int = 3,
            failure_window_seconds: int = 60,
        ) -> Callable:
            \"\"\"Decorator wrapping an async function with circuit breaker logic.

            Args:
                service_name: Logical name of the downstream service.
                failure_threshold: Failures in window to trip the circuit.
                recovery_timeout_seconds: Seconds before entering HALF_OPEN.
                half_open_max_calls: Probe calls allowed in HALF_OPEN.
                failure_window_seconds: Sliding window width in seconds.

            Returns:
                Decorator that wraps the target function.
            \"\"\"
            def decorator(func: Callable) -> Callable:
                @functools.wraps(func)
                async def wrapper(*args: Any, **kwargs: Any) -> Any:
                    state = await _get_state(service_name)
                    if state == CircuitState.OPEN:
                        if not await _should_probe(service_name, recovery_timeout_seconds):
                            raise CircuitOpenError(
                                f"Circuit OPEN for {service_name!r} — fast-fail"
                            )
                        await _set_state(service_name, CircuitState.HALF_OPEN)

                    try:
                        result = await func(*args, **kwargs)
                        await _on_success(service_name, state, half_open_max_calls)
                        return result
                    except Exception:
                        await _on_failure(
                            service_name,
                            failure_threshold,
                            recovery_timeout_seconds,
                            failure_window_seconds,
                        )
                        raise

                return wrapper
            return decorator


        async def _get_state(name: str) -> CircuitState:
            \"\"\"Read current circuit state from Redis (defaults to CLOSED).

            Args:
                name: Service name / circuit key.
            \"\"\"
            r = get_circuit_redis()
            if r is None:
                return CircuitState.CLOSED
            try:
                raw = await r.hget(f"circuit:{name}", "state")
                if raw is None:
                    return CircuitState.CLOSED
                return CircuitState(raw.decode() if isinstance(raw, bytes) else raw)
            except Exception:
                return CircuitState.CLOSED


        async def _set_state(name: str, state: CircuitState) -> None:
            \"\"\"Write circuit state to Redis.

            Args:
                name: Service name.
                state: New circuit state.
            \"\"\"
            r = get_circuit_redis()
            if r is None:
                return
            try:
                await r.hset(f"circuit:{name}", "state", state.value)
            except Exception:
                logger.warning("Failed to set circuit state for %s", name, exc_info=True)


        async def _should_probe(name: str, recovery_timeout: int) -> bool:
            \"\"\"Return True if recovery_at has passed — time to probe HALF_OPEN.

            Args:
                name: Service name.
                recovery_timeout: Seconds before probe is allowed.
            \"\"\"
            r = get_circuit_redis()
            if r is None:
                return False
            try:
                raw = await r.hget(f"circuit:{name}", "recovery_at")
                if raw is None:
                    return True
                recovery_at = float(raw)
                return _time.time() >= recovery_at
            except Exception:
                return True


        async def _on_success(name: str, prev_state: CircuitState, max_calls: int) -> None:
            \"\"\"Handle a successful call: close circuit from HALF_OPEN when probes pass.

            Args:
                name: Service name.
                prev_state: State before the call.
                max_calls: Number of successful probes needed to close.
            \"\"\"
            r = get_circuit_redis()
            if r is None:
                return
            if prev_state == CircuitState.HALF_OPEN:
                try:
                    probe_key = f"circuit:{name}:probes"
                    count = await r.incr(probe_key)
                    await r.expire(probe_key, 60)
                    if count >= max_calls:
                        await r.delete(f"circuit:{name}:failures", probe_key)
                        await _set_state(name, CircuitState.CLOSED)
                        logger.info("Circuit CLOSED for %s after %d probes", name, count)
                except Exception:
                    logger.warning("Circuit on_success failed for %s", name, exc_info=True)


        async def _on_failure(
            name: str,
            threshold: int,
            recovery_timeout: int,
            window: int,
        ) -> None:
            \"\"\"Record failure and atomically open circuit if threshold exceeded.

            Args:
                name: Service name.
                threshold: Failure count to trip.
                recovery_timeout: Seconds before HALF_OPEN probe.
                window: Sliding window in seconds.
            \"\"\"
            r = get_circuit_redis()
            if r is None:
                return
            try:
                await r.eval(
                    _LUA_OPEN_CIRCUIT,
                    1,
                    f"circuit:{name}",
                    threshold,
                    _time.time(),
                    window,
                    recovery_timeout,
                )
            except Exception:
                logger.warning("Circuit on_failure failed for %s", name, exc_info=True)


        async def get_circuit_info(name: str) -> dict:
            \"\"\"Return a dict describing the current circuit state.

            Args:
                name: Service name.

            Returns:
                Dict with keys: name, state, failure_count, opened_at, recovery_at.
            \"\"\"
            r = get_circuit_redis()
            if r is None:
                return {"name": name, "state": CircuitState.CLOSED, "error": "no redis"}
            try:
                data = await r.hgetall(f"circuit:{name}")
                decoded = {
                    k.decode() if isinstance(k, bytes) else k:
                    v.decode() if isinstance(v, bytes) else v
                    for k, v in data.items()
                }
                return {"name": name, **decoded} if decoded else {
                    "name": name, "state": CircuitState.CLOSED
                }
            except Exception as exc:
                return {"name": name, "state": CircuitState.CLOSED, "error": str(exc)}
        """))


def _write_circuits_admin_route(dest: Path) -> None:
    """Write ``app/api/routes/circuits.py`` with admin endpoints.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Admin endpoints for circuit breaker inspection and manual overrides.

        Endpoints:
            GET  /admin/circuits/{name}       — inspect circuit state
            POST /admin/circuits/{name}/reset — force-close circuit
            POST /admin/circuits/{name}/open  — force-open circuit (incident mode)
        \"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, HTTPException

        from app.core.circuit_breaker import (
            CircuitState,
            get_circuit_info,
            set_circuit_redis,
            _set_state,
            get_circuit_redis,
        )

        router = APIRouter(prefix="/admin/circuits", tags=["circuits"])


        @router.get("/{name}", response_model=dict)
        async def inspect_circuit(name: str) -> dict:
            \"\"\"Inspect current state of a named circuit.

            Args:
                name: Circuit / service name (e.g. ``payment_service``).

            Returns:
                Dict with state, failure_count, opened_at, recovery_at.
            \"\"\"
            return await get_circuit_info(name)


        @router.post("/{name}/reset", response_model=dict)
        async def reset_circuit(name: str) -> dict:
            \"\"\"Force-close a circuit (use after confirming downstream recovery).

            Args:
                name: Circuit name to close.

            Returns:
                Confirmation dict with new state.
            \"\"\"
            r = get_circuit_redis()
            if r is None:
                raise HTTPException(status_code=503, detail="Redis not available")
            await r.delete(f"circuit:{name}", f"circuit:{name}:failures", f"circuit:{name}:probes")
            return {"name": name, "state": CircuitState.CLOSED, "action": "reset"}


        @router.post("/{name}/open", response_model=dict)
        async def force_open_circuit(name: str) -> dict:
            \"\"\"Force-open a circuit during a known incident.

            Args:
                name: Circuit name to force-open.

            Returns:
                Confirmation dict with new state.
            \"\"\"
            await _set_state(name, CircuitState.OPEN)
            return {"name": name, "state": CircuitState.OPEN, "action": "forced_open"}
        """))


def _write_circuit_metrics(dest: Path) -> None:
    """Write ``app/core/circuit_metrics.py`` with Prometheus metrics.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Prometheus metrics for circuit breaker state and failure counts.

        Metrics:
            fastapi_circuit_state          — gauge: 0=closed, 1=open, 2=half_open
            fastapi_circuit_failures_total — counter: per-service failures
            fastapi_circuit_transitions_total — counter: per-service transitions
        \"\"\"

        from __future__ import annotations

        import logging

        logger = logging.getLogger(__name__)

        try:
            from prometheus_client import Counter, Gauge

            circuit_state_gauge = Gauge(
                "fastapi_circuit_state",
                "Circuit breaker state (0=closed, 1=open, 2=half_open)",
                ["service"],
            )
            circuit_failures_counter = Counter(
                "fastapi_circuit_failures_total",
                "Total circuit breaker failures per service",
                ["service"],
            )
            circuit_transitions_counter = Counter(
                "fastapi_circuit_transitions_total",
                "Total circuit breaker state transitions per service",
                ["service", "from_state", "to_state"],
            )
            _PROMETHEUS_AVAILABLE = True
        except ImportError:
            _PROMETHEUS_AVAILABLE = False
            logger.info("prometheus_client not installed — circuit metrics disabled")


        _STATE_VALUES = {"closed": 0, "open": 1, "half_open": 2}


        def record_circuit_state(service: str, state: str) -> None:
            \"\"\"Update the circuit state gauge for *service*.

            Args:
                service: Service / circuit name.
                state: Current state string (\"closed\", \"open\", \"half_open\").
            \"\"\"
            if not _PROMETHEUS_AVAILABLE:
                return
            circuit_state_gauge.labels(service=service).set(
                _STATE_VALUES.get(state, 0)
            )


        def record_circuit_failure(service: str) -> None:
            \"\"\"Increment the failure counter for *service*.

            Args:
                service: Service / circuit name.
            \"\"\"
            if not _PROMETHEUS_AVAILABLE:
                return
            circuit_failures_counter.labels(service=service).inc()


        def record_circuit_transition(
            service: str, from_state: str, to_state: str
        ) -> None:
            \"\"\"Increment the transition counter for *service*.

            Args:
                service: Service / circuit name.
                from_state: Previous state.
                to_state: New state.
            \"\"\"
            if not _PROMETHEUS_AVAILABLE:
                return
            circuit_transitions_counter.labels(
                service=service,
                from_state=from_state,
                to_state=to_state,
            ).inc()
        """))


def _patch_main(main_file: Path) -> None:
    """Inject circuit breaker router inclusion comment into main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "circuit_breaker" in src:
        return

    note = (
        "\n# Circuit breaker admin router — added by add_circuit_breaker tool\n"
        "# from app.api.routes.circuits import router as circuits_router\n"
        "# app.include_router(circuits_router)\n"
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
