"""Layer B — sum invariant after random swaps."""
from __future__ import annotations

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st


@settings(
    max_examples=8, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(swaps=st.lists(st.tuples(st.integers(0, 3), st.integers(0, 3)),
                      min_size=0, max_size=12))
def test_B_property__sum_invariant_under_swaps(
    client: httpx.Client, swaps: list,
) -> None:
    # Seed 4 counters with DISTINCT values so swaps produce real changes
    # when implemented correctly, and break the sum invariant when buggy.
    names = ["p0", "p1", "p2", "p3"]
    for idx, n in enumerate(names):
        client.post("/counters", json={"name": n, "value": 100 + idx * 7})
    total_before = client.get("/state").json()["total"]
    for i, j in swaps:
        if i == j:
            continue
        client.post("/swap", json={"a": names[i], "b": names[j]})
    total_after = client.get("/state").json()["total"]
    assert total_after == total_before, (
        f"sum broken: before={total_before} after={total_after}"
    )
