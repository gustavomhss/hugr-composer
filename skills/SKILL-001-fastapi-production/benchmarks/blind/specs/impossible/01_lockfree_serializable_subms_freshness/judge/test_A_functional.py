"""Layer A — functional."""
from __future__ import annotations

import httpx


def test_A_functional__health(client: httpx.Client) -> None:
    assert client.get("/health").status_code == 200


def test_A_functional__create_incr_swap_state(client: httpx.Client) -> None:
    for n, v in (("a", 10), ("b", 20)):
        r = client.post("/counters", json={"name": n, "value": v})
        assert r.status_code in (200, 201), r.text[:200]
    client.post("/incr", json={"name": "a", "delta": 5})
    client.post("/swap", json={"a": "a", "b": "b"})
    st = client.get("/state").json()
    assert st["counters"]["a"] == 20
    assert st["counters"]["b"] == 15
    assert st["total"] == 35


def test_A_functional__swap_unknown_404(client: httpx.Client) -> None:
    r = client.post("/swap", json={"a": "ghost-x", "b": "ghost-y"})
    assert r.status_code == 404
