"""Layer A — RBAC functional acceptance."""
from __future__ import annotations

import uuid

import httpx


def test_A_functional__health(client: httpx.Client) -> None:
    assert client.get("/health").status_code == 200


def test_A_functional__admin_put_then_get(client: httpx.Client, admin_headers) -> None:
    did = f"doc-{uuid.uuid4().hex[:8]}"
    r = client.put(f"/docs/{did}", headers=admin_headers, json={"body": "hello"})
    assert r.status_code == 200, r.text[:200]
    g = client.get(f"/docs/{did}", headers=admin_headers)
    assert g.status_code == 200 and g.json()["body"] == "hello"


def test_A_functional__reader_put_403(client: httpx.Client, reader_headers) -> None:
    r = client.put("/docs/x", headers=reader_headers, json={"body": "nope"})
    assert r.status_code == 403, f"reader PUT must 403, got {r.status_code}"


def test_A_functional__missing_user_header_401(client: httpx.Client) -> None:
    r = client.get("/docs/whatever")
    assert r.status_code == 401, f"missing X-User must 401, got {r.status_code}"


def test_A_functional__unknown_user_401(client: httpx.Client) -> None:
    r = client.get("/docs/whatever", headers={"X-User": "mallory"})
    assert r.status_code == 401


def test_A_functional__reader_cannot_view_audit_403(
    client: httpx.Client, reader_headers,
) -> None:
    r = client.get("/audit", headers=reader_headers)
    assert r.status_code == 403, f"reader /audit must 403, got {r.status_code}"


def test_A_functional__admin_audit_chain_integrity(
    client: httpx.Client, admin_headers,
) -> None:
    for i in range(5):
        client.put(f"/docs/chain-{i}", headers=admin_headers, json={"body": f"v{i}"})
    ev = client.get("/audit", headers=admin_headers)
    assert ev.status_code == 200
    events = ev.json()["events"]
    assert len(events) >= 5
    v = client.get("/audit/verify", headers=admin_headers)
    assert v.status_code == 200
    assert v.json()["ok"] is True, v.text[:200]
