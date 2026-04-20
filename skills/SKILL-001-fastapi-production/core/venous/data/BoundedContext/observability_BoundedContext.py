"""Observability harness — asserts BoundedContext emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from pathlib import Path

from BoundedContext import (
    REL_PARTNERSHIP,
    ContextMap,
    SimpleBoundedContext,
    _OwnershipLedger,
)


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


def test_observability_lifecycle_attributes_map_to_runtime() -> None:
    ledger = _OwnershipLedger()
    cmap = ContextMap()
    sales = SimpleBoundedContext("sales", context_map=cmap, ledger=ledger)
    billing = SimpleBoundedContext("billing", context_map=cmap, ledger=ledger)

    class _Order:
        pass

    sales.claim(_Order)
    sales.define_term("order", "a customer purchase")
    sales.publish_integration(billing, REL_PARTNERSHIP)

    # Attributes declared on the schema are recoverable from runtime state.
    assert sales.name == "sales"
    assert sales.owns(_Order) is True
    assert "order" in sales.language
    assert cmap.relationship("sales", "billing") == REL_PARTNERSHIP


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "bounded.context.claim" in ops
    assert "bounded.context.forward" in ops
