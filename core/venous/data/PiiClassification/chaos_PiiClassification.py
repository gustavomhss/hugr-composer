"""Chaos tests for PiiClassification."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from PiiClassification import (
    InMemoryPiiClassification,
    PiiClass,
    PiiClassificationError,
)


@dataclass
class U:
    f: str


def test_chaos_unregistered_field_cannot_leak_through_mask() -> None:
    c = InMemoryPiiClassification()
    with pytest.raises(PiiClassificationError):
        c.mask(U(f="secret"), audience="internal")


def test_chaos_invalid_audience_rejected() -> None:
    c = InMemoryPiiClassification()
    c.register(U, "f", PiiClass.PUBLIC)
    with pytest.raises(PiiClassificationError):
        c.mask(U(f="x"), audience="bogus")


def test_chaos_downward_register_blocked_repeatedly() -> None:
    c = InMemoryPiiClassification()
    c.register(U, "f", PiiClass.PCI)
    for lower in (PiiClass.PHI, PiiClass.PII, PiiClass.INTERNAL, PiiClass.PUBLIC):
        with pytest.raises(PiiClassificationError):
            c.register(U, "f", lower)


def test_chaos_reclassify_unregistered_fails() -> None:
    c = InMemoryPiiClassification()
    with pytest.raises(PiiClassificationError):
        c.reclassify(U, "f", PiiClass.PII, approver="x")


def test_chaos_non_dataclass_object() -> None:
    c = InMemoryPiiClassification()
    # Plain object without __dict__ — masking refuses.
    with pytest.raises(PiiClassificationError):
        c.mask(object(), audience="internal")


def test_chaos_whitespace_rejected_everywhere() -> None:
    c = InMemoryPiiClassification()
    with pytest.raises(PiiClassificationError):
        c.register(U, "   ", PiiClass.PUBLIC)
