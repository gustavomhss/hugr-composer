"""Layer C — 50 parallel always-fails sagas leave zero leftovers."""
from __future__ import annotations

import threading

import httpx


def test_C_concurrency__50_parallel_failing_sagas_no_leftovers(
    client: httpx.Client, base_url: str,
) -> None:
    five_xx: list[int] = []
    booking_ids: set[str] = set()
    lock = threading.Lock()

    def worker(i: int) -> None:
        with httpx.Client(base_url=base_url, timeout=10.0) as c:
            r = c.post("/bookings", json={
                "user_id": f"u-C-{i}",
                "flight": {"code": "F-C", "fail": False},
                "hotel":  {"code": "H-C", "fail": False},
                "car":    {"code": "C-C", "fail": True},    # car fails → both previous must compensate
            })
            if r.status_code >= 500:
                with lock:
                    five_xx.append(r.status_code)
                return
            try:
                bid = r.json().get("booking_id")
                if bid:
                    with lock:
                        booking_ids.add(bid)
            except Exception:
                pass

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not five_xx, f"5xx under load: {five_xx[:5]}"
    res = client.get("/reservations").json()
    # Count active reservations belonging to THIS storm only.
    leaked = 0
    for leg in ("flight", "hotel", "car"):
        for x in res.get(leg, []):
            if x.get("booking_id") in booking_ids and x.get("active"):
                leaked += 1
    assert leaked == 0, f"{leaked} leaked active reservations after 50 failing sagas"
