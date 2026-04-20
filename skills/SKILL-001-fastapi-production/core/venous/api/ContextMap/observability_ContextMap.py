"""Observability harness — asserts the declared schema is well-formed and the
primitive surfaces the documented mutation/lookup operations.
"""

from __future__ import annotations

import json
from pathlib import Path

from ContextMap import InMemoryContextMap


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_operations_cover_mutation_and_lookup_paths() -> None:
    schema = _load_schema()
    ops = {str(s["operation_name"]) for s in schema["spans"]}
    assert "contextmap.relationship.add" in ops
    assert "contextmap.relationship.lookup" in ops


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


def test_observability_primitive_surfaces_version_counter() -> None:
    # CTXMAP-INV-04 is the "audit trail" invariant; the version counter is the
    # observable SLI — this test proves it increments on every successful mutation.
    m = InMemoryContextMap()
    assert m.version == 0
    m.add_relationship("A", "B", "Conformist")
    m.add_relationship("B", "C", "Published Language")
    m.add_relationship("C", "D", "Customer-Supplier")
    assert m.version == 3
    # Total edges exposed for the "contextmap.edges.total" gauge.
    assert len(tuple(m.integrations())) == 3
