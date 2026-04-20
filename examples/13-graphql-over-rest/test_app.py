"""Tests for the GraphQL-over-REST example."""
from __future__ import annotations

import pytest

from app import (
    DataLoader,
    DepthLimitError,
    FieldACL,
    PersistedQueryRegistry,
    enforce_depth,
    resolve_orders_query,
)


def _make_loaders(n_orders: int = 50):
    orders = DataLoader(lambda ids: {
        oid: {"id": oid, "customer_id": f"c{int(oid[1:]) % 10}",
              "product_id": f"p{int(oid[1:]) % 7}"}
        for oid in ids
    })
    customers = DataLoader(lambda ids: {c: {"id": c, "name": f"Cust-{c}"} for c in ids})
    products = DataLoader(lambda ids: {p: {"id": p, "name": f"Prod-{p}"} for p in ids})
    return orders, customers, products


def test_50_orders_query_issues_three_batched_calls() -> None:
    orders, customers, products = _make_loaders()
    acl = FieldACL()
    result = resolve_orders_query(
        order_ids=[f"o{i}" for i in range(50)],
        orders_loader=orders, customers_loader=customers,
        products_loader=products, acl=acl, user_roles={"viewer"},
    )
    assert orders.calls == 1
    assert customers.calls == 1
    assert products.calls == 1
    assert len(result.data["orders"]) == 50


def test_40_level_deep_query_is_rejected_before_execution() -> None:
    deep: dict = {}
    cur = deep
    for _ in range(40):
        cur["next"] = {}
        cur = cur["next"]
    with pytest.raises(DepthLimitError):
        enforce_depth(deep, max_depth=15)


def test_unauthorized_field_returns_null_and_error_entry() -> None:
    orders, customers, products = _make_loaders()
    acl = FieldACL(required_roles={"product": "admin"})
    result = resolve_orders_query(
        order_ids=["o1", "o2"],
        orders_loader=orders, customers_loader=customers,
        products_loader=products, acl=acl, user_roles={"viewer"},
    )
    assert all(r["product"] is None for r in result.data["orders"])
    assert len(result.errors) == 2
    assert all("unauthorized" in e["message"] for e in result.errors)


def test_persisted_query_unknown_id_rejected_in_production() -> None:
    reg = PersistedQueryRegistry()
    known_id = reg.register("query { orders { id } }")
    assert reg.resolve(known_id) is not None
    assert reg.resolve("0" * 64) is None  # unknown id → reject


def test_dataloader_dedups_within_batch() -> None:
    calls = []
    def batch(ids):
        calls.append(tuple(ids))
        return {i: i * 2 for i in ids}

    loader = DataLoader(batch)
    loader.load(1)
    loader.load(2)
    loader.load(1)  # duplicate
    loader.dispatch()
    assert calls == [(1, 2)]  # de-duped, one batch


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
