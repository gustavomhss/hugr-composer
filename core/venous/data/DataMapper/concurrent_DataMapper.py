"""Concurrency / linearizability harness for DataMapper.

The mapper itself is pure; however, the MapperRegistry and internal I/O
tripwire MUST behave correctly under thread races. These tests confirm:

- registry register() is atomic (exactly one writer wins),
- concurrent map calls on the same mapper instance preserve DM-INV-03 (no
  domain mutation) and DM-INV-04 (io_attempts stays zero),
- concurrent readers see consistent payload shapes.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from DataMapper import (
    AbstractDataMapper,
    DataMapperInvariantError,
    MapperRegistry,
)


@dataclass
class Packet:
    id: int
    body: str


class PacketMapper(AbstractDataMapper[Packet]):
    columns = frozenset({"id", "body", "body_len"})
    identity_columns = ("id",)
    table = "packets"

    def _row_to_entity(self, row: Mapping[str, Any]) -> Packet:
        return Packet(id=int(row["id"]), body=str(row["body"]))

    def _entity_to_row(self, entity: Packet) -> dict[str, Any]:
        return {
            "id": entity.id,
            "body": entity.body,
            "body_len": len(entity.body),
        }

    def _identity_key(self, entity: Packet) -> tuple[Any, ...]:
        return (entity.id,)


def test_concurrent_registry_single_winner() -> None:
    reg = MapperRegistry()
    winners: list[int] = []
    losers: list[int] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            reg.register(Packet, PacketMapper())
            with lock:
                winners.append(1)
        except DataMapperInvariantError:
            with lock:
                losers.append(1)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert len(winners) == 1
    assert len(losers) == 31


def test_concurrent_map_calls_preserve_domain() -> None:
    mapper = PacketMapper()
    packets = [Packet(id=i, body=f"b{i}") for i in range(20)]
    baseline = [dict(vars(p)) for p in packets]
    errors: list[BaseException] = []
    payload_counts: list[int] = []
    lock = threading.Lock()

    def worker(p: Packet) -> None:
        try:
            for _ in range(200):
                mapper.insert(p)
                mapper.update(p)
                mapper.delete(p)
            with lock:
                payload_counts.append(600)
        except BaseException as exc:
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(p,)) for p in packets]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert sum(payload_counts) == 20 * 600
    assert [dict(vars(p)) for p in packets] == baseline
    assert mapper._io_attempts == 0


def test_concurrent_round_trip_preserves_identity() -> None:
    mapper = PacketMapper()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            row = {"id": i, "body": f"x{i}", "body_len": len(f"x{i}")}
            for _ in range(100):
                p = mapper.round_trip(row)
                assert p["row"]["id"] == i
        except BaseException as exc:
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
