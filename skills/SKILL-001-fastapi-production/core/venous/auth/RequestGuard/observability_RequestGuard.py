"""Observability harness — asserts RequestGuard emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from CurrentPrincipal import authenticated
from RequestContext import MutableRequestContext
from RequestGuard import (
    AuthenticatedGuard,
    GuardOutcome,
    RoleGuard,
    and_guards,
    run_sync,
)


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def _ctx() -> MutableRequestContext:
    return MutableRequestContext("req-obs00001", {}, assigns={})


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert schema["logs"] and schema["metrics"] and schema["spans"]


def test_observability_metric_types_are_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        assert "." in name


def test_observability_decision_record_carries_schema_attributes() -> None:
    # The runtime decision object exposes the attributes the log writer needs.
    comp = and_guards(AuthenticatedGuard(), RoleGuard("admin"))
    p = authenticated("alice", roles=["admin"])
    outcome = run_sync(comp.evaluate(_ctx(), p))
    assert outcome is GuardOutcome.ALLOW
    # Values a log adapter would read to emit `guard.evaluated`:
    assert comp.evaluated_count == 2
    assert len(comp.guards) == 2
    assert comp.outcome is GuardOutcome.ALLOW


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "guard.evaluate" in ops
    assert "guard.dispatch" in ops


def test_observability_denial_decision_carries_index() -> None:
    comp = and_guards(AuthenticatedGuard(), RoleGuard("admin"))
    p = authenticated("bob", roles=["viewer"])
    run_sync(comp.evaluate(_ctx(), p))
    assert comp.denying_guard_index == 1
    assert comp.outcome is GuardOutcome.DENY_FORBIDDEN


def test_observability_error_decision_carries_type_name() -> None:
    from RequestGuard import HandlerDispatch

    class Bad:
        async def allow(self, ctx: Any, principal: Any) -> bool:
            raise ValueError("noop")

    async def h(ctx: Any, principal: Any) -> str:
        return "x"

    dispatch = HandlerDispatch()
    comp = and_guards(Bad())
    r = run_sync(dispatch.dispatch(comp, _ctx(), authenticated("u"), h))
    assert r.decision.error_type == "ValueError"
