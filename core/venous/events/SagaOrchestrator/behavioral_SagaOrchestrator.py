"""End-to-end behavioral scenarios for SagaOrchestrator — prove invariants at runtime."""

from __future__ import annotations

import pytest

from SagaOrchestrator import (
    STATE_COMPLETED,
    STATE_FAILED,
    CompensationOrderError,
    InMemorySagaOrchestrator,
    SagaDefinition,
)


def _order_saga(compensations: list[str]) -> SagaDefinition:
    sd = SagaDefinition("order")

    sd.register("reserve", compensator=lambda p: compensations.append(f"unreserve:{p!r}"))(
        lambda p: p
    )
    sd.register("charge", compensator=lambda p: compensations.append(f"refund:{p!r}"))(
        lambda p: p
    )
    sd.register("ship", compensator=lambda p: compensations.append(f"cancel_ship:{p!r}"))(
        lambda p: p
    )
    return sd


def test_scenario_happy_path_completes_in_order() -> None:
    comps: list[str] = []
    sd = _order_saga(comps)
    emitted: list[str] = []
    saga = InMemorySagaOrchestrator(sd, command_sink=lambda _c, cmd, _p: emitted.append(cmd))
    saga.start("order-1", {"sku": "A", "qty": 2})
    saga.step("order-1", "reserve", {"reservation_id": "r1"})
    saga.step("order-1", "charge", {"txn_id": "t1"})
    saga.step("order-1", "ship", {"tracking": "x"})
    state, done = saga.status("order-1")
    assert state == STATE_COMPLETED
    assert list(done) == ["reserve", "charge", "ship"]
    # No compensations fired on the happy path.
    assert comps == []
    # Commands were emitted in the expected order.
    assert emitted[0] == "invoke_reserve"
    assert emitted[-1] == "saga_completed"


def test_scenario_failure_on_last_step_compensates_all_prior_in_reverse() -> None:
    comps: list[str] = []
    sd = _order_saga(comps)
    saga = InMemorySagaOrchestrator(sd)
    saga.start("order-2", {"sku": "B"})
    saga.step("order-2", "reserve", "r-ok")
    saga.step("order-2", "charge", "c-ok")
    saga.step("order-2", "ship", {"__saga_failed__": True, "reason": "no carrier"})
    state, done = saga.status("order-2")
    assert state == STATE_FAILED
    assert list(done) == []
    # Reverse compensation: refund BEFORE unreserve.
    assert comps == ["refund:'c-ok'", "unreserve:'r-ok'"]


def test_scenario_failure_on_first_step_no_compensations_needed() -> None:
    comps: list[str] = []
    sd = _order_saga(comps)
    saga = InMemorySagaOrchestrator(sd)
    saga.start("order-3", {"sku": "C"})
    saga.step("order-3", "reserve", {"__saga_failed__": True, "reason": "out of stock"})
    state, _done = saga.status("order-3")
    assert state == STATE_FAILED
    assert comps == []  # Nothing completed → nothing to compensate.


def test_scenario_explicit_compensate_from_tail() -> None:
    comps: list[str] = []
    sd = _order_saga(comps)
    saga = InMemorySagaOrchestrator(sd)
    saga.start("order-4", {})
    saga.step("order-4", "reserve", "r")
    saga.step("order-4", "charge", "c")
    # Operator explicitly compensates from the tail (e.g., after a manual intervention).
    saga.compensate("order-4", from_step="charge")
    state, _done = saga.status("order-4")
    assert state == STATE_FAILED
    assert comps == ["refund:'c'", "unreserve:'r'"]


def test_scenario_out_of_order_compensate_is_rejected() -> None:
    comps: list[str] = []
    sd = _order_saga(comps)
    saga = InMemorySagaOrchestrator(sd)
    saga.start("order-5", {})
    saga.step("order-5", "reserve", "r")
    saga.step("order-5", "charge", "c")
    with pytest.raises(CompensationOrderError):
        saga.compensate("order-5", from_step="reserve")


def test_scenario_idempotent_redelivery_of_step_reports() -> None:
    comps: list[str] = []
    sd = _order_saga(comps)
    saga = InMemorySagaOrchestrator(sd)
    saga.start("order-6", {})
    # A flaky bus redelivers the reserve outcome five times.
    for _ in range(5):
        saga.step("order-6", "reserve", {"reservation_id": "r-same"})
    # Only ONE advance, state is RUNNING awaiting `charge`.
    state, done = saga.status("order-6")
    assert list(done) == ["reserve"]
    assert state == "running"


def test_scenario_journal_survives_sink_outage() -> None:
    comps: list[str] = []
    sd = _order_saga(comps)

    def down_sink(_cid: str, _cmd: str, _p: object) -> None:
        raise RuntimeError("bus offline")

    saga = InMemorySagaOrchestrator(sd, command_sink=down_sink)
    saga.start("order-7", {})
    # Sink threw but journal is intact → operator can replay journalled commands.
    records = saga.journal_for("order-7")
    assert records and records[0].command_name == "invoke_reserve"
    assert "sink failure" in (saga.last_error("order-7") or "")
