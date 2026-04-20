"""Layer B — property: events count == outbox entries count per order."""
from __future__ import annotations

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st


@settings(
    max_examples=8, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(n_items=st.integers(min_value=0, max_value=5))
def test_B_property__events_count_equals_outbox_count_per_order(
    client: httpx.Client, make_order, n_items: int,
) -> None:
    oid = make_order()
    for i in range(n_items):
        client.post(f"/orders/{oid}/items", json={"sku": f"S{i}", "quantity": 1})
    # Grab events.
    ev = client.get(f"/orders/{oid}/events").json()["events"]
    # Grab outbox (both pending + delivered — we do not drain here,
    # so pending equals all current outbox entries).
    ob = client.get("/outbox").json()["pending"]
    # Count outbox entries that reference this order.
    ob_for_order = [
        e for e in ob
        if (e.get("order_id") == oid or e.get("aggregate_id") == oid)
    ]
    assert len(ev) == len(ob_for_order), (
        f"events={len(ev)} outbox_for_order={len(ob_for_order)}"
    )
