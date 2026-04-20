"""Behavioral scenarios for EncryptionPolicy."""

from __future__ import annotations

from datetime import timedelta

import pytest

from EncryptionPolicy import (
    EncryptionPolicy,
    EncryptionPolicyError,
    InMemoryEncryptionRegistry,
)


def test_scenario_pci_pan_binding() -> None:
    r = InMemoryEncryptionRegistry()
    r.bind(EncryptionPolicy(
        data_class="cardholder_pan",
        at_rest_cipher="AES-256-GCM",
        in_transit_min_tls="TLS1.2",
        key_provider="aws-kms://alias/pci-pan",
        rotation=timedelta(days=365),
    ))
    assert r.resolve("cardholder_pan").rotation == timedelta(days=365)


def test_scenario_weak_cipher_rejected() -> None:
    with pytest.raises(EncryptionPolicyError):
        EncryptionPolicy(
            data_class="x", at_rest_cipher="AES-128-CBC",
            in_transit_min_tls="TLS1.2", key_provider="aws-kms://x",
            rotation=timedelta(days=30),
        )


def test_scenario_write_rejected_without_binding() -> None:
    r = InMemoryEncryptionRegistry()
    with pytest.raises(EncryptionPolicyError):
        r.resolve("unbound_class")


def test_scenario_require_tls_collects_endpoints() -> None:
    r = InMemoryEncryptionRegistry()
    r.require_tls("/api/users")
    r.require_tls("/api/payments")
    assert {"/api/users", "/api/payments"} <= r.tls_endpoints


def test_scenario_tls10_rejected_everywhere() -> None:
    with pytest.raises(EncryptionPolicyError):
        EncryptionPolicy(
            data_class="x", at_rest_cipher="AES-256-GCM",
            in_transit_min_tls="TLS1.0", key_provider="aws-kms://x",
            rotation=timedelta(days=30),
        )
