"""Judge fixtures — RBAC + audit."""
from __future__ import annotations

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


def as_user(user: str) -> dict:
    return {"X-User": user}


@pytest.fixture()
def admin_headers():
    return {"X-User": "alice"}


@pytest.fixture()
def editor_headers():
    return {"X-User": "bob"}


@pytest.fixture()
def reader_headers():
    return {"X-User": "carol"}
