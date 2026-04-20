"""Unit tests for CONTRACT §B2.1 — `find_primitive` retrieval tool.

Tests enforce the contract's DoD and invariants:

- Pure retrieval (no network, no LLM).
- Latency p95 < 50 ms on full 97-primitive registry.
- Every concern in the fixed taxonomy returns ≥ 1 hit on empty-query probe.
- Deterministic given identical input.
- Schema shape matches contract exactly.
- Limit is capped at 10 regardless of caller input.
"""
from __future__ import annotations

import time

import pytest

from engine.discovery import PrimitiveIndex, find_primitive, get_index


@pytest.fixture(scope="module")
def index() -> PrimitiveIndex:
    return get_index()


def test_index_loads_all_registered_primitives(index: PrimitiveIndex) -> None:
    # Registry must equal on-disk production primitive count (CONTRACT §B1.1).
    import yaml
    from pathlib import Path
    reg = yaml.safe_load((Path(__file__).resolve().parents[1] / "primitives_by_concern.yaml").read_text())
    assert index.size == len(reg["primitives"])
    assert index.size >= 97, f"registry shrunk below Phase 1 floor: {index.size}"


def test_every_concern_returns_at_least_one_hit_on_empty_query(index: PrimitiveIndex) -> None:
    for concern in index.concerns:
        hits = find_primitive(concern=concern, query="", limit=10)
        assert hits, f"concern {concern!r} yielded no hits on empty-query probe"
        assert all(h["concern"] == concern for h in hits)


def test_schema_shape_matches_contract() -> None:
    hits = find_primitive(query="circuit breaker", limit=5)
    assert hits
    required = {"name", "namespace", "concern", "purpose", "score"}
    for h in hits:
        assert required <= set(h.keys())
        assert isinstance(h["name"], str)
        assert isinstance(h["namespace"], str)
        assert isinstance(h["concern"], str)
        assert isinstance(h["purpose"], str)
        assert isinstance(h["score"], float)


def test_exact_name_query_ranks_that_primitive_first() -> None:
    for name in ("CircuitBreaker", "SignatureVerifier", "RateLimiter", "SecretsVault", "IdempotentConsumer"):
        hits = find_primitive(query=name, limit=3)
        assert hits and hits[0]["name"] == name, f"exact-name query {name!r} did not rank itself first"


def test_unknown_concern_returns_empty() -> None:
    assert find_primitive(concern="not-a-real-concern", query="logger") == []


def test_limit_is_capped_at_ten() -> None:
    hits = find_primitive(query="event", limit=999)
    assert len(hits) <= 10


def test_limit_zero_returns_empty() -> None:
    assert find_primitive(query="event", limit=0) == []


def test_limit_negative_returns_empty() -> None:
    assert find_primitive(query="event", limit=-5) == []


def test_stemmer_symmetry_plurals() -> None:
    """Regression: 'classes'/'class' and 'verifier'/'verify' must converge."""
    from engine.discovery.find_primitive import _stem

    assert _stem("classes") == _stem("class"), (_stem("classes"), _stem("class"))
    assert _stem("verifier") == _stem("verify"), (_stem("verifier"), _stem("verify"))
    assert _stem("limiter") == _stem("limit"), (_stem("limiter"), _stem("limit"))
    assert _stem("hashes") == _stem("hash") == _stem("hashed") == _stem("hashing")


def test_latency_p95_under_fifty_ms(index: PrimitiveIndex) -> None:
    queries = [
        "circuit breaker", "deduplicate webhook", "signature verify", "audit tamper",
        "rate limit", "retry budget", "saga compensation", "outbox transactional",
        "dead letter", "distributed lock", "structured log correlation", "workflow durable",
        "feature toggle", "secrets vault", "password hash", "encrypt envelope",
        "graceful shutdown", "csrf cookie", "totp one time password", "bulkhead pool",
    ]
    # Warm any lazy state.
    for q in queries:
        find_primitive(query=q, limit=10)

    samples: list[float] = []
    for q in queries * 5:
        t0 = time.perf_counter()
        find_primitive(query=q, limit=10)
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    p95 = samples[int(0.95 * len(samples))]
    assert p95 < 50.0, f"p95 latency {p95:.3f} ms >= 50 ms"


def test_determinism_identical_inputs_identical_outputs() -> None:
    runs = [find_primitive(concern="events", query="dedupe webhook", limit=5) for _ in range(5)]
    assert all(r == runs[0] for r in runs)


def test_no_network_calls_during_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pure-retrieval invariant: no socket traffic during query."""
    import socket

    def boom(*args, **kwargs):  # noqa: ANN001, ANN003
        raise AssertionError("find_primitive must not open sockets")

    monkeypatch.setattr(socket.socket, "connect", boom, raising=True)
    monkeypatch.setattr(socket.socket, "connect_ex", boom, raising=True)
    hits = find_primitive(concern="resiliency", query="circuit breaker", limit=5)
    assert hits[0]["name"] == "CircuitBreaker"


def test_quality_bench_meets_contract() -> None:
    """CONTRACT §B2.1 Quality gate: top-1 ≥ 80% on curated set."""
    from engine.discovery.quality_bench import _DEFAULT_SET, run

    top1, p_at_3, rows = run(_DEFAULT_SET)
    assert top1 >= 0.80, f"top-1 {top1:.0%} below contract floor 80% — rows: {rows}"
    assert p_at_3 >= 0.90, f"P@3 {p_at_3:.0%} below contract floor 90% — rows: {rows}"
