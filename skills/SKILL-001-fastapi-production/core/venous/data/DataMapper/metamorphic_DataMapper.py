"""Metamorphic + differential tests for DataMapper.

Algebraic laws:
- load ∘ (row from insert) ≈ identity on the entity (round-trip identity).
- update is idempotent on the persistence-visible columns: update(e) == update(update_result_domain(e)).
- delete payload is a projection: row ⊆ identity columns.
- Two different orderings of (insert, update, delete) on independent entities yield
  the same payload set regardless of order (mapper is order-independent).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from DataMapper import (
    PAYLOAD_DELETE,
    PAYLOAD_UPDATE,
    AbstractDataMapper,
)


@dataclass
class Widget:
    id: int
    name: str
    qty: int


class WidgetMapper(AbstractDataMapper[Widget]):
    columns = frozenset({"id", "name", "qty", "qty_doubled"})
    identity_columns = ("id",)
    table = "widgets"

    def _row_to_entity(self, row: Mapping[str, Any]) -> Widget:
        return Widget(id=int(row["id"]), name=str(row["name"]), qty=int(row["qty"]))

    def _entity_to_row(self, entity: Widget) -> dict[str, Any]:
        return {
            "id": entity.id,
            "name": entity.name,
            "qty": entity.qty,
            "qty_doubled": entity.qty * 2,
        }

    def _identity_key(self, entity: Widget) -> tuple[Any, ...]:
        return (entity.id,)


def test_metamorphic_load_insert_load_yields_equal_entity() -> None:
    m = WidgetMapper()
    row = {"id": 3, "name": "bolt", "qty": 10, "qty_doubled": 20}
    e1 = m.load(row)
    payload = m.insert(e1)
    e2 = m.load(payload["row"])
    assert e1 == e2


def test_metamorphic_update_is_idempotent_on_row_projection() -> None:
    m = WidgetMapper()
    w = Widget(id=5, name="nut", qty=7)
    p1 = m.update(w)
    p2 = m.update(w)  # same entity, same call
    assert p1 == p2
    assert p1["kind"] == PAYLOAD_UPDATE


def test_metamorphic_delete_row_is_identity_projection() -> None:
    m = WidgetMapper()
    w = Widget(id=17, name="pin", qty=999)
    p = m.delete(w)
    assert p["kind"] == PAYLOAD_DELETE
    assert set(p["row"].keys()) == set(m.identity_columns)
    assert p["row"]["id"] == 17


def test_metamorphic_order_independence() -> None:
    m = WidgetMapper()
    a = Widget(id=1, name="a", qty=1)
    b = Widget(id=2, name="b", qty=2)
    c = Widget(id=3, name="c", qty=3)

    seq_a = [m.insert(a), m.update(b), m.delete(c)]
    seq_b = [m.delete(c), m.update(b), m.insert(a)]
    # Order-independence on the *set* of payloads emitted.
    def key(p: dict[str, Any]) -> tuple[str, int]:
        return (p["kind"], int(p["identity_values"][0]))

    assert sorted(seq_a, key=key) == sorted(seq_b, key=key)


def test_differential_row_equal_after_round_trip() -> None:
    m = WidgetMapper()
    row = {"id": 42, "name": "x", "qty": 5, "qty_doubled": 10}
    e = m.load(row)
    again = m.update(e)["row"]
    assert again == row  # Differential: round-trip leaves row bit-equal.
