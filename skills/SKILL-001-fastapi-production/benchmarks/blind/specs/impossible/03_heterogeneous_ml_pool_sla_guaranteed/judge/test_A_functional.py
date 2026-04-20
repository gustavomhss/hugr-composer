"""Layer A — routing functional."""
from __future__ import annotations

import httpx


def test_A_functional__health(client: httpx.Client) -> None:
    assert client.get("/health").status_code == 200


def test_A_functional__tight_deadline_routes_gpu(client: httpx.Client) -> None:
    r = client.post("/infer", json={
        "session_id": "s1", "deadline_ms": 30, "prompt": "hi",
    })
    assert r.status_code == 200, r.text[:200]
    assert r.json()["worker"] == "gpu", r.json()


def test_A_functional__loose_deadline_routable(client: httpx.Client) -> None:
    r = client.post("/infer", json={
        "session_id": "s2", "deadline_ms": 500, "prompt": "ok",
    })
    assert r.status_code == 200
    assert r.json()["worker"] in ("cpu", "gpu")


def test_A_functional__pool_endpoint_shape(client: httpx.Client) -> None:
    r = client.get("/pool")
    assert r.status_code == 200
    data = r.json()
    assert "cpu" in data and "gpu" in data
    for cls in ("cpu", "gpu"):
        assert "in_flight" in data[cls]
        assert "healthy" in data[cls]
