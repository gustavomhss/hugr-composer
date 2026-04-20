"""Metamorphic + differential tests for Specification.

Algebraic properties proven here (SPEC-INV-02):
- Commutativity of AND and OR
- Associativity of AND and OR
- Idempotence: p AND p == p, p OR p == p
- Double negation: NOT NOT p == p (structural)
- De Morgan: NOT (p AND q) == (NOT p) OR (NOT q)
- De Morgan: NOT (p OR q) == (NOT p) AND (NOT q)
- Distributivity: p AND (q OR r) == (p AND q) OR (p AND r)
- Differential: in-memory filter vs translator-driven evaluator (SPEC-INV-04)
"""

from __future__ import annotations

from Specification import (
    BaseSpecification,
    PredicateSpecification,
    TranslatorRegistry,
    in_memory_filter,
)


def _p() -> PredicateSpecification[int]:
    return PredicateSpecification[int]("p_positive", lambda x: x > 0)


def _q() -> PredicateSpecification[int]:
    return PredicateSpecification[int]("q_even", lambda x: x % 2 == 0)


def _r() -> PredicateSpecification[int]:
    return PredicateSpecification[int]("r_small", lambda x: x < 10)


_DOMAIN = list(range(-20, 21))


def _eq(a: BaseSpecification[int], b: BaseSpecification[int]) -> bool:
    return all(a.is_satisfied_by(x) == b.is_satisfied_by(x) for x in _DOMAIN)


def test_metamorphic_commutativity() -> None:
    p, q = _p(), _q()
    assert _eq(p.and_(q), q.and_(p))
    assert _eq(p.or_(q), q.or_(p))


def test_metamorphic_associativity() -> None:
    p, q, r = _p(), _q(), _r()
    assert _eq(p.and_(q).and_(r), p.and_(q.and_(r)))
    assert _eq(p.or_(q).or_(r), p.or_(q.or_(r)))


def test_metamorphic_idempotence() -> None:
    p = _p()
    assert _eq(p.and_(p), p)
    assert _eq(p.or_(p), p)


def test_metamorphic_double_negation_structural() -> None:
    # NOT NOT p returns the same object reference — collapsing avoids
    # unbounded negation-wrapping.
    p = _p()
    assert p.not_().not_() is p


def test_metamorphic_de_morgan() -> None:
    p, q = _p(), _q()
    assert _eq(p.and_(q).not_(), p.not_().or_(q.not_()))
    assert _eq(p.or_(q).not_(), p.not_().and_(q.not_()))


def test_metamorphic_distributivity() -> None:
    p, q, r = _p(), _q(), _r()
    # p AND (q OR r) == (p AND q) OR (p AND r)
    assert _eq(p.and_(q.or_(r)), p.and_(q).or_(p.and_(r)))
    # p OR (q AND r) == (p OR q) AND (p OR r)
    assert _eq(p.or_(q.and_(r)), p.or_(q).and_(p.or_(r)))


def test_differential_in_memory_vs_translated_evaluator() -> None:
    reg = TranslatorRegistry()
    reg.register("fake", "p_positive", lambda s: lambda x: x > 0)
    reg.register("fake", "q_even", lambda s: lambda x: x % 2 == 0)
    reg.register("fake", "r_small", lambda s: lambda x: x < 10)

    def evaluate(query: object, x: int) -> bool:
        if isinstance(query, dict):
            op = query["op"]
            if op == "AND":
                return evaluate(query["left"], x) and evaluate(query["right"], x)
            if op == "OR":
                return evaluate(query["left"], x) or evaluate(query["right"], x)
            if op == "NOT":
                return not evaluate(query["inner"], x)
        return bool(query(x))  # type: ignore[operator]  — differential leaf callable

    p, q, r = _p(), _q(), _r()
    spec = p.and_(q).or_(r.not_())
    translated = reg.translate("fake", spec)
    mem = in_memory_filter(spec, _DOMAIN)
    tr = [x for x in _DOMAIN if evaluate(translated, x)]
    assert mem == tr
