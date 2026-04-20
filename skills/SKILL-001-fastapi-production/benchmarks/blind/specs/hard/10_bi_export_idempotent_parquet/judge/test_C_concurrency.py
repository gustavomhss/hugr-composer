"""Layer C — 50 concurrent exports of same pair → 1 created, 49 already_exists."""
from __future__ import annotations

import threading

import httpx


def test_C_concurrency__50_parallel_same_pair_one_create(
    client: httpx.Client, base_url: str,
) -> None:
    pair = {"dataset": "events", "partition": "2026-05-10"}
    created = 0
    lock = threading.Lock()
    five_xx = []

    def worker() -> None:
        nonlocal created
        with httpx.Client(base_url=base_url, timeout=10.0) as c:
            r = c.post("/exports", json=pair)
            if r.status_code >= 500:
                with lock:
                    five_xx.append(r.status_code)
                return
            if r.json().get("status") == "created":
                with lock:
                    created += 1

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not five_xx, f"5xx: {five_xx[:5]}"
    assert created == 1, f"expected 1 created, got {created}"
