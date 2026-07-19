"""Unit tests for WorkflowRun — three per invariant."""

from __future__ import annotations

import asyncio

import pytest
from WorkflowRun import (
    IdReusePolicy,
    InMemoryWorkflowClient,
    RunStatus,
    WorkflowAlreadyRunningError,
    WorkflowClosedError,
    WorkflowRunError,
    validate_workflow_id,
)


# ---------------------------------------------------------------------------
# WFR_INV_01 — deterministic replay
# ---------------------------------------------------------------------------
def test_inv_deterministic_replay_confirms() -> None:
    c = InMemoryWorkflowClient()
    asyncio.run(c.start("Ship", "w-1", "orders", args=(42,)))
    c.schedule_activity("w-1", "ChargeCard")
    c.schedule_activity("w-1", "ReserveStock")
    c.complete("w-1")
    trace1 = c.replay("w-1")
    trace2 = c.replay("w-1")
    # Replaying MUST produce the same ordered decision kinds.
    assert trace1 == trace2
    assert trace1 == ("started", "activity_scheduled", "activity_scheduled", "completed")


def test_inv_deterministic_replay_prevents() -> None:
    # Invalid workflow_id (non-deterministic identity) MUST be refused.
    with pytest.raises(WorkflowRunError, match="WFR-INV-01"):
        validate_workflow_id("bad id with spaces")
    with pytest.raises(WorkflowRunError, match="WFR-INV-01"):
        validate_workflow_id("")


def test_inv_deterministic_replay_under_failure() -> None:
    c = InMemoryWorkflowClient()
    asyncio.run(c.start("Ship", "w-1", "orders", args=()))
    c.schedule_activity("w-1", "A")
    c.fail("w-1", "downstream blew up")
    # Replay MUST still be deterministic — same kinds whether the workflow
    # ended in success or failure.
    assert c.replay("w-1") == ("started", "activity_scheduled", "failed")


# ---------------------------------------------------------------------------
# WFR_INV_02 — no non-deterministic calls inside workflow surface
# ---------------------------------------------------------------------------
def test_inv_no_nondeterministic_calls_confirms() -> None:
    # The WorkflowClient Protocol has ONLY start / describe / cancel —
    # no time, no random, no network IO hooks. Absence IS the guarantee.
    c = InMemoryWorkflowClient()
    surface = {m for m in dir(c) if not m.startswith("_")}
    assert {"start", "describe", "cancel"}.issubset(surface)


def test_inv_no_nondeterministic_calls_prevents() -> None:
    c = InMemoryWorkflowClient()
    public = {m for m in dir(c) if not m.startswith("_")}
    for forbidden in ("now", "sleep", "rand", "random", "urandom", "current_time", "network_call"):
        assert forbidden not in public


def test_inv_no_nondeterministic_calls_under_failure() -> None:
    # args MUST be a tuple (serialisable, deterministic).
    c = InMemoryWorkflowClient()
    with pytest.raises(WorkflowRunError):
        asyncio.run(c.start("Ship", "w-x", "orders", args=[1, 2]))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# WFR_INV_03 — closed runs cannot be resumed under the same run_id
# ---------------------------------------------------------------------------
def test_inv_no_resume_closed_confirms() -> None:
    c = InMemoryWorkflowClient(id_reuse=IdReusePolicy.TERMINATE_EXISTING)
    r1 = asyncio.run(c.start("T", "w-1", "q", args=()))
    c.complete("w-1")
    r2 = asyncio.run(c.start("T", "w-1", "q", args=()))
    # Two different run_ids.
    assert r1.run_id != r2.run_id


def test_inv_no_resume_closed_prevents() -> None:
    c = InMemoryWorkflowClient()
    asyncio.run(c.start("T", "w-1", "q", args=()))
    c.complete("w-1")
    # No operation on a completed run.
    with pytest.raises(WorkflowClosedError, match="WFR-INV-03"):
        c.schedule_activity("w-1", "A")
    with pytest.raises(WorkflowClosedError, match="WFR-INV-03"):
        asyncio.run(c.cancel("w-1"))


def test_inv_no_resume_closed_under_failure() -> None:
    c = InMemoryWorkflowClient()
    asyncio.run(c.start("T", "w-1", "q", args=()))
    c.fail("w-1", "because")
    assert c.status_of("w-1") is RunStatus.FAILED
    with pytest.raises(WorkflowClosedError):
        c.complete("w-1")


# ---------------------------------------------------------------------------
# WFR_INV_04 — side effects flow through activities/timers/signals
# ---------------------------------------------------------------------------
def test_inv_effects_through_activities_confirms() -> None:
    c = InMemoryWorkflowClient()
    asyncio.run(c.start("T", "w-1", "q", args=()))
    c.schedule_activity("w-1", "SendEmail")
    history = c.history_of("w-1")
    kinds = [e.kind for e in history]
    assert "activity_scheduled" in kinds


def test_inv_effects_through_activities_prevents() -> None:
    # There is NO `raw_network_call` or `direct_io` method on the surface.
    c = InMemoryWorkflowClient()
    public = {m for m in dir(c) if not m.startswith("_")}
    for forbidden in ("raw_network_call", "direct_io", "exec_shell"):
        assert forbidden not in public


def test_inv_effects_through_activities_under_failure() -> None:
    # Scheduling an activity on a closed run MUST raise, preserving the
    # invariant that history is an immutable record of intended effects.
    c = InMemoryWorkflowClient()
    asyncio.run(c.start("T", "w-1", "q", args=()))
    c.complete("w-1")
    with pytest.raises(WorkflowClosedError):
        c.schedule_activity("w-1", "A")


# ---------------------------------------------------------------------------
# WFR_INV_05 — id-reuse policy controls duplicate starts
# ---------------------------------------------------------------------------
def test_inv_id_reuse_policy_confirms() -> None:
    c = InMemoryWorkflowClient(id_reuse=IdReusePolicy.REJECT)
    asyncio.run(c.start("T", "w-1", "q", args=()))
    with pytest.raises(WorkflowAlreadyRunningError, match="WFR-INV-05"):
        asyncio.run(c.start("T", "w-1", "q", args=()))


def test_inv_id_reuse_policy_prevents() -> None:
    c = InMemoryWorkflowClient(id_reuse=IdReusePolicy.REUSE_EXISTING)
    r1 = asyncio.run(c.start("T", "w-1", "q", args=()))
    r2 = asyncio.run(c.start("T", "w-1", "q", args=()))
    # REUSE policy MUST return the same run_id; never two opens.
    assert r1.run_id == r2.run_id
    # Only ONE run appears in the history index.
    assert len(c.all_runs_of("w-1")) == 1


def test_inv_id_reuse_policy_under_failure() -> None:
    c = InMemoryWorkflowClient(id_reuse=IdReusePolicy.TERMINATE_EXISTING)
    r1 = asyncio.run(c.start("T", "w-1", "q", args=()))
    r2 = asyncio.run(c.start("T", "w-1", "q", args=()))
    assert r1.run_id != r2.run_id
    # r1 was terminated (canceled), r2 is open.
    assert c.status_of("w-1") is RunStatus.OPEN
    assert len(c.all_runs_of("w-1")) == 2
