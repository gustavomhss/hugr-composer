"""Judge fixtures for the financial-ledger spec.

The base URL of the emitted app is provided via `BLIND_BASE_URL` env.
Every test layer in this directory uses `client()` → httpx.Client
pointed at the emitted app.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import httpx
import pytest


def _base_url() -> str:
    url = os.environ.get("BLIND_BASE_URL", "").rstrip("/")
    if not url:
        pytest.skip("BLIND_BASE_URL not set — judge invoked without boot")
    return url


@pytest.fixture(scope="session")
def base_url() -> str:
    return _base_url()


@pytest.fixture()
def client(base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=base_url, timeout=10.0) as c:
        yield c


@pytest.fixture()
def open_account(client: httpx.Client):
    def _open() -> str:
        r = client.post("/accounts")
        assert r.status_code in (200, 201), f"open_account failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        return data.get("id") or data.get("account_id") or data.get("uuid")
    return _open


@pytest.fixture()
def deposit(client: httpx.Client):
    def _deposit(account_id: str, cents: int) -> dict:
        r = client.post(f"/accounts/{account_id}/deposit", json={"amount_cents": cents})
        assert r.status_code in (200, 201), f"deposit failed: {r.status_code} {r.text[:200]}"
        return r.json()
    return _deposit


@pytest.fixture()
def balance(client: httpx.Client):
    def _balance(account_id: str) -> int:
        r = client.get(f"/accounts/{account_id}")
        assert r.status_code == 200, f"GET balance failed: {r.status_code}"
        data = r.json()
        return int(data.get("balance_cents") or data.get("balance") or 0)
    return _balance
