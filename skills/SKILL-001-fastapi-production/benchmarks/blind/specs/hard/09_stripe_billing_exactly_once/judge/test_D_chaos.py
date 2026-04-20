"""Layer D — malformed bodies never 500."""
from __future__ import annotations

import httpx


def test_D_chaos__malformed_bill_body_never_500(client: httpx.Client) -> None:
    for b in (
        {}, {"customer_id": "x"}, {"customer_id": "x", "cycle_id": "y"},
        {"customer_id": "x", "cycle_id": "y", "amount_cents": -1},
        {"customer_id": None, "cycle_id": "y", "amount_cents": 100},
        {"amount_cents": 100},
    ):
        r = client.post("/bill", json=b)
        assert r.status_code < 500, f"body={b} → {r.status_code}"
