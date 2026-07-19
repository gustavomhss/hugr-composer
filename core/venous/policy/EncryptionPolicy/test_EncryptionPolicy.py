"""Unit tests for EncryptionPolicy — 3 per invariant."""

from __future__ import annotations

from datetime import timedelta

import pytest
from EncryptionPolicy import (
    EncryptionPolicy,
    EncryptionPolicyError,
    InMemoryEncryptionRegistry,
)


def _policy(**overrides: object) -> EncryptionPolicy:
    base: dict[str, object] = {
        "data_class": "user_pii",
        "at_rest_cipher": "AES-256-GCM",
        "in_transit_min_tls": "TLS1.2",
        "key_provider": "aws-kms://alias/test",
        "rotation": timedelta(days=90),
    }
    base.update(overrides)
    return EncryptionPolicy(**base)  # type: ignore[arg-type]


# EP_INV_01 — policy bound for sensitive data_classes.
def test_inv_bound_required_confirms() -> None:
    r = InMemoryEncryptionRegistry()
    r.bind(_policy())
    assert r.resolve("user_pii").data_class == "user_pii"


def test_inv_bound_required_prevents() -> None:
    r = InMemoryEncryptionRegistry()
    with pytest.raises(EncryptionPolicyError):
        r.resolve("unbound")


def test_inv_bound_required_under_failure() -> None:
    with pytest.raises(EncryptionPolicyError):
        _policy(data_class="")


# EP_INV_02 — cipher enum.
def test_inv_cipher_enum_confirms() -> None:
    for c in ("AES-256-GCM", "ChaCha20-Poly1305"):
        _policy(at_rest_cipher=c)


def test_inv_cipher_enum_prevents() -> None:
    with pytest.raises(EncryptionPolicyError):
        _policy(at_rest_cipher="DES")
    with pytest.raises(EncryptionPolicyError):
        _policy(at_rest_cipher="AES-128-CBC")


def test_inv_cipher_enum_under_failure() -> None:
    with pytest.raises(EncryptionPolicyError):
        _policy(at_rest_cipher="")


# EP_INV_03 — TLS >= 1.2.
def test_inv_tls_min_confirms() -> None:
    _policy(in_transit_min_tls="TLS1.2")
    _policy(in_transit_min_tls="TLS1.3")


def test_inv_tls_min_prevents() -> None:
    for bad in ("TLS1.0", "TLS1.1", "SSL3.0", "tls1.2"):
        with pytest.raises(EncryptionPolicyError):
            _policy(in_transit_min_tls=bad)


def test_inv_tls_min_under_failure() -> None:
    r = InMemoryEncryptionRegistry()
    with pytest.raises(EncryptionPolicyError):
        r.require_tls("")


# EP_INV_04 — KMS scheme required.
def test_inv_kms_scheme_confirms() -> None:
    for kp in (
        "aws-kms://alias/x",
        "gcp-kms://projects/p/locations/l/keyRings/k/cryptoKeys/c",
        "azure-keyvault://vault.vault.azure.net/keys/k/v",
        "hashicorp-vault://transit/keys/k",
    ):
        _policy(key_provider=kp)


def test_inv_kms_scheme_prevents() -> None:
    for bad in ("raw://key", "file:///etc/secret", "key=abc123", ""):
        with pytest.raises(EncryptionPolicyError):
            _policy(key_provider=bad)


def test_inv_kms_scheme_under_failure() -> None:
    with pytest.raises(EncryptionPolicyError):
        _policy(key_provider="plaintext-key-bytes")


# EP_INV_05 — PCI rotation cap.
def test_inv_pci_rotation_confirms() -> None:
    r = InMemoryEncryptionRegistry()
    r.bind(_policy(data_class="pci_pan", rotation=timedelta(days=365)))
    r.bind(_policy(data_class="pci_pan2", rotation=timedelta(days=90)))


def test_inv_pci_rotation_prevents() -> None:
    r = InMemoryEncryptionRegistry()
    with pytest.raises(EncryptionPolicyError):
        r.bind(_policy(data_class="pci_pan", rotation=timedelta(days=400)))


def test_inv_pci_rotation_under_failure() -> None:
    # Non-PCI class with long rotation is permitted.
    r = InMemoryEncryptionRegistry()
    r.bind(_policy(data_class="user_pii", rotation=timedelta(days=730)))
