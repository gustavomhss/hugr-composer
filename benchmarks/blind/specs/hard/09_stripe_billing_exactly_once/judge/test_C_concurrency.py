"""Layer C — 50 concurrent /bill for same pair → exactly one charge."""
from __future__ import annotations

import threading
import uuid

import httpx


def test_C_concurrency__50_parallel_same_pair_one_charge(
    client: httpx.Client, base_url: str,
) -> None:
    cust, cyc = f"cc-{uuid.uuid4().hex[:8]}", "storm"
    body = {"customer_id": cust, "cycle_id": cyc, "amount_cents": 777}
    results: list[dict] = []
    lock = threading.Lock()
    five_xx: list[int] = []

    def worker() -> None:
        with httpx.Client(base_url=base_url, timeout=15.0) as c:
            r = c.post("/bill", json=body)
            if r.status_code >= 500:
                with lock:
                    five_xx.append(r.status_code)
                return
            with lock:
                results.append(r.json())

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not five_xx, f"5xx under load: {five_xx[:5]}"
    # How many "charged" vs "already_charged"?
    charged = sum(1 for x in results if x.get("status") == "charged")
    assert charged == 1, f"expected exactly 1 charged response, got {charged}"
    # /charges must have exactly 1 entry for this pair.
    all_charges = client.get("/charges").json()["charges"]
    matches = [c for c in all_charges if c.get("customer_id") == cust and c.get("cycle_id") == cyc]
    assert len(matches) == 1, f"/charges has {len(matches)} entries for this pair"


def test_C_concurrency__50_parallel_distinct_pairs_50_charges(
    client: httpx.Client, base_url: str,
) -> None:
    base_tag = uuid.uuid4().hex[:8]
    five_xx: list[int] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        with httpx.Client(base_url=base_url, timeout=15.0) as c:
            r = c.post("/bill", json={
                "customer_id": f"cust-{base_tag}-{i}",
                "cycle_id": "batch",
                "amount_cents": 100,
            })
            if r.status_code >= 500:
                with lock:
                    five_xx.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not five_xx, f"5xx: {five_xx[:5]}"
    all_charges = client.get("/charges").json()["charges"]
    distinct = {
        (c.get("customer_id"), c.get("cycle_id"))
        for c in all_charges
        if c.get("customer_id", "").startswith(f"cust-{base_tag}-")
    }
    assert len(distinct) == 50, f"expected 50 distinct charges, got {len(distinct)}"
