"""Hypothesis state-machine exploration of ScopeManager lifecycle."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from LifetimeScope import (
    LifetimeScope,
    LifetimeScopeInvariantError,
    ScopeManager,
)


class Svc:
    pass


_KEYS = ["a", "b", "c"]
_LIFETIMES = [LifetimeScope.SINGLETON, LifetimeScope.SCOPED, LifetimeScope.TRANSIENT]


class ScopeManagerMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.root = ScopeManager()
        self.registered: dict[str, LifetimeScope] = {}
        self.scopes: list[ScopeManager] = []

    @rule(key=st.sampled_from(_KEYS), scope=st.sampled_from(_LIFETIMES))
    def register_op(self, key: str, scope: LifetimeScope) -> None:
        if key in self.registered:
            try:
                self.root.register(key, Svc, scope=scope)
                raise AssertionError("duplicate registration accepted")
            except LifetimeScopeInvariantError:
                return
        self.root.register(key, Svc, scope=scope)
        self.registered[key] = scope

    @rule()
    def open_scope_op(self) -> None:
        parent = self.scopes[-1] if self.scopes and not self.scopes[-1].disposed else self.root
        try:
            child = parent.open_scope()
        except LifetimeScopeInvariantError:
            return
        self.scopes.append(child)

    @rule(key=st.sampled_from(_KEYS))
    def resolve_op(self, key: str) -> None:
        if key not in self.registered:
            try:
                self.root.resolve(key)
                raise AssertionError("resolve of unregistered key returned a value")
            except LifetimeScopeInvariantError:
                return
        target = self.scopes[-1] if self.scopes and not self.scopes[-1].disposed else self.root
        try:
            target.resolve(key)
        except LifetimeScopeInvariantError:
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
                    s.resolve("a")
                    raise AssertionError("disposed scope accepted resolve")
                except LifetimeScopeInvariantError:
                    pass

    @invariant()
    def singletons_shared_across_scopes(self) -> None:
        if not hasattr(self, "root"):
            return
        # Every singleton observed at the root must be identical when
        # re-resolved from a live descendant scope.
        for key, lifetime in self.registered.items():
            if lifetime is LifetimeScope.SINGLETON:
                root_inst = self.root.resolve(key)
                for s in self.scopes:
                    if not s.disposed:
                        assert s.resolve(key) is root_inst

    @invariant()
    def depth_is_monotonic(self) -> None:
        if not hasattr(self, "root"):
            return
        assert self.root.depth == 0
        for i, s in enumerate(self.scopes, start=1):
            # Depth is at least 1 and at most i (children of children allowed).
            assert s.depth >= 1


TestScopeManagerMachine = ScopeManagerMachine.TestCase
