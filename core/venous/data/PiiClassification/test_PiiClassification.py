"""Unit tests for PiiClassification — 3 per invariant."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from PiiClassification import (
    InMemoryPiiClassification,
    PiiClass,
    PiiClassificationError,
)


@dataclass
class Patient:
    id: str
    ssn: str
    public_note: str


# PIC_INV_01 — every field must carry a PiiClass.
def test_inv_registration_required_confirms() -> None:
    c = InMemoryPiiClassification()
    c.register(Patient, "id", PiiClass.INTERNAL)
    assert c.classify(Patient, "id") is PiiClass.INTERNAL


def test_inv_registration_required_prevents() -> None:
    c = InMemoryPiiClassification()
    with pytest.raises(PiiClassificationError):
        c.classify(Patient, "id")  # not registered
    with pytest.raises(PiiClassificationError):
        c.register(Patient, "", PiiClass.PII)


def test_inv_registration_required_under_failure() -> None:
    c = InMemoryPiiClassification()
    with pytest.raises(PiiClassificationError):
        c.register(Patient, "id", "pii")  # type: ignore[arg-type]


# PIC_INV_02 — mask() is the only legal path to emission.
def test_inv_mask_only_confirms() -> None:
    c = InMemoryPiiClassification()
    c.register(Patient, "id", PiiClass.INTERNAL)
    c.register(Patient, "ssn", PiiClass.PII)
    c.register(Patient, "public_note", PiiClass.PUBLIC)
    p = Patient(id="u-1", ssn="123-45-6789", public_note="hi")
    out = c.mask(p, audience="internal")
    assert out["id"] == "u-1"
    assert out["public_note"] == "hi"
    # INTERNAL audience caps at INTERNAL; PII is above cap → redacted.
    assert out["ssn"] == "[REDACTED]"


def test_inv_mask_only_prevents() -> None:
    c = InMemoryPiiClassification()
    c.register(Patient, "id", PiiClass.INTERNAL)
    # Masking an object with an unregistered field fails.
    p = Patient(id="u", ssn="x", public_note="y")
    with pytest.raises(PiiClassificationError):
        c.mask(p, audience="internal")


def test_inv_mask_only_under_failure() -> None:
    c = InMemoryPiiClassification()
    # audit_leak is the acknowledged escape hatch for error reporting.
    c.audit_leak(object(), sink="stdout")
    assert c.leak_count == 1


# PIC_INV_03 — PHI / PCI never to unauthenticated audience.
def test_inv_phi_no_leak_confirms() -> None:
    c = InMemoryPiiClassification()
    c.register(Patient, "id", PiiClass.PUBLIC)
    c.register(Patient, "ssn", PiiClass.PHI)
    c.register(Patient, "public_note", PiiClass.PUBLIC)
    p = Patient(id="u-1", ssn="xxx", public_note="hi")
    out = c.mask(p, audience="public")
    assert out["ssn"] == "[REDACTED]"
    assert out["id"] == "u-1"


def test_inv_phi_no_leak_prevents() -> None:
    c = InMemoryPiiClassification()
    with pytest.raises(PiiClassificationError):
        c.mask(Patient(id="u", ssn="x", public_note="y"), audience="bogus")


def test_inv_phi_no_leak_under_failure() -> None:
    c = InMemoryPiiClassification()
    c.register(Patient, "id", PiiClass.PCI)
    c.register(Patient, "ssn", PiiClass.PCI)
    c.register(Patient, "public_note", PiiClass.PUBLIC)
    p = Patient(id="4111", ssn="4111", public_note="hi")
    out = c.mask(p, audience="public")
    assert out["id"] == "[REDACTED]" and out["ssn"] == "[REDACTED]"


# PIC_INV_04 — mask() deterministic.
def test_inv_mask_deterministic_confirms() -> None:
    c = InMemoryPiiClassification()
    for f, cls in (("id", PiiClass.INTERNAL), ("ssn", PiiClass.PII),
                   ("public_note", PiiClass.PUBLIC)):
        c.register(Patient, f, cls)
    p = Patient(id="u-1", ssn="ssn", public_note="p")
    o1 = dict(c.mask(p, audience="internal"))
    o2 = dict(c.mask(p, audience="internal"))
    assert o1 == o2


def test_inv_mask_deterministic_prevents() -> None:
    c = InMemoryPiiClassification()
    c.register(Patient, "id", PiiClass.PUBLIC)
    c.register(Patient, "ssn", PiiClass.PUBLIC)
    c.register(Patient, "public_note", PiiClass.PUBLIC)
    with pytest.raises(PiiClassificationError):
        c.mask(Patient(id="x", ssn="y", public_note="z"), audience="")


def test_inv_mask_deterministic_under_failure() -> None:
    c = InMemoryPiiClassification()
    c.register(Patient, "id", PiiClass.PUBLIC)
    c.register(Patient, "ssn", PiiClass.PII)
    c.register(Patient, "public_note", PiiClass.PUBLIC)
    # Two audiences → different outputs; each deterministic per audience.
    p = Patient(id="x", ssn="y", public_note="z")
    int_a = c.mask(p, audience="internal")
    pub_a = c.mask(p, audience="public")
    assert int_a["ssn"] == "[REDACTED]" and pub_a["ssn"] == "[REDACTED]"


# PIC_INV_05 — downward reclassification needs approver.
class _Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def append(self, actor: str, action: str, resource: str, outcome: str,
               attributes: object) -> str:
        self.rows.append({"actor": actor, "action": action,
                          "resource": resource, "attrs": dict(attributes)})  # type: ignore[arg-type]
        return "h"


def test_inv_reclassify_approver_confirms() -> None:
    sink = _Sink()
    c = InMemoryPiiClassification(audit_sink=sink)
    c.register(Patient, "ssn", PiiClass.PHI)
    rec = c.reclassify(Patient, "ssn", PiiClass.PII, approver="compliance@ex.com")
    assert rec.approver == "compliance@ex.com"
    assert any(r["action"] == "pii.reclassify" for r in sink.rows)


def test_inv_reclassify_approver_prevents() -> None:
    c = InMemoryPiiClassification()
    c.register(Patient, "ssn", PiiClass.PHI)
    with pytest.raises(PiiClassificationError):
        c.reclassify(Patient, "ssn", PiiClass.PII, approver="")


def test_inv_reclassify_approver_under_failure() -> None:
    c = InMemoryPiiClassification()
    # Direct downward `register` call (without reclassify) is rejected.
    c.register(Patient, "ssn", PiiClass.PHI)
    with pytest.raises(PiiClassificationError):
        c.register(Patient, "ssn", PiiClass.PII)
