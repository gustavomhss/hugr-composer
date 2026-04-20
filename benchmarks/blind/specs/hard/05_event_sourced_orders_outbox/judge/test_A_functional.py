"""Layer A — functional acceptance for event-sourced orders."""
from __future__ import annotations

import httpx


def test_A_functional__health(client: httpx.Client) -> None:
    assert client.get("/health").status_code == 200


def test_A_functional__create_add_confirm_flow(client: httpx.Client, make_order) -> None:
    oid = make_order()
    r = client.post(f"/orders/{oid}/items", json={"sku": "SKU-1", "quantity": 2})
    assert r.status_code in (200, 201), r.text[:200]
    r2 = client.post(f"/orders/{oid}/confirm")
    assert r2.status_code in (200, 201), r2.text[:200]
    got = client.get(f"/orders/{oid}").json()
    assert got["status"] == "confirmed"
    assert got["version"] >= 3


def test_A_functional__confirm_is_idempotent(client: httpx.Client, make_order) -> None:
    oid = make_order()
    client.post(f"/orders/{oid}/confirm")
    r = client.post(f"/orders/{oid}/confirm")
    assert r.status_code in (200, 201), r.text[:200]
    ev = client.get(f"/orders/{oid}/events").json()["events"]
    confirmed = [e for e in ev if (e.get("type") or e.get("event_type")) == "OrderConfirmed"]
    assert len(confirmed) == 1, f"expected exactly one OrderConfirmed, got {len(confirmed)}: {ev}"


def test_A_functional__cancel_after_confirm_is_422(client: httpx.Client, make_order) -> None:
    oid = make_order()
    client.post(f"/orders/{oid}/confirm")
    r = client.post(f"/orders/{oid}/cancel")
    assert r.status_code == 422, f"cancel confirmed should 422, got {r.status_code}"


def test_A_functional__outbox_drain_clears_pending(client: httpx.Client, make_order) -> None:
    make_order()
    before = client.get("/outbox").json()["pending"]
    assert len(before) >= 1
    r = client.post("/outbox/drain")
    assert r.status_code in (200, 201)
    after = client.get("/outbox").json()["pending"]
    assert after == [], f"after drain pending should be empty, got {len(after)}"
