"""Layer D — malformed mutations → 4xx, not 500."""
from __future__ import annotations

import httpx


def test_D_chaos__malformed_item_body_4xx(client: httpx.Client, make_order) -> None:
    oid = make_order()
    for bad in ({}, {"quantity": 1}, {"sku": "x", "quantity": -5},
                {"sku": "x", "quantity": "two"}):
        r = client.post(f"/orders/{oid}/items", json=bad)
        assert 400 <= r.status_code < 500, f"body={bad} → {r.status_code}"


def test_D_chaos__unknown_order_confirm_404(client: httpx.Client) -> None:
    r = client.post("/orders/deadbeef-0000-0000-0000-000000000000/confirm")
    assert r.status_code in (404, 422), r.text[:200]
