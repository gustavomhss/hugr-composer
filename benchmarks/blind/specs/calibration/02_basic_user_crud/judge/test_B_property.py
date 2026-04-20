"""Layer B — property-based: roundtrip create→get."""
from __future__ import annotations

import uuid

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st


@settings(
    max_examples=15, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    display=st.text(
        alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
        min_size=1, max_size=40,
    ),
)
def test_B_property__create_then_get_roundtrip_preserves_display_name(
    client: httpx.Client, display: str,
) -> None:
    email = f"u-{uuid.uuid4().hex[:10]}@example.test"
    r = client.post("/users", json={"email": email, "display_name": display})
    assert r.status_code in (200, 201), r.text[:200]
    uid = r.json()["id"]
    g = client.get(f"/users/{uid}")
    assert g.status_code == 200
    assert g.json()["display_name"] == display
    assert g.json()["email"] == email
