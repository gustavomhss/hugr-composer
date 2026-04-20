"""Metamorphic tests for DataResidencyPolicy."""

from __future__ import annotations

from DataResidencyPolicy import DataResidencyPolicy, InMemoryResidencyEnforcer


def _p(**o: object) -> DataResidencyPolicy:
    base: dict[str, object] = {
        "data_class": "x", "allowed_regions": ("DE", "FR"),
        "transfer_mechanism": "SCC_2021/914",
    }
    base.update(o)
    return DataResidencyPolicy(**base)  # type: ignore[arg-type]


def test_metamorphic_bind_is_idempotent() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(_p())
    e.bind(_p())
    assert e.size == 1


def test_metamorphic_rebind_replaces_allowed_regions() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(_p(allowed_regions=("DE",)))
    e.bind(_p(allowed_regions=("DE", "FR")))
    e.check_write("x", "FR")


def test_metamorphic_frozen_equality() -> None:
    p1 = _p()
    p2 = _p()
    assert p1 == p2 and hash(p1) == hash(p2)


def test_differential_two_data_classes_independent() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(_p(data_class="a", allowed_regions=("DE",)))
    e.bind(_p(data_class="b", allowed_regions=("US",)))
    e.check_write("a", "DE")
    e.check_write("b", "US")


def test_metamorphic_check_transfer_mirrors_check_write_on_destination() -> None:
    import pytest

    from DataResidencyPolicy import DataResidencyPolicyError
    e = InMemoryResidencyEnforcer()
    e.bind(_p(allowed_regions=("DE",)))
    with pytest.raises(DataResidencyPolicyError):
        e.check_transfer("x", source="DE", destination="FR")
