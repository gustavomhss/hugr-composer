"""Layer C — class isolation under concurrent load."""
from __future__ import annotations

import threading
import time

import httpx


def test_C_concurrency__silver_flood_does_not_starve_gold(
    base_url: str, client: httpx.Client,
) -> None:
    time.sleep(1.1)

    # Start a silver flood that will exhaust silver budget.
    def silver_flood() -> None:
        with httpx.Client(base_url=base_url, timeout=5.0) as c:
            for _ in range(40):
                c.post("/call", json={}, headers={"X-Api-Key": "silver-1"})

    threads = [threading.Thread(target=silver_flood) for _ in range(3)]
    for t in threads:
        t.start()
    # Give the flood a head-start.
    time.sleep(0.05)
    # Gold keys must still get served (class isolation).
    ok = 0
    for _ in range(5):
        r = client.post("/call", json={}, headers={"X-Api-Key": "gold-1"})
        if r.status_code == 200:
            ok += 1
    for t in threads:
        t.join()
    assert ok >= 3, f"gold got starved by silver flood: only {ok}/5 succeeded"


def test_C_concurrency__parallel_bronze_only_one_200(base_url: str) -> None:
    time.sleep(1.1)
    codes: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        with httpx.Client(base_url=base_url, timeout=5.0) as c:
            r = c.post("/call", json={}, headers={"X-Api-Key": "bronze-1"})
            with lock:
                codes.append(r.status_code)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    count_200 = sum(1 for c in codes if c == 200)
    count_500 = sum(1 for c in codes if c >= 500)
    assert count_500 == 0, f"got 5xx: {codes}"
    assert count_200 == 1, f"bronze should get exactly 1 success in one window, got {count_200}"
