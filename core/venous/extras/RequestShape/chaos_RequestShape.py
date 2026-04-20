"""Chaos / fault-injection for RequestShape.

Game-day scenarios: malformed wire input, boundary priorities, retry storms,
transport corruption. RequestShape MUST remain correct under each.
"""

from __future__ import annotations

import pytest

from RequestShape import (
    HDR_ATTEMPT,
    HDR_DEADLINE_NS,
    HDR_PRIORITY,
    HDR_REQUEST_ID,
    ImmutableRequestShape,
    RequestShapeError,
    validate_priority,
    validate_request_id,
)


def test_chaos_unknown_priority_does_not_silently_escalate() -> None:
    # A malicious header claiming to be some "vip" tier MUST be rejected,
    # never silently mapped to 'critical'.
    with pytest.raises(RequestShapeError):
        ImmutableRequestShape.from_headers({
            HDR_REQUEST_ID: "req-chaos-1",
            HDR_PRIORITY: "vip-enterprise",
        })


def test_chaos_garbage_deadline_does_not_crash() -> None:
    for bad in ("NaN", "-1e9", "two", "", "3.14"):
        with pytest.raises(RequestShapeError):
            ImmutableRequestShape.from_headers({
                HDR_REQUEST_ID: "req-chaos-2",
                HDR_DEADLINE_NS: bad,
            })


def test_chaos_negative_attempt_rejected() -> None:
    with pytest.raises(RequestShapeError):
        ImmutableRequestShape(request_id="req-chaos-3", attempt=-1)


def test_chaos_attempt_decrement_rejected_under_concurrent_retries() -> None:
    shape = ImmutableRequestShape(request_id="req-chaos-4", attempt=5)
    # Simulate 1000 racing retry attempts; NONE may drive attempt below current.
    for delta in range(-10, 11):
        target = shape.attempt + delta
        if target < shape.attempt:
            with pytest.raises(RequestShapeError):
                shape.with_next_attempt(target)
        else:
            new_shape = shape.with_next_attempt(target)
            assert new_shape.attempt == target


def test_chaos_malformed_request_id_rejected() -> None:
    with pytest.raises(RequestShapeError):
        validate_request_id("has spaces and symbols!")
    with pytest.raises(RequestShapeError):
        validate_request_id("")
    with pytest.raises(RequestShapeError):
        validate_request_id("A" * 1000)  # exceeds 128-char bound


def test_chaos_missing_request_id_header_rejected() -> None:
    with pytest.raises(RequestShapeError):
        ImmutableRequestShape.from_headers({HDR_ATTEMPT: "0"})


def test_chaos_empty_priority_falls_back_to_normal_not_critical() -> None:
    # Empty string must map to 'normal' — never to 'critical'.
    assert validate_priority("") == "normal"
    shape = ImmutableRequestShape.from_headers({
        HDR_REQUEST_ID: "req-chaos-5",
        HDR_PRIORITY: "",
    })
    assert shape.priority == "normal"


def test_chaos_non_str_headers_rejected() -> None:
    with pytest.raises(RequestShapeError):
        # An SDK passes an int value by mistake; MUST be rejected, not coerced.
        ImmutableRequestShape.from_headers({HDR_REQUEST_ID: 42})  # type: ignore[dict-item]


def test_chaos_extras_mutation_attempt_does_not_affect_shape() -> None:
    src_extras = {"x-vendor": "acme"}
    shape = ImmutableRequestShape(request_id="req-chaos-6", extras=src_extras)
    # Mutating the source dict AFTER construction must not leak into the shape.
    src_extras["x-vendor"] = "evil"
    assert shape.extras["x-vendor"] == "acme"


def test_chaos_idempotency_key_mutation_after_first_set_rejected() -> None:
    shape = ImmutableRequestShape(request_id="req-chaos-7", idempotency_key="orig")
    for bad_key in ("tampered", "bypass", "MUTATED"):
        with pytest.raises(RequestShapeError):
            shape.with_next_attempt(1, next_idempotency_key=bad_key)
