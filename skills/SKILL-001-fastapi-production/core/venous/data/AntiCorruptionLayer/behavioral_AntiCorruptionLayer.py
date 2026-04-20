"""Behavioral end-to-end scenarios for AntiCorruptionLayer — proves invariants at runtime."""

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
    detect_schema_drift,
)


class _FakeRepo:
    """Stand-in for a local aggregate repository.

    The ACL MUST NEVER touch this repo during translation (ACL-INV-03). The
    scenarios below call ``repo.add`` AFTER the ACL has produced a local
    value — the repo's ``calls`` counter proves the ordering.
    """

    def __init__(self) -> None:
        self.calls: int = 0
        self.stored: list[Mapping[str, object]] = []

    def add(self, local: Mapping[str, object]) -> None:
        self.calls += 1
        self.stored.append(local)


def test_scenario_inbound_payload_is_fully_translated() -> None:
    acl = DictAntiCorruptionLayer()
    repo = _FakeRepo()
    msg = {"legacy_id": 7, "legacy_name": "Bob"}
    acl.guard(msg)
    local = acl.to_local(msg)
    repo.add(local)  # domain side runs AFTER translation (ACL-INV-01)
    assert repo.stored == [{"id": 7, "name": "Bob"}]
    # The foreign shape has disappeared from the local value entirely.
    assert "legacy_id" not in local
    assert "legacy_name" not in local


def test_scenario_bidirectional_round_trip_preserves_identity() -> None:
    acl = DictAntiCorruptionLayer()
    foreign = {"legacy_id": 1, "legacy_name": "Eve"}
    local = acl.to_local(foreign)
    back = acl.to_foreign(local)
    assert back == foreign


def test_scenario_guard_rejects_before_domain_is_touched() -> None:
    acl = DictAntiCorruptionLayer()
    repo = _FakeRepo()
    # A malformed payload: guard MUST raise before the repository sees anything.
    with pytest.raises(ForeignPayloadRejectedError):
        acl.guard({"legacy_name": "no id"})
    assert repo.calls == 0


def test_scenario_multiversion_old_and_new_payloads_both_work() -> None:
    v_old = ContractVersion("legacy.billing", "1.0")
    v_new = ContractVersion("legacy.billing", "2.0")
    acl: VersionedAntiCorruptionLayer[Mapping[str, object], Mapping[str, object]] = (
        VersionedAntiCorruptionLayer(default_version=v_new)
    )

    def _guard_v1(b: object) -> None:
        if not isinstance(b, Mapping) or "user_id" not in b:
            raise ForeignPayloadRejectedError("v1 missing user_id")

    def _guard_v2(b: object) -> None:
        if not isinstance(b, Mapping) or "id" not in b:
            raise ForeignPayloadRejectedError("v2 missing id")

    def _in_v1(b: object) -> Mapping[str, object]:
        assert isinstance(b, Mapping)
        return {"id": b["user_id"], "name": b.get("full_name", "?")}

    def _in_v2(b: object) -> Mapping[str, object]:
        assert isinstance(b, Mapping)
        return {"id": b["id"], "name": b.get("name", "?")}

    def _out_passthrough(local: object) -> Mapping[str, object]:
        assert isinstance(local, Mapping)
        return {"id": local["id"], "name": local["name"]}

    acl.register_version(v_old, inbound=_in_v1, outbound=_out_passthrough, guard=_guard_v1)
    acl.register_version(v_new, inbound=_in_v2, outbound=_out_passthrough, guard=_guard_v2)

    old_msg = ForeignPayload(v_old, {"user_id": 1, "full_name": "Old"})
    new_msg = ForeignPayload(v_new, {"id": 2, "name": "New"})
    assert acl.to_local(old_msg) == {"id": 1, "name": "Old"}
    assert acl.to_local(new_msg) == {"id": 2, "name": "New"}


def test_scenario_schema_drift_is_detected_and_logged() -> None:
    acl = DictAntiCorruptionLayer()
    unknown = ForeignPayload(ContractVersion("legacy.example", "9.0-beta"), {"legacy_id": 1})
    # Helper surfaces drift without raising — useful for metrics.
    assert detect_schema_drift(acl, unknown) is True
    # Translation still raises loudly so the caller cannot silently proceed.
    with pytest.raises(SchemaDriftError):
        acl.to_local(unknown)


def test_scenario_stateful_translator_is_forbidden() -> None:
    # A translator that reads from the local repository (modelled as ACL re-entry)
    # MUST be blocked (ACL-INV-03).
    version = ContractVersion("sys.tainted", "1.0")
    acl: VersionedAntiCorruptionLayer[object, object] = VersionedAntiCorruptionLayer(
        default_version=version,
    )

    def bad_translator(body: object) -> object:
        return acl.to_local({"echo": True})

    acl.register_version(
        version,
        inbound=bad_translator,
        outbound=lambda local: local,
        guard=lambda b: None,
    )
    with pytest.raises(StatefulTranslationError):
        acl.to_local({"trigger": 1})


def test_scenario_outbound_never_returns_local_type() -> None:
    class LocalOrder:
        def __init__(self, oid: int) -> None:
            self.oid = oid

    version = ContractVersion("legacy.orders", "1.0")
    acl: VersionedAntiCorruptionLayer[LocalOrder, object] = VersionedAntiCorruptionLayer(
        default_version=version,
        local_types=(LocalOrder,),
    )

    def bad_outbound(local: object) -> object:
        # Intentionally returns the local type unchanged — MUST be rejected.
        return local

    acl.register_version(
        version,
        inbound=lambda b: LocalOrder(1),
        outbound=bad_outbound,
        guard=lambda b: None,
    )
    with pytest.raises(ForeignTypeLeakError):
        acl.to_foreign(LocalOrder(42))
