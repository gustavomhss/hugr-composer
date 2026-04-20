"""Layer D — malformed bodies never 500."""
from __future__ import annotations

import httpx


def test_D_chaos__malformed_q_body_never_500(client: httpx.Client) -> None:
    for body in (
        {}, {"variables": {}}, {"query_id": 123},
        {"query_id": "x"}, {"query_id": "z" * 64},
    ):
        r = client.post("/q", json=body)
        assert r.status_code < 500, f"body={body} → {r.status_code}"


def test_D_chaos__register_malformed_never_500(client: httpx.Client) -> None:
    for body in (
        {}, {"name": "list_users"}, {"depth_limit": 1},
        {"name": 123, "depth_limit": 1}, {"name": "unknown_query", "depth_limit": 1},
    ):
        r = client.post("/queries/register", json=body)
        assert r.status_code < 500, f"body={body} → {r.status_code}"
