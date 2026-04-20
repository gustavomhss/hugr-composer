"""Layer B — property: at most one leg fails, but in every case the
active-reservations invariant holds."""
from __future__ import annotations

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st


@settings(
    max_examples=12, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    flight_fail=st.booleans(),
    hotel_fail=st.booleans(),
    car_fail=st.booleans(),
)
def test_B_property__reservation_invariant_holds_after_any_outcome(
    client: httpx.Client, flight_fail: bool, hotel_fail: bool, car_fail: bool,
) -> None:
    body = {
        "user_id": "u_prop",
        "flight": {"code": "F1", "fail": flight_fail},
        "hotel":  {"code": "H1", "fail": hotel_fail},
        "car":    {"code": "C1", "fail": car_fail},
    }
    r = client.post("/bookings", json=body)
    assert r.status_code in (201, 422), f"unexpected {r.status_code}: {r.text[:200]}"
    data = r.json()
    if any((flight_fail, hotel_fail, car_fail)):
        assert r.status_code == 422
        assert data["status"] == "compensated"
    else:
        assert r.status_code == 201
        assert data["status"] == "confirmed"
