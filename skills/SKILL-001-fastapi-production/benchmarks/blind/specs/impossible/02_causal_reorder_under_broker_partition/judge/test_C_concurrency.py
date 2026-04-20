"""Layer C — 100 interleaved events across 20 aggregates, causal order held."""
from __future__ import annotations

import random
import threading
import time
import uuid

import httpx


def test_C_concurrency__interleaved_events_causal_order_per_aggregate(
    client: httpx.Client, base_url: str,
) -> None:
    aggs = [f"Z-{uuid.uuid4().hex[:6]}-{i}" for i in range(20)]
    events: list[tuple[str, int]] = []
    for agg in aggs:
        for s in range(5):
            events.append((agg, s))
    random.shuffle(events)

    five_xx: list[int] = []
    lock = threading.Lock()

    def worker(batch: list[tuple[str, int]]) -> None:
        with httpx.Client(base_url=base_url, timeout=10.0) as c:
            for agg, s in batch:
                r = c.post("/events", json={"aggregate_id": agg, "sequence": s, "payload": {}})
                if r.status_code >= 500:
                    with lock:
                        five_xx.append(r.status_code)

    chunks = [events[i::10] for i in range(10)]
    threads = [threading.Thread(target=worker, args=(c,)) for c in chunks]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not five_xx, f"5xx: {five_xx[:5]}"
    time.sleep(0.6)
    for agg in aggs:
        ev = client.get(f"/delivered/{agg}").json()["events"]
        seqs = [e.get("sequence") for e in ev]
        assert seqs == sorted(seqs), f"agg {agg}: not sorted {seqs}"
