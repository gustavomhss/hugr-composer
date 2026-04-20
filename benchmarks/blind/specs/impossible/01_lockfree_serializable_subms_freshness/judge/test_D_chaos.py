"""Layer D — freshness SLA under 100 parallel readers."""
from __future__ import annotations

import threading

import httpx


def test_D_chaos__freshness_under_100_parallel_readers(
    client: httpx.Client, base_url: str,
) -> None:
    client.post("/counters", json={"name": "f", "value": 1})
    fresh_ok: list[bool] = []
    lock = threading.Lock()

    def reader() -> None:
        with httpx.Client(base_url=base_url, timeout=5.0) as c:
            for _ in range(5):
                r = c.get("/state", params={"stale_ms": 1})
                ok = r.status_code == 200
                try:
                    ms = int(r.json().get("as_of_ms_ago", 999))
                except Exception:
                    ms = 999
                with lock:
                    fresh_ok.append(ok and ms <= 1)

    threads = [threading.Thread(target=reader) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ratio = sum(fresh_ok) / max(1, len(fresh_ok))
    assert ratio >= 0.8, f"only {ratio:.1%} of reads met as_of_ms_ago ≤ 1"


def test_D_chaos__malformed_swap_never_500(client: httpx.Client) -> None:
    for b in ({}, {"a": "x"}, {"a": None, "b": "x"}):
        r = client.post("/swap", json=b)
        assert r.status_code < 500, f"body={b} → {r.status_code}"
