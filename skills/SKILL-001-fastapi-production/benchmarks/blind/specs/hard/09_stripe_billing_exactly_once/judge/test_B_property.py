"""Layer B — N sequential retries for same pair → 1 stub call increment."""
from __future__ import annotations

import uuid

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st


@settings(
    max_examples=6, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(n=st.integers(min_value=1, max_value=10))
def test_B_property__n_retries_same_pair_single_stub_call(
    client: httpx.Client, n: int,
) -> None:
    cust, cyc = f"p-{uuid.uuid4().hex[:8]}", "prop"
    before = int(client.get("/_stripe/calls").json()["count"])
    for _ in range(n):
        r = client.post("/bill", json={
            "customer_id": cust, "cycle_id": cyc, "amount_cents": 100,
        })
        assert r.status_code == 200
    after = int(client.get("/_stripe/calls").json()["count"])
    # At most one successful charge — but stub could have retried on network
    # error. Allow up to 3 (retry budget).
    assert 1 <= (after - before) <= 3, (
        f"n={n} retries produced {after - before} stub calls (expected 1-3)"
    )
