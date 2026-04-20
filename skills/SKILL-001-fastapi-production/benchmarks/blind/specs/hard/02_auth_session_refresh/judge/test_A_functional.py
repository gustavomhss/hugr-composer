"""Layer A — functional acceptance for session refresh."""
from __future__ import annotations

import httpx


def test_A_functional__health(client: httpx.Client) -> None:
    assert client.get("/health").status_code == 200


def test_A_functional__login_then_whoami(client: httpx.Client, login) -> None:
    sess = login("alice")
    r = client.get("/whoami", headers={"Authorization": f"Bearer {sess['access_token']}"})
    assert r.status_code == 200, r.text[:200]
    assert r.json().get("username") == "alice"


def test_A_functional__refresh_issues_new_tokens(client: httpx.Client, login) -> None:
    sess = login()
    r = client.post("/refresh", json={"refresh_token": sess["refresh_token"]})
    assert r.status_code == 200, r.text[:200]
    new = r.json()
    assert new["access_token"] != sess["access_token"], "access token must rotate"
    assert new["refresh_token"] != sess["refresh_token"], "refresh token must rotate"
    # The new access token works.
    r2 = client.get("/whoami", headers={"Authorization": f"Bearer {new['access_token']}"})
    assert r2.status_code == 200


def test_A_functional__invalid_bearer_returns_401_not_500(client: httpx.Client) -> None:
    r = client.get("/whoami", headers={"Authorization": "Bearer totally-garbage"})
    assert r.status_code == 401, f"got {r.status_code}"
    r2 = client.get("/whoami")
    assert r2.status_code == 401


def test_A_functional__logout_revokes_family(client: httpx.Client, login) -> None:
    sess = login()
    r = client.post("/logout", json={"refresh_token": sess["refresh_token"]})
    assert r.status_code in (200, 204), r.text[:200]
    r2 = client.get("/whoami", headers={"Authorization": f"Bearer {sess['access_token']}"})
    assert r2.status_code == 401, f"after logout whoami must 401, got {r2.status_code}"


def test_A_functional__access_token_is_not_username(client: httpx.Client, login) -> None:
    sess = login("alice")
    tok = sess["access_token"]
    assert "alice" not in tok, "access token must be opaque, not encoded username"
    assert tok != sess["refresh_token"], "access and refresh tokens must differ"
    assert len(tok) >= 16, "access token too short to be opaque-random"
