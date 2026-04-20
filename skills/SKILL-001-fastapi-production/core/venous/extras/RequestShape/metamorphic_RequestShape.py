"""Metamorphic + differential tests for RequestShape.

Algebraic laws:
- to_headers ∘ from_headers == identity (on the declared fields)
- from_headers ∘ to_headers == identity (on the declared fields)
- with_incremented_attempt composes (n lifts = attempt + n)
- shape_hash is deterministic and depends only on (method, route, header_keys, size_class, priority)
"""

from __future__ import annotations

from RequestShape import (
    ImmutableRequestShape,
    size_class,
)


def test_metamorphic_roundtrip_is_identity_on_declared_fields() -> None:
    shape = ImmutableRequestShape(
        request_id="req-mm-1",
        priority="sheddable_plus",
        deadline_ns=42_000_000,
        idempotency_key="k",
        attempt=7,
        origin="svc-A",
    )
    parsed = ImmutableRequestShape.from_headers(shape.to_headers())
    # Every declared field round-trips losslessly.
    assert parsed.request_id == shape.request_id
    assert parsed.priority == shape.priority
    assert parsed.deadline_ns == shape.deadline_ns
    assert parsed.idempotency_key == shape.idempotency_key
    assert parsed.attempt == shape.attempt
    assert parsed.origin == shape.origin


def test_metamorphic_double_roundtrip_is_idempotent() -> None:
    shape = ImmutableRequestShape(request_id="req-mm-2", priority="critical")
    once = ImmutableRequestShape.from_headers(shape.to_headers())
    twice = ImmutableRequestShape.from_headers(once.to_headers())
    assert once.to_headers() == twice.to_headers()


def test_metamorphic_attempt_composition_is_additive() -> None:
    shape = ImmutableRequestShape(request_id="req-mm-3", attempt=0)
    for _ in range(50):
        shape = shape.with_incremented_attempt()
    assert shape.attempt == 50


def test_metamorphic_shape_hash_deterministic() -> None:
    s = ImmutableRequestShape(request_id="req-mm-4", priority="normal")
    kwargs = {
        "method": "GET",
        "route_pattern": "/v1/items/{id}",
        "header_keys": ("accept", "user-agent"),
        "body_bytes": 0,
    }
    a = s.shape_hash(**kwargs)
    b = s.shape_hash(**kwargs)
    assert a == b


def test_metamorphic_shape_hash_insensitive_to_header_order() -> None:
    s = ImmutableRequestShape(request_id="req-mm-5", priority="normal")
    a = s.shape_hash(
        method="POST", route_pattern="/x", body_bytes=100,
        header_keys=("a", "b", "c"),
    )
    b = s.shape_hash(
        method="POST", route_pattern="/x", body_bytes=100,
        header_keys=("c", "b", "a"),
    )
    assert a == b


def test_metamorphic_shape_hash_sensitive_to_priority_change() -> None:
    low = ImmutableRequestShape(request_id="req-mm-6", priority="sheddable")
    high = ImmutableRequestShape(request_id="req-mm-7", priority="critical")
    common = {
        "method": "POST",
        "route_pattern": "/v1/charge",
        "header_keys": ("content-type",),
        "body_bytes": 200,
    }
    assert low.shape_hash(**common) != high.shape_hash(**common)


def test_metamorphic_size_class_monotone() -> None:
    # Larger byte counts never bucket into a SMALLER label.
    order = ("xs", "s", "m", "l", "xl", "xxl", "xxxl", "huge")
    last_idx = 0
    for n in (0, 127, 128, 1023, 1024, 8191, 8192, 65535, 65536, 524287, 524288,
              4194303, 4194304, 10_000_000):
        idx = order.index(size_class(n))
        assert idx >= last_idx
        last_idx = idx


def test_differential_same_route_different_body_size_changes_hash() -> None:
    s = ImmutableRequestShape(request_id="req-mm-8", priority="normal")
    small = s.shape_hash(
        method="POST", route_pattern="/x", body_bytes=10,
        header_keys=("content-type",),
    )
    large = s.shape_hash(
        method="POST", route_pattern="/x", body_bytes=5_000_000,
        header_keys=("content-type",),
    )
    assert small != large
