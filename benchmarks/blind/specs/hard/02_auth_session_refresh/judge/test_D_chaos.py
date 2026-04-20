"""Layer D — chaos: random-garbage bearers + mixed malformed bodies."""
from __future__ import annotations

import os

import httpx


def test_D_chaos__random_garbage_bearers_never_500(client: httpx.Client) -> None:
    junk = [
        "", "Bearer", "Bearer " + "A" * 5000,
        "Bearer %00", "Basic user:pass", "Bearer ../../etc/passwd",
    ]
    for token in junk:
        try:
            r = client.get("/whoami", headers={"Authorization": token})
        except httpx.LocalProtocolError:
            # httpx rejects some malformed header values before send — fine.
            continue
        assert r.status_code < 500, f"500 on auth header {token!r}: {r.text[:200]}"
    # Random high-entropy garbage.
    for _ in range(10):
        garbage = "Bearer " + os.urandom(32).hex()
        r = client.get("/whoami", headers={"Authorization": garbage})
        assert r.status_code == 401, f"random garbage must 401, got {r.status_code}"


def test_D_chaos__malformed_refresh_body_returns_4xx(client: httpx.Client) -> None:
    bodies = [
        {}, {"refresh_token": None}, {"refresh_token": ""},
        {"refresh_token": "xyz"}, {"wrong_field": "abc"},
    ]
    for b in bodies:
        r = client.post("/refresh", json=b)
        assert 400 <= r.status_code < 500, f"body={b!r} got {r.status_code}"
