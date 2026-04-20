"""Metamorphic tests for ProcessingRecord."""

from __future__ import annotations

from ProcessingRecord import InMemoryProcessingRegistry, ProcessingRecord


def _r(**o: object) -> ProcessingRecord:
    base: dict[str, object] = {
        "activity": "a", "controller": "c", "purposes": ("p",),
        "data_classes": ("pii",), "recipients": ("i",),
        "retention_ref": "r", "legal_basis": "GDPR Art 6(1)(a) consent",
    }
    base.update(o)
    return ProcessingRecord(**base)  # type: ignore[arg-type]


def test_metamorphic_export_is_pure() -> None:
    r = InMemoryProcessingRegistry()
    r.register(_r())
    a = r.export_ropa()
    b = r.export_ropa()
    assert a == b


def test_metamorphic_insertion_order_irrelevant() -> None:
    r1 = InMemoryProcessingRegistry()
    r2 = InMemoryProcessingRegistry()
    r1.register(_r(activity="z"))
    r1.register(_r(activity="a"))
    r2.register(_r(activity="a"))
    r2.register(_r(activity="z"))
    assert r1.export_ropa() == r2.export_ropa()


def test_metamorphic_reregister_replaces() -> None:
    r = InMemoryProcessingRegistry()
    r.register(_r(controller="old"))
    r.register(_r(controller="new"))
    assert b"new" in r.export_ropa()


def test_metamorphic_frozen_equality() -> None:
    a = _r()
    b = _r()
    assert a == b
    assert hash(a) == hash(b)


def test_differential_activities_independent() -> None:
    r = InMemoryProcessingRegistry()
    r.register(_r(activity="a"))
    r.register(_r(activity="b"))
    assert r.size == 2
