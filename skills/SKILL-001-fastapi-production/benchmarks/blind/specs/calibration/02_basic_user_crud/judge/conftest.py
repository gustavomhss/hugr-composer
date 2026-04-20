"""Judge fixtures — basic user CRUD."""
from __future__ import annotations

import os
import uuid
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


@pytest.fixture()
def fresh_email():
    def _make(tag: str = "") -> str:
        return f"user-{tag or uuid.uuid4().hex[:8]}@example.test"
    return _make


@pytest.fixture()
def create_user(client: httpx.Client, fresh_email):
    def _create(email: str | None = None, display: str | None = None) -> dict:
        body = {
            "email": email or fresh_email(),
            "display_name": display or "Test User",
        }
        r = client.post("/users", json=body)
        assert r.status_code in (200, 201), f"create failed: {r.status_code} {r.text[:200]}"
        return r.json()
    return _create
