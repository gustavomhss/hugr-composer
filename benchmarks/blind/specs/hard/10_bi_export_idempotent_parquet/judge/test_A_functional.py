"""Layer A — export functional acceptance."""
from __future__ import annotations

import uuid

import httpx


def test_A_functional__health(client: httpx.Client) -> None:
    assert client.get("/health").status_code == 200


def test_A_functional__first_created_second_already_exists(
    client: httpx.Client,
) -> None:
    part = "2026-04-01"
    body = {"dataset": "orders", "partition": part}
    r1 = client.post("/exports", json=body)
    assert r1.status_code == 200, r1.text[:200]
    j1 = r1.json()
    assert j1["status"] == "created"
    assert j1["rows"] == 100
    assert j1["bytes"] == 6400
    r2 = client.post("/exports", json=body)
    assert r2.json()["status"] == "already_exists"
    assert r2.json()["export_id"] == j1["export_id"]


def test_A_functional__force_replaces(client: httpx.Client) -> None:
    part = "2026-04-02"
    client.post("/exports", json={"dataset": "users", "partition": part})
    r = client.post("/exports", json={"dataset": "users", "partition": part, "force": True})
    assert r.status_code == 200
    assert r.json()["status"] == "replaced"


def test_A_functional__invalid_dataset_400(client: httpx.Client) -> None:
    r = client.post("/exports", json={"dataset": "unknown", "partition": "2026-04-01"})
    assert r.status_code == 400


def test_A_functional__malformed_partition_400(client: httpx.Client) -> None:
    for p in ("2026-4-1", "yesterday", "", "2026/04/01"):
        r = client.post("/exports", json={"dataset": "orders", "partition": p})
        assert r.status_code == 400, f"partition {p!r} got {r.status_code}"


def test_A_functional__get_after_create(client: httpx.Client) -> None:
    part = "2026-04-03"
    client.post("/exports", json={"dataset": "events", "partition": part})
    r = client.get(f"/exports/events/{part}")
    assert r.status_code == 200
    assert r.json()["rows"] == 1000
