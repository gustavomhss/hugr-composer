"""Metamorphic + differential tests for AntiCorruptionLayer.

Algebraic properties:
- to_foreign(to_local(x)) preserves the foreign identity on a round-trip.
- to_local is idempotent on repeated invocations with the same input.
- guard is pure — calling it N times has no observable side effect.
- Two ACL instances with the SAME registered version behave identically
  (differential parity).
- Registering a version twice is last-write-wins.
"""

from __future__ import annotations

from collections.abc import Mapping

from AntiCorruptionLayer import (
    ContractVersion,
    DictAntiCorruptionLayer,
    VersionedAntiCorruptionLayer,
)


def _legit() -> Mapping[str, object]:
    return {"legacy_id": 9, "legacy_name": "Mallory"}


def test_metamorphic_round_trip_preserves_foreign_identity() -> None:
    acl = DictAntiCorruptionLayer()
    foreign = _legit()
    assert acl.to_foreign(acl.to_local(foreign)) == foreign


def test_metamorphic_to_local_is_idempotent() -> None:
    acl = DictAntiCorruptionLayer()
    a = acl.to_local(_legit())
    b = acl.to_local(_legit())
    assert a == b


def test_metamorphic_guard_is_pure() -> None:
    acl = DictAntiCorruptionLayer()
    payload = _legit()
    snapshot = dict(payload)
    for _ in range(10):
        acl.guard(payload)
    assert dict(payload) == snapshot


def test_differential_two_acls_same_version_agree() -> None:
    acl1 = DictAntiCorruptionLayer()
    acl2 = DictAntiCorruptionLayer()
    foreign = _legit()
    assert acl1.to_local(foreign) == acl2.to_local(foreign)
    assert acl1.to_foreign(acl1.to_local(foreign)) == acl2.to_foreign(acl2.to_local(foreign))


def test_metamorphic_register_version_last_write_wins() -> None:
    v = ContractVersion("sys.diff", "1.0")
    acl: VersionedAntiCorruptionLayer[object, object] = VersionedAntiCorruptionLayer(
        default_version=v,
    )
    acl.register_version(
        v,
        inbound=lambda b: {"answer": "first"},
        outbound=lambda local: local,
        guard=lambda b: None,
    )
    acl.register_version(
        v,
        inbound=lambda b: {"answer": "second"},
        outbound=lambda local: local,
        guard=lambda b: None,
    )
    assert acl.to_local({"x": 1}) == {"answer": "second"}


def test_metamorphic_inbound_never_returns_foreign_envelope() -> None:
    # For the reference ACL, result NEVER carries the foreign-shape keys.
    acl = DictAntiCorruptionLayer()
    out = acl.to_local(_legit())
    assert "legacy_id" not in out
    assert "legacy_name" not in out
