"""Unit tests for Specification — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest

from Specification import (
    BaseSpecification,
    PredicateSpecification,
    SpecificationInvariantError,
    TranslatorRegistry,
    in_memory_filter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _positive() -> PredicateSpecification[int]:
    return PredicateSpecification[int]("positive", lambda x: x > 0)


def _even() -> PredicateSpecification[int]:
    return PredicateSpecification[int]("even", lambda x: x % 2 == 0)


def _big() -> PredicateSpecification[int]:
    return PredicateSpecification[int]("big", lambda x: x >= 100)


# ---------------------------------------------------------------------------
# SPEC_INV_01 — is_satisfied_by is pure (no mutation, no I/O, no time dependence)
# ---------------------------------------------------------------------------
def test_inv_pure_predicate_confirms() -> None:
    spec = PredicateSpecification[list[int]](
        "nonempty", lambda xs: len(xs) > 0,
    )
    candidate = [1, 2, 3]
    original = list(candidate)
    assert spec.is_satisfied_by(candidate) is True
    # Candidate MUST NOT be mutated.
    assert candidate == original


def test_inv_pure_predicate_prevents() -> None:
    # A predicate-backed leaf requires a valid identifier name so translation
    # dispatch stays deterministic (SPEC-INV-03 — but enforced here too to
    # prevent unnamed / impure leaves slipping through).
    with pytest.raises(SpecificationInvariantError):
        PredicateSpecification[int]("", lambda x: x > 0)
    with pytest.raises(SpecificationInvariantError):
        PredicateSpecification[int]("not a python identifier!", lambda x: x > 0)


def test_inv_pure_predicate_under_failure() -> None:
    # Repeated evaluations MUST return identical results regardless of when
    # (no hidden time dependence). SPEC-INV-01 demands idempotent evaluation.
    spec = _positive()
    results = [spec.is_satisfied_by(5) for _ in range(1000)]
    assert all(r is True for r in results)
    results2 = [spec.is_satisfied_by(-5) for _ in range(1000)]
    assert all(r is False for r in results2)


# ---------------------------------------------------------------------------
# SPEC_INV_02 — boolean algebra laws
# ---------------------------------------------------------------------------
def test_inv_boolean_algebra_confirms() -> None:
    p, e = _positive(), _even()
    # De Morgan: NOT(p AND e) <=> (NOT p) OR (NOT e)
    lhs = p.and_(e).not_()
    rhs = p.not_().or_(e.not_())
    for x in (-3, -2, -1, 0, 1, 2, 3, 4):
        assert lhs.is_satisfied_by(x) == rhs.is_satisfied_by(x)

    # Double negation: NOT NOT p <=> p (and_.not_ returns the inner ref)
    assert p.not_().not_() is p

    # Commutativity: p AND e <=> e AND p, p OR e <=> e OR p
    for x in range(-5, 10):
        assert p.and_(e).is_satisfied_by(x) == e.and_(p).is_satisfied_by(x)
        assert p.or_(e).is_satisfied_by(x) == e.or_(p).is_satisfied_by(x)


def test_inv_boolean_algebra_prevents() -> None:
    p = _positive()
    # Non-Specification operands MUST be rejected (SPEC-INV-02 preserves the
    # closed algebra).
    with pytest.raises(SpecificationInvariantError):
        p.and_("not a spec")  # type: ignore[arg-type]  — SPEC-INV-02: operand type check
    with pytest.raises(SpecificationInvariantError):
        p.or_(42)  # type: ignore[arg-type]  — SPEC-INV-02: operand type check


def test_inv_boolean_algebra_under_failure() -> None:
    # Associativity: (p AND e) AND b <=> p AND (e AND b) across many inputs.
    p, e, b = _positive(), _even(), _big()
    left = p.and_(e).and_(b)
    right = p.and_(e.and_(b))
    for x in (-100, -1, 0, 1, 2, 50, 99, 100, 101, 102):
        assert left.is_satisfied_by(x) == right.is_satisfied_by(x)


# ---------------------------------------------------------------------------
# SPEC_INV_03 — persistence isolation via translator registry
# ---------------------------------------------------------------------------
def test_inv_translator_isolation_confirms() -> None:
    reg = TranslatorRegistry()
    reg.register("sql", "positive", lambda s: "x > 0")
    reg.register("sql", "even", lambda s: "x % 2 = 0")
    spec = _positive().and_(_even())
    out = reg.translate("sql", spec)
    assert out == {"op": "AND", "left": "x > 0", "right": "x % 2 = 0"}


def test_inv_translator_isolation_prevents() -> None:
    reg = TranslatorRegistry()
    # Invalid backend / leaf names MUST be rejected so the registry cannot be
    # corrupted by ad-hoc callers (SPEC-INV-03).
    with pytest.raises(SpecificationInvariantError):
        reg.register("", "x", lambda s: None)
    with pytest.raises(SpecificationInvariantError):
        reg.register("sql", "", lambda s: None)
    # Missing translator MUST fail loudly — no silent persistence coupling.
    with pytest.raises(SpecificationInvariantError):
        reg.translate("sql", _positive())


def test_inv_translator_isolation_under_failure() -> None:
    # Concurrent registrations MUST preserve the registry's consistency
    # (SPEC-INV-03 — shared state, no torn writes).
    reg = TranslatorRegistry()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            reg.register("sql", f"leaf_{i}", lambda s, i=i: f"col = {i}")
        except BaseException as exc:  # pragma: no cover — defensive
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # All 50 leaves registered.
    for i in range(50):
        spec = PredicateSpecification[int](f"leaf_{i}", lambda x: True)
        assert reg.translate("sql", spec) == f"col = {i}"


# ---------------------------------------------------------------------------
# SPEC_INV_04 — in-memory filter vs translated query parity
# ---------------------------------------------------------------------------
def _fake_query_evaluator(query: object, candidates: list[int]) -> list[int]:
    """Evaluate a translated query tree against in-memory candidates.

    The fake backend MUST yield results logically equivalent to
    ``in_memory_filter`` (SPEC-INV-04).
    """
    def matches(q: object, x: int) -> bool:
        if isinstance(q, dict):
            op = q["op"]
            if op == "AND":
                return matches(q["left"], x) and matches(q["right"], x)
            if op == "OR":
                return matches(q["left"], x) or matches(q["right"], x)
            if op == "NOT":
                return not matches(q["inner"], x)
        # Leaf evaluator: the translator returned a callable fn(candidate)->bool.
        return bool(q(x))  # type: ignore[operator]  — SPEC-INV-04: leaf is a predicate callable

    return [c for c in candidates if matches(query, c)]


def test_inv_filter_query_parity_confirms() -> None:
    reg = TranslatorRegistry()
    reg.register("fake", "positive", lambda s: lambda x: x > 0)
    reg.register("fake", "even", lambda s: lambda x: x % 2 == 0)
    spec = _positive().and_(_even())
    candidates = list(range(-5, 10))
    mem = in_memory_filter(spec, candidates)
    translated = reg.translate("fake", spec)
    fake = _fake_query_evaluator(translated, candidates)
    assert mem == fake


def test_inv_filter_query_parity_prevents() -> None:
    # A translator that intentionally diverges from the predicate semantics
    # MUST be detected as a parity violation — this is the anti-scenario
    # that SPEC-INV-04 protects against.
    reg = TranslatorRegistry()
    reg.register("bad", "positive", lambda s: lambda x: x < 0)  # wrong!
    spec = _positive()
    candidates = [-3, -1, 0, 1, 3]
    mem = in_memory_filter(spec, candidates)
    translated = reg.translate("bad", spec)
    fake = _fake_query_evaluator(translated, candidates)
    assert mem != fake  # parity violated — the test proves detection works


def test_inv_filter_query_parity_under_failure() -> None:
    # Parity MUST hold across deep compositions (NOT/AND/OR nested).
    reg = TranslatorRegistry()
    reg.register("fake", "positive", lambda s: lambda x: x > 0)
    reg.register("fake", "even", lambda s: lambda x: x % 2 == 0)
    reg.register("fake", "big", lambda s: lambda x: x >= 100)
    spec = _positive().and_(_even().or_(_big().not_()))
    candidates = list(range(-50, 150))
    mem = in_memory_filter(spec, candidates)
    translated = reg.translate("fake", spec)
    fake = _fake_query_evaluator(translated, candidates)
    assert mem == fake


# ---------------------------------------------------------------------------
# SPEC_INV_05 — sealed operator override protection
# ---------------------------------------------------------------------------
def test_inv_sealed_operators_confirms() -> None:
    # A subclass that only overrides is_satisfied_by is accepted.
    class MySpec(BaseSpecification[int]):
        def is_satisfied_by(self, candidate: int) -> bool:
            return candidate > 42

    s = MySpec()
    assert s.is_satisfied_by(50) is True
    assert s.is_satisfied_by(10) is False


def test_inv_sealed_operators_prevents() -> None:
    # Overriding `and_` / `or_` / `not_` MUST raise at class-creation time.
    with pytest.raises(SpecificationInvariantError):

        class BadAnd(BaseSpecification[int]):
            def and_(
                self, other: BaseSpecification[int],
            ) -> BaseSpecification[int]:
                return self  # SPEC-INV-05: forbidden override

    with pytest.raises(SpecificationInvariantError):

        class BadOr(BaseSpecification[int]):
            def or_(self, other: BaseSpecification[int]) -> BaseSpecification[int]:
                return self  # SPEC-INV-05: forbidden override

    with pytest.raises(SpecificationInvariantError):

        class BadNot(BaseSpecification[int]):
            def not_(self) -> BaseSpecification[int]:
                return self  # SPEC-INV-05: forbidden override


def test_inv_sealed_operators_under_failure() -> None:
    # Under repeated subclass-creation attempts, the seal NEVER leaks; the
    # class body raises every time.
    failures = 0
    for _ in range(20):
        try:

            class Bad(BaseSpecification[int]):
                def and_(
                    self, other: BaseSpecification[int],
                ) -> BaseSpecification[int]:
                    return self

        except SpecificationInvariantError:
            failures += 1
    assert failures == 20
