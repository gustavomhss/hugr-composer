"""Layer D — malformed / impossible-SLA → 4xx|503, never 500."""
from __future__ import annotations

import httpx


def test_D_chaos__impossible_sla_returns_503_not_500(client: httpx.Client) -> None:
    # deadline 1ms — faster than even GPU.
    r = client.post("/infer", json={
        "session_id": "tight", "deadline_ms": 1, "prompt": "x",
    })
    assert r.status_code in (503, 200), f"got {r.status_code}"
    if r.status_code == 503:
        assert r.json().get("error") == "sla_infeasible"


def test_D_chaos__malformed_bodies_never_500(client: httpx.Client) -> None:
    for b in (
        {}, {"session_id": "s"}, {"deadline_ms": 100},
        {"session_id": None, "deadline_ms": 100, "prompt": "x"},
        {"session_id": "s", "deadline_ms": "fast", "prompt": "x"},
    ):
        r = client.post("/infer", json=b)
        assert r.status_code < 500, f"body={b} → {r.status_code}"
