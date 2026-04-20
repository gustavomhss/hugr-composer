"""Layer B — property: bytes == rows * 64 for every export."""
from __future__ import annotations

import datetime as dt

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st


@settings(
    max_examples=8, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    dataset=st.sampled_from(["orders", "users", "events"]),
    day=st.integers(min_value=1, max_value=28),
    month=st.integers(min_value=1, max_value=12),
)
def test_B_property__bytes_equals_rows_times_64(
    client: httpx.Client, dataset: str, day: int, month: int,
) -> None:
    partition = dt.date(2026, month, day).isoformat()
    r = client.post("/exports", json={"dataset": dataset, "partition": partition})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["bytes"] == body["rows"] * 64, body
