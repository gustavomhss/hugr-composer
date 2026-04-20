"""Layer D — malformed bodies never 500."""
from __future__ import annotations

import httpx


def test_D_chaos__malformed_body_never_500(client: httpx.Client) -> None:
    for b in (
        {}, {"dataset": "orders"}, {"partition": "2026-04-01"},
        {"dataset": None, "partition": "2026-04-01"},
        {"dataset": 123, "partition": "2026-04-01"},
        "not a dict",
    ):
        r = client.post("/exports", json=b)
        assert r.status_code < 500, f"body={b!r} → {r.status_code}"
