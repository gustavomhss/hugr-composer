"""Unit tests for DataMapper — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from DataMapper import (
    PAYLOAD_INSERT,
    PAYLOAD_UPDATE,
    AbstractDataMapper,
    DataMapperInvariantError,
    MapperRegistry,
    SchemaDriftError,
    assert_domain_has_no_storage_coupling,
    detect_schema_drift,
)


# ---------------------------------------------------------------------------
# Pure domain object — NO storage imports (fixture for DM-INV-01)
# ---------------------------------------------------------------------------
@dataclass
class Account:
    id: int
    owner: str
    balance: int
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Concrete mapper — subclass of AbstractDataMapper
# ---------------------------------------------------------------------------
class AccountMapper(AbstractDataMapper[Account]):
    columns = frozenset({"id", "owner", "balance", "tags_csv", "balance_plus_tax"})
    identity_columns = ("id",)
    table = "accounts"

    def _row_to_entity(self, row: Mapping[str, Any]) -> Account:
        tags = [t for t in str(row["tags_csv"]).split(",") if t]
        return Account(
            id=int(row["id"]),
            owner=str(row["owner"]),
            balance=int(row["balance"]),
            tags=tags,
        )

    def _entity_to_row(self, entity: Account) -> dict[str, Any]:
        # Derived column ``balance_plus_tax`` is computed here — NEVER injected
        # back into the Account instance (DM-INV-03).
        return {
            "id": entity.id,
            "owner": entity.owner,
            "balance": entity.balance,
            "tags_csv": ",".join(entity.tags),
            "balance_plus_tax": entity.balance + entity.balance // 10,
        }

    def _identity_key(self, entity: Account) -> tuple[Any, ...]:
        return (entity.id,)


# ---------------------------------------------------------------------------
# DM_INV_01 — domain decoupled from storage
# ---------------------------------------------------------------------------
def test_inv_domain_decoupled_confirms() -> None:
    # Account lives in this test module; this module imports no storage libs.
    assert_domain_has_no_storage_coupling(Account)
    mapper = AccountMapper()
    row = {
        "id": 1,
        "owner": "alice",
        "balance": 100,
        "tags_csv": "vip,eu",
        "balance_plus_tax": 110,
    }
    acc = mapper.load(row)
    assert isinstance(acc, Account)
    # The domain object has no persistence fields.
    assert not hasattr(acc, "balance_plus_tax")


def test_inv_domain_decoupled_prevents() -> None:
    # Build a synthetic "domain" module that imports sqlite3 and verify we reject it.
    import sqlite3  # stdlib — used as a stand-in forbidden storage symbol
    import sys as _sys
    import types as _types

    fake = _types.ModuleType("fake_domain_module_for_dm_inv_01")
    fake.sqlite3 = sqlite3  # type: ignore[attr-defined]  # DM-INV-01: coupling witness

    class Coupled:
        pass

    Coupled.__module__ = fake.__name__
    _sys.modules[fake.__name__] = fake
    try:
        with pytest.raises(DataMapperInvariantError):
            assert_domain_has_no_storage_coupling(Coupled)
    finally:
        _sys.modules.pop(fake.__name__, None)


def test_inv_domain_decoupled_under_failure() -> None:
    # Even under repeated registration attempts, a coupled class NEVER lands in the registry.
    import sqlite3
    import sys as _sys
    import types as _types

    fake = _types.ModuleType("fake_domain_module_for_dm_inv_01_reg")
    fake.sqlite3 = sqlite3  # type: ignore[attr-defined]  # DM-INV-01: coupling witness

    class Coupled:
        pass

    Coupled.__module__ = fake.__name__
    _sys.modules[fake.__name__] = fake

    reg = MapperRegistry()
    mapper = AccountMapper()
    try:
        for _ in range(25):
            with pytest.raises(DataMapperInvariantError):
                reg.register(Coupled, mapper)
        with pytest.raises(DataMapperInvariantError):
            reg.get(Coupled)
    finally:
        _sys.modules.pop(fake.__name__, None)


# ---------------------------------------------------------------------------
# DM_INV_02 — round-trip identity + schema drift
# ---------------------------------------------------------------------------
def test_inv_round_trip_identity_confirms() -> None:
    mapper = AccountMapper()
    row = {
        "id": 42,
        "owner": "bob",
        "balance": 500,
        "tags_csv": "retail",
        "balance_plus_tax": 550,
    }
    payload = mapper.round_trip(row)
    assert payload["kind"] == PAYLOAD_UPDATE
    assert payload["row"]["id"] == 42  # identity preserved
    assert payload["identity_values"] == [42]


def test_inv_round_trip_identity_prevents() -> None:
    # Schema drift — missing a required column — MUST be rejected before round-trip.
    mapper = AccountMapper()
    with pytest.raises(SchemaDriftError):
        mapper.load({"id": 1, "owner": "x", "balance": 10})  # missing tags_csv/tax
    # Unknown column — also rejected.
    with pytest.raises(SchemaDriftError):
        mapper.load({
            "id": 1, "owner": "x", "balance": 10,
            "tags_csv": "", "balance_plus_tax": 11,
            "secret_flag": True,
        })


def test_inv_round_trip_identity_under_failure() -> None:
    # A broken mapper that rewrites the identity key MUST be detected by round_trip.
    class BrokenMapper(AccountMapper):
        def _entity_to_row(self, entity: Account) -> dict[str, Any]:
            row = super()._entity_to_row(entity)
            row["id"] = entity.id + 1  # identity-mangling bug
            return row

    bm = BrokenMapper()
    row = {
        "id": 7,
        "owner": "zed",
        "balance": 1,
        "tags_csv": "",
        "balance_plus_tax": 1,
    }
    with pytest.raises(DataMapperInvariantError):
        bm.round_trip(row)


# ---------------------------------------------------------------------------
# DM_INV_03 — no domain mutation
# ---------------------------------------------------------------------------
def test_inv_no_domain_mutation_confirms() -> None:
    mapper = AccountMapper()
    acc = Account(id=1, owner="alice", balance=100, tags=["eu"])
    before_vars = dict(vars(acc))
    payload = mapper.insert(acc)
    after_vars = dict(vars(acc))
    assert before_vars == after_vars
    assert "balance_plus_tax" not in after_vars
    assert payload["row"]["balance_plus_tax"] == 110


def test_inv_no_domain_mutation_prevents() -> None:
    class MutatingMapper(AccountMapper):
        def _entity_to_row(self, entity: Account) -> dict[str, Any]:
            # Injecting a derived column back into the domain is forbidden.
            entity.tags.append("__injected__")
            return super()._entity_to_row(entity)

    mm = MutatingMapper()
    acc = Account(id=1, owner="alice", balance=10, tags=["eu"])
    with pytest.raises(DataMapperInvariantError):
        mm.insert(acc)


def test_inv_no_domain_mutation_under_failure() -> None:
    # Repeated invocations of a correct mapper NEVER drift the domain state.
    mapper = AccountMapper()
    acc = Account(id=9, owner="u", balance=1000, tags=["a", "b"])
    baseline = dict(vars(acc))
    for _ in range(100):
        mapper.insert(acc)
        mapper.update(acc)
        mapper.delete(acc)
    assert vars(acc) == baseline


# ---------------------------------------------------------------------------
# DM_INV_04 — no direct I/O; payload semantics
# ---------------------------------------------------------------------------
def test_inv_no_direct_io_confirms() -> None:
    mapper = AccountMapper()
    acc = Account(id=3, owner="u", balance=200, tags=[])
    payload = mapper.insert(acc)
    assert payload["kind"] == PAYLOAD_INSERT
    assert payload["table"] == "accounts"
    assert "row" in payload
    # No I/O recorded.
    assert mapper._io_attempts == 0


def test_inv_no_direct_io_prevents() -> None:
    class IoMapper(AccountMapper):
        def _entity_to_row(self, entity: Account) -> dict[str, Any]:
            self._record_io_attempt()  # simulate DB call
            return super()._entity_to_row(entity)

    m = IoMapper()
    acc = Account(id=5, owner="u", balance=50, tags=[])
    with pytest.raises(DataMapperInvariantError):
        m.insert(acc)


def test_inv_no_direct_io_under_failure() -> None:
    # A mapper that returns a partial row (missing declared columns) MUST fail;
    # this proves the payload guard fires before any would-be flush.
    class TruncatingMapper(AccountMapper):
        def _entity_to_row(self, entity: Account) -> dict[str, Any]:
            full = super()._entity_to_row(entity)
            full.pop("balance_plus_tax", None)
            return full

    tm = TruncatingMapper()
    acc = Account(id=8, owner="u", balance=1, tags=[])
    with pytest.raises(SchemaDriftError):
        tm.insert(acc)


# ---------------------------------------------------------------------------
# Drift detector unit coverage
# ---------------------------------------------------------------------------
def test_detect_schema_drift_allows_extra_when_flagged() -> None:
    expected = frozenset({"a", "b"})
    detect_schema_drift({"a": 1, "b": 2, "c": 3}, expected, allow_extra=True)


def test_detect_schema_drift_rejects_extra_by_default() -> None:
    with pytest.raises(SchemaDriftError):
        detect_schema_drift({"a": 1, "b": 2, "c": 3}, frozenset({"a", "b"}))
