"""Judge fixtures — saga bookings."""
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


def _body(flight_fail=False, hotel_fail=False, car_fail=False) -> dict:
    return {
        "user_id": "u1",
        "flight": {"code": "F1", "fail": flight_fail},
        "hotel":  {"code": "H1", "fail": hotel_fail},
        "car":    {"code": "C1", "fail": car_fail},
    }


@pytest.fixture()
def book_body():
    return _body
