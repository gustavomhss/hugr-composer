"""Layer B — property: replaying an OLD refresh token invalidates the family."""
from __future__ import annotations

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st


@settings(
    max_examples=8, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(chain_len=st.integers(min_value=1, max_value=4))
def test_B_property__old_refresh_token_replay_kills_family(
    client: httpx.Client, login, chain_len: int,
) -> None:
    """Rotate the refresh token chain_len times; then replay the ORIGINAL
    refresh token. The replay must 401, AND the latest-valid access
    token must also 401 because the family is now compromised.
    """
    sess = login()
    original_refresh = sess["refresh_token"]
    current = sess
    for _ in range(chain_len):
        r = client.post("/refresh", json={"refresh_token": current["refresh_token"]})
        assert r.status_code == 200, r.text[:200]
        current = r.json()

    # Latest access token works right before the replay.
    r_ok = client.get("/whoami", headers={"Authorization": f"Bearer {current['access_token']}"})
    assert r_ok.status_code == 200

    # Replay the ORIGINAL refresh token (now stale).
    r_replay = client.post("/refresh", json={"refresh_token": original_refresh})
    assert r_replay.status_code == 401, f"replay must 401, got {r_replay.status_code}"

    # Family is now compromised — latest access token must 401.
    r_post = client.get("/whoami", headers={"Authorization": f"Bearer {current['access_token']}"})
    assert r_post.status_code == 401, (
        f"after replay the family must be invalidated; whoami returned {r_post.status_code}"
    )
