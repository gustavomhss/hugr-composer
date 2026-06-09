"""Layer C — concurrency stress.

200 parallel transfers between 10 accounts. Conservation must hold and
no account may go negative. Agents without UnitOfWork + OptimisticConcurrency
typically fail one of:
  - lost update (sum drifts down)
  - phantom read (account goes negative)
  - 500 under contention
"""

from __future__ import annotations

import threading
import uuid

import httpx

ACCOUNTS = 10
INITIAL_CENTS = 10_000
PARALLELISM = 200
TRANSFER_CENTS = 50


def _open_and_fund(client: httpx.Client, n: int, fund_cents: int) -> list[str]:
    accs = []
    for _ in range(n):
        r = client.post("/accounts")
        assert r.status_code in (200, 201)
        j = r.json()
        aid = j.get("id") or j.get("account_id") or j.get("uuid")
        client.post(f"/accounts/{aid}/deposit", json={"amount_cents": fund_cents})
        accs.append(aid)
    return accs


def test_C_concurrency__200_parallel_transfers_preserve_sum_and_no_negative(
    client: httpx.Client,
    base_url: str,
) -> None:
    accs = _open_and_fund(client, ACCOUNTS, INITIAL_CENTS)
    total_pre = sum(
        int((client.get(f"/accounts/{a}").json() or {}).get("balance_cents", 0)) for a in accs
    )

    errors: list[str] = []
    http_5xx: list[int] = []
    lock = threading.Lock()

    # Share ONE pooled client across all workers, with a BOUNDED connection
    # count. 200 threads each opening their own socket (or a pool sized to
    # 200) slams 200 brand-new TCP connections onto a single uvicorn instance
    # at once — on macOS the kernel trips RST / EINVAL ("Connection reset by
    # peer" / "Invalid argument") and the sockets pile up in TIME_WAIT. That
    # is a transport-layer artifact of the load generator, NOT a defect in the
    # emitted server. Capping max_connections makes httpx *queue* the excess
    # requests on a bounded socket set: all 200 transfers still fly
    # concurrently and contend on the server's locks (the property under
    # test), we just don't open 200 sockets simultaneously.
    pool = httpx.Client(
        base_url=base_url,
        timeout=30.0,
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=50),
    )

    def worker(i: int) -> None:
        src = accs[i % ACCOUNTS]
        dst = accs[(i + 1) % ACCOUNTS]
        try:
            r = pool.post(
                "/transfers",
                json={
                    "source_account_id": src,
                    "destination_account_id": dst,
                    "amount_cents": TRANSFER_CENTS,
                    "idempotency_key": str(uuid.uuid4()),
                },
            )
            if r.status_code >= 500:
                with lock:
                    http_5xx.append(r.status_code)
        except httpx.HTTPError as exc:
            with lock:
                errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(PARALLELISM)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        pool.close()

    # Verify NO 5xx under contention (spec requirement).
    assert not http_5xx, f"server returned 5xx under load: {http_5xx[:5]}"
    assert not errors, f"httpx errors: {errors[:3]}"

    balances = [
        int((client.get(f"/accounts/{a}").json() or {}).get("balance_cents", 0)) for a in accs
    ]
    assert all(b >= 0 for b in balances), f"account went negative: {balances}"
    assert sum(balances) == total_pre, (
        f"conservation broken: pre={total_pre} post={sum(balances)} diff={sum(balances) - total_pre}"
    )


def test_C_concurrency__idempotency_key_replay_100x_single_effect(
    client: httpx.Client,
    base_url: str,
    open_account,
    deposit,
    balance,
) -> None:
    """Same idempotency_key replayed 100 times from parallel workers must
    produce exactly one debit and one credit.
    """
    src = open_account()
    dst = open_account()
    deposit(src, 100_000)

    key = str(uuid.uuid4())
    body = {
        "source_account_id": src,
        "destination_account_id": dst,
        "amount_cents": 10_000,
        "idempotency_key": key,
    }

    # Shared pooled client with a bounded socket count (see
    # _200_parallel_transfers above): all 100 replays fly concurrently and
    # contend on the idempotency lock, but httpx queues them over a small
    # socket set instead of opening 100 sockets at once.
    pool = httpx.Client(
        base_url=base_url,
        timeout=30.0,
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=50),
    )

    def worker() -> None:
        pool.post("/transfers", json=body)

    threads = [threading.Thread(target=worker) for _ in range(100)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        pool.close()

    assert balance(src) == 90_000, (
        f"source balance {balance(src)} ≠ 90,000 — replay caused multiple debits"
    )
    assert balance(dst) == 10_000, (
        f"dest balance {balance(dst)} ≠ 10,000 — replay caused multiple credits"
    )
