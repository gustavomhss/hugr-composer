"""Observability harness for KeyValueBucket."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from KeyValueBucket import InMemoryKeyValueBucket

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


def test_observability_revision_counter_increments() -> None:
    async def scenario() -> None:
        kv = InMemoryKeyValueBucket()
        base = kv.current_revision()
        await kv.create("k", b"v")
        assert kv.current_revision() == base + 1
    _run(scenario())


def test_observability_span_ops_present() -> None:
    ops = {s["operation_name"] for s in _load_schema()["spans"]}
    assert "kv.bucket.update" in ops
