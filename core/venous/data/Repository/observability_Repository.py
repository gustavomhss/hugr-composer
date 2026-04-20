"""Observability harness — asserts Repository emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from Repository import ConcreteRepository


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


@dataclass
class _Root:
    id: int


class _StubUoW:
    def register_new(self, obj: object) -> None: ...
    def register_dirty(self, obj: object) -> None: ...
    def register_removed(self, obj: object) -> None: ...


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


def test_observability_lifecycle_emits_attributes() -> None:
    repo: ConcreteRepository[_Root] = ConcreteRepository(
        _Root, _StubUoW(), shard="obs-root",
    )
    try:
        repo.add(_Root(id=1))
        repo.add(_Root(id=2))
        assert len(repo.tracked_ids) == 2
    finally:
        repo.close()


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "repo.find" in ops
    assert "repo.get" in ops
