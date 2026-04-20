"""Observability harness — asserts the declared schema is well-formed and the
primitive surfaces the documented event/metric/span operations.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from MiddlewarePipeline import (
    InMemoryMiddlewarePipeline,
    Next,
    RequestContext,
)

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_operations_cover_request_and_middleware_paths() -> None:
    schema = _load_schema()
    ops = {str(s["operation_name"]) for s in schema["spans"]}
    assert "mwp.request.run" in ops
    assert "mwp.middleware.invoke" in ops
    assert "mwp.error.filter" in ops


def test_observability_metric_types_are_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_are_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        assert "." in name


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_primitive_surfaces_names_and_status() -> None:
    pipe = InMemoryMiddlewarePipeline()

    async def mw(ctx: RequestContext, call_next: Next) -> None:
        await call_next()

    async def handler(ctx: RequestContext, call_next: Next) -> None:
        ctx.write_response(200, {"ok": True})

    mw.__name__ = "mw"
    handler.__name__ = "handler"
    pipe.use(mw).use(handler)
    assert pipe.names == ("mw", "handler")
    ctx = RequestContext()
    asyncio.run(pipe.run(ctx))
    assert ctx.status == 200  # observable for mwp.requests.total{status}
