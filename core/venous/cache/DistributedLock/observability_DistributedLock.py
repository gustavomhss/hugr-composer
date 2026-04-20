"""Observability harness for DistributedLock."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from DistributedLock import InMemoryDistributedLock

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _run(coro):  # type: ignore[no-untyped-def]  # test helper
    return asyncio.run(coro)


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    s = _load_schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_log_names_lowercase() -> None:
    for log in _load_schema()["logs"]:
        assert str(log["event_name"]) == str(log["event_name"]).lower()


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _load_schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_cardinality_bounds() -> None:
    for m in _load_schema()["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_lock_hold_is_observable() -> None:
    async def scenario() -> None:
        lock = InMemoryDistributedLock()
        assert not lock.is_held("r")
        h = await lock.try_lock("r", "o", lease_s=30)
        assert h is not None
        assert lock.is_held("r")
        await lock.unlock(h)
        assert not lock.is_held("r")
    _run(scenario())


def test_observability_span_ops_present() -> None:
    ops = {s["operation_name"] for s in _load_schema()["spans"]}
    assert "lock.try_lock" in ops
    assert "lock.unlock" in ops
