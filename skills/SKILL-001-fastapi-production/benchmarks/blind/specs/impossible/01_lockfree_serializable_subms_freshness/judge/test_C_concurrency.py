"""Layer C — invariant under 200 concurrent swaps + incrs."""
from __future__ import annotations

import random
import threading

import httpx


def test_C_concurrency__200_concurrent_swaps_incr_sum_invariant(
    client: httpx.Client, base_url: str,
) -> None:
    names = [f"c{i}" for i in range(10)]
    for n in names:
        client.post("/counters", json={"name": n, "value": 100})
    total_pre = client.get("/state").json()["total"]
    deltas_sum = 0
    five_xx: list[int] = []
    lock = threading.Lock()

    def swap_worker() -> None:
        with httpx.Client(base_url=base_url, timeout=15.0) as c:
            for _ in range(5):
                a, b = random.sample(names, 2)
                r = c.post("/swap", json={"a": a, "b": b})
                if r.status_code >= 500:
                    with lock:
                        five_xx.append(r.status_code)

    def incr_worker() -> None:
        nonlocal deltas_sum
        with httpx.Client(base_url=base_url, timeout=15.0) as c:
            for _ in range(5):
                n = random.choice(names)
                d = random.randint(-3, 5)
                r = c.post("/incr", json={"name": n, "delta": d})
                if r.status_code >= 500:
                    with lock:
                        five_xx.append(r.status_code)
                else:
                    with lock:
                        deltas_sum += d

    swap_threads = [threading.Thread(target=swap_worker) for _ in range(20)]
    incr_threads = [threading.Thread(target=incr_worker) for _ in range(20)]
    for t in swap_threads + incr_threads:
        t.start()
    for t in swap_threads + incr_threads:
        t.join()
    assert not five_xx, f"5xx: {five_xx[:5]}"
    total_post = client.get("/state").json()["total"]
    assert total_post == total_pre + deltas_sum, (
        f"invariant broken: pre={total_pre} delta_sum={deltas_sum} post={total_post}"
    )
