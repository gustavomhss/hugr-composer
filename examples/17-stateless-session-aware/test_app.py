"""Tests for the stateless-but-session-aware example."""
from __future__ import annotations

import random

import pytest

from app import KeyValueBucket, Node


def test_node_kill_does_not_lose_quota_or_cursor() -> None:
    bucket = KeyValueBucket()
    n1 = Node("n1", bucket)
    n1.incr_quota("alice", now=0.0)
    n1.incr_quota("alice", now=0.1)
    n1.set_cursor("alice", 42, now=0.2)
    # Node n1 "dies" — create a new node on the same bucket.
    n2 = Node("n2", bucket)
    assert n2.get_rate("alice", now=1.0) == 2
    assert n2.get_cursor("alice", now=1.0) == 42


def test_flag_propagates_within_one_second() -> None:
    bucket = KeyValueBucket()
    n1 = Node("n1", bucket, ttl_s=1.0)
    n2 = Node("n2", bucket, ttl_s=1.0)
    # n2 populates its local cache with False.
    assert n2.flag("alice", "beta", now=0.0) is False
    # n1 flips the flag.
    n1.set_flag("alice", "beta", True, now=0.1)
    # Within 1 second, n2's cache is still stale.
    # After TTL expiry (>= 1.0s since last fetch), n2 reads fresh from bucket.
    assert n2.flag("alice", "beta", now=1.1) is True


def test_random_routing_matches_sticky_behavior() -> None:
    bucket = KeyValueBucket()
    nodes = [Node(f"n{i}", bucket) for i in range(4)]
    rng = random.Random(42)
    # Caller alice makes 20 requests; each hits a random node.
    now = 0.0
    for _ in range(20):
        n = rng.choice(nodes)
        n.incr_quota("alice", now=now)
        now += 0.05
    # Rate count is 20 on any node, just like sticky routing would give.
    for n in nodes:
        assert n.get_rate("alice", now=now + 2.0) == 20


def test_cold_cache_node_does_not_reset_rate_limit() -> None:
    bucket = KeyValueBucket()
    n1 = Node("n1", bucket)
    for _ in range(5):
        n1.incr_quota("alice", now=0.0)
    # Brand-new cold node — reads from bucket, NOT from zero.
    cold = Node("cold", bucket)
    assert cold.get_rate("alice", now=10.0) == 5


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
