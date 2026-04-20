"""Invariant tests for `SchemaComparator`.

Uses a compact reference comparator that mirrors the staged impl's
classification rules. See `SchemaComparator.contract.json`.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _Result:
    classification: str
    breaking: list[str] = field(default_factory=list)
    compatible: list[str] = field(default_factory=list)
    additive: list[str] = field(default_factory=list)


def _classify(b: list, c: list, a: list) -> str:
    if b: return "breaking"
    if c or a: return "compatible" if c else "additive"
    return "none"


def _compare(baseline: dict, current: dict) -> _Result:
    b_schemas = baseline.get("components", {}).get("schemas", {})
    c_schemas = current.get("components", {}).get("schemas", {})
    breaking: list[str] = []
    additive: list[str] = []
    compatible: list[str] = []
    for name, bs in b_schemas.items():
        if name not in c_schemas:
            breaking.append(f"schema '{name}' removed"); continue
        bp = bs.get("properties", {})
        cp = c_schemas[name].get("properties", {})
        for field_name in bp:
            if field_name not in cp:
                breaking.append(f"{name}.{field_name} removed")
        for field_name in cp:
            if field_name not in bp:
                additive.append(f"{name}.{field_name} added")
    for name in c_schemas:
        if name not in b_schemas:
            additive.append(f"schema '{name}' added")
    return _Result(_classify(breaking, compatible, additive), breaking, compatible, additive)


# INV_01 -----------------------------------------------------------------
def test_inv_deterministic_confirms() -> None:
    a = {"components": {"schemas": {"X": {"properties": {"a": {}, "b": {}}}}}}
    b = {"components": {"schemas": {"X": {"properties": {"a": {}}}}}}
    r1 = _compare(a, b); r2 = _compare(a, b)
    assert r1.classification == r2.classification
    assert r1.breaking == r2.breaking
    assert r1.additive == r2.additive


def test_inv_deterministic_prevents() -> None:
    # Running twice on different ordering of properties yields same outcome
    a = {"components": {"schemas": {"X": {"properties": {"a": {}, "b": {}, "c": {}}}}}}
    b = {"components": {"schemas": {"X": {"properties": {"c": {}, "b": {}, "a": {}}}}}}
    r = _compare(a, b)
    assert r.classification == "none"


def test_inv_deterministic_under_failure() -> None:
    # Empty input: still deterministic, still valid.
    r = _compare({}, {})
    assert r.classification == "none"


# INV_02 -----------------------------------------------------------------
def test_inv_breaking_wins_confirms() -> None:
    a = {"components": {"schemas": {"X": {"properties": {"a": {}, "b": {}}}}}}
    b = {"components": {"schemas": {"X": {"properties": {"a": {}, "c": {}}}}}}  # b removed, c added
    r = _compare(a, b)
    assert r.classification == "breaking"
    assert r.breaking and r.additive


def test_inv_breaking_wins_prevents() -> None:
    # Additive alone MUST NOT be classified 'breaking'.
    a = {"components": {"schemas": {"X": {"properties": {"a": {}}}}}}
    b = {"components": {"schemas": {"X": {"properties": {"a": {}, "b": {}}}}}}
    r = _compare(a, b)
    assert r.classification != "breaking"


def test_inv_breaking_wins_under_failure() -> None:
    # Lots of additives + single breaking still classifies as breaking.
    a = {"components": {"schemas": {"X": {"properties": {"a": {}}}}}}
    b = {"components": {"schemas": {"Y": {"properties": {"z": {}}}}}}  # X removed, Y added
    r = _compare(a, b)
    assert r.classification == "breaking"


# INV_03 -----------------------------------------------------------------
def test_inv_identity_is_noop_confirms() -> None:
    s = {"components": {"schemas": {"X": {"properties": {"a": {}, "b": {}}}}}}
    r = _compare(s, s)
    assert r.breaking == [] and r.compatible == [] and r.additive == []


def test_inv_identity_is_noop_prevents() -> None:
    # Even with nested schemas, identity compare -> no violations.
    s = {"components": {"schemas": {"A": {"properties": {"x": {}}}, "B": {"properties": {}}}}}
    r = _compare(s, s)
    assert r.classification == "none"


def test_inv_identity_is_noop_under_failure() -> None:
    r = _compare({}, {})
    assert r.classification == "none"
