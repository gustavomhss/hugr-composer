"""Layer A — billing functional."""
from __future__ import annotations

import uuid

import httpx


def test_A_functional__health(client: httpx.Client) -> None:
    assert client.get("/health").status_code == 200


def test_A_functional__first_charged_second_already_charged(client: httpx.Client) -> None:
    cust, cyc = f"c-{uuid.uuid4().hex[:8]}", "2026-04"
    body = {"customer_id": cust, "cycle_id": cyc, "amount_cents": 4999}
    r1 = client.post("/bill", json=body)
    assert r1.status_code == 200, r1.text[:200]
    assert r1.json()["status"] == "charged"
    sid = r1.json()["stripe_charge_id"]
    r2 = client.post("/bill", json=body)
    assert r2.status_code == 200
    assert r2.json()["status"] == "already_charged"
    assert r2.json()["stripe_charge_id"] == sid


def test_A_functional__distinct_cycles_independent(client: httpx.Client) -> None:
    for cyc in ("a", "b", "c"):
        r = client.post("/bill", json={"customer_id": "ccc", "cycle_id": cyc, "amount_cents": 100})
        assert r.status_code == 200, r.text[:200]
        assert r.json()["status"] == "charged"


def test_A_functional__charges_list_contains_unique_pairs(client: httpx.Client) -> None:
    client.post("/bill", json={"customer_id": "LX", "cycle_id": "2026-01", "amount_cents": 1})
    client.post("/bill", json={"customer_id": "LX", "cycle_id": "2026-02", "amount_cents": 2})
    r = client.get("/charges")
    assert r.status_code == 200
    pairs = {
        (c.get("customer_id"), c.get("cycle_id"))
        for c in r.json()["charges"]
    }
    assert ("LX", "2026-01") in pairs
    assert ("LX", "2026-02") in pairs
