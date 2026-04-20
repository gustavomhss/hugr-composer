"""Judge fixtures — persisted queries."""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator

import httpx
import pytest


def _base_url() -> str:
    url = os.environ.get("BLIND_BASE_URL", "").rstrip("/")
    if not url:
        pytest.skip("BLIND_BASE_URL not set")
    return url


@pytest.fixture(scope="session")
def base_url() -> str:
    return _base_url()


@pytest.fixture()
def client(base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=base_url, timeout=10.0) as c:
        yield c


def expected_id(name: str, depth_limit: int) -> str:
    return hashlib.sha256(
        json.dumps({"name": name, "depth_limit": depth_limit}, sort_keys=True).encode()
    ).hexdigest()


@pytest.fixture()
def register(client: httpx.Client):
    def _reg(name: str, depth: int) -> dict:
        r = client.post("/queries/register", json={"name": name, "depth_limit": depth})
        return {"status": r.status_code, "body": r.json() if r.status_code < 500 else {}}
    return _reg
