"""Unit tests for AntiCorruptionLayer — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from AntiCorruptionLayer import (
    ContractVersion,
    DictAntiCorruptionLayer,
    ForeignPayload,
    ForeignPayloadRejectedError,
    ForeignTypeLeakError,
    SchemaDriftError,
    StatefulTranslationError,
    UnversionedContractError,
    VersionedAntiCorruptionLayer,
)


def _legit_payload() -> Mapping[str, object]:
    return {"legacy_id": 42, "legacy_name": "Alice"}


# ---------------------------------------------------------------------------
# ACL_INV_01 — foreign types NEVER leak into the local domain
# ---------------------------------------------------------------------------
def test_inv_no_foreign_leak_confirms() -> None:
    acl = DictAntiCorruptionLayer()
    local = acl.to_local(_legit_payload())
    assert local == {"id": 42, "name": "Alice"}
    # No ForeignPayload ever appears on the local side.
    assert not isinstance(local, ForeignPayload)


def test_inv_no_foreign_leak_prevents() -> None:
    version = ContractVersion("sys.X", "1.0")
    acl: VersionedAntiCorruptionLayer[object, object] = VersionedAntiCorruptionLayer(
        default_version=version,
        foreign_types=(ForeignPayload,),
    )
    acl.register_version(
        version,
        inbound=lambda body: ForeignPayload(version, body),  # buggy translator
        outbound=lambda local: local,
        guard=lambda body: None,
    )
    with pytest.raises(ForeignTypeLeakError):
        acl.to_local({"k": 1})


def test_inv_no_foreign_leak_under_failure() -> None:
    # Repeated translation attempts MUST NOT accumulate state or corrupt the ACL.
    acl = DictAntiCorruptionLayer()
    for _ in range(50):
        local = acl.to_local(_legit_payload())
        assert local == {"id": 42, "name": "Alice"}
    # A hostile envelope with an unknown version MUST STILL raise drift after
    # many correct translations — no state has polluted the registry.
    with pytest.raises(SchemaDriftError):
        acl.to_local(ForeignPayload(ContractVersion("sys.ghost", "9.9"), {}))


# ---------------------------------------------------------------------------
# ACL_INV_02 — guard rejects invalid inbound payloads BEFORE translation
# ---------------------------------------------------------------------------
def test_inv_guard_rejects_invalid_confirms() -> None:
    acl = DictAntiCorruptionLayer()
    # Guard is a no-op on a well-formed payload.
    acl.guard(_legit_payload())


def test_inv_guard_rejects_invalid_prevents() -> None:
    acl = DictAntiCorruptionLayer()
    # Missing required field — guard MUST raise.
    with pytest.raises(ForeignPayloadRejectedError):
        acl.guard({"legacy_name": "Alice"})
    # Wrong type — guard MUST raise.
    with pytest.raises(ForeignPayloadRejectedError):
        acl.guard({"legacy_id": 1, "legacy_name": 9999})


def test_inv_guard_rejects_invalid_under_failure() -> None:
    acl = DictAntiCorruptionLayer()
    # Calling to_local on an invalid payload MUST NOT reach the inbound fn —
    # the guard raises first, and no "id" key is ever produced locally.
    translated: list[object] = []

    def spy_inbound(body: object) -> Mapping[str, object]:
        translated.append(body)
        return {"id": -1, "name": "leaked"}

    acl.register_version(
        acl.default_version,
        inbound=spy_inbound,
        outbound=DictAntiCorruptionLayer.outbound_fn,
        guard=DictAntiCorruptionLayer.guard_fn,
    )
    with pytest.raises(ForeignPayloadRejectedError):
        acl.to_local({"legacy_name": "still no id"})
    assert translated == []


# ---------------------------------------------------------------------------
# ACL_INV_03 — translation is stateless (no re-entry into the ACL)
# ---------------------------------------------------------------------------
def test_inv_stateless_translation_confirms() -> None:
    acl = DictAntiCorruptionLayer()
    # A pure translator completes without raising the re-entry guard.
    for i in range(10):
        out = acl.to_local({"legacy_id": i, "legacy_name": f"n{i}"})
        assert out["id"] == i


def test_inv_stateless_translation_prevents() -> None:
    version = ContractVersion("sys.Y", "2.0")
    acl: VersionedAntiCorruptionLayer[object, object] = VersionedAntiCorruptionLayer(
        default_version=version,
    )

    # A stateful translator that calls BACK into the ACL is rejected.
    def hostile_inbound(body: object) -> object:
        return acl.to_local({"legacy_id": 1, "legacy_name": "x"})

    acl.register_version(
        version,
        inbound=hostile_inbound,
        outbound=lambda local: local,
        guard=lambda body: None,
    )
    with pytest.raises(StatefulTranslationError):
        acl.to_local({"seed": True})


def test_inv_stateless_translation_under_failure() -> None:
    # Even when a prior translation raised, the re-entry counter is reset.
    version = ContractVersion("sys.Z", "3.0")
    acl: VersionedAntiCorruptionLayer[object, object] = VersionedAntiCorruptionLayer(
        default_version=version,
    )
    attempts = {"n": 0}

    def flaky_inbound(body: object) -> object:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ValueError("flaky translator")
        return {"ok": True}

    acl.register_version(
        version,
        inbound=flaky_inbound,
        outbound=lambda local: local,
        guard=lambda body: None,
    )
    # First two calls raise; the re-entry depth must be back to 0 on success.
    for _ in range(2):
        with pytest.raises(ValueError):
            acl.to_local({"x": 1})
    result = acl.to_local({"x": 1})
    assert result == {"ok": True}


# ---------------------------------------------------------------------------
# ACL_INV_04 — explicit versioning is mandatory
# ---------------------------------------------------------------------------
def test_inv_explicit_version_confirms() -> None:
    v = ContractVersion("legacy.billing", "2024-01")
    acl: VersionedAntiCorruptionLayer[object, object] = VersionedAntiCorruptionLayer(
        default_version=v,
    )
    acl.register_version(
        v,
        inbound=lambda b: b,
        outbound=lambda local: local,
        guard=lambda b: None,
    )
    assert acl.default_version == v
    assert v in acl.known_versions()


def test_inv_explicit_version_prevents() -> None:
    # Empty strings are rejected at ContractVersion construction time.
    with pytest.raises(UnversionedContractError):
        ContractVersion("", "1.0")
    with pytest.raises(UnversionedContractError):
        ContractVersion("sys", "")


def test_inv_explicit_version_under_failure() -> None:
    acl = DictAntiCorruptionLayer()
    # A payload for an unknown version MUST surface SchemaDrift, not silently
    # fall back to the default translator.
    unknown = ForeignPayload(ContractVersion("legacy.example", "9.9"), {"x": 1})
    with pytest.raises(SchemaDriftError):
        acl.guard(unknown)
    with pytest.raises(SchemaDriftError):
        acl.to_local(unknown)
