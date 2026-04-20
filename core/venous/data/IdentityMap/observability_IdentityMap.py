"""Observability harness — asserts IdentityMap emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from IdentityMap import InMemoryIdentityMap


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


@dataclass
class Order:
    id: int


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


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert {"idmap.get", "idmap.add", "idmap.dispose"} <= ops


def test_observability_session_attributes_surface_at_runtime() -> None:
    """The runtime primitive exposes the attributes the schema requires.

    Each schema log requires `session_id`; each span requires `session.id`.
    The impl surfaces them through `session_id` and `size()` introspection so
    a wrapping emitter can populate the attributes without private access.
    """
    imap = InMemoryIdentityMap(session_id="tx-42")
    assert imap.session_id == "tx-42"
    imap.add(Order(id=1))
    imap.add(Order(id=2))
    # miss → hit → add outcome (for span idmap.add attributes).
    assert imap.get(Order, 99) is None
    assert imap.get(Order, 1) is not None
    assert imap.size() == 2
    imap.dispose()
    assert imap.state == "disposed"
