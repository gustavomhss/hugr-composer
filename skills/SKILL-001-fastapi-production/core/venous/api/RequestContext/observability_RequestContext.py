"""Observability harness — asserts RequestContext emits logs/metrics matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from RequestContext import MutableRequestContext, REDACTED

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


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


def test_observability_for_log_fields_match_schema_required_attributes() -> None:
    ctx = MutableRequestContext(
        request_id="req-obs-1",
        headers={"x-trace-id": "t-1"},
    )
    ctx.put("user", "alice")
    log = ctx.for_log()
    schema = _load_schema()
    started_entry = next(
        entry for entry in schema["logs"] if entry["event_name"] == "api.request.started"
    )
    required = started_entry["required_attributes"]
    assert isinstance(required, list)
    for attr in required:
        assert attr in log, f"for_log() missing required attribute {attr!r}"


def test_observability_halted_log_fields_present() -> None:
    ctx = MutableRequestContext(request_id="req-obs-2")
    ctx.halt()
    log = ctx.for_log()
    for key in ("request_id", "is_halted", "is_disposed", "assign_keys"):
        assert key in log


def test_observability_no_raw_sensitive_assigns_in_log_payload() -> None:
    ctx = MutableRequestContext(request_id="req-obs-3")
    ctx.put("authorization", "Bearer sk-leak")
    ctx.put("api_key", "AKIA-leak")
    ctx.put("benign", "public")
    payload = json.dumps(ctx.for_log(), sort_keys=True, default=str)
    assert "sk-leak" not in payload
    assert "AKIA-leak" not in payload
    assert "public" in payload
    assert REDACTED in payload
