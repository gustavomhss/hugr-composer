"""Chaos / fault-injection for ValueTransform.

Game-day scenarios: adversarial inputs, giant payloads, weird types, thread
contention on a shared transform. ValueTransform MUST remain correct under
each (purity + no-mutation + typed errors).
"""

from __future__ import annotations

import threading

import pytest

from ValueTransform import (
    ArgumentMetadata,
    CoercionError,
    Compose,
    ParseBool,
    ParseInt,
    Validation,
    ValueTransformError,
)

META = ArgumentMetadata(kind="param", metatype=int, data="id")


def test_chaos_huge_integer_string_does_not_crash() -> None:
    p = ParseInt()
    big = "9" * 4096
    # Pure Python `int` has arbitrary precision; ParseInt MUST not crash.
    out = p.transform(big, META)
    assert out == int(big)


def test_chaos_adversarial_strings_rejected_cleanly() -> None:
    p = ParseInt()
    for bad in ("", "   ", "0x10", "1e3", "NaN", "inf", "--1", "1.5"):
        with pytest.raises(CoercionError):
            p.transform(bad, META)


def test_chaos_unexpected_types_raise_typed_error() -> None:
    p = ParseInt()
    for v in (object(), [1], {"a": 1}, (1, 2), b"42"):
        with pytest.raises(CoercionError):
            p.transform(v, META)


def test_chaos_concurrent_transforms_are_safe() -> None:
    p = ParseInt()
    errors: list[BaseException] = []
    results: list[int] = []
    lock = threading.Lock()

    def worker(n: int) -> None:
        try:
            for _ in range(500):
                out = p.transform(str(n), META)
                with lock:
                    results.append(out)
        except BaseException as exc:  # noqa: BLE001 — collect then assert below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == 8 * 500


def test_chaos_pipeline_failure_does_not_corrupt_state() -> None:
    positive = Validation(lambda x: isinstance(x, int) and x > 0, message="positive")
    pipeline = Compose([ParseInt(), positive])
    # Alternate failing and succeeding calls; each call MUST be independent.
    for i in range(50):
        if i % 2 == 0:
            assert pipeline.transform(str(i + 1), META) == i + 1
        else:
            with pytest.raises(ValueTransformError):
                pipeline.transform(str(-(i + 1)), META)


def test_chaos_bool_coercion_refuses_truthy_numbers() -> None:
    p = ParseBool()
    meta = ArgumentMetadata(kind="query", metatype=bool, data="f")
    # Silent truthiness (2 → True) is FORBIDDEN — must raise.
    for v in (2, -1, 3, 99):
        with pytest.raises(CoercionError):
            p.transform(v, meta)


def test_chaos_deeply_nested_compose_has_bounded_depth() -> None:
    # Build a Compose with 200 no-op validations; must still be correct.
    noops = [Validation(lambda x: True, message="noop") for _ in range(200)]
    deep = Compose([ParseInt()] + noops)
    assert deep.transform("7", META) == 7


def test_chaos_parse_int_rejects_bool_input() -> None:
    # bool is an int subclass; silent True→1 coercion would leak type info.
    p = ParseInt()
    with pytest.raises(CoercionError):
        p.transform(True, META)
    with pytest.raises(CoercionError):
        p.transform(False, META)
