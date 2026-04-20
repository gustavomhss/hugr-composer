"""Layer C — concurrency: 200 parallel duplicate deliveries → count==1."""
from __future__ import annotations

import threading

import httpx


def test_C_concurrency__200_parallel_duplicates_count_equals_one(
    client: httpx.Client, base_url: str, make_event,
) -> None:
    raw, headers = make_event()
    five_xx: list[int] = []

    def worker() -> None:
        with httpx.Client(base_url=base_url, timeout=10.0) as c:
            r = c.post("/webhook", content=raw, headers=headers)
            if r.status_code >= 500:
                five_xx.append(r.status_code)

    threads = [threading.Thread(target=worker) for _ in range(200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not five_xx, f"5xx under load: {five_xx[:5]}"
    # After the storm, count must be exactly 1.
    body = client.get(f"/events/{__event_id_from_raw(raw)}")
    assert body.status_code == 200
    assert body.json().get("count") == 1, f"count: {body.json()}"


def __event_id_from_raw(raw: bytes) -> str:
    import json
    return json.loads(raw)["event_id"]
