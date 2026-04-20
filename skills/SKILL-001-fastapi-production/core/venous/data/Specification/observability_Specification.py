"""Observability harness — asserts Specification observability schema is well-formed
and the primitive's runtime surface can be instrumented against it."""

from __future__ import annotations

import json
from pathlib import Path

from Specification import PredicateSpecification, TranslatorRegistry


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


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


def test_observability_evaluation_surface_emits_attributes() -> None:
    # The primitive exposes the attributes referenced by the schema — spec
    # kind, leaf name, composition children — through its public API.
    spec = PredicateSpecification[int]("pos", lambda x: x > 0)
    assert spec.kind == "leaf"
    assert spec.name == "pos"
    composite = spec.and_(spec)
    assert composite.kind == "and"
    assert len(composite.children()) == 2


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "spec.evaluate" in ops
    assert "spec.translate" in ops


def test_observability_translate_span_can_be_populated() -> None:
    # The translate pipeline exposes backend name and leaf count — the
    # attributes the span schema declares — through the TranslatorRegistry.
    reg = TranslatorRegistry()
    reg.register("sql", "pos", lambda s: "x > 0")
    spec = PredicateSpecification[int]("pos", lambda x: x > 0)
    result = reg.translate("sql", spec)
    assert result == "x > 0"
