"""Layer A — saga functional acceptance."""
from __future__ import annotations

import httpx


def test_A_functional__health(client: httpx.Client) -> None:
    assert client.get("/health").status_code == 200


def test_A_functional__happy_path_201(client: httpx.Client, book_body) -> None:
    r = client.post("/bookings", json=book_body())
    assert r.status_code == 201, r.text[:200]
    data = r.json()
    assert data["status"] == "confirmed"
    assert data["legs"] == {"flight": "ok", "hotel": "ok", "car": "ok"}


def test_A_functional__hotel_fails_flight_rolled_back(
    client: httpx.Client, book_body,
) -> None:
    r = client.post("/bookings", json=book_body(hotel_fail=True))
    assert r.status_code == 422, r.text[:200]
    data = r.json()
    assert data["status"] == "compensated"
    assert data["failed_leg"] == "hotel"
    assert "flight" in data["compensated_legs"]
    # Verify THIS booking's flight reservation is inactive.
    bid = data["booking_id"]
    res = client.get("/reservations").json()
    for r_ in res.get("flight", []):
        if r_.get("booking_id") == bid:
            assert not r_.get("active"), f"flight leg of {bid} still active: {r_}"


def test_A_functional__car_fails_both_prev_rolled_back(
    client: httpx.Client, book_body,
) -> None:
    r = client.post("/bookings", json=book_body(car_fail=True))
    assert r.status_code == 422
    data = r.json()
    bid = data["booking_id"]
    assert set(data["compensated_legs"]) >= {"flight", "hotel"}
    res = client.get("/reservations").json()
    for leg_name in ("flight", "hotel"):
        for r_ in res.get(leg_name, []):
            if r_.get("booking_id") == bid:
                assert not r_.get("active"), (
                    f"{leg_name} leg of {bid} still active after rollback: {r_}"
                )
