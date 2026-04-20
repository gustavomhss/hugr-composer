"""Layer A — functional CRUD acceptance."""
from __future__ import annotations

import httpx


def test_A_functional__health_ok(client: httpx.Client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_A_functional__create_then_get_returns_same_record(
    client: httpx.Client, create_user,
) -> None:
    u = create_user(display="Alice")
    uid = u["id"]
    r = client.get(f"/users/{uid}")
    assert r.status_code == 200, r.text[:200]
    got = r.json()
    assert got["id"] == uid
    assert got["email"] == u["email"]
    assert got["display_name"] == "Alice"


def test_A_functional__get_unknown_user_404(client: httpx.Client) -> None:
    r = client.get("/users/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_A_functional__patch_updates_display_name_only(
    client: httpx.Client, create_user,
) -> None:
    u = create_user(display="Before")
    r = client.patch(f"/users/{u['id']}", json={"display_name": "After"})
    assert r.status_code in (200, 201), r.text[:200]
    body = r.json()
    assert body["display_name"] == "After"
    assert body["email"] == u["email"], "email must be unchanged by PATCH"


def test_A_functional__delete_then_get_404(
    client: httpx.Client, create_user,
) -> None:
    u = create_user()
    r = client.delete(f"/users/{u['id']}")
    assert r.status_code in (200, 204), r.text[:200]
    r2 = client.get(f"/users/{u['id']}")
    assert r2.status_code == 404


def test_A_functional__duplicate_email_returns_409(
    client: httpx.Client, create_user, fresh_email,
) -> None:
    email = fresh_email("dup")
    create_user(email=email)
    r = client.post("/users", json={"email": email, "display_name": "Other"})
    assert r.status_code == 409, f"expected 409 on duplicate email, got {r.status_code}"


def test_A_functional__malformed_email_rejected_4xx(
    client: httpx.Client,
) -> None:
    r = client.post("/users", json={"email": "not-an-email", "display_name": "X"})
    assert 400 <= r.status_code < 500, f"expected 4xx, got {r.status_code}"
    r2 = client.post("/users", json={"email": "", "display_name": "X"})
    assert 400 <= r2.status_code < 500, f"expected 4xx, got {r2.status_code}"


def test_A_functional__list_recent_first(
    client: httpx.Client, create_user,
) -> None:
    a = create_user(display="First")
    b = create_user(display="Second")
    r = client.get("/users")
    assert r.status_code == 200
    users = r.json().get("users", [])
    ids = [u["id"] for u in users]
    assert a["id"] in ids and b["id"] in ids
    # Second-created should appear before first-created.
    assert ids.index(b["id"]) < ids.index(a["id"]), f"ordering wrong: {ids}"
