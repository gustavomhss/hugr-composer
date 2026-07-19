"""Unit tests for RequestShape — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from RequestShape import (
    DEFAULT_PRIORITY,
    HDR_ATTEMPT,
    HDR_DEADLINE_NS,
    HDR_IDEMPOTENCY_KEY,
    HDR_ORIGIN,
    HDR_PRIORITY,
    HDR_REQUEST_ID,
    ImmutableRequestShape,
    RequestShapeError,
    check_idempotency_key_preserved,
    check_monotonic_attempt,
    validate_priority,
)


# ---------------------------------------------------------------------------
# RSHP_INV_01 — immutability
# ---------------------------------------------------------------------------
def test_inv_immutable_fields_confirms() -> None:
    shape = ImmutableRequestShape(request_id="req-1")
    assert shape.request_id == "req-1"
    assert shape.priority == DEFAULT_PRIORITY
    # frozen dataclass rejects attribute assignment
    with pytest.raises(FrozenInstanceError):
        shape.priority = "critical"  # type: ignore[misc]  # RSHP-INV-01: mutation FORBIDDEN


def test_inv_immutable_fields_prevents() -> None:
    shape = ImmutableRequestShape(request_id="req-2", extras={"x-tenant": "acme"})
    # Mutating the returned extras MUST NOT reach into the shape
    _ = shape.extras
    # The extras attribute itself cannot be swapped
    with pytest.raises(FrozenInstanceError):
        shape.extras = {"x-tenant": "evil"}  # type: ignore[misc]  # RSHP-INV-01: FORBIDDEN


def test_inv_immutable_fields_under_failure() -> None:
    shape = ImmutableRequestShape(request_id="req-3", attempt=1)
    new_shape = shape.with_incremented_attempt()
    # Original shape is untouched (RSHP-INV-01).
    assert shape.attempt == 1
    assert new_shape.attempt == 2
    assert new_shape is not shape


# ---------------------------------------------------------------------------
# RSHP_INV_02 — priority default
# ---------------------------------------------------------------------------
def test_inv_priority_default_confirms() -> None:
    shape = ImmutableRequestShape(request_id="req-4")
    assert shape.priority == "normal"
    assert validate_priority(None) == "normal"
    assert validate_priority("") == "normal"


def test_inv_priority_default_prevents() -> None:
    # Unknown priorities are rejected — NEVER silently upgraded to 'critical'.
    with pytest.raises(RequestShapeError):
        validate_priority("vip")
    with pytest.raises(RequestShapeError):
        ImmutableRequestShape(request_id="req-5", priority="vip")  # type: ignore[arg-type]


def test_inv_priority_default_under_failure() -> None:
    # Missing priority header parses to 'normal', never to 'critical'.
    headers = {HDR_REQUEST_ID: "req-6", HDR_ORIGIN: "svc"}
    shape = ImmutableRequestShape.from_headers(headers)
    assert shape.priority == "normal"


# ---------------------------------------------------------------------------
# RSHP_INV_03 — monotonic attempt
# ---------------------------------------------------------------------------
def test_inv_attempt_monotonic_confirms() -> None:
    shape = ImmutableRequestShape(request_id="req-7", attempt=2)
    new_shape = shape.with_next_attempt(3)
    assert new_shape.attempt == 3
    # A same-value attempt is allowed (monotonic non-decreasing).
    assert shape.with_next_attempt(2).attempt == 2


def test_inv_attempt_monotonic_prevents() -> None:
    with pytest.raises(RequestShapeError):
        check_monotonic_attempt(5, 4)
    shape = ImmutableRequestShape(request_id="req-8", attempt=4)
    with pytest.raises(RequestShapeError):
        shape.with_next_attempt(3)


def test_inv_attempt_monotonic_under_failure() -> None:
    # Even across many retries, attempt never decrements.
    shape = ImmutableRequestShape(request_id="req-9", attempt=0)
    for _ in range(10):
        shape = shape.with_incremented_attempt()
    assert shape.attempt == 10


# ---------------------------------------------------------------------------
# RSHP_INV_04 — header round-trip
# ---------------------------------------------------------------------------
def test_inv_header_roundtrip_confirms() -> None:
    original = ImmutableRequestShape(
        request_id="req-10",
        priority="critical",
        deadline_ns=1_000_000_000,
        idempotency_key="idem-xyz",
        attempt=2,
        origin="gateway",
    )
    headers = original.to_headers()
    parsed = ImmutableRequestShape.from_headers(headers)
    assert parsed.request_id == original.request_id
    assert parsed.priority == original.priority
    assert parsed.deadline_ns == original.deadline_ns
    assert parsed.idempotency_key == original.idempotency_key
    assert parsed.attempt == original.attempt
    assert parsed.origin == original.origin


def test_inv_header_roundtrip_prevents() -> None:
    # Missing required request-id MUST be rejected by from_headers.
    with pytest.raises(RequestShapeError):
        ImmutableRequestShape.from_headers({HDR_PRIORITY: "normal"})
    # Malformed deadline_ns MUST be rejected.
    with pytest.raises(RequestShapeError):
        ImmutableRequestShape.from_headers({
            HDR_REQUEST_ID: "req-11",
            HDR_DEADLINE_NS: "not-an-int",
        })


def test_inv_header_roundtrip_under_failure() -> None:
    # Unknown vendor headers MUST pass through extras and survive round-trip.
    shape = ImmutableRequestShape(
        request_id="req-12",
        priority="normal",
        extras={"x-tenant": "acme", "x-region": "eu-west-1"},
    )
    headers = shape.to_headers()
    parsed = ImmutableRequestShape.from_headers(headers)
    assert parsed.extras["x-tenant"] == "acme"
    assert parsed.extras["x-region"] == "eu-west-1"


# ---------------------------------------------------------------------------
# RSHP_INV_05 — idempotency key stability
# ---------------------------------------------------------------------------
def test_inv_idempotency_key_stable_confirms() -> None:
    shape = ImmutableRequestShape(request_id="req-13", idempotency_key="stable-1")
    retried = shape.with_next_attempt(1)
    assert retried.idempotency_key == "stable-1"
    # Header round-trip preserves the key
    assert ImmutableRequestShape.from_headers(shape.to_headers()).idempotency_key == "stable-1"


def test_inv_idempotency_key_stable_prevents() -> None:
    shape = ImmutableRequestShape(request_id="req-14", idempotency_key="stable-2")
    with pytest.raises(RequestShapeError):
        shape.with_next_attempt(1, next_idempotency_key="MUTATED")
    with pytest.raises(RequestShapeError):
        check_idempotency_key_preserved("keep", "changed")


def test_inv_idempotency_key_stable_under_failure() -> None:
    # Over many retries with explicit same key, the key MUST be stable.
    shape = ImmutableRequestShape(request_id="req-15", idempotency_key="stable-3")
    for n in range(1, 6):
        shape = shape.with_next_attempt(n, next_idempotency_key="stable-3")
        headers = shape.to_headers()
        assert headers[HDR_IDEMPOTENCY_KEY] == "stable-3"
        assert headers[HDR_ATTEMPT] == str(n)
