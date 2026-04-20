"""Behavioral scenarios for RetentionPolicy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from RetentionPolicy import (
    InMemoryRetentionEnforcer,
    RetentionPolicy,
    RetentionPolicyError,
)


def test_scenario_gdpr_storage_limitation() -> None:
    policy = RetentionPolicy(
        data_class="user_login_ip",
        max_age=timedelta(days=30),
        legal_basis="GDPR Art 5(1)(e) storage limitation",
        deletion_mode="hard",
    )
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    enf = InMemoryRetentionEnforcer(now=lambda: clock[0])
    enf.bind(policy)
    enf.enforce_on_write("user_login_ip", "login-1")
    clock[0] = datetime(2026, 3, 1, tzinfo=timezone.utc)  # 59 days later
    assert enf.sweep() == 1


def test_scenario_pci_dss_cardholder_ttl() -> None:
    policy = RetentionPolicy(
        data_class="cardholder_pan",
        max_age=timedelta(days=365),
        legal_basis="PCI-DSS v4 Req 3.2",
        deletion_mode="crypto_shred",
    )
    enf = InMemoryRetentionEnforcer()
    enf.bind(policy)
    enf.enforce_on_write("cardholder_pan", "pan-1")
    assert enf.size == 1


def test_scenario_unclassified_write_rejected() -> None:
    enf = InMemoryRetentionEnforcer()
    with pytest.raises(RetentionPolicyError):
        enf.enforce_on_write("unknown_class", "x")


def test_scenario_legal_hold_blocks_purge() -> None:
    class _Hold:
        def covers(self, rid: str) -> bool:
            return rid.startswith("case-")

    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    enf = InMemoryRetentionEnforcer(hold_check=_Hold(), now=lambda: clock[0])
    enf.bind(RetentionPolicy(
        data_class="email",
        max_age=timedelta(days=1),
        legal_basis="internal retention policy v3",
        deletion_mode="hard",
    ))
    enf.enforce_on_write("email", "case-123")
    enf.enforce_on_write("email", "routine-1")
    clock[0] = datetime(2026, 1, 3, tzinfo=timezone.utc)
    assert enf.sweep() == 1


def test_scenario_deletion_modes_bindable() -> None:
    for mode in ("hard", "crypto_shred", "anonymize"):
        p = RetentionPolicy(
            data_class=f"dc_{mode}",
            max_age=timedelta(days=7),
            legal_basis="internal",
            deletion_mode=mode,
        )
        InMemoryRetentionEnforcer().bind(p)


def test_scenario_zero_ttl_cannot_register() -> None:
    with pytest.raises(RetentionPolicyError):
        RetentionPolicy(
            data_class="x", max_age=timedelta(0),
            legal_basis="none", deletion_mode="hard",
        )
