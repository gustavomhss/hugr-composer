"""Layer A — functional acceptance."""
from __future__ import annotations

import time

import httpx


def test_A_functional__health(client: httpx.Client) -> None:
    assert client.get("/health").status_code == 200


def test_A_functional__known_key_gets_200(client: httpx.Client) -> None:
    time.sleep(1.1)  # fresh window
    r = client.post("/call", json={}, headers={"X-Api-Key": "gold-1"})
    assert r.status_code == 200, r.text[:200]
    assert r.json().get("class") == "gold"
    assert r.headers.get("X-RateLimit-Class", "").lower() == "gold"


def test_A_functional__unknown_key_returns_401(client: httpx.Client) -> None:
    r = client.post("/call", json={}, headers={"X-Api-Key": "nope"})
    assert r.status_code == 401


def test_A_functional__bronze_second_call_is_429(client: httpx.Client) -> None:
    time.sleep(1.1)
    r1 = client.post("/call", json={}, headers={"X-Api-Key": "bronze-1"})
    assert r1.status_code == 200, r1.text[:200]
    r2 = client.post("/call", json={}, headers={"X-Api-Key": "bronze-1"})
    assert r2.status_code == 429, f"second bronze call should 429, got {r2.status_code}"
    assert "retry_after_ms" in r2.json()


def test_A_functional__silver_sixth_call_is_429(client: httpx.Client) -> None:
    time.sleep(1.1)
    codes = []
    for _ in range(6):
        r = client.post("/call", json={}, headers={"X-Api-Key": "silver-1"})
        codes.append(r.status_code)
    assert codes[:5] == [200] * 5, f"first 5 silver must be 200, got {codes}"
    assert codes[5] == 429, f"6th silver must be 429, got {codes}"
