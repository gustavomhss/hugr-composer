"""Chaos / game-day tests for AntiCorruptionLayer.

Simulates hostile or buggy usage: malformed payloads, wrong-version drift,
hostile translators that leak types or try to re-enter the ACL, and very
large batches of inbound messages.
"""

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
    VersionedAntiCorruptionLayer,
)


def test_chaos_many_malformed_payloads_all_rejected() -> None:
    acl = DictAntiCorruptionLayer()
    failures = 0
    for i in range(500):
        payload = {"legacy_name": f"attacker-{i}"}  # missing legacy_id
        try:
            acl.guard(payload)
        except ForeignPayloadRejectedError:
            failures += 1
    assert failures == 500


def test_chaos_unknown_version_drift_raises() -> None:
    acl = DictAntiCorruptionLayer()
    for minor in range(10):
        unknown = ForeignPayload(ContractVersion("legacy.example", f"9.{minor}"), {})
        with pytest.raises(SchemaDriftError):
            acl.to_local(unknown)


def test_chaos_hostile_translator_leaks_foreign_type_blocked() -> None:
    version = ContractVersion("sys.evil", "1.0")
    acl: VersionedAntiCorruptionLayer[object, object] = VersionedAntiCorruptionLayer(
        default_version=version,
        foreign_types=(ForeignPayload,),
    )
    acl.register_version(
        version,
        inbound=lambda body: ForeignPayload(version, body),  # hostile
        outbound=lambda local: local,
        guard=lambda b: None,
    )
    with pytest.raises(ForeignTypeLeakError):
        acl.to_local({"x": 1})


def test_chaos_hostile_translator_reenters_blocked() -> None:
    version = ContractVersion("sys.loop", "1.0")
    acl: VersionedAntiCorruptionLayer[object, object] = VersionedAntiCorruptionLayer(
        default_version=version,
    )

    def bad(body: object) -> object:
        return acl.to_local({"depth": 1})

    acl.register_version(
        version,
        inbound=bad,
        outbound=lambda local: local,
        guard=lambda b: None,
    )
    with pytest.raises(StatefulTranslationError):
        acl.to_local({"depth": 0})


def test_chaos_large_batch_translations_stay_consistent() -> None:
    acl = DictAntiCorruptionLayer()
    for i in range(2000):
        local = acl.to_local({"legacy_id": i, "legacy_name": f"u{i}"})
        assert local == {"id": i, "name": f"u{i}"}


def test_chaos_guard_isolated_from_translator() -> None:
    # Raising inside the registered guard MUST surface as ForeignPayloadRejectedError
    # even if the caller's payload is a pathological object.
    acl = DictAntiCorruptionLayer()

    class _Weird:
        def __getitem__(self, _key: str) -> object:
            raise RuntimeError("hostile __getitem__")

    with pytest.raises(ForeignPayloadRejectedError):
        acl.guard(_Weird())


def test_chaos_outbound_translator_bug_surfaces_as_leak() -> None:
    class LocalOrder:
        pass

    version = ContractVersion("legacy.orders", "1.0")
    acl: VersionedAntiCorruptionLayer[LocalOrder, object] = VersionedAntiCorruptionLayer(
        default_version=version,
        local_types=(LocalOrder,),
    )
    acl.register_version(
        version,
        inbound=lambda b: LocalOrder(),
        outbound=lambda local: LocalOrder(),  # BUG: returns a local type
        guard=lambda b: None,
    )
    with pytest.raises(ForeignTypeLeakError):
        acl.to_foreign(LocalOrder())


def test_chaos_mixed_valid_and_invalid_stream() -> None:
    acl = DictAntiCorruptionLayer()
    ok = 0
    bad = 0
    for i in range(100):
        if i % 3 == 0:
            try:
                acl.to_local({"legacy_name": "bad"})  # missing id
            except ForeignPayloadRejectedError:
                bad += 1
        else:
            payload: Mapping[str, object] = {"legacy_id": i, "legacy_name": f"n{i}"}
            acl.to_local(payload)
            ok += 1
    assert ok + bad == 100
    assert bad > 0 and ok > 0
