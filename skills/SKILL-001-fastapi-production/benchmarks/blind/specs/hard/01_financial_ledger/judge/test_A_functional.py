"""Layer A — functional smoke against the emitted app.

Every Acceptance-criterion bullet maps to at least one test here.
Test IDs follow the convention: `test_A_functional__<descriptor>`.
"""
from __future__ import annotations

import uuid

import httpx


def test_A_functional__health_endpoint(client: httpx.Client) -> None:
    r = client.get("/health")
    assert r.status_code == 200


def test_A_functional__open_account_returns_id_and_zero_balance(
    client: httpx.Client, open_account, balance,
) -> None:
    acc = open_account()
    assert isinstance(acc, str) and len(acc) > 0
    assert balance(acc) == 0


def test_A_functional__deposit_increases_balance_exact_cents(
    open_account, deposit, balance,
) -> None:
    a = open_account()
    deposit(a, 12_345)
    deposit(a, 67)
    assert balance(a) == 12_345 + 67


def test_A_functional__transfer_moves_funds_atomically(
    client: httpx.Client, open_account, deposit, balance,
) -> None:
    src = open_account()
    dst = open_account()
    deposit(src, 100_000)
    r = client.post("/transfers", json={
        "source_account_id": src,
        "destination_account_id": dst,
        "amount_cents": 40_000,
        "idempotency_key": str(uuid.uuid4()),
    })
    assert r.status_code in (200, 201), r.text[:200]
    assert balance(src) == 60_000
    assert balance(dst) == 40_000


def test_A_functional__withdraw_beyond_balance_refused_4xx(
    client: httpx.Client, open_account, deposit, balance,
) -> None:
    a = open_account()
    deposit(a, 100)
    r = client.post(f"/accounts/{a}/withdraw", json={"amount_cents": 500})
    assert 400 <= r.status_code < 500, f"expected 4xx, got {r.status_code}"
    assert balance(a) == 100
