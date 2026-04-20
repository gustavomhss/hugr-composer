"""Unit tests for CONTRACT §B2.2 — `suggest_composition` retrieval tool."""
from __future__ import annotations

import time

import pytest

from engine.discovery import RecipeIndex, get_recipe_index, suggest_composition


@pytest.fixture(scope="module")
def index() -> RecipeIndex:
    return get_recipe_index()


def test_index_parses_all_compose_with_sections(index: RecipeIndex) -> None:
    # 97 primitives × ~3 recipes each — contract A5 guarantees ≥3 per primitive.
    assert index.size >= 97 * 3 - 10, f"expected ≥~285 recipes, got {index.size}"


def test_schema_shape_matches_contract() -> None:
    hits = suggest_composition("webhook receiver dedup audit", limit=3)
    assert hits
    required = {"primitives", "rationale", "score", "source", "name"}
    for h in hits:
        assert required <= set(h.keys())
        assert isinstance(h["primitives"], list) and all(isinstance(p, str) for p in h["primitives"])
        assert isinstance(h["rationale"], str) and h["rationale"]
        assert isinstance(h["score"], float) and h["score"] > 0
        assert isinstance(h["source"], str) and h["source"]


def test_source_primitive_always_included() -> None:
    for h in suggest_composition("circuit breaker timeout budget retry", limit=5):
        assert h["source"] in h["primitives"], f"source {h['source']} missing from {h['primitives']}"


def test_limit_capped_at_five() -> None:
    hits = suggest_composition("event", limit=999)
    assert len(hits) <= 5


def test_limit_zero_returns_empty() -> None:
    assert suggest_composition("event", limit=0) == []


def test_empty_intent_returns_empty() -> None:
    assert suggest_composition("", limit=5) == []
    assert suggest_composition("   ", limit=5) == []


def test_determinism() -> None:
    a = suggest_composition("webhook receiver with dedup and audit", limit=5)
    b = suggest_composition("webhook receiver with dedup and audit", limit=5)
    assert a == b


def test_dedup_composition_tuples() -> None:
    """Same primitive set should not appear twice in the result list."""
    hits = suggest_composition("circuit breaker retry timeout", limit=5)
    keys = [tuple(sorted(h["primitives"])) for h in hits]
    assert len(keys) == len(set(keys)), f"duplicate compositions: {keys}"


def test_latency_p95_under_one_hundred_ms(index: RecipeIndex) -> None:
    intents = [
        "webhook receiver dedup audit",
        "encrypt then sign outbound",
        "circuit breaker timeout retry",
        "saga compensation durable",
        "rate limit load shed",
        "outbox change data capture",
        "tamper evident audit log",
        "totp replay protection",
        "oauth authorization code",
        "dead letter poison retry",
    ]
    for i in intents:
        suggest_composition(i, limit=5)
    samples: list[float] = []
    for i in intents * 5:
        t0 = time.perf_counter()
        suggest_composition(i, limit=5)
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    p95 = samples[int(0.95 * len(samples))]
    assert p95 < 100.0, f"p95 latency {p95:.3f} ms >= 100 ms"


def test_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def boom(*a, **kw):  # noqa: ANN001, ANN003
        raise AssertionError("suggest_composition must not open sockets")

    monkeypatch.setattr(socket.socket, "connect", boom, raising=True)
    monkeypatch.setattr(socket.socket, "connect_ex", boom, raising=True)
    hits = suggest_composition("webhook receiver", limit=3)
    assert hits and "IdempotentConsumer" in hits[0]["primitives"] or "SignatureVerifier" in hits[0]["primitives"]


def test_quality_bench_meets_contract() -> None:
    """CONTRACT §B2.2: top-1 ≥ 70%, P@3 ≥ 90%."""
    from engine.discovery.compose_bench import _DEFAULT_SET, run

    top1, p3, rows = run(_DEFAULT_SET)
    assert top1 >= 0.70, f"top-1 {top1:.0%} below contract floor 70% — rows: {rows}"
    assert p3 >= 0.90, f"P@3 {p3:.0%} below contract floor 90% — rows: {rows}"
