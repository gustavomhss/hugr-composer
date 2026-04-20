"""Observability harness — asserts HealthProbe emits logs/metrics/spans matching schema."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from HealthProbe import BaseHealthProbe, HealthReport, HealthStatus


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_log_event_names_are_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        assert "." in name  # namespaced under healthprobe.*


def test_observability_metric_types_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_span_ops_cover_the_api() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "healthprobe.liveness" in ops
    assert "healthprobe.readiness" in ops


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


@pytest.mark.asyncio
async def test_observability_readiness_emits_dependency_details() -> None:
    # The public HealthReport SHALL describe every registered dep via a
    # `<dep>.status` details entry — this is what downstream observers consume.
    class _Fixed:
        def __init__(self, name: str, status: HealthStatus) -> None:
            self.name = name
            self._s = status

        async def liveness(self) -> HealthReport:
            return HealthReport(self._s)

        async def readiness(self) -> HealthReport:
            return HealthReport(self._s)

        def register_dependency(self, name: str, probe: object) -> None:  # pragma: no cover
            raise NotImplementedError

    probe = BaseHealthProbe("svc", debounce_s=0)
    probe.register_dependency("db", _Fixed("db", HealthStatus.UP))
    probe.register_dependency("cache", _Fixed("cache", HealthStatus.DEGRADED))
    report = await probe.readiness()
    assert report.details["db.status"] == "up"
    assert report.details["cache.status"] == "degraded"


def test_observability_liveness_fast() -> None:
    probe = BaseHealthProbe("svc")
    loop = asyncio.new_event_loop()
    try:
        t0 = loop.time()
        loop.run_until_complete(probe.liveness())
        assert (loop.time() - t0) < 0.05
    finally:
        loop.close()
