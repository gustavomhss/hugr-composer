"""Judge fixtures — signed webhook."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from collections.abc import Iterator

import httpx
import pytest

SECRET = b"s3cr3t-bench-key"


def _base_url() -> str:
    url = os.environ.get("BLIND_BASE_URL", "").rstrip("/")
    if not url:
        pytest.skip("BLIND_BASE_URL not set")
    return url


def sign(raw: bytes) -> str:
    return hmac.new(SECRET, raw, hashlib.sha256).hexdigest()


@pytest.fixture(scope="session")
def base_url() -> str:
    return _base_url()


@pytest.fixture()
def client(base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=base_url, timeout=10.0) as c:
        yield c


@pytest.fixture()
def make_event():
    def _make(event_id: str | None = None, event_type: str = "charge.completed") -> tuple[bytes, dict]:
        eid = event_id or str(uuid.uuid4())
        body = {"event_id": eid, "event_type": event_type, "payload": {"amount": 100}}
        raw = json.dumps(body, sort_keys=True).encode()
        headers = {"X-Signature": sign(raw), "content-type": "application/json"}
        return raw, headers
    return _make
