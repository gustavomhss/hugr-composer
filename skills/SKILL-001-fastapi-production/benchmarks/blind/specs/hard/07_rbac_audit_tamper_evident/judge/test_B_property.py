"""Layer B — every PUT by any authorized user leaves exactly one audit event."""
from __future__ import annotations

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st


@settings(
    max_examples=8, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(n_updates=st.integers(min_value=1, max_value=5))
def test_B_property__audit_grows_by_exactly_n_after_n_admin_puts(
    client: httpx.Client, admin_headers, n_updates: int,
) -> None:
    before = len(client.get("/audit", headers=admin_headers).json()["events"])
    for i in range(n_updates):
        client.put(f"/docs/p-{i}-{n_updates}", headers=admin_headers, json={"body": "x"})
    after = len(client.get("/audit", headers=admin_headers).json()["events"])
    assert after - before == n_updates, (
        f"expected {n_updates} new events, got {after - before}"
    )
