"""Behavioral end-to-end scenarios for DataMapper — proves invariants at runtime.

These scenarios wire a DataMapper into a UnitOfWork-like flush pipeline and
exercise realistic bidirectional flows: load → mutate → insert/update,
batch persistence, schema evolution, and registry-based dispatch.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pytest

from DataMapper import (
    PAYLOAD_DELETE,
    PAYLOAD_INSERT,
    PAYLOAD_UPDATE,
    AbstractDataMapper,
    DataMapperInvariantError,
    MapperRegistry,
    SchemaDriftError,
    enqueue_payload_sink,
)


@dataclass
class Order:
    id: int
    customer: str
    total_cents: int
    status: str


class OrderMapper(AbstractDataMapper[Order]):
    columns = frozenset({"id", "customer", "total_cents", "status", "total_with_vat"})
    identity_columns = ("id",)
    table = "orders"

    def _row_to_entity(self, row: Mapping[str, Any]) -> Order:
        return Order(
            id=int(row["id"]),
            customer=str(row["customer"]),
            total_cents=int(row["total_cents"]),
            status=str(row["status"]),
        )

    def _entity_to_row(self, entity: Order) -> dict[str, Any]:
        return {
            "id": entity.id,
            "customer": entity.customer,
            "total_cents": entity.total_cents,
            "status": entity.status,
            "total_with_vat": entity.total_cents + entity.total_cents * 20 // 100,
        }

    def _identity_key(self, entity: Order) -> tuple[Any, ...]:
        return (entity.id,)


def test_scenario_load_mutate_update_round_trip() -> None:
    mapper = OrderMapper()
    row = {
        "id": 101,
        "customer": "alice",
        "total_cents": 10_000,
        "status": "pending",
        "total_with_vat": 12_000,
    }
    order = mapper.load(row)
    order.status = "shipped"  # domain mutation — allowed, done by the app
    payload = mapper.update(order)
    assert payload["kind"] == PAYLOAD_UPDATE
    assert payload["row"]["id"] == 101  # identity preserved
    assert payload["row"]["status"] == "shipped"
    assert payload["row"]["total_with_vat"] == 12_000


def test_scenario_batch_insert_drained_into_uow_sink() -> None:
    mapper = OrderMapper()
    sink, flush = enqueue_payload_sink()
    orders = [
        Order(id=i, customer=f"c{i}", total_cents=1000 * i, status="new")
        for i in range(1, 6)
    ]
    payloads = [mapper.insert(o) for o in orders]
    flush(payloads)
    assert len(sink) == 5
    assert all(p["kind"] == PAYLOAD_INSERT for p in sink)
    assert [p["row"]["id"] for p in sink] == [1, 2, 3, 4, 5]


def test_scenario_delete_emits_identity_only_payload() -> None:
    mapper = OrderMapper()
    order = Order(id=7, customer="x", total_cents=1, status="cancelled")
    payload = mapper.delete(order)
    assert payload["kind"] == PAYLOAD_DELETE
    assert payload["row"] == {"id": 7}
    assert payload["identity_values"] == [7]


def test_scenario_schema_drift_blocks_load_before_translation() -> None:
    mapper = OrderMapper()
    # Simulated bad row from a stale replica missing the new derived column.
    bad = {"id": 1, "customer": "a", "total_cents": 1, "status": "n"}
    with pytest.raises(SchemaDriftError):
        mapper.load(bad)


def test_scenario_registry_dispatches_by_type() -> None:
    reg = MapperRegistry()
    reg.register(Order, OrderMapper())
    o = Order(id=11, customer="y", total_cents=500, status="new")
    mapper = reg.for_entity(o)
    payload = mapper.insert(o)
    assert payload["table"] == "orders"
    # Unregistered type raises.
    class Unknown:
        pass

    with pytest.raises(DataMapperInvariantError):
        reg.get(Unknown)


def test_scenario_domain_stays_pure_across_many_flushes() -> None:
    mapper = OrderMapper()
    order = Order(id=2, customer="c2", total_cents=2000, status="new")
    before = dict(vars(order))
    sink, flush = enqueue_payload_sink()
    for _ in range(50):
        flush([mapper.update(order)])
    after = dict(vars(order))
    assert before == after
    assert len(sink) == 50
