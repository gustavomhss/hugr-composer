"""Unit tests for ProcessingRecord — 3 per invariant."""

from __future__ import annotations

import pytest

from ProcessingRecord import (
    InMemoryProcessingRegistry,
    ProcessingRecord,
    ProcessingRecordError,
)


def _rec(**o: object) -> ProcessingRecord:
    base: dict[str, object] = {
        "activity": "user.signup",
        "controller": "AcmeCorp GmbH",
        "purposes": ("account_creation",),
        "data_classes": ("pii_email", "pii_name"),
        "recipients": ("internal",),
        "retention_ref": "retention:user_account",
        "legal_basis": "GDPR Art 6(1)(b) contract",
        "transfers_outside_eea": (),
    }
    base.update(o)
    return ProcessingRecord(**base)  # type: ignore[arg-type]


class _Resolver:
    def __init__(self, valid: set[str]) -> None:
        self._valid = valid

    def has(self, retention_ref: str) -> bool:
        return retention_ref in self._valid


# PR_INV_01 — every activity must register.
def test_inv_activity_registered_confirms() -> None:
    r = InMemoryProcessingRegistry()
    r.register(_rec())
    assert r.size == 1


def test_inv_activity_registered_prevents() -> None:
    r = InMemoryProcessingRegistry()
    with pytest.raises(ProcessingRecordError):
        _rec(activity="")


def test_inv_activity_registered_under_failure() -> None:
    with pytest.raises(ProcessingRecordError):
        _rec(purposes=())


# PR_INV_02 — retention_ref resolves.
def test_inv_retention_ref_confirms() -> None:
    resolver = _Resolver(valid={"retention:user_account"})
    r = InMemoryProcessingRegistry(retention_resolver=resolver)
    r.register(_rec())


def test_inv_retention_ref_prevents() -> None:
    resolver = _Resolver(valid=set())
    r = InMemoryProcessingRegistry(retention_resolver=resolver)
    with pytest.raises(ProcessingRecordError):
        r.register(_rec())


def test_inv_retention_ref_under_failure() -> None:
    with pytest.raises(ProcessingRecordError):
        _rec(retention_ref="")


# PR_INV_03 — legal_basis enum.
def test_inv_legal_basis_confirms() -> None:
    for lb in (
        "GDPR Art 6(1)(a) consent",
        "GDPR Art 6(1)(b) contract",
        "GDPR Art 6(1)(f) legitimate interest",
    ):
        _rec(legal_basis=lb)


def test_inv_legal_basis_prevents() -> None:
    for bad in ("consent", "legitimate", "", "Art 6"):
        with pytest.raises(ProcessingRecordError):
            _rec(legal_basis=bad)


def test_inv_legal_basis_under_failure() -> None:
    with pytest.raises(ProcessingRecordError):
        _rec(legal_basis="GDPR Art 6(1)(g) custom")


# PR_INV_04 — ISO-3166 alpha-2.
def test_inv_iso_countries_confirms() -> None:
    _rec(transfers_outside_eea=("US", "UK", "CA"))


def test_inv_iso_countries_prevents() -> None:
    with pytest.raises(ProcessingRecordError):
        _rec(transfers_outside_eea=("USA",))
    with pytest.raises(ProcessingRecordError):
        _rec(transfers_outside_eea=("us",))
    with pytest.raises(ProcessingRecordError):
        _rec(transfers_outside_eea=("",))


def test_inv_iso_countries_under_failure() -> None:
    with pytest.raises(ProcessingRecordError):
        _rec(transfers_outside_eea=("U1",))


# PR_INV_05 — export_ropa reproducible.
def test_inv_ropa_reproducible_confirms() -> None:
    r = InMemoryProcessingRegistry()
    r.register(_rec(activity="a"))
    r.register(_rec(activity="b"))
    one = r.export_ropa()
    two = r.export_ropa()
    assert one == two


def test_inv_ropa_reproducible_prevents() -> None:
    # Insertion order does NOT affect output — deterministic sort by activity.
    r1 = InMemoryProcessingRegistry()
    r2 = InMemoryProcessingRegistry()
    r1.register(_rec(activity="a"))
    r1.register(_rec(activity="b"))
    r2.register(_rec(activity="b"))
    r2.register(_rec(activity="a"))
    assert r1.export_ropa() == r2.export_ropa()


def test_inv_ropa_reproducible_under_failure() -> None:
    r = InMemoryProcessingRegistry()
    assert r.export_ropa() == b"[]"
