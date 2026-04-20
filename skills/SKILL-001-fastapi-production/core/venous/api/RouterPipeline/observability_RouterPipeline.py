"""Observability harness — asserts the declared schema is well-formed and the
primitive surfaces the documented events/metrics/spans.
"""

from __future__ import annotations

import json
from pathlib import Path

from RouterPipeline import Handler, RequestContext, Router

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_operations_cover_register_and_dispatch() -> None:
    schema = _load_schema()
    ops = {str(s["operation_name"]) for s in schema["spans"]}
    assert "router.pipeline.dispatch" in ops
    assert "router.pipeline.register" in ops


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


def test_observability_primitive_exposes_pipeline_and_attachment_counts() -> None:
    router = Router()
    router.register("api", [])
    router.register("browser", [])
    router.get("api").attach("/x")
    router.get("browser").attach("/")
    router.seal()
    assert len(router.pipelines) == 2
    assert len(router.attachments) == 2


def test_observability_request_dispatch_produces_halted_attribute() -> None:
    router = Router()

    def halter(ctx: RequestContext, _next: Handler) -> object:
        ctx.halt("policy")
        return {"status": 403}

    router.register("api", [halter])
    router.get("api").attach("/x")
    router.seal()

    ctx = RequestContext(route="/x")
    out = router.dispatch("/x", lambda _c: "ok", ctx)
    # The halted attribute is the instrumentation hook callers sample.
    assert ctx.halted is True
    assert isinstance(out, dict) and out.get("status") == 403
