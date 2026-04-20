"""Chaos tests for EncryptionPolicy."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest

from EncryptionPolicy import (
    EncryptionPolicy,
    EncryptionPolicyError,
    InMemoryEncryptionRegistry,
)


def _p(**o: object) -> EncryptionPolicy:
    base: dict[str, object] = {
        "data_class": "x", "at_rest_cipher": "AES-256-GCM",
        "in_transit_min_tls": "TLS1.2", "key_provider": "aws-kms://k",
        "rotation": timedelta(days=30),
    }
    base.update(o)
    return EncryptionPolicy(**base)  # type: ignore[arg-type]


def test_chaos_concurrent_bind() -> None:
    r = InMemoryEncryptionRegistry()

    def worker(i: int) -> None:
        r.bind(_p(data_class=f"dc-{i}"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert r.size == 30


def test_chaos_banned_tls_rejected_repeatedly() -> None:
    for bad in ("TLS1.0", "TLS1.1", "SSL3.0", ""):
        with pytest.raises(EncryptionPolicyError):
            _p(in_transit_min_tls=bad)


def test_chaos_banned_key_scheme_rejected() -> None:
    for bad in ("raw://", "file:///", "unknown-kms://", ""):
        with pytest.raises(EncryptionPolicyError):
            _p(key_provider=bad)


def test_chaos_negative_rotation_rejected() -> None:
    with pytest.raises(EncryptionPolicyError):
        _p(rotation=timedelta(days=-1))
    with pytest.raises(EncryptionPolicyError):
        _p(rotation=timedelta(0))


def test_chaos_pci_long_rotation_rejected() -> None:
    r = InMemoryEncryptionRegistry()
    with pytest.raises(EncryptionPolicyError):
        r.bind(_p(data_class="pci_pan", rotation=timedelta(days=400)))
