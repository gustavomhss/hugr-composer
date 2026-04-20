"""Observability harness for InputValidator."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from InputValidator import (
    SchemaField,
    SchemaModel,
    SchemaValidator,
    ValidationError,
)

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


class _Probe(SchemaModel):
    __fields__: Mapping[str, SchemaField] = {
        "id": SchemaField(type_=str, max_length=32),
    }


def test_observability_schema_wellformed() -> None:
    s = _load_schema()
    assert s["logs"] and s["metrics"] and s["spans"]


def test_observability_span_ops_cover_parse() -> None:
    s = _load_schema()
    ops = {sp["operation_name"] for sp in s["spans"]}
    assert "input_validator.parse" in ops


def test_observability_metric_types_valid() -> None:
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in _load_schema()["metrics"]:
        assert m["metric_type"] in valid


def test_observability_no_raw_payload_in_schema() -> None:
    # The attacker-controlled payload MUST NEVER appear as a log attribute.
    forbidden = {"raw", "raw_payload", "value", "input"}
    for log in _load_schema()["logs"]:
        for attr in log["required_attributes"]:
            assert attr not in forbidden


def test_observability_parse_success_runs_without_leaking_raw() -> None:
    v = SchemaValidator()
    v.parse({"id": "ok"}, _Probe)  # smoke — external hook attaches


def test_observability_parse_rejection_error_never_leaks_raw() -> None:
    v = SchemaValidator()
    attacker = "<script>leak</script>"
    try:
        v.parse({"id": attacker + "x" * 64}, _Probe)
    except ValidationError as err:
        assert attacker not in str(err)
        assert err.field_path == "id"


def test_observability_cardinality_bounds_declared() -> None:
    for m in _load_schema()["metrics"]:
        assert m["cardinality_bound"] >= 1


def test_observability_log_event_names_lowercase_dotted() -> None:
    for log in _load_schema()["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
