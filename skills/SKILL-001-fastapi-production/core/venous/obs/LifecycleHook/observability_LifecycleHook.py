"""Observability harness — asserts schema wellformedness."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from LifecycleHook import (
    LifecycleHook,
    LifecyclePhase,
    LifecycleRegistry,
)


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    s = _load_schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _load_schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_dotted() -> None:
    for log in _load_schema()["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        # dotted namespace required
        assert "." in name


def test_observability_span_op_names_dotted() -> None:
    for span in _load_schema()["spans"]:
        op = str(span["operation_name"])
        assert "." in op
        assert op == op.lower()


def test_observability_cardinality_bounds_declared() -> None:
    for m in _load_schema()["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_lifecycle_phases_observable() -> None:
    async def run() -> None:
        reg = LifecycleRegistry()

        async def r() -> None:
            pass

        reg.register(LifecycleHook(LifecyclePhase.READY, r))
        await reg.run_ready()
        assert reg.ready_fired

    asyncio.run(run())
