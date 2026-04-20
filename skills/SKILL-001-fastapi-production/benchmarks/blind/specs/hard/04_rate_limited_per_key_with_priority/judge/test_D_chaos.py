"""Layer D — 401s don't consume budget; malformed headers → 401 not 500."""
from __future__ import annotations

import time

import httpx


def test_D_chaos__unknown_key_does_not_consume_budget(client: httpx.Client) -> None:
    time.sleep(1.1)
    # Burn a lot of 401s.
    for _ in range(20):
        r = client.post("/call", json={}, headers={"X-Api-Key": "nope-nope"})
        assert r.status_code == 401
    # Now bronze-1 should still get a fresh 200 in this (assumed-same) window.
    r = client.post("/call", json={}, headers={"X-Api-Key": "bronze-1"})
    assert r.status_code == 200, f"bronze budget was eaten by 401s: {r.status_code}"


def test_D_chaos__missing_key_header_returns_4xx_not_500(client: httpx.Client) -> None:
    r = client.post("/call", json={})
    assert 400 <= r.status_code < 500, f"missing key → {r.status_code}"
