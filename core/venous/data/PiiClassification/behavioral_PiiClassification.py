"""Behavioral scenarios for PiiClassification."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from PiiClassification import (
    InMemoryPiiClassification,
    PiiClass,
    PiiClassificationError,
)


@dataclass
class User:
    email: str
    ssn: str
    public_name: str


def test_scenario_hipaa_phi_redaction_for_public() -> None:
    c = InMemoryPiiClassification()
    c.register(User, "email", PiiClass.PII)
    c.register(User, "ssn", PiiClass.PHI)
    c.register(User, "public_name", PiiClass.PUBLIC)
    u = User(email="a@ex.com", ssn="999-99-9999", public_name="Alice")
    out = c.mask(u, audience="public")
    assert out["ssn"] == "[REDACTED]" and out["email"] == "[REDACTED]"
    assert out["public_name"] == "Alice"


def test_scenario_clinician_sees_phi() -> None:
    c = InMemoryPiiClassification()
    c.register(User, "email", PiiClass.PII)
    c.register(User, "ssn", PiiClass.PHI)
    c.register(User, "public_name", PiiClass.PUBLIC)
    u = User(email="a@ex.com", ssn="999", public_name="Alice")
    out = c.mask(u, audience="clinician")
    # Clinician cap is PHI so both email (PII) and ssn (PHI) pass.
    assert out["email"] == "a@ex.com" and out["ssn"] == "999"


def test_scenario_unregistered_field_blocks_mask() -> None:
    c = InMemoryPiiClassification()
    c.register(User, "email", PiiClass.PII)
    # missing ssn + public_name
    with pytest.raises(PiiClassificationError):
        c.mask(User(email="a", ssn="b", public_name="c"), audience="internal")


def test_scenario_reclassify_logged() -> None:
    class _Sink:
        def __init__(self) -> None:
            self.rows: list[dict[str, object]] = []

        def append(self, actor: str, action: str, resource: str, outcome: str,
                   attributes: object) -> str:
            self.rows.append({"action": action, "actor": actor, "resource": resource})
            return "h"

    sink = _Sink()
    c = InMemoryPiiClassification(audit_sink=sink)
    c.register(User, "email", PiiClass.PHI)
    c.reclassify(User, "email", PiiClass.PII, approver="dpo@ex.com")
    assert any(r["action"] == "pii.reclassify" for r in sink.rows)


def test_scenario_pci_redacted_for_non_finance() -> None:
    c = InMemoryPiiClassification()
    c.register(User, "email", PiiClass.PUBLIC)
    c.register(User, "ssn", PiiClass.PCI)
    c.register(User, "public_name", PiiClass.PUBLIC)
    out = c.mask(User(email="a", ssn="4111", public_name="x"), audience="clinician")
    assert out["ssn"] == "[REDACTED]"


def test_scenario_leak_counter_grows() -> None:
    c = InMemoryPiiClassification()
    before = c.leak_count
    c.audit_leak(User(email="x", ssn="y", public_name="z"), sink="stdout")
    assert c.leak_count == before + 1
