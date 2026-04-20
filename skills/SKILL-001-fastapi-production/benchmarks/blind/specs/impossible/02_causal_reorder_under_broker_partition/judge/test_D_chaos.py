"""Layer D — broker partition: events buffered then released."""
from __future__ import annotations

import time
import uuid

import httpx


def test_D_chaos__partition_then_recover(client: httpx.Client) -> None:
    r = client.post("/broker/_partition", json={"duration_ms": 150})
    assert r.status_code in (200, 202, 204)
    agg = f"P-{uuid.uuid4().hex[:6]}"
    for s in (0, 1, 2):
        client.post("/events", json={"aggregate_id": agg, "sequence": s, "payload": {}})
    time.sleep(0.3)  # past partition window
    ev = client.get(f"/delivered/{agg}").json()["events"]
    seqs = [e.get("sequence") for e in ev]
    assert seqs == [0, 1, 2], f"after partition recovery: {seqs}"


def test_D_chaos__malformed_bodies_never_500(client: httpx.Client) -> None:
    for b in (
        {}, {"aggregate_id": "a"}, {"sequence": 0},
        {"aggregate_id": "a", "sequence": "x"}, {"aggregate_id": None, "sequence": 0},
    ):
        r = client.post("/events", json=b)
        assert r.status_code < 500, f"body={b} → {r.status_code}"
