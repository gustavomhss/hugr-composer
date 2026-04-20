"""Layer D — tamper the chain and verify detection."""
from __future__ import annotations

import httpx


def test_D_chaos__tamper_detected(client: httpx.Client, admin_headers) -> None:
    # Ensure at least 3 entries exist.
    for i in range(3):
        client.put(f"/docs/tam-{i}", headers=admin_headers, json={"body": "x"})
    t = client.post("/audit/_test_tamper", headers=admin_headers, json={"at_index": 1})
    assert t.status_code in (200, 201, 204), t.text[:200]
    v = client.get("/audit/verify", headers=admin_headers)
    assert v.status_code == 200
    j = v.json()
    assert j.get("ok") is False
    assert "broken_index" in j


def test_D_chaos__non_admin_tamper_endpoint_403(
    client: httpx.Client, reader_headers,
) -> None:
    r = client.post(
        "/audit/_test_tamper", headers=reader_headers, json={"at_index": 0},
    )
    assert r.status_code == 403, f"reader tamper must 403, got {r.status_code}"
