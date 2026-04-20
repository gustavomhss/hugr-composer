"""Layer C — 50 parallel PUTs produce 50 audit events + intact chain."""
from __future__ import annotations

import threading

import httpx


def test_C_concurrency__50_parallel_puts_yield_intact_chain(
    client: httpx.Client, base_url: str, admin_headers,
) -> None:
    before = len(client.get("/audit", headers=admin_headers).json()["events"])
    five_xx: list[int] = []

    def worker(i: int) -> None:
        with httpx.Client(base_url=base_url, timeout=10.0) as c:
            r = c.put(
                f"/docs/c-{i}", headers=admin_headers, json={"body": f"v{i}"},
            )
            if r.status_code >= 500:
                five_xx.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not five_xx, f"5xx under load: {five_xx[:5]}"
    after = len(client.get("/audit", headers=admin_headers).json()["events"])
    assert after - before == 50, f"{after - before} new audit events from 50 puts"
    v = client.get("/audit/verify", headers=admin_headers)
    assert v.json()["ok"] is True, "chain broke under concurrent PUTs"
