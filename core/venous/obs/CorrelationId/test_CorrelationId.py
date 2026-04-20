"""Unit tests for CorrelationId — 3 per invariant."""

from __future__ import annotations

import re

import pytest

from CorrelationId import (
    CorrelationIdError,
    StatelessCorrelationIdProvider,
    extract,
    generate,
    inject,
    parse,
    to_str,
)

_HEX_RE = re.compile(r"^[0-9a-f]{16,64}$")


# ---------------------------------------------------------------------------
# CORRID_INV_01 — every inbound request gets an id before any log.
# ---------------------------------------------------------------------------
def test_inv_populated_before_first_log_confirms() -> None:
    # Empty headers still yield a valid id (so a logger can bind it first).
    cid = extract({})
    assert _HEX_RE.match(cid)


def test_inv_populated_before_first_log_prevents() -> None:
    # parse() refuses empty / short / non-hex values — forces callers to
    # either supply a valid id or go through extract()/generate().
    with pytest.raises(CorrelationIdError):
        parse("")
    with pytest.raises(CorrelationIdError):
        parse("short")
    with pytest.raises(CorrelationIdError):
        parse("NOTHEX-NOTHEX-!")


def test_inv_populated_before_first_log_under_failure() -> None:
    # Garbage upstream header — we still produce a fresh valid id.
    cid = extract({"x-request-id": "not-valid!"})
    assert _HEX_RE.match(cid)


# ---------------------------------------------------------------------------
# CORRID_INV_02 — propagate a valid upstream id, never overwrite.
# ---------------------------------------------------------------------------
def test_inv_propagates_upstream_confirms() -> None:
    upstream = "deadbeefcafebabe0123456789abcdef"
    cid = extract({"x-request-id": upstream})
    assert cid == upstream


def test_inv_propagates_upstream_prevents() -> None:
    # Two consecutive extract() calls with the SAME upstream header MUST NOT
    # mint a new id — propagation is deterministic.
    headers = {"X-Request-Id": "aaaabbbbccccdddd1111222233334444"}
    a = extract(headers)
    b = extract(headers)
    assert a == b == "aaaabbbbccccdddd1111222233334444"


def test_inv_propagates_upstream_under_failure() -> None:
    # traceparent is accepted when x-request-id is absent or invalid.
    tp = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    cid = extract({"traceparent": tp})
    assert cid == "0af7651916cd43dd8448eb211c80319c"


# ---------------------------------------------------------------------------
# CORRID_INV_03 — CSPRNG, not sequential.
# ---------------------------------------------------------------------------
def test_inv_csprng_generated_confirms() -> None:
    cid = generate()
    assert _HEX_RE.match(cid)
    assert len(cid) == 32  # 16 bytes → 32 hex


def test_inv_csprng_generated_prevents() -> None:
    # 10_000 generated ids all distinct — sequential counters would collide
    # with near-certainty on this cardinality.
    ids = {generate() for _ in range(10_000)}
    assert len(ids) == 10_000


def test_inv_csprng_generated_under_failure() -> None:
    # No two consecutive calls are off-by-one in hex — rules out a counter.
    prev = int(generate(), 16)
    for _ in range(50):
        nxt = int(generate(), 16)
        assert abs(nxt - prev) > 1
        prev = nxt


# ---------------------------------------------------------------------------
# CORRID_INV_04 — appears in outbound headers.
# ---------------------------------------------------------------------------
def test_inv_appears_in_outbound_confirms() -> None:
    cid = generate()
    out = inject(cid)
    assert out["x-request-id"] == cid


def test_inv_appears_in_outbound_prevents() -> None:
    # inject MUST NOT mutate caller's mapping.
    cid = generate()
    caller: dict[str, str] = {"authorization": "Bearer x"}
    snapshot = dict(caller)
    new_headers = inject(cid, caller)
    assert caller == snapshot
    assert new_headers["x-request-id"] == cid
    assert new_headers["authorization"] == "Bearer x"


def test_inv_appears_in_outbound_under_failure() -> None:
    # Even when pre-existing x-request-id in the caller dict differs,
    # the canonical cid is what leaves the process.
    cid = generate()
    out = inject(cid, {"x-request-id": "stalevaluewillbereplaced"})
    assert out["x-request-id"] == cid


# ---------------------------------------------------------------------------
# CORRID_INV_05 — immutable value, frozen type semantics.
# ---------------------------------------------------------------------------
def test_inv_immutable_confirms() -> None:
    cid = generate()
    # to_str on the same id always yields the same rendering.
    assert to_str(cid) == to_str(cid) == cid


def test_inv_immutable_prevents() -> None:
    # Attempting to "mutate" by re-parsing a malformed sibling is rejected.
    with pytest.raises(CorrelationIdError):
        parse("aaaaaaaaaaaaaaa")  # 15 chars — off-by-one below minimum.


def test_inv_immutable_under_failure() -> None:
    # A provider is stateless but each call yields an independent valid id —
    # there is no shared mutable state that a peer could corrupt.
    p = StatelessCorrelationIdProvider()
    a = p.current()
    b = p.current()
    assert _HEX_RE.match(a) and _HEX_RE.match(b)
    # Distinctness is near-certain for CSPRNG output.
    assert a != b
