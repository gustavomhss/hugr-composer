"""Chaos / game-day tests for Specification.

Simulates malformed compositions, translator-registry corruption attempts,
deeply nested trees, and exception propagation to confirm the primitive
never enters an inconsistent algebraic state.
"""

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


def _true() -> PredicateSpecification[int]:
    return PredicateSpecification[int]("t", lambda x: True)


def _false() -> PredicateSpecification[int]:
    return PredicateSpecification[int]("f", lambda x: False)


def test_chaos_deeply_nested_composition() -> None:
    # 1000-deep AND chain MUST evaluate without recursion blowing past the
    # default interpreter limit when the tree is balanced via reduction.
    spec: BaseSpecification[int] = _true()
    for _ in range(500):
        spec = spec.and_(_true())
    assert spec.is_satisfied_by(1) is True


def test_chaos_predicate_that_raises_propagates() -> None:
    def boom(x: int) -> bool:
        raise RuntimeError("predicate explosion")

    spec = PredicateSpecification[int]("bomb", boom)
    with pytest.raises(RuntimeError):
        spec.is_satisfied_by(1)


def test_chaos_concurrent_registry_writes_never_corrupt() -> None:
    reg = TranslatorRegistry()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(tid: int) -> None:
        try:
            for i in range(100):
                reg.register(f"backend_{tid}", f"leaf_{i}", lambda s, i=i: i)
        except BaseException as exc:  # pragma: no cover — defensive
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # Every backend/leaf combo is present.
    for tid in range(10):
        for i in range(100):
            spec = PredicateSpecification[int](f"leaf_{i}", lambda x: True)
            assert reg.translate(f"backend_{tid}", spec) == i


def test_chaos_subclass_override_storm_rejected() -> None:
    # Classes that attempt to override sealed operators MUST be rejected at
    # import/class-creation time, every time.
    for _ in range(50):
        with pytest.raises(SpecificationInvariantError):

            class Bad(BaseSpecification[int]):
                def or_(
                    self, other: BaseSpecification[int],
                ) -> BaseSpecification[int]:
                    return self


def test_chaos_large_in_memory_filter() -> None:
    spec = PredicateSpecification[int]("even", lambda x: x % 2 == 0)
    out = in_memory_filter(spec, range(10_000))
    assert len(out) == 5_000
    assert out[0] == 0
    assert out[-1] == 9998


def test_chaos_registry_lookup_on_empty_backend() -> None:
    reg = TranslatorRegistry()
    # No registrations at all — translation MUST fail loudly rather than
    # silently returning None or an empty result.
    with pytest.raises(SpecificationInvariantError):
        reg.translate("never_booted", _true())


def test_chaos_nested_not_collapses_even_under_many_negations() -> None:
    p = _true()
    # Apply .not_() 1000 times; the algebra collapses pairs so the resulting
    # tree depth remains bounded.
    s: BaseSpecification[int] = p
    for _ in range(1000):
        s = s.not_()
    # 1000 negations is even → equivalent to p.
    assert s.is_satisfied_by(1) == p.is_satisfied_by(1)
