"""Observability harness — asserts Bulkhead emits rejection metrics per BH_INV_05."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from Bulkhead import BulkheadFull, InMemoryBulkhead


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def _run(coro: object) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


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


def test_observability_rejection_metric_labelled_with_partition() -> None:
    """BH_INV_05: every rejection MUST be emitted with a partition label."""
    bh = InMemoryBulkhead(name="obs", max_concurrent_calls=1, max_wait_duration_ms=0)
    started = asyncio.Event()
    block = asyncio.Event()

    async def hang() -> None:
        started.set()
        await block.wait()

    async def drive() -> None:
        hang_task = asyncio.create_task(bh.submit(hang))
        await started.wait()
        with pytest.raises(BulkheadFull):
            await bh.submit(lambda: asyncio.sleep(0))  # type: ignore[arg-type]
        block.set()
        await hang_task

    _run(drive())
    events = bh.meter.events
    assert len(events) == 1
    assert events[0].partition == "obs"
    assert events[0].reason in ("wait_timeout", "retry_forbidden")


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "bulkhead.submit" in ops


def test_observability_rejection_metric_label_present_in_schema() -> None:
    schema = _load_schema()
    rejection = next(m for m in schema["metrics"] if m["name"] == "bulkhead.rejections")
    labels = rejection.get("label_keys", [])
    # BH_INV_05 mandates the partition label on every rejection metric.
    assert "partition" in labels
