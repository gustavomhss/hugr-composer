"""Behavioral end-to-end scenarios for Specification — proves invariants at runtime."""

from __future__ import annotations

from dataclasses import dataclass

from Specification import (
    BaseSpecification,
    PredicateSpecification,
    TranslatorRegistry,
    in_memory_filter,
)


# ---------------------------------------------------------------------------
# Domain fixture: bank-account eligibility (mirrors the catalog consumption example)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Account:
    id: int
    balance: int
    last_login_days: int


def _dormant() -> PredicateSpecification[Account]:
    return PredicateSpecification[Account]("dormant", lambda a: a.last_login_days > 180)


def _high_value() -> PredicateSpecification[Account]:
    return PredicateSpecification[Account]("high_value", lambda a: a.balance >= 100_000)


def test_scenario_composed_specification_selects_dormant_non_vip() -> None:
    # Catalog consumption example: dormant AND NOT high_value.
    spec = _dormant().and_(_high_value().not_())
    accounts = [
        Account(1, balance=50_000, last_login_days=365),    # dormant, low value — match
        Account(2, balance=200_000, last_login_days=400),   # dormant, VIP — NOT match
        Account(3, balance=10_000, last_login_days=5),      # active, low value — NOT match
        Account(4, balance=30_000, last_login_days=200),    # dormant, low value — match
    ]
    hits = in_memory_filter(spec, accounts)
    assert [a.id for a in hits] == [1, 4]


def test_scenario_filter_and_translator_agree() -> None:
    reg = TranslatorRegistry()
    reg.register("sql", "dormant", lambda s: "last_login_days > 180")
    reg.register("sql", "high_value", lambda s: "balance >= 100000")
    spec = _dormant().and_(_high_value().not_())
    translated = reg.translate("sql", spec)
    # Translation is a structural tree — it carries the leaf fragments verbatim.
    assert translated == {
        "op": "AND",
        "left": "last_login_days > 180",
        "right": {"op": "NOT", "inner": "balance >= 100000"},
    }


def test_scenario_subclass_leaf_composes_with_predicate_leaf() -> None:
    class IsVIP(BaseSpecification[Account]):
        def is_satisfied_by(self, candidate: Account) -> bool:
            return candidate.balance >= 1_000_000

    spec = IsVIP().or_(_high_value())
    poor = Account(1, balance=100, last_login_days=1)
    high = Account(2, balance=500_000, last_login_days=1)
    vip = Account(3, balance=5_000_000, last_login_days=1)
    assert spec.is_satisfied_by(poor) is False
    assert spec.is_satisfied_by(high) is True
    assert spec.is_satisfied_by(vip) is True


def test_scenario_deep_composition_preserves_semantics() -> None:
    # ((dormant AND NOT high_value) OR (high_value AND NOT dormant)) — XOR of the two.
    d = _dormant()
    h = _high_value()
    xor_like = d.and_(h.not_()).or_(h.and_(d.not_()))
    acc_both = Account(1, balance=500_000, last_login_days=365)
    acc_neither = Account(2, balance=50, last_login_days=1)
    acc_only_d = Account(3, balance=100, last_login_days=500)
    acc_only_h = Account(4, balance=200_000, last_login_days=1)
    assert xor_like.is_satisfied_by(acc_both) is False
    assert xor_like.is_satisfied_by(acc_neither) is False
    assert xor_like.is_satisfied_by(acc_only_d) is True
    assert xor_like.is_satisfied_by(acc_only_h) is True


def test_scenario_translator_missing_leaf_reveals_persistence_gap() -> None:
    # Registering only one of two leaves SHALL surface an explicit error
    # rather than silently coupling the Specification to the backend.
    reg = TranslatorRegistry()
    reg.register("sql", "dormant", lambda s: "last_login_days > 180")
    spec = _dormant().and_(_high_value())
    try:
        reg.translate("sql", spec)
    except Exception as exc:
        assert "high_value" in str(exc)
    else:
        raise AssertionError("missing translator MUST raise")
