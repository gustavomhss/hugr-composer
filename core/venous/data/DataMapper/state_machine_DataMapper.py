"""Hypothesis state-machine exploration of DataMapper behaviour.

The state machine drives a mapper through arbitrary interleavings of load /
insert / update / delete / round_trip and asserts:
- DM-INV-02: round-trips preserve identity,
- DM-INV-03: the mapped entity's vars() never drift across calls,
- DM-INV-04: io_attempts stays at 0.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from DataMapper import (
    AbstractDataMapper,
)


@dataclass
class Thing:
    id: int
    name: str
    qty: int


class ThingMapper(AbstractDataMapper[Thing]):
    columns = frozenset({"id", "name", "qty", "qty_sq"})
    identity_columns = ("id",)
    table = "things"

    def _row_to_entity(self, row: Mapping[str, Any]) -> Thing:
        return Thing(id=int(row["id"]), name=str(row["name"]), qty=int(row["qty"]))

    def _entity_to_row(self, entity: Thing) -> dict[str, Any]:
        return {
            "id": entity.id,
            "name": entity.name,
            "qty": entity.qty,
            "qty_sq": entity.qty * entity.qty,
        }

    def _identity_key(self, entity: Thing) -> tuple[Any, ...]:
        return (entity.id,)


class DataMapperMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.mapper: ThingMapper = ThingMapper()
        self.entities: dict[int, Thing] = {}
        self.baseline_vars: dict[int, dict[str, Any]] = {}

    @rule(
        ident=st.integers(min_value=0, max_value=50),
        name=st.text(min_size=0, max_size=8),
        qty=st.integers(min_value=0, max_value=1000),
    )
    def create_entity(self, ident: int, name: str, qty: int) -> None:
        if ident in self.entities:
            return
        e = Thing(id=ident, name=name, qty=qty)
        self.entities[ident] = e
        self.baseline_vars[ident] = dict(vars(e))

    @rule(ident=st.integers(min_value=0, max_value=50))
    def do_insert(self, ident: int) -> None:
        if ident not in self.entities:
            return
        payload = self.mapper.insert(self.entities[ident])
        assert payload["row"]["id"] == ident
        assert payload["identity_values"] == [ident]

    @rule(ident=st.integers(min_value=0, max_value=50))
    def do_update(self, ident: int) -> None:
        if ident not in self.entities:
            return
        payload = self.mapper.update(self.entities[ident])
        assert payload["kind"] == "update"

    @rule(ident=st.integers(min_value=0, max_value=50))
    def do_delete(self, ident: int) -> None:
        if ident not in self.entities:
            return
        payload = self.mapper.delete(self.entities[ident])
        assert payload["kind"] == "delete"
        assert payload["row"] == {"id": ident}

    @rule(ident=st.integers(min_value=0, max_value=50))
    def do_round_trip(self, ident: int) -> None:
        if ident not in self.entities:
            return
        e = self.entities[ident]
        row = self.mapper._entity_to_row(e)
        payload = self.mapper.round_trip(row)
        assert payload["row"]["id"] == ident

    @invariant()
    def domain_never_mutated(self) -> None:
        if not hasattr(self, "entities"):
            return
        for ident, e in self.entities.items():
            assert vars(e) == self.baseline_vars[ident]

    @invariant()
    def no_io_ever(self) -> None:
        if not hasattr(self, "mapper"):
            return
        assert self.mapper._io_attempts == 0


TestDataMapperMachine = DataMapperMachine.TestCase
