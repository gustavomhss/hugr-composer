"""Hypothesis state-machine exploration of Specification composition and registry."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from Specification import (
    BaseSpecification,
    PredicateSpecification,
    SpecificationInvariantError,
    TranslatorRegistry,
    in_memory_filter,
)


_LEAF_PREDICATES: dict[str, object] = {
    "pos": lambda x: x > 0,
    "neg": lambda x: x < 0,
    "zero": lambda x: x == 0,
    "even": lambda x: x % 2 == 0,
    "big": lambda x: abs(x) >= 50,
}


class SpecificationMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.specs: list[BaseSpecification[int]] = [
            PredicateSpecification[int](name, fn)  # type: ignore[arg-type]  — SPEC leaf builder
            for name, fn in _LEAF_PREDICATES.items()
        ]
        self.registry = TranslatorRegistry()
        for name in _LEAF_PREDICATES:
            # Register a fake backend that mirrors the leaf predicate so
            # SPEC-INV-04 parity can be asserted under any composition.
            self.registry.register(
                "fake", name,
                lambda s, n=name: lambda x, n=n: bool(_LEAF_PREDICATES[n](x)),  # type: ignore[operator]  — SPEC-INV-04 parity leaf
            )

    @rule(a=st.integers(min_value=0, max_value=4), b=st.integers(min_value=0, max_value=4))
    def compose_and(self, a: int, b: int) -> None:
        if not self.specs:
            return
        a = a % len(self.specs)
        b = b % len(self.specs)
        self.specs.append(self.specs[a].and_(self.specs[b]))

    @rule(a=st.integers(min_value=0, max_value=4), b=st.integers(min_value=0, max_value=4))
    def compose_or(self, a: int, b: int) -> None:
        if not self.specs:
            return
        a = a % len(self.specs)
        b = b % len(self.specs)
        self.specs.append(self.specs[a].or_(self.specs[b]))

    @rule(idx=st.integers(min_value=0, max_value=4))
    def compose_not(self, idx: int) -> None:
        if not self.specs:
            return
        idx = idx % len(self.specs)
        self.specs.append(self.specs[idx].not_())

    @invariant()
    def double_negation_semantics(self) -> None:
        # SPEC-INV-02: NOT NOT p is SEMANTICALLY equal to p over the domain.
        domain = list(range(-5, 6))
        for s in self.specs[:20]:
            dn = s.not_().not_()
            for x in domain:
                assert dn.is_satisfied_by(x) == s.is_satisfied_by(x)

    @invariant()
    def parity_holds(self) -> None:
        # SPEC-INV-04: in-memory filter == translator-driven evaluator over a
        # modest domain for every tracked specification.
        if not hasattr(self, "registry"):
            return
        if len(self.specs) > 30:
            return  # avoid exponential blow-up

        def evaluate(query: object, x: int) -> bool:
            if isinstance(query, dict):
                op = query["op"]
                if op == "AND":
                    return evaluate(query["left"], x) and evaluate(query["right"], x)
                if op == "OR":
                    return evaluate(query["left"], x) or evaluate(query["right"], x)
                if op == "NOT":
                    return not evaluate(query["inner"], x)
            return bool(query(x))  # type: ignore[operator]  — SPEC-INV-04 leaf is a callable

        domain = list(range(-10, 11))
        for s in self.specs:
            try:
                translated = self.registry.translate("fake", s)
            except SpecificationInvariantError:
                continue
            mem = in_memory_filter(s, domain)
            fake = [x for x in domain if evaluate(translated, x)]
            assert mem == fake


TestSpecificationMachine = SpecificationMachine.TestCase
