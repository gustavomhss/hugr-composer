"""Hypothesis state-machine exploration of DiContainer lifecycle."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from DiContainer import DiContainerInvariantError, InMemoryDiContainer


class IFace:
    pass


class Impl(IFace):
    pass


class DiContainerMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.root = InMemoryDiContainer()
        self.registered: set[tuple[type, str | None]] = set()
        self.scopes: list[InMemoryDiContainer] = []

    @rule(name=st.sampled_from([None, "a", "b", "c"]), scope=st.sampled_from(["singleton", "scoped", "transient"]))
    def register_op(self, name: str | None, scope: str) -> None:
        key = (IFace, name)
        if key in self.registered:
            try:
                self.root.register(IFace, Impl, scope=scope, name=name)
                raise AssertionError("duplicate registration accepted")
            except DiContainerInvariantError:
                return
        self.root.register(IFace, Impl, scope=scope, name=name)
        self.registered.add(key)

    @rule()
    def create_scope_op(self) -> None:
        scope = self.root.create_scope()
        self.scopes.append(scope)

    @rule(name=st.sampled_from([None, "a", "b", "c"]))
    def resolve_op(self, name: str | None) -> None:
        key = (IFace, name)
        if key not in self.registered:
            try:
                self.root.resolve(IFace, name=name)
                raise AssertionError("resolve of unregistered iface returned a value")
            except DiContainerInvariantError:
                return
        # Try from most recent scope if available, else root.
        target = self.scopes[-1] if self.scopes and not self.scopes[-1].disposed else self.root
        try:
            target.resolve(IFace, name=name)
        except DiContainerInvariantError:
            # Scoped-from-root is legitimately rejected.
            pass

    @rule()
    def dispose_scope_op(self) -> None:
        if not self.scopes:
            return
        scope = self.scopes.pop()
        scope.dispose()

    @invariant()
    def disposed_scopes_reject_resolves(self) -> None:
        if not hasattr(self, "root"):
            return
        for s in self.scopes:
            if s.disposed:
                try:
                    s.resolve(IFace)
                    raise AssertionError("disposed scope accepted resolve")
                except DiContainerInvariantError:
                    pass


TestDiContainerMachine = DiContainerMachine.TestCase
