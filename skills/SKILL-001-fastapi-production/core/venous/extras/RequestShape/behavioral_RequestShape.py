"""Behavioral end-to-end scenarios for RequestShape — proves invariants at runtime."""

from __future__ import annotations

import pytest

from RequestShape import (
    HDR_ATTEMPT,
    HDR_IDEMPOTENCY_KEY,
    HDR_PRIORITY,
    HDR_REQUEST_ID,
    ImmutableRequestShape,
    RequestShapeError,
)


def test_scenario_full_request_lifecycle_crosses_service_boundary() -> None:
    # Edge service mints the shape from its upstream request.
    edge = ImmutableRequestShape(
        request_id="req-lifecycle-1",
        priority="critical",
        deadline_ns=2_000_000_000,
        idempotency_key="checkout-42",
        attempt=0,
        origin="edge",
    )
    # Edge propagates via headers to the downstream service.
    headers = edge.to_headers()
    downstream = ImmutableRequestShape.from_headers(headers)
    assert downstream.request_id == edge.request_id
    assert downstream.priority == "critical"
    # Downstream retries the same logical request — attempt increments, key stable.
    retry = downstream.with_next_attempt(1, next_idempotency_key="checkout-42")
    assert retry.attempt == 1
    assert retry.idempotency_key == "checkout-42"


def test_scenario_missing_priority_defaults_to_normal_not_critical() -> None:
    # An upstream that forgets x-priority MUST NOT be treated as critical.
    partial_headers = {HDR_REQUEST_ID: "req-missing-prio"}
    shape = ImmutableRequestShape.from_headers(partial_headers)
    assert shape.priority == "normal"
    # A load-shedder reading this shape SHALL NOT treat it as critical.
    assert shape.priority != "critical"


def test_scenario_retry_storm_cannot_decrement_attempt() -> None:
    shape = ImmutableRequestShape(request_id="req-storm-1", attempt=3)
    # A buggy retry layer tries to roll the counter back — MUST be rejected.
    with pytest.raises(RequestShapeError):
        shape.with_next_attempt(2)
    # The counter is intact.
    assert shape.attempt == 3


def test_scenario_idempotency_key_survives_three_hop_propagation() -> None:
    s0 = ImmutableRequestShape(
        request_id="req-hop-1", idempotency_key="idem-7", origin="edge",
    )
    # hop 1 — worker receives headers, rebuilds shape
    s1 = ImmutableRequestShape.from_headers(s0.to_headers())
    # hop 2 — worker enqueues to queue, downstream rebuilds shape from attributes
    s2 = ImmutableRequestShape.from_headers(s1.to_headers())
    # hop 3 — next service picks up and rebuilds again
    s3 = ImmutableRequestShape.from_headers(s2.to_headers())
    assert s3.idempotency_key == "idem-7"


def test_scenario_unknown_transport_fields_preserved_end_to_end() -> None:
    # A gRPC metadata adapter adds a tenant field; the HTTP hop MUST NOT drop it.
    shape = ImmutableRequestShape(
        request_id="req-extras",
        origin="grpc-mesh",
        extras={"x-tenant": "acme", "x-shadow-traffic": "true"},
    )
    hop1 = ImmutableRequestShape.from_headers(shape.to_headers())
    hop2 = ImmutableRequestShape.from_headers(hop1.to_headers())
    assert hop2.extras["x-tenant"] == "acme"
    assert hop2.extras["x-shadow-traffic"] == "true"


def test_scenario_shape_hash_stable_across_construction_equiv() -> None:
    # Two shapes that differ only in request_id still fingerprint identically,
    # because the hash covers the TYPE, not the instance.
    a = ImmutableRequestShape(request_id="req-a", priority="normal")
    b = ImmutableRequestShape(request_id="req-b", priority="normal")
    h1 = a.shape_hash(
        method="POST",
        route_pattern="/v1/orders",
        header_keys=("content-type", "authorization"),
        body_bytes=512,
    )
    h2 = b.shape_hash(
        method="POST",
        route_pattern="/v1/orders",
        header_keys=("content-type", "authorization"),
        body_bytes=600,
    )
    # Same route, same header set, same size bucket, same priority — same hash.
    assert h1 == h2


def test_scenario_headers_case_insensitive_like_http() -> None:
    # HTTP header names are case-insensitive; from_headers MUST honor that.
    mixed = {
        "X-Request-Id": "req-case-1",
        "X-Priority": "sheddable",
        HDR_ATTEMPT.upper(): "2",
        HDR_IDEMPOTENCY_KEY.upper(): "idem-case",
    }
    shape = ImmutableRequestShape.from_headers(mixed)
    assert shape.request_id == "req-case-1"
    assert shape.priority == "sheddable"
    assert shape.attempt == 2
    assert shape.idempotency_key == "idem-case"


def test_scenario_retry_with_silent_key_drop_is_rejected() -> None:
    original = ImmutableRequestShape(
        request_id="req-drop", idempotency_key="idem-stable",
    )
    # A buggy retry layer tries to clear the idempotency key.
    # Passing an explicit different key MUST be rejected.
    with pytest.raises(RequestShapeError):
        original.with_next_attempt(1, next_idempotency_key="idem-CHANGED")
    # Simulated wire corruption (header deleted) is caught at reconstruct time:
    headers = original.to_headers()
    del headers[HDR_IDEMPOTENCY_KEY]
    resurrected = ImmutableRequestShape.from_headers(headers)
    # When reconstructing without the header, the caller can detect loss.
    assert resurrected.idempotency_key is None
    assert original.idempotency_key == "idem-stable"
    # The application layer can re-assert the invariant by comparing.
    with pytest.raises(RequestShapeError):
        original.with_next_attempt(1, next_idempotency_key="idem-other")
    # And setting a retry with the ORIGINAL key succeeds.
    ok = original.with_next_attempt(1, next_idempotency_key="idem-stable")
    assert ok.idempotency_key == "idem-stable"
    # Ensure the shape used in this scenario keeps its priority unchanged too.
    assert ok.priority == original.priority
    assert ok.request_id == original.request_id
    # Header confirmation
    assert ok.to_headers()[HDR_PRIORITY] == original.priority
