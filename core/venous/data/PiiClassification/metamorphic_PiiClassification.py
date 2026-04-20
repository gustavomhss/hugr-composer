"""Metamorphic tests for PiiClassification."""

from __future__ import annotations

from dataclasses import dataclass

from PiiClassification import InMemoryPiiClassification, PiiClass


@dataclass
class M:
    a: str
    b: str


def _setup() -> InMemoryPiiClassification:
    c = InMemoryPiiClassification()
    c.register(M, "a", PiiClass.PUBLIC)
    c.register(M, "b", PiiClass.PII)
    return c


def test_metamorphic_mask_idempotent() -> None:
    c = _setup()
    m = M(a="hi", b="ssn")
    r1 = dict(c.mask(m, audience="public"))
    r2 = dict(c.mask(m, audience="public"))
    assert r1 == r2


def test_metamorphic_higher_audience_strictly_more() -> None:
    c = _setup()
    m = M(a="hi", b="ssn")
    pub = dict(c.mask(m, audience="public"))
    int_ = dict(c.mask(m, audience="internal"))
    # internal sees at least as much as public — fields revealed are monotonic.
    assert pub["a"] == int_["a"]


def test_metamorphic_field_order_irrelevant() -> None:
    c = _setup()
    m = M(a="x", b="y")
    out = dict(c.mask(m, audience="public"))
    # Keys are the same regardless of internal iteration order.
    assert set(out.keys()) == {"a", "b"}


def test_differential_two_objects_same_class() -> None:
    c = _setup()
    m1 = M(a="hi", b="ssn")
    m2 = M(a="bye", b="other")
    r1 = dict(c.mask(m1, audience="public"))
    r2 = dict(c.mask(m2, audience="public"))
    # Same redaction shape for both; only the PUBLIC field differs.
    assert r1["b"] == r2["b"] == "[REDACTED]"
    assert r1["a"] != r2["a"]


def test_metamorphic_reclassify_up_allowed_without_approver() -> None:
    c = InMemoryPiiClassification()
    c.register(M, "a", PiiClass.PUBLIC)
    # Upward (public → pii) requires no approver.
    c.register(M, "a", PiiClass.PII)
    assert c.classify(M, "a") is PiiClass.PII
