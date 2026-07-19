"""Unit tests for ActivityCall — three per invariant."""

from __future__ import annotations

import asyncio

import pytest
from ActivityCall import (
    ActivityCall,
    ActivityCallError,
    ActivityMaxAttemptsExceededError,
    InMemoryActivityExecutor,
    RetryPolicy,
    retry_delay_s,
)


def _policy(max_attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(initial_interval_s=0.0, backoff_coefficient=2.0, maximum_attempts=max_attempts)


def _call(name: str = "Charge", start_to_close_s: int = 1, heartbeat_s: int | None = 1) -> ActivityCall:
    return ActivityCall(
        name=name, task_queue="q",
        start_to_close_s=start_to_close_s,
        schedule_to_close_s=60, heartbeat_s=heartbeat_s,
        retry=_policy(), args=(),
    )


# ---------------------------------------------------------------------------
# AC_INV_01 — at-least-once / idempotent retry
# ---------------------------------------------------------------------------
def test_inv_at_least_once_confirms() -> None:
    ex = InMemoryActivityExecutor()
    calls = {"n": 0}

    async def ok(_a: tuple[object, ...]) -> str:
        calls["n"] += 1
        return "done"

    ex.register("Charge", ok)
    out = asyncio.run(ex.execute(_call()))
    assert out == "done"
    assert calls["n"] == 1


def test_inv_at_least_once_prevents() -> None:
    # args non-tuple rejected (AC-INV-01 supporting).
    with pytest.raises(ActivityCallError):
        ActivityCall(name="x", task_queue="q", start_to_close_s=1,
                     schedule_to_close_s=None, heartbeat_s=None,
                     retry=_policy(), args=[1, 2])  # type: ignore[arg-type]


def test_inv_at_least_once_under_failure() -> None:
    ex = InMemoryActivityExecutor()
    calls = {"n": 0}

    async def flaky(_a: tuple[object, ...]) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("blip")
        return "ok"

    ex.register("Charge", flaky)
    out = asyncio.run(ex.execute(_call()))
    assert out == "ok"
    assert calls["n"] == 3  # retried twice before success (at-least-once)


# ---------------------------------------------------------------------------
# AC_INV_02 — start_to_close_s MUST be a positive int
# ---------------------------------------------------------------------------
def test_inv_start_to_close_required_confirms() -> None:
    ac = _call(start_to_close_s=30)
    assert ac.start_to_close_s == 30


def test_inv_start_to_close_required_prevents() -> None:
    with pytest.raises(ActivityCallError, match="AC-INV-02"):
        ActivityCall(name="x", task_queue="q", start_to_close_s=0,
                     schedule_to_close_s=None, heartbeat_s=None,
                     retry=_policy(), args=())
    with pytest.raises(ActivityCallError, match="AC-INV-02"):
        ActivityCall(name="x", task_queue="q", start_to_close_s=-5,
                     schedule_to_close_s=None, heartbeat_s=None,
                     retry=_policy(), args=())


def test_inv_start_to_close_required_under_failure() -> None:
    with pytest.raises(ActivityCallError):
        ActivityCall(name="x", task_queue="q", start_to_close_s=1.5,  # type: ignore[arg-type]
                     schedule_to_close_s=None, heartbeat_s=None,
                     retry=_policy(), args=())


# ---------------------------------------------------------------------------
# AC_INV_03 — missed heartbeat CANNOT be success
# ---------------------------------------------------------------------------
def test_inv_heartbeat_missed_confirms() -> None:
    ex = InMemoryActivityExecutor()

    async def slow(_a: tuple[object, ...]) -> str:
        await asyncio.sleep(5)  # exceeds start_to_close_s=1
        return "late"

    ex.register("Slow", slow)
    with pytest.raises(ActivityMaxAttemptsExceededError):
        asyncio.run(ex.execute(_call(name="Slow", start_to_close_s=1)))


def test_inv_heartbeat_missed_prevents() -> None:
    # heartbeat_s <= 0 rejected at construction.
    with pytest.raises(ActivityCallError, match="AC-INV-03"):
        ActivityCall(name="x", task_queue="q", start_to_close_s=10,
                     schedule_to_close_s=None, heartbeat_s=0,
                     retry=_policy(), args=())


def test_inv_heartbeat_missed_under_failure() -> None:
    ex = InMemoryActivityExecutor()
    attempts: list[int] = []

    async def slow_then_ok(_a: tuple[object, ...]) -> str:
        attempts.append(1)
        if len(attempts) < 3:
            await asyncio.sleep(5)  # triggers timeout
        return "eventually"

    ex.register("SlowOk", slow_then_ok)
    out = asyncio.run(ex.execute(_call(name="SlowOk", start_to_close_s=1)))
    assert out == "eventually"
    # Each timeout counted as an attempt.
    records = ex.attempts_for_latest("SlowOk")
    assert any(r.outcome == "heartbeat_missed" for r in records)


# ---------------------------------------------------------------------------
# AC_INV_04 — max attempts surface terminal error
# ---------------------------------------------------------------------------
def test_inv_max_attempts_terminal_confirms() -> None:
    ex = InMemoryActivityExecutor()

    async def always_fail(_a: tuple[object, ...]) -> str:
        raise RuntimeError("downstream")

    ex.register("Doom", always_fail)
    with pytest.raises(ActivityMaxAttemptsExceededError, match="AC-INV-04"):
        asyncio.run(ex.execute(_call(name="Doom")))


def test_inv_max_attempts_terminal_prevents() -> None:
    # RetryPolicy with maximum_attempts < 1 rejected at construction.
    with pytest.raises(ActivityCallError, match="AC-INV-04"):
        RetryPolicy(initial_interval_s=0.1, backoff_coefficient=2.0, maximum_attempts=0)


def test_inv_max_attempts_terminal_under_failure() -> None:
    # Deterministic exponential backoff calculation.
    p = RetryPolicy(initial_interval_s=1.0, backoff_coefficient=2.0, maximum_attempts=4)
    assert retry_delay_s(p, 1) == 1.0
    assert retry_delay_s(p, 2) == 2.0
    assert retry_delay_s(p, 3) == 4.0
    assert retry_delay_s(p, 4) == 8.0


# ---------------------------------------------------------------------------
# AC_INV_05 — heartbeat details scoped to attempt, never outlive success
# ---------------------------------------------------------------------------
def test_inv_heartbeat_scope_confirms() -> None:
    ex = InMemoryActivityExecutor()

    async def ok(_a: tuple[object, ...]) -> str:
        return "done"

    ex.register("Ok", ok)
    asyncio.run(ex.execute(_call(name="Ok")))
    records = ex.attempts_for_latest("Ok")
    # Post-success: heartbeat_details empty (AC-INV-05).
    assert all(r.heartbeat_details == () for r in records)


def test_inv_heartbeat_scope_prevents() -> None:
    # The reference executor exposes NO public mutator that writes
    # heartbeat details back to the attempt log after success.
    ex = InMemoryActivityExecutor()
    public = {m for m in dir(ex) if not m.startswith("_")}
    for forbidden in ("set_heartbeat_details", "persist_heartbeat", "carry_forward_heartbeat"):
        assert forbidden not in public


def test_inv_heartbeat_scope_under_failure() -> None:
    ex = InMemoryActivityExecutor()
    attempts: list[int] = []

    async def flaky(_a: tuple[object, ...]) -> str:
        attempts.append(1)
        if len(attempts) < 2:
            raise RuntimeError("blip")
        return "ok"

    ex.register("Flaky", flaky)
    asyncio.run(ex.execute(_call(name="Flaky")))
    # Only the successful attempt counts toward the completion;
    # prior failures are recorded but do NOT carry heartbeat details forward.
    records = ex.attempts_for_latest("Flaky")
    assert records[-1].outcome == "success"
    assert records[-1].heartbeat_details == ()
