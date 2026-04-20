"""Layer A — persisted-queries functional."""
from __future__ import annotations

import hashlib
import json

import httpx


def test_A_functional__health(client: httpx.Client) -> None:
    assert client.get("/health").status_code == 200


def test_A_functional__register_then_exec(client: httpx.Client, register) -> None:
    reg = register("list_users", 2)
    assert reg["status"] == 200, reg
    qid = reg["body"]["query_id"]
    r = client.post("/q", json={"query_id": qid, "variables": {}})
    assert r.status_code == 200
    users = r.json()["data"]["users"]
    assert len(users) == 2


def test_A_functional__deterministic_query_id(client: httpx.Client, register) -> None:
    a = register("list_users", 1)["body"]["query_id"]
    b = register("list_users", 1)["body"]["query_id"]
    assert a == b, "same registration must yield same query_id"
    expected = hashlib.sha256(
        json.dumps({"name": "list_users", "depth_limit": 1}, sort_keys=True).encode()
    ).hexdigest()
    assert a == expected


def test_A_functional__raw_name_rejected(client: httpx.Client) -> None:
    r = client.post("/q", json={"name": "list_users", "variables": {}})
    assert r.status_code == 400, f"raw-name must 400, got {r.status_code}"


def test_A_functional__unknown_query_id_400(client: httpx.Client) -> None:
    r = client.post("/q", json={"query_id": "ab" * 32, "variables": {}})
    assert r.status_code == 400
    assert r.json().get("error") == "unknown query"


def test_A_functional__depth_limit_exceeded_rejected_at_register(
    client: httpx.Client, register,
) -> None:
    reg = register("deep_nested", 10)
    assert reg["status"] == 400, f"depth 10 registration should 400, got {reg}"
