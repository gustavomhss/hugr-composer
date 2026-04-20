"""Metamorphic tests for EncryptionPolicy."""

from __future__ import annotations

from datetime import timedelta

from EncryptionPolicy import EncryptionPolicy, InMemoryEncryptionRegistry


def _p(**o: object) -> EncryptionPolicy:
    base: dict[str, object] = {
        "data_class": "x", "at_rest_cipher": "AES-256-GCM",
        "in_transit_min_tls": "TLS1.2", "key_provider": "aws-kms://k",
        "rotation": timedelta(days=30),
    }
    base.update(o)
    return EncryptionPolicy(**base)  # type: ignore[arg-type]


def test_metamorphic_bind_then_resolve_identity() -> None:
    r = InMemoryEncryptionRegistry()
    p = _p()
    r.bind(p)
    assert r.resolve("x") == p


def test_metamorphic_rebind_replaces() -> None:
    r = InMemoryEncryptionRegistry()
    r.bind(_p(rotation=timedelta(days=30)))
    r.bind(_p(rotation=timedelta(days=60)))
    assert r.resolve("x").rotation == timedelta(days=60)


def test_metamorphic_frozen_equality() -> None:
    p1 = _p()
    p2 = _p()
    assert p1 == p2
    assert hash(p1) == hash(p2)


def test_differential_data_class_isolation() -> None:
    r = InMemoryEncryptionRegistry()
    r.bind(_p(data_class="a"))
    r.bind(_p(data_class="b"))
    assert r.size == 2


def test_metamorphic_tls_endpoint_idempotent() -> None:
    r = InMemoryEncryptionRegistry()
    for _ in range(3):
        r.require_tls("/api/x")
    assert len(r.tls_endpoints) == 1
