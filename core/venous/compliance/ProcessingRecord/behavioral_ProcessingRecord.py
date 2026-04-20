"""Behavioral scenarios for ProcessingRecord."""

from __future__ import annotations

import pytest

from ProcessingRecord import (
    InMemoryProcessingRegistry,
    ProcessingRecord,
    ProcessingRecordError,
)


def test_scenario_signup_ropa_entry() -> None:
    r = InMemoryProcessingRegistry()
    r.register(ProcessingRecord(
        activity="user.signup",
        controller="AcmeCorp GmbH",
        purposes=("account_creation",),
        data_classes=("pii_email", "pii_name"),
        recipients=("internal",),
        retention_ref="retention:user_account",
        legal_basis="GDPR Art 6(1)(b) contract",
    ))
    assert r.size == 1


def test_scenario_international_transfer_recorded() -> None:
    r = InMemoryProcessingRegistry()
    r.register(ProcessingRecord(
        activity="analytics.export",
        controller="AcmeCorp GmbH",
        purposes=("analytics",),
        data_classes=("pii_event",),
        recipients=("vendor:snowflake",),
        retention_ref="retention:analytics",
        legal_basis="GDPR Art 6(1)(f) legitimate interest",
        transfers_outside_eea=("US",),
    ))
    payload = r.export_ropa()
    assert b"US" in payload


def test_scenario_invalid_legal_basis_rejected() -> None:
    with pytest.raises(ProcessingRecordError):
        ProcessingRecord(
            activity="x", controller="y", purposes=("z",),
            data_classes=("pii",), recipients=("a",),
            retention_ref="r", legal_basis="best_effort",
        )


def test_scenario_ropa_stable_across_releases() -> None:
    r1 = InMemoryProcessingRegistry()
    r2 = InMemoryProcessingRegistry()
    for reg in (r1, r2):
        reg.register(ProcessingRecord(
            activity="a", controller="c", purposes=("p",),
            data_classes=("pii",), recipients=("i",),
            retention_ref="r", legal_basis="GDPR Art 6(1)(a) consent",
        ))
    assert r1.export_ropa() == r2.export_ropa()


def test_scenario_dangling_retention_ref_rejected() -> None:
    class _R:
        def has(self, x: str) -> bool:
            return False
    r = InMemoryProcessingRegistry(retention_resolver=_R())
    with pytest.raises(ProcessingRecordError):
        r.register(ProcessingRecord(
            activity="a", controller="c", purposes=("p",),
            data_classes=("pii",), recipients=("i",),
            retention_ref="no-such", legal_basis="GDPR Art 6(1)(b) contract",
        ))
