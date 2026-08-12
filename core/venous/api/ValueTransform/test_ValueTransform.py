"""Unit tests for ValueTransform — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

from uuid import UUID

import pytest
from ValueTransform import (
    ArgumentMetadata,
    CoercionError,
    Compose,
    MetatypeMismatchError,
    ParseBool,
    ParseInt,
    ParseUUID,
    Validation,
    ValidationError,
    ValueTransformError,
)

META_INT = ArgumentMetadata(kind="param", metatype=int, data="id")
META_BOOL = ArgumentMetadata(kind="query", metatype=bool, data="active")
META_BODY = ArgumentMetadata(kind="body", metatype=None, data="payload")


# ---------------------------------------------------------------------------
# VTRANSFORM_INV_01 — typed errors, never None on bad input
# ---------------------------------------------------------------------------
def test_inv_typed_error_confirms() -> None:
    p = ParseInt()
    with pytest.raises(CoercionError) as excinfo:
        p.transform("not-a-number", META_INT)
    err = excinfo.value
    assert isinstance(err, ValueTransformError)
    assert err.field == "id"
    assert err.received == "not-a-number"
    assert err.expected == "int"


def test_inv_typed_error_prevents() -> None:
    # Contract: transforms NEVER return None to signal invalid — they raise.
    # Exhaustively check the reference set: bad input produces a raise, not None.
    bad_cases: list[tuple[object, ArgumentMetadata, object]] = [
        (ParseInt(), META_INT, "xyz"),
        (ParseBool(), META_BOOL, "maybe"),
        (ParseUUID(), ArgumentMetadata(kind="param", metatype=UUID, data="id"), "garbage"),
    ]
    for t, meta, v in bad_cases:
        with pytest.raises(ValueTransformError):
            t.transform(v, meta)  # type: ignore[attr-defined]


def test_inv_typed_error_under_failure() -> None:
    # Even under chained Validation, the raised error is still a typed subclass.
    pipeline = Compose([ParseInt(), Validation(lambda x: isinstance(x, int) and x > 0, message="must be positive")])
    with pytest.raises(ValidationError):
        pipeline.transform("-7", META_INT)


# ---------------------------------------------------------------------------
# VTRANSFORM_INV_02 — purity (deterministic, no side effects)
# ---------------------------------------------------------------------------
def test_inv_purity_confirms() -> None:
    p = ParseInt()
    # Same inputs → identical outputs across 100 calls.
    outs = {p.transform("42", META_INT) for _ in range(100)}
    assert outs == {42}


def test_inv_purity_prevents() -> None:
    # A transform MUST NOT read or mutate module-level state to decide its output.
    p = ParseBool()
    a = p.transform("true", META_BOOL)
    b = p.transform("true", META_BOOL)
    assert a == b is True
    # Swapping the order of two independent calls MUST NOT change outputs.
    x = p.transform("false", META_BOOL)
    y = p.transform("true", META_BOOL)
    assert x is False and y is True


def test_inv_purity_under_failure() -> None:
    # After a failed call, a subsequent valid call MUST yield the same answer
    # it would have given before the failure (no latent state corruption).
    p = ParseInt()
    with pytest.raises(CoercionError):
        p.transform("boom", META_INT)
    assert p.transform("9", META_INT) == 9


# ---------------------------------------------------------------------------
# VTRANSFORM_INV_03 — metatype drives coercion target
# ---------------------------------------------------------------------------
def test_inv_metatype_drives_confirms() -> None:
    p = ParseInt()
    assert p.transform("7", ArgumentMetadata(kind="param", metatype=int, data="id")) == 7


def test_inv_metatype_drives_prevents() -> None:
    # Declaring a metatype that disagrees with the transform's output MUST raise,
    # NOT silently ignore.
    p = ParseInt()
    meta_wrong = ArgumentMetadata(kind="param", metatype=str, data="id")
    with pytest.raises(MetatypeMismatchError):
        p.transform("7", meta_wrong)


def test_inv_metatype_drives_under_failure() -> None:
    # metatype=None is "not declared" and MUST be allowed (no silent-ignore risk).
    p = ParseInt()
    meta_none = ArgumentMetadata(kind="param", metatype=None, data="id")
    assert p.transform("7", meta_none) == 7


# ---------------------------------------------------------------------------
# VTRANSFORM_INV_04 — compose is left-to-right, swapping is explicit
# ---------------------------------------------------------------------------
def test_inv_compose_order_confirms() -> None:
    positive = Validation(lambda x: isinstance(x, int) and x > 0, message="must be positive")
    pipeline = Compose([ParseInt(), positive])
    assert pipeline.transform("3", META_INT) == 3


def test_inv_compose_order_prevents() -> None:
    # Reversing order MUST produce a different outcome (here: a type error on
    # the predicate, because the raw str reaches Validation before ParseInt).
    positive = Validation(lambda x: isinstance(x, int) and x > 0, message="must be positive")
    wrong = Compose([positive, ParseInt()])
    with pytest.raises(ValidationError):
        wrong.transform("3", META_INT)  # predicate sees str, fails isinstance(int)


def test_inv_compose_order_under_failure() -> None:
    # Order is exposed through .transforms and MUST reflect declaration order,
    # so callers can audit. Swapping requires constructing a new Compose.
    a = ParseInt()
    b = Validation(lambda x: True, message="noop")
    p = Compose([a, b])
    assert p.transforms == (a, b)
    p2 = Compose([b, a])
    assert p2.transforms == (b, a)
    assert p.transforms != p2.transforms


# ---------------------------------------------------------------------------
# VTRANSFORM_INV_05 — no in-place mutation
# ---------------------------------------------------------------------------
def test_inv_no_mutation_confirms() -> None:
    original = [1, 2, 3]
    before = list(original)
    v = Validation(lambda x: isinstance(x, list) and len(x) == 3, message="len=3")
    out = v.transform(original, META_BODY)
    assert original == before  # caller's list untouched
    assert out == original
    assert out is not original  # fresh object


def test_inv_no_mutation_prevents() -> None:
    original = {"a": 1}
    before = dict(original)
    v = Validation(lambda x: isinstance(x, dict), message="dict")
    out = v.transform(original, META_BODY)
    assert isinstance(out, dict)
    # Confirm deep-copy semantics: mutating the returned object MUST NOT reach
    # the caller's original (i.e. the transform returned a fresh container).
    out["a"] = 99
    assert original == before


def test_inv_no_mutation_under_failure() -> None:
    # Even on validation failure, the input MUST be returned untouched.
    original = [1, 2, 3]
    before = list(original)
    v = Validation(lambda x: False, message="always fails")
    with pytest.raises(ValidationError):
        v.transform(original, META_BODY)
    assert original == before
