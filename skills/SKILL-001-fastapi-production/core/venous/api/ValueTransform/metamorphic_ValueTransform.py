"""Metamorphic + differential tests for ValueTransform.

Algebraic properties:
- Identity under Compose([t]) == t.transform
- Associativity: Compose([a,b,c]) == Compose([a, Compose([b,c])]) (when Compose nests)
- Determinism / referential transparency: repeated calls yield equal results
- Non-mutation: output != id(input) for mutable inputs
- Differential: ParseInt accepts str(n) iff int(str(n)) succeeds in pure Python
"""

from __future__ import annotations

import random

import pytest

from ValueTransform import (
    ArgumentMetadata,
    Compose,
    ParseBool,
    ParseInt,
    Validation,
    ValueTransformError,
)

META = ArgumentMetadata(kind="param", metatype=int, data="n")


def test_metamorphic_identity_singleton_compose() -> None:
    p = ParseInt()
    c = Compose([p])
    for i in (-3, 0, 1, 1_000_000):
        assert c.transform(str(i), META) == p.transform(str(i), META)


def test_metamorphic_associativity_of_nested_compose() -> None:
    a = ParseInt()
    b = Validation(lambda x: isinstance(x, int), message="int")
    c = Validation(lambda x: isinstance(x, int) and x >= 0, message=">=0")
    flat = Compose([a, b, c])
    nested = Compose([a, Compose([b, c])])
    for i in (0, 1, 42, 9999):
        assert flat.transform(str(i), META) == nested.transform(str(i), META)


def test_metamorphic_determinism_over_random_inputs() -> None:
    rng = random.Random(0xC0FFEE)
    p = ParseInt()
    samples = [rng.randint(-10_000, 10_000) for _ in range(200)]
    first = [p.transform(str(n), META) for n in samples]
    second = [p.transform(str(n), META) for n in samples]
    assert first == second


def test_metamorphic_non_mutation_identity() -> None:
    original = [1, 2, 3]
    v = Validation(lambda x: True, message="noop")
    out = v.transform(original, ArgumentMetadata(kind="body", metatype=None, data="b"))
    assert out == original
    assert out is not original


def test_differential_parseint_matches_python_int() -> None:
    p = ParseInt()
    cases = ["0", "-1", "1", "123456", " 42 ", "-7"]
    for c in cases:
        assert p.transform(c, META) == int(c.strip(), 10)


def test_differential_parsebool_is_closed_set() -> None:
    p = ParseBool()
    meta = ArgumentMetadata(kind="query", metatype=bool, data="f")
    truthy = ("1", "true", "TRUE", "yes", "on")
    falsy = ("0", "false", "NO", "off")
    for t in truthy:
        assert p.transform(t, meta) is True
    for f in falsy:
        assert p.transform(f, meta) is False
    for bad in ("maybe", "truthy", "2"):
        with pytest.raises(ValueTransformError):
            p.transform(bad, meta)


def test_metamorphic_compose_order_is_not_commutative() -> None:
    # Building blocks that demonstrate order-dependence without exception paths:
    add_one = Validation(lambda x: True, message="pass")  # pure pass-through
    ensure_int = Validation(lambda x: isinstance(x, int), message="int")
    # Compose([ParseInt, ensure_int]) succeeds; Compose([ensure_int, ParseInt]) fails
    # on the same input — demonstrates order matters.
    ok = Compose([ParseInt(), ensure_int, add_one])
    bad = Compose([ensure_int, ParseInt(), add_one])
    assert ok.transform("5", META) == 5
    with pytest.raises(ValueTransformError):
        bad.transform("5", META)
