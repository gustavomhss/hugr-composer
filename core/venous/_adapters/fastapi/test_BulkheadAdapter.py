"""Behavioral tests for BulkheadAdapter.

Not "does it return 200?" — each test proves one contract:

- Config validation catches the failure modes before construction.
- ``acquire(group)`` gates callers by partition capacity AND releases on exit.
- ``acquire`` raises ``BulkheadFullError`` at capacity with zero wait.
- ``acquire`` releases permits when the body raises.
- Partition isolation: saturating one group MUST NOT block another.
- ``status()`` shape AND values reflect live counter state.
- ``BulkheadMiddleware`` returns 503 + ``X-Bulkhead-Group`` on rejection AND
  200 when capacity is free AND releases permits after the response.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from core.venous._adapters.fastapi.BulkheadAdapter import (
    Bulkhead,
    BulkheadConfig,
    BulkheadFullError,
    BulkheadMiddleware,
)
from core.venous.resiliency.Bulkhead import snapshot


def _run(coro: object) -> object:
    """Run ``coro`` on a fresh loop (keeps tests synchronous)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# BulkheadConfig validation — fail fast at construction, not first use
# ---------------------------------------------------------------------------
def test_config_rejects_empty_limits() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        BulkheadConfig(limits={})


def test_config_rejects_zero_or_negative_limit() -> None:
    with pytest.raises(ValueError, match="MUST be int >= 1"):
        BulkheadConfig(limits={"payments": 0})
    with pytest.raises(ValueError, match="MUST be int >= 1"):
        BulkheadConfig(limits={"payments": -1})


def test_config_rejects_empty_group_name() -> None:
    with pytest.raises(ValueError, match="non-empty str"):
        BulkheadConfig(limits={"": 10})


def test_config_rejects_negative_wait_ms() -> None:
    with pytest.raises(ValueError, match="wait_ms"):
        BulkheadConfig(limits={"payments": 10}, wait_ms=-1)


# ---------------------------------------------------------------------------
# Bulkhead facade — multi-partition acquire + status
# ---------------------------------------------------------------------------
def test_acquire_permits_body_entry_within_capacity() -> None:
    bh = Bulkhead(BulkheadConfig(limits={"payments": 2}))

    async def drive() -> None:
        async with bh.acquire("payments"):
            assert bh.status()["payments"]["active"] == 1
            async with bh.acquire("payments"):
                assert bh.status()["payments"]["active"] == 2
            assert bh.status()["payments"]["active"] == 1
        assert bh.status()["payments"]["active"] == 0

    _run(drive())


def test_acquire_raises_bulkhead_full_error_at_capacity() -> None:
    """Reproduces the old failing test_b02 pattern: two __aenter__ on a cap-1 group, second fails."""
    bh = Bulkhead(BulkheadConfig(limits={"test_group": 1}))
    pool = bh.acquire("test_group")

    async def drive() -> None:
        await pool.__aenter__()
        try:
            with pytest.raises(BulkheadFullError):
                await pool.__aenter__()
        finally:
            await pool.__aexit__(None, None, None)

    _run(drive())
    assert bh.status()["test_group"]["active"] == 0


def test_acquire_releases_permit_on_body_exception() -> None:
    bh = Bulkhead(BulkheadConfig(limits={"crud": 1}))

    async def drive() -> None:
        with pytest.raises(RuntimeError, match="boom"):
            async with bh.acquire("crud"):
                assert bh.status()["crud"]["active"] == 1
                raise RuntimeError("boom")
        # Permit returned despite the exception.
        assert bh.status()["crud"]["active"] == 0
        async with bh.acquire("crud"):
            assert bh.status()["crud"]["active"] == 1

    _run(drive())


def test_acquire_raises_for_unknown_group() -> None:
    from core.venous.resiliency.Bulkhead import BulkheadInvariantError

    bh = Bulkhead(BulkheadConfig(limits={"payments": 10}))
    with pytest.raises(BulkheadInvariantError, match="not registered"):
        bh.acquire("nonexistent")


def test_partition_isolation_saturating_one_group_does_not_block_others() -> None:
    bh = Bulkhead(BulkheadConfig(limits={"a": 1, "b": 3}))
    started_a = asyncio.Event()
    release_a = asyncio.Event()

    async def hold_a() -> None:
        async with bh.acquire("a"):
            started_a.set()
            await release_a.wait()

    async def drive() -> None:
        ta = asyncio.create_task(hold_a())
        await started_a.wait()
        # a is saturated — new acquire on a must fail.
        with pytest.raises(BulkheadFullError):
            async with bh.acquire("a"):
                raise AssertionError("a admitted despite saturation")
        # b must still admit three concurrent callers — two here + one nested.
        async with bh.acquire("b"), bh.acquire("b"), bh.acquire("b"):
            assert bh.status()["b"]["active"] == 3
        release_a.set()
        await ta

    _run(drive())
    # Both partitions returned to zero in_flight.
    assert bh.status()["a"]["active"] == 0
    assert bh.status()["b"]["active"] == 0
    # Exactly one rejection was recorded against partition "a".
    labels = [e.partition for e in bh.meter.events]
    assert labels == ["a"]


def test_status_shape_matches_contract() -> None:
    bh = Bulkhead(BulkheadConfig(limits={"payments": 10, "crud": 50}))
    status = bh.status()
    assert set(status.keys()) == {"payments", "crud"}
    for group_status in status.values():
        assert set(group_status.keys()) == {"active", "max", "available"}
        assert group_status["active"] == 0
        assert group_status["available"] == group_status["max"]
    assert status["payments"]["max"] == 10
    assert status["crud"]["max"] == 50


def test_acquire_waits_when_wait_ms_positive_and_permit_frees() -> None:
    """With ``wait_ms > 0``, a second caller queues up to the deadline."""
    bh = Bulkhead(BulkheadConfig(limits={"payments": 1}, wait_ms=500))
    started = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with bh.acquire("payments"):
            started.set()
            await release.wait()

    async def late_caller() -> str:
        async with bh.acquire("payments"):
            return "admitted"

    async def drive() -> None:
        th = asyncio.create_task(holder())
        await started.wait()
        late_task = asyncio.create_task(late_caller())
        # Let the late caller start waiting, then release the holder.
        await asyncio.sleep(0.05)
        assert not late_task.done()
        release.set()
        result = await asyncio.wait_for(late_task, timeout=1.0)
        assert result == "admitted"
        await th

    _run(drive())
    # Zero rejections — the late caller queued, didn't fail.
    assert not bh.meter.events


# ---------------------------------------------------------------------------
# BulkheadMiddleware — end-to-end FastAPI integration
# ---------------------------------------------------------------------------
def _build_app(bulkhead: Bulkhead, classify_route=lambda path: "api") -> FastAPI:
    """Build a FastAPI app with the middleware installed + one endpoint per group."""
    app = FastAPI()
    app.add_middleware(
        BulkheadMiddleware,
        bulkhead=bulkhead,
        classify_route=classify_route,
    )

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_middleware_returns_200_when_capacity_available() -> None:
    bh = Bulkhead(BulkheadConfig(limits={"api": 5}))
    app = _build_app(bh)
    with TestClient(app) as client:
        r = client.get("/ping")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    # Middleware released the permit after the response completed.
    assert bh.status()["api"]["active"] == 0


def test_middleware_returns_503_and_x_bulkhead_group_on_saturation() -> None:
    """Middleware MUST emit 503 + X-Bulkhead-Group when the group's partition rejects."""
    bh = Bulkhead(BulkheadConfig(limits={"api": 1}))
    # Pre-occupy the single slot by entering the acquire and leaving it open.
    gate = bh.acquire("api")

    async def drive() -> None:
        await gate.__aenter__()

    _run(drive())
    try:
        app = _build_app(bh)
        with TestClient(app) as client:
            r = client.get("/ping")
        assert r.status_code == 503
        assert r.headers["X-Bulkhead-Group"] == "api"
        body = r.json()
        assert "api" in body["detail"]
        assert "capacity" in body["detail"].lower()
    finally:
        # Restore counter — without releasing, a subsequent test would
        # inherit a saturated partition (we share no state across tests,
        # but release anyway for symmetry).
        async def cleanup() -> None:
            await gate.__aexit__(None, None, None)

        _run(cleanup())
    # After cleanup, partition fully released.
    assert bh.status()["api"]["active"] == 0
    # Exactly one rejection was recorded.
    assert len(bh.meter.events) == 1
    assert bh.meter.events[0].partition == "api"


def test_middleware_logs_rejection_with_supplied_logger(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test_bulkhead_middleware_logger")
    bh = Bulkhead(BulkheadConfig(limits={"api": 1}))
    gate = bh.acquire("api")

    async def pre() -> None:
        await gate.__aenter__()

    _run(pre())
    app = FastAPI()
    app.add_middleware(
        BulkheadMiddleware,
        bulkhead=bh,
        classify_route=lambda path: "api",
        logger=logger,
    )

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    try:
        with caplog.at_level(logging.WARNING, logger="test_bulkhead_middleware_logger"):
            with TestClient(app) as client:
                r = client.get("/ping")
        assert r.status_code == 503
        # Warning line MUST include the group name.
        matches = [
            rec for rec in caplog.records
            if rec.name == "test_bulkhead_middleware_logger" and "api" in rec.getMessage()
        ]
        assert matches, "rejection should emit a WARNING with the group name"
    finally:
        async def cleanup() -> None:
            await gate.__aexit__(None, None, None)

        _run(cleanup())


def test_middleware_classify_route_is_called_with_request_path() -> None:
    bh = Bulkhead(BulkheadConfig(limits={"payments": 1, "crud": 1}))
    seen_paths: list[str] = []

    def classify(path: str) -> str:
        seen_paths.append(path)
        if path.startswith("/pay"):
            return "payments"
        return "crud"

    app = FastAPI()
    app.add_middleware(
        BulkheadMiddleware,
        bulkhead=bh,
        classify_route=classify,
    )

    @app.get("/pay/charge")
    def charge() -> dict[str, str]:
        return {"status": "charged"}

    @app.get("/items/42")
    def item() -> dict[str, str]:
        return {"status": "got"}

    with TestClient(app) as client:
        r1 = client.get("/pay/charge")
        r2 = client.get("/items/42")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert seen_paths == ["/pay/charge", "/items/42"]
    # Both partitions are now idle.
    assert bh.status()["payments"]["active"] == 0
    assert bh.status()["crud"]["active"] == 0


# ---------------------------------------------------------------------------
# Snapshot parity — status() == per-partition motor snapshot
# ---------------------------------------------------------------------------
def test_status_matches_motor_snapshot() -> None:
    """``status()`` is a literal re-shaping of motor ``snapshot``; parity MUST hold."""
    bh = Bulkhead(BulkheadConfig(limits={"payments": 10, "crud": 50}))

    async def drive() -> None:
        async with bh.acquire("payments"):
            status = bh.status()
            partition = bh._registry.get("payments")
            snap = snapshot(partition)
            assert status["payments"]["active"] == snap.in_flight
            assert status["payments"]["max"] == snap.capacity
            assert status["payments"]["available"] == snap.available

    _run(drive())
