"""Layer C — 200 concurrent register+exec never 500."""
from __future__ import annotations

import threading

import httpx


def test_C_concurrency__200_parallel_register_exec_no_5xx(
    client: httpx.Client, base_url: str,
) -> None:
    five_xx: list[int] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        with httpx.Client(base_url=base_url, timeout=10.0) as c:
            r = c.post("/queries/register", json={"name": "echo_vars", "depth_limit": 1})
            if r.status_code >= 500:
                with lock:
                    five_xx.append(r.status_code)
                return
            qid = r.json().get("query_id")
            if not qid:
                return
            r2 = c.post("/q", json={"query_id": qid, "variables": {"i": i}})
            if r2.status_code >= 500:
                with lock:
                    five_xx.append(r2.status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not five_xx, f"5xx under load: {five_xx[:5]}"
