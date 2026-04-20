"""Layer B — property: only registered hashes execute."""
from __future__ import annotations

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st


@settings(
    max_examples=10, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    qid=st.text(
        alphabet="0123456789abcdef", min_size=64, max_size=64,
    ),
)
def test_B_property__random_hex_hashes_always_400(
    client: httpx.Client, qid: str,
) -> None:
    r = client.post("/q", json={"query_id": qid, "variables": {}})
    assert r.status_code == 400, f"random qid {qid[:12]}... → {r.status_code}"
