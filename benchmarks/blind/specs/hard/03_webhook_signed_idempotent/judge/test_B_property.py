"""Layer B — property: N duplicate deliveries never increment past 1."""
from __future__ import annotations

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st


@settings(
    max_examples=10, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(n=st.integers(min_value=1, max_value=15))
def test_B_property__n_sequential_duplicates_count_is_one(
    client: httpx.Client, make_event, n: int,
) -> None:
    raw, headers = make_event()
    for _ in range(n):
        r = client.post("/webhook", content=raw, headers=headers)
        assert r.status_code == 200
    # Count should always be 1 no matter how many duplicates.
    j = r.json()
    assert j.get("count") == 1, f"{n} duplicates -> count={j.get('count')}"
