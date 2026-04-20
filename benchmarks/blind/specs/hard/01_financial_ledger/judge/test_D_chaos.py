"""Layer D — failure-injection / chaos.

The spec requires tamper-evident audit. A deliberate mutation of an
audit record MUST be detectable via `GET /audit/verify`.
"""
from __future__ import annotations

import uuid

import httpx


def test_D_chaos__audit_verify_returns_ok_on_clean_ledger(
    client: httpx.Client, open_account, deposit,
) -> None:
    a = open_account()
    deposit(a, 500)
    r = client.get("/audit/verify")
    assert r.status_code == 200, r.text[:200]
    j = r.json()
    assert j.get("ok") is True, f"clean ledger verify should return ok=True, got {j}"


def test_D_chaos__audit_verify_detects_tampering(
    client: httpx.Client, open_account, deposit,
) -> None:
    """Ask the app to tamper with its own audit (via a deliberate test-mode
    endpoint declared in the brief as {/audit/_test_tamper}). If the
    emitted app does not implement this endpoint, fall back to a pre-
    registered semantic check: the verify endpoint must at minimum reject
    a crafted record via POST /audit/_test_break if available.

    A SOTA solution declares one of these test hooks. Naked agents rarely
    do, which is precisely the discrimination we want.
    """
    a = open_account()
    deposit(a, 500)

    # Try either test hook the spec's reference solution can expose.
    for path in ("/audit/_test_tamper", "/audit/_test_break"):
        r = client.post(path, json={"at_index": 0})
        if r.status_code in (200, 201, 204):
            # Tamper accepted — verify must now fail.
            v = client.get("/audit/verify")
            assert v.status_code == 200
            j = v.json()
            assert j.get("ok") is False, (
                f"after {path}, verify should report ok=False + broken_index; got {j}"
            )
            assert "broken_index" in j, f"verify payload must include broken_index when ok=False; got {j}"
            return

    # Neither test hook exposed → the solution cannot demonstrate tamper
    # detection under sealed conditions. This is a spec-required surface
    # even though the brief doesn't specify the exact endpoint names — a
    # SOTA solution anticipates the need.
    import pytest
    pytest.fail(
        "emitted app exposes no test-tamper hook; cannot verify tamper-evidence. "
        "Add either POST /audit/_test_tamper or POST /audit/_test_break that mutates "
        "an audit record by index and returns 2xx."
    )
