"""Unit tests for DataResidencyPolicy — 3 per invariant."""

from __future__ import annotations

import pytest
from DataResidencyPolicy import (
    DataResidencyPolicy,
    DataResidencyPolicyError,
    InMemoryResidencyEnforcer,
)


def _p(**o: object) -> DataResidencyPolicy:
    base: dict[str, object] = {
        "data_class": "eu_user_profile",
        "allowed_regions": ("DE", "IE", "FR"),
        "transfer_mechanism": "SCC_2021/914",
    }
    base.update(o)
    return DataResidencyPolicy(**base)  # type: ignore[arg-type]


# DRP_INV_01 — ISO-3166 alpha-2 regions.
def test_inv_iso_regions_confirms() -> None:
    _p(allowed_regions=("DE", "FR", "US", "JP"))


def test_inv_iso_regions_prevents() -> None:
    for bad in ("de", "DEU", "", "D1"):
        with pytest.raises(DataResidencyPolicyError):
            _p(allowed_regions=(bad,))


def test_inv_iso_regions_under_failure() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(_p())
    with pytest.raises(DataResidencyPolicyError):
        e.check_write("eu_user_profile", "deu")


# DRP_INV_02 — writes to non-allowed regions fail.
def test_inv_write_gate_confirms() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(_p())
    e.check_write("eu_user_profile", "DE")


def test_inv_write_gate_prevents() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(_p())
    with pytest.raises(DataResidencyPolicyError):
        e.check_write("eu_user_profile", "US")


def test_inv_write_gate_under_failure() -> None:
    e = InMemoryResidencyEnforcer()
    with pytest.raises(DataResidencyPolicyError):
        e.check_write("unbound_class", "DE")


# DRP_INV_03 — cross-EEA transfer requires mechanism (the policy always has one).
def test_inv_cross_border_confirms() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(_p(allowed_regions=("DE", "US"), transfer_mechanism="SCC_2021/914"))
    e.check_transfer("eu_user_profile", source="DE", destination="US")


def test_inv_cross_border_prevents() -> None:
    with pytest.raises(DataResidencyPolicyError):
        _p(transfer_mechanism="gentleman_agreement")


def test_inv_cross_border_under_failure() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(_p())
    # Destination not allowed → transfer fails.
    with pytest.raises(DataResidencyPolicyError):
        e.check_transfer("eu_user_profile", source="DE", destination="US")


# DRP_INV_04 — check_write MUST precede persistence.
def test_inv_write_time_enforcement_confirms() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(_p())
    # Surface exists for write-time checks.
    e.check_write("eu_user_profile", "DE")


def test_inv_write_time_enforcement_prevents() -> None:
    e = InMemoryResidencyEnforcer()
    # No surface to "undo" a write — enforcement is pre-write only.
    for attr in ("check_read", "check_after_write", "retroactive_check"):
        assert not hasattr(e, attr)


def test_inv_write_time_enforcement_under_failure() -> None:
    e = InMemoryResidencyEnforcer()
    with pytest.raises(DataResidencyPolicyError):
        e.check_write("no_policy", "DE")


# DRP_INV_05 — policy changes emit audit.
class _Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def append(self, actor: str, action: str, resource: str, outcome: str,
               attributes: object) -> str:
        self.rows.append({"action": action, "resource": resource})
        return "h"


def test_inv_policy_audit_confirms() -> None:
    sink = _Sink()
    e = InMemoryResidencyEnforcer(audit_sink=sink)
    e.bind(_p())
    assert any(r["action"] == "residency.policy_changed" for r in sink.rows)


def test_inv_policy_audit_prevents() -> None:
    # check_write does not emit; only bind does.
    sink = _Sink()
    e = InMemoryResidencyEnforcer(audit_sink=sink)
    e.bind(_p())
    before = len(sink.rows)
    e.check_write("eu_user_profile", "DE")
    assert len(sink.rows) == before


def test_inv_policy_audit_under_failure() -> None:
    # Without sink, bind still works.
    e = InMemoryResidencyEnforcer()
    e.bind(_p())
    assert e.size == 1
