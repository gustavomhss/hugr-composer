"""Layer D — malformed saga body → 4xx, never 500."""
from __future__ import annotations

import httpx


def test_D_chaos__malformed_body_never_500(client: httpx.Client) -> None:
    bodies = [
        {},
        {"user_id": "u"},
        {"user_id": "u", "flight": "x"},
        {"user_id": None, "flight": {}, "hotel": {}, "car": {}},
        {"user_id": "u", "flight": {"code": "F", "fail": "no"}, "hotel": {"code": "H", "fail": False}, "car": {"code": "C", "fail": False}},
    ]
    for b in bodies:
        r = client.post("/bookings", json=b)
        assert r.status_code < 500, f"500 on body={b!r}: {r.text[:200]}"
