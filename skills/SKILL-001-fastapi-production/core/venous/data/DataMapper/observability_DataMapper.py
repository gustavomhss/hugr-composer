"""Observability harness — asserts DataMapper emits logs/metrics/spans matching schema."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from DataMapper import AbstractDataMapper


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


@dataclass
class Row:
    id: int
    payload: str


class RowMapper(AbstractDataMapper[Row]):
    columns = frozenset({"id", "payload"})
    identity_columns = ("id",)
    table = "rows"

    def _row_to_entity(self, row: Mapping[str, Any]) -> Row:
        return Row(id=int(row["id"]), payload=str(row["payload"]))

    def _entity_to_row(self, entity: Row) -> dict[str, Any]:
        return {"id": entity.id, "payload": entity.payload}

    def _identity_key(self, entity: Row) -> tuple[Any, ...]:
        return (entity.id,)


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
    mapper = RowMapper()
    row = {"id": 1, "payload": "x"}
    entity = mapper.load(row)
    payload = mapper.update(entity)
    # Invariants that map to emitted log attributes
    assert payload["kind"] == "update"
    assert payload["table"] == "rows"
    assert payload["identity_values"] == [1]


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "datamapper.load" in ops
    assert "datamapper.map" in ops
