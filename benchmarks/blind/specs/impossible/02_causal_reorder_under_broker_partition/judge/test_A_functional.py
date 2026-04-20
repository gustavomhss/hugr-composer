"""Layer A — causal reorder functional."""
from __future__ import annotations

import time
import uuid

import httpx


def _send(client, agg, seq):
    return client.post("/events", json={
        "aggregate_id": agg, "sequence": seq, "payload": {"i": seq},
    })


def test_A_functional__health(client: httpx.Client) -> None:
    assert client.get("/health").status_code == 200


def test_A_functional__in_order_delivery(client: httpx.Client) -> None:
    agg = f"A-{uuid.uuid4().hex[:6]}"
    for i in (0, 1, 2):
        assert _send(client, agg, i).status_code in (200, 202)
    time.sleep(0.1)
    ev = client.get(f"/delivered/{agg}").json()["events"]
    seqs = [e.get("sequence") for e in ev]
    assert seqs == [0, 1, 2], f"expected [0,1,2] got {seqs}"


def test_A_functional__reverse_order_buffered_then_delivered(
    client: httpx.Client,
) -> None:
    agg = f"B-{uuid.uuid4().hex[:6]}"
    for i in (5, 4, 3, 2, 1, 0):
        _send(client, agg, i)
    time.sleep(0.2)
    ev = client.get(f"/delivered/{agg}").json()["events"]
    seqs = [e.get("sequence") for e in ev]
    assert seqs == [0, 1, 2, 3, 4, 5], f"expected sorted; got {seqs}"


def test_A_functional__gap_detected_after_timeout(client: httpx.Client) -> None:
    agg = f"G-{uuid.uuid4().hex[:6]}"
    _send(client, agg, 0)
    _send(client, agg, 2)
    time.sleep(0.8)  # longer than 500ms gap timeout
    gaps = client.get(f"/gaps/{agg}").json()["gaps"]
    assert 1 in gaps, f"expected gap at 1, got gaps={gaps}"
    ev = client.get(f"/delivered/{agg}").json()["events"]
    seqs = [e.get("sequence") for e in ev]
    # 0 and 2 should be present.
    assert 0 in seqs and 2 in seqs, f"delivered seqs: {seqs}"
