"""Hypothesis state-machine exploration of AntiCorruptionLayer + VersionedAntiCorruptionLayer."""

from __future__ import annotations

from collections.abc import Mapping

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from AntiCorruptionLayer import (
    ContractVersion,
    ForeignPayload,
    ForeignPayloadRejectedError,
    ForeignTypeLeakError,
    SchemaDriftError,
    VersionedAntiCorruptionLayer,
)


_SYSTEM = "sys.sm"


def _mk_version(tag: str) -> ContractVersion:
    return ContractVersion(_SYSTEM, tag)


def _inbound_ok(body: object) -> Mapping[str, object]:
    assert isinstance(body, Mapping)
    return {"id": body["legacy_id"]}


def _outbound_ok(local: object) -> Mapping[str, object]:
    assert isinstance(local, Mapping)
    return {"legacy_id": local["id"]}


def _guard_ok(body: object) -> None:
    if not isinstance(body, Mapping) or "legacy_id" not in body:
        raise ForeignPayloadRejectedError("missing legacy_id")


class AntiCorruptionLayerMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        v = _mk_version("1.0")
        self.default = v
        self.acl: VersionedAntiCorruptionLayer[object, object] = (
            VersionedAntiCorruptionLayer(default_version=v)
        )
        self.acl.register_version(v, inbound=_inbound_ok, outbound=_outbound_ok, guard=_guard_ok)
        self.registered_tags: set[str] = {"1.0"}

    @rule(
        legacy_id=st.integers(min_value=0, max_value=1000),
    )
    def translate_valid(self, legacy_id: int) -> None:
        body: Mapping[str, object] = {"legacy_id": legacy_id}
        out = self.acl.to_local(body)
        assert isinstance(out, Mapping)
        assert out["id"] == legacy_id

    @rule()
    def translate_invalid(self) -> None:
        try:
            self.acl.to_local({"not_legacy_id": 1})
            raise AssertionError("invalid payload unexpectedly accepted")
        except ForeignPayloadRejectedError:
            return

    @rule(tag=st.text(alphabet="0123456789.", min_size=1, max_size=5))
    def register_new_version(self, tag: str) -> None:
        v = _mk_version(tag)
        self.acl.register_version(
            v, inbound=_inbound_ok, outbound=_outbound_ok, guard=_guard_ok,
        )
        self.registered_tags.add(tag)

    @rule()
    def drift_unknown_version(self) -> None:
        ghost = ForeignPayload(_mk_version("ghost"), {"legacy_id": 1})
        if "ghost" in self.registered_tags:
            # Already registered — skip to keep the rule precondition simple.
            return
        try:
            self.acl.to_local(ghost)
            raise AssertionError("unknown version unexpectedly accepted")
        except SchemaDriftError:
            return

    @invariant()
    def no_foreign_leak(self) -> None:
        if not hasattr(self, "acl"):
            return
        # The ACL's registered inbound never returns a ForeignPayload.
        try:
            out = self.acl.to_local({"legacy_id": 0})
        except (ForeignPayloadRejectedError, ForeignTypeLeakError):
            return
        assert not isinstance(out, ForeignPayload)

    @invariant()
    def default_version_remains(self) -> None:
        if not hasattr(self, "acl"):
            return
        assert self.acl.default_version == self.default


TestAntiCorruptionLayerMachine = AntiCorruptionLayerMachine.TestCase
