"""Layer C — 100 concurrent create calls: 100 unique ids + 100 outbox entries."""
from __future__ import annotations

import threading

import httpx


def test_C_concurrency__100_parallel_creates_no_lost_events(
    client: httpx.Client, base_url: str,
) -> None:
    ids: set[str] = set()
    five_xx: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        with httpx.Client(base_url=base_url, timeout=10.0) as c:
            r = c.post("/orders", json={"customer_id": "load"})
            if r.status_code >= 500:
                with lock:
                    five_xx.append(r.status_code)
                return
            oid = r.json()["order_id"]
            with lock:
                ids.add(oid)

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not five_xx, f"5xx under load: {five_xx[:5]}"
    assert len(ids) == 100, f"{len(ids)} unique order_ids from 100 parallel creates"
    # Drain & count: exactly 100 OrderCreated entries must exist.
    ob = client.get("/outbox").json()["pending"]
    created = [
        e for e in ob
        if (e.get("type") or e.get("event_type")) == "OrderCreated"
        and (e.get("order_id") in ids or e.get("aggregate_id") in ids)
    ]
    assert len(created) == 100, (
        f"expected 100 OrderCreated in outbox, got {len(created)}"
    )
