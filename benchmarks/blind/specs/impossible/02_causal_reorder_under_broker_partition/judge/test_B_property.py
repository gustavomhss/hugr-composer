"""Layer B — property: within an aggregate, delivered seqs are sorted."""
from __future__ import annotations

import random
import time
import uuid

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st


@settings(
    max_examples=5, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(n=st.integers(min_value=3, max_value=8))
def test_B_property__delivered_per_aggregate_is_sorted(
    client: httpx.Client, n: int,
) -> None:
    agg = f"P-{uuid.uuid4().hex[:6]}"
    seqs = list(range(n))
    random.shuffle(seqs)
    for s in seqs:
        client.post("/events", json={"aggregate_id": agg, "sequence": s, "payload": {}})
    time.sleep(0.4)
    ev = client.get(f"/delivered/{agg}").json()["events"]
    delivered = [e.get("sequence") for e in ev]
    assert delivered == sorted(delivered), (
        f"delivered not sorted: {delivered}"
    )
