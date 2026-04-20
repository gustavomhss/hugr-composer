"""Chaos / game-day tests for DataMapper.

Injects realistic faults at the map boundary: schema drift from upstream
replicas, mutating mapper implementations, concurrent registry churn, and
adversarial payload-kind corruption. Confirms the mapper FAILS LOUDLY rather
than silently smuggling bad rows to storage.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pytest

from DataMapper import (
    AbstractDataMapper,
    DataMapperInvariantError,
    MapperRegistry,
    SchemaDriftError,
)


@dataclass
class Item:
    id: int
    label: str


class ItemMapper(AbstractDataMapper[Item]):
    columns = frozenset({"id", "label"})
    identity_columns = ("id",)
    table = "items"

    def _row_to_entity(self, row: Mapping[str, Any]) -> Item:
        return Item(id=int(row["id"]), label=str(row["label"]))

    def _entity_to_row(self, entity: Item) -> dict[str, Any]:
        return {"id": entity.id, "label": entity.label}

    def _identity_key(self, entity: Item) -> tuple[Any, ...]:
        return (entity.id,)


def test_chaos_replica_drift_rejected_on_every_call() -> None:
    m = ItemMapper()
    # 100 rows from a stale replica missing a column → every single one fails.
    for i in range(100):
        with pytest.raises(SchemaDriftError):
            m.load({"id": i})  # missing label


def test_chaos_mutating_mapper_detected_first_call() -> None:
    class BadMapper(ItemMapper):
        def _entity_to_row(self, entity: Item) -> dict[str, Any]:
            entity.label = entity.label.upper()  # mutation
            return super()._entity_to_row(entity)

    bad = BadMapper()
    item = Item(id=1, label="a")
    with pytest.raises(DataMapperInvariantError):
        bad.insert(item)


def test_chaos_concurrent_registry_registration_is_safe() -> None:
    reg = MapperRegistry()
    errors: list[BaseException] = []
    wins: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            reg.register(Item, ItemMapper())
            with lock:
                wins.append(1)
        except DataMapperInvariantError:
            # duplicate registration — expected for losers
            pass
        except BaseException as exc:  # pragma: no cover — defensive
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(16)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert len(wins) == 1  # exactly one thread wins the race


def test_chaos_unknown_payload_kind_rejected() -> None:
    m = ItemMapper()
    item = Item(id=1, label="x")
    with pytest.raises(DataMapperInvariantError):
        m._map_with_guards(item, "upsert")  # not a declared kind


def test_chaos_io_attempt_counter_is_sticky() -> None:
    class LeakyMapper(ItemMapper):
        def _entity_to_row(self, entity: Item) -> dict[str, Any]:
            self._record_io_attempt()
            return super()._entity_to_row(entity)

    lm = LeakyMapper()
    item = Item(id=1, label="x")
    with pytest.raises(DataMapperInvariantError):
        lm.insert(item)
    # Subsequent calls also fail — the tripwire does not self-heal.
    with pytest.raises(DataMapperInvariantError):
        lm.insert(item)


def test_chaos_large_batch_keeps_domain_pure() -> None:
    m = ItemMapper()
    items = [Item(id=i, label=f"l{i}") for i in range(2000)]
    before = [dict(vars(it)) for it in items]
    payloads = [m.insert(it) for it in items]
    after = [dict(vars(it)) for it in items]
    assert before == after
    assert len(payloads) == 2000


def test_chaos_round_trip_under_repeated_pressure() -> None:
    m = ItemMapper()
    row = {"id": 999, "label": "stable"}
    for _ in range(500):
        p = m.round_trip(row)
        assert p["row"]["id"] == 999
