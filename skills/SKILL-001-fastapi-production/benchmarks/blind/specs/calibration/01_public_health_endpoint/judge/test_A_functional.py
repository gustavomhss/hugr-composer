"""Layer A — functional acceptance for the health + version surface."""
from __future__ import annotations

import httpx


def test_A_functional__health_returns_200_ok_true(client: httpx.Client) -> None:
    r = client.get("/health")
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    assert isinstance(data, dict), f"body must be object, got {type(data).__name__}"
    assert data.get("ok") is True, f"ok must be boolean True, got {data!r}"


def test_A_functional__version_has_non_empty_strings(client: httpx.Client) -> None:
    r = client.get("/version")
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    assert isinstance(data.get("service"), str) and data["service"], data
    assert isinstance(data.get("version"), str) and data["version"], data


def test_A_functional__ready_returns_true(client: httpx.Client) -> None:
    r = client.get("/ready")
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    assert data.get("ready") is True, f"ready must be boolean True, got {data!r}"


def test_A_functional__unknown_path_404_json(client: httpx.Client) -> None:
    r = client.get("/totally-not-a-real-path")
    assert r.status_code == 404
    # Body must parse as JSON (no HTML error page).
    try:
        r.json()
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"404 body must be JSON, got: {r.text[:200]}") from exc


def test_A_functional__content_type_json(client: httpx.Client) -> None:
    for path in ("/health", "/version", "/ready"):
        r = client.get(path)
        ct = r.headers.get("content-type", "").lower()
        assert "application/json" in ct, f"{path}: content-type={ct!r}"
