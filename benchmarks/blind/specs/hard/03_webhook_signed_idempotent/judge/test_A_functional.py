"""Layer A — functional acceptance for signed webhook."""
from __future__ import annotations

import json
import uuid

import httpx


def test_A_functional__health(client: httpx.Client) -> None:
    assert client.get("/health").status_code == 200


def test_A_functional__valid_signed_accepted(client: httpx.Client, make_event) -> None:
    raw, headers = make_event()
    r = client.post("/webhook", content=raw, headers=headers)
    assert r.status_code == 200, r.text[:200]
    j = r.json()
    assert j.get("applied") is True
    assert j.get("count") == 1


def test_A_functional__duplicate_is_idempotent(client: httpx.Client, make_event) -> None:
    raw, headers = make_event()
    client.post("/webhook", content=raw, headers=headers)
    r = client.post("/webhook", content=raw, headers=headers)
    assert r.status_code == 200, r.text[:200]
    j = r.json()
    assert j.get("applied") is False
    assert j.get("count") == 1


def test_A_functional__missing_signature_401(client: httpx.Client, make_event) -> None:
    raw, headers = make_event()
    headers.pop("X-Signature", None)
    r = client.post("/webhook", content=raw, headers=headers)
    assert r.status_code == 401, f"expected 401, got {r.status_code}"


def test_A_functional__tampered_body_401(client: httpx.Client, make_event) -> None:
    raw, headers = make_event()
    # Signature is for raw; send a different body.
    different = raw.replace(b"100", b"1000")
    r = client.post("/webhook", content=different, headers=headers)
    assert r.status_code == 401, f"expected 401 on tampered body, got {r.status_code}"


def test_A_functional__events_list_and_get(client: httpx.Client, make_event) -> None:
    eid = str(uuid.uuid4())
    raw, headers = make_event(event_id=eid)
    client.post("/webhook", content=raw, headers=headers)
    r = client.get(f"/events/{eid}")
    assert r.status_code == 200, r.text[:200]
    assert r.json().get("count") == 1
    r_list = client.get("/events")
    assert r_list.status_code == 200
    ids = [e["event_id"] for e in r_list.json().get("events", [])]
    assert eid in ids
