"""Layer B — property-based: repeated calls are deterministic + idempotent."""
from __future__ import annotations

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st


@settings(
    max_examples=20, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(path=st.sampled_from(["/health", "/version", "/ready"]))
def test_B_property__endpoints_are_idempotent(
    client: httpx.Client, path: str,
) -> None:
    r1 = client.get(path)
    r2 = client.get(path)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json(), f"{path}: body changed between calls"
