"""Hypothesis state-machine tests for PromptTemplate registry.

Explores the reachable states of `PromptRegistry`:
- register a fresh (name, version) → succeeds, resolvable
- register conflicting (name, version) → raises, registry unchanged
- register identical (name, version, fingerprint) → idempotent no-op
"""

from __future__ import annotations

from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule
from hypothesis.strategies import integers, sampled_from, text

from PromptTemplate import (
    FrozenPromptTemplate,
    PromptRegistry,
    PromptTemplateInvariantError,
)

_NAMES = ("alpha", "beta", "gamma")
_MODELS = ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5")


class RegistryModel(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.reg = PromptRegistry()
        self.shadow: dict[tuple[str, int], str] = {}

    @rule(
        name=sampled_from(_NAMES),
        version=integers(min_value=1, max_value=20),
        model=sampled_from(_MODELS),
        suffix=text(alphabet="abc ", min_size=0, max_size=6),
    )
    def try_register(self, name: str, version: int, model: str, suffix: str) -> None:
        tpl = FrozenPromptTemplate(
            name=name, version=version, target_model=model,
            text=f"hello{suffix} {{{{x}}}}", variables=("x",),
        )
        key = (name, version)
        if key in self.shadow:
            expected_fp = self.shadow[key]
            if expected_fp == tpl.fingerprint():
                # Idempotent — must succeed.
                self.reg.register(tpl)
            else:
                try:
                    self.reg.register(tpl)
                except PromptTemplateInvariantError:
                    pass
                else:
                    raise AssertionError(f"expected conflict for {key}")
        else:
            self.reg.register(tpl)
            self.shadow[key] = tpl.fingerprint()

    @rule(name=sampled_from(_NAMES), version=integers(min_value=1, max_value=20))
    @precondition(lambda self: True)
    def try_resolve(self, name: str, version: int) -> None:
        key = (name, version)
        if key in self.shadow:
            resolved = self.reg.resolve(name, version)
            assert resolved.fingerprint() == self.shadow[key]
        else:
            try:
                self.reg.resolve(name, version)
            except PromptTemplateInvariantError:
                pass
            else:
                raise AssertionError(f"unexpected resolve of unregistered {key}")

    @invariant()
    def registered_keys_match_shadow(self) -> None:
        for key, fp in self.shadow.items():
            resolved = self.reg.resolve(key[0], key[1])
            assert resolved.fingerprint() == fp


TestRegistry = RegistryModel.TestCase
TestRegistry.settings = settings(max_examples=50, deadline=None)
