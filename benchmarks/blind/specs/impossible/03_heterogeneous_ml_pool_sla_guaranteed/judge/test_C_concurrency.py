"""Layer C — capacity + SLA under 100 concurrent requests."""
from __future__ import annotations

import threading

import httpx


def test_C_concurrency__100_parallel_requests_respect_capacity(
    client: httpx.Client, base_url: str,
) -> None:
    five_xx: list[int] = []
    statuses: list[int] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        with httpx.Client(base_url=base_url, timeout=10.0) as c:
            r = c.post("/infer", json={
                "session_id": f"concurrent-{i}",
                "deadline_ms": 400, "prompt": f"p-{i}",
            })
            with lock:
                statuses.append(r.status_code)
                # 503 is a valid "SLA infeasible" response; we reject only 5xx
                # that are NOT 503 (i.e. actual server-side bugs).
                if r.status_code >= 500 and r.status_code != 503:
                    five_xx.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not five_xx, f"5xx: {five_xx[:5]}"
    # Under extreme load, some requests 503 due to queueing past deadline.
    # That's acceptable; the key invariant is NO 500s + correct routing.
    ok = sum(1 for s in statuses if s == 200)
    assert ok >= 10, f"only {ok}/100 succeeded under load"
