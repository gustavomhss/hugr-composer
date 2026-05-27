"""Tests for real-time revocation: deny-list store + authorize() + admin endpoints.

Proves the entitlement layer on top of authenticity: a validly-signed,
unexpired key is denied the moment its seat is cancelled or its jti revoked;
revocation survives a restart (file store); and the admin endpoints that the
billing flow calls are fail-closed.

Run standalone or via pytest::

    PYTHONPATH=. python3 hugr_auth/test_store.py
    PYTHONPATH=. pytest hugr_auth/test_store.py -v
"""

from __future__ import annotations

import asyncio
import os
import secrets as _secrets
import sys
import tempfile
from pathlib import Path

from hugr_auth.license import introspect_license, mint_license
from hugr_auth.store import (
    FileSubscriptionStore,
    InMemorySubscriptionStore,
    authorize,
)

_SECRET = _secrets.token_bytes(32)


def _authorize_checks() -> list[str]:
    f: list[str] = []
    store = InMemorySubscriptionStore()

    k1 = mint_license(_SECRET, seat="acme")
    k2 = mint_license(_SECRET, seat="acme")  # 2nd key, same seat
    j1 = (introspect_license(_SECRET, k1) or {}).get("jti")

    # clean store → authentic+entitled
    if authorize(_SECRET, k1, store) is None:
        f.append("clean store denied a valid key")

    # revoke a single key (jti) → that key dead, sibling key for the seat survives
    store.revoke_key(j1)
    if authorize(_SECRET, k1, store) is not None:
        f.append("revoked key still authorized")
    if authorize(_SECRET, k2, store) is None:
        f.append("revoking one key killed a sibling key on the same seat")

    # cancel the seat → every key it holds dies immediately, even pre-exp
    store.cancel_seat("acme")
    if authorize(_SECRET, k2, store) is not None:
        f.append("cancelled seat still authorized")

    # reactivate → live again (sibling k2; k1 stays revoked by jti)
    store.reactivate_seat("acme")
    if authorize(_SECRET, k2, store) is None:
        f.append("reactivated seat not authorized")
    if authorize(_SECRET, k1, store) is not None:
        f.append("reactivating seat un-revoked an individually-revoked key")

    return f


def _persistence_checks() -> list[str]:
    f: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "subs.json"
        s1 = FileSubscriptionStore(path)
        s1.cancel_seat("beta")
        s1.revoke_key("deadbeef")

        # a fresh store on the same path sees the revocations (survives restart)
        s2 = FileSubscriptionStore(path)
        if not s2.seat_cancelled("beta"):
            f.append("cancelled seat did not persist across reload")
        if not s2.key_revoked("deadbeef"):
            f.append("revoked key did not persist across reload")
        if s2.seat_cancelled("other"):
            f.append("unrelated seat reported cancelled")
    return f


def _endpoint_checks() -> list[str]:
    import httpx

    f: list[str] = []
    saved = {k: os.environ.get(k) for k in
             ("HUGR_LICENSE_SIGNING_SECRET", "HUGR_ADMIN_TOKEN", "HUGR_STORE_PATH")}
    os.environ["HUGR_LICENSE_SIGNING_SECRET"] = _SECRET.hex()
    os.environ["HUGR_ADMIN_TOKEN"] = "admin-token-at-least-16-chars"
    os.environ.pop("HUGR_STORE_PATH", None)
    try:
        # import fresh so the module-global store is in-memory and empty
        for m in [x for x in list(sys.modules) if x.startswith("hugr_auth.app")]:
            del sys.modules[m]
        from hugr_auth import app as app_mod

        key = mint_license(_SECRET, seat="seat-rev")
        claims = introspect_license(_SECRET, key) or {}

        async def _run() -> None:
            transport = httpx.ASGITransport(app=app_mod.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://auth") as c:
                # active before cancellation
                r = await c.post("/introspect", json={"key": key})
                if not r.json().get("active"):
                    f.append("key inactive before any revocation")

                # admin guard: no token → 403
                r = await c.post("/admin/cancel_seat", json={"seat": "seat-rev"})
                if r.status_code != 403:
                    f.append(f"admin cancel without token: expected 403, got {r.status_code}")

                # admin guard: wrong token → 403
                r = await c.post("/admin/cancel_seat", json={"seat": "seat-rev"},
                                 headers={"Authorization": "Bearer wrong"})
                if r.status_code != 403:
                    f.append(f"admin cancel wrong token: expected 403, got {r.status_code}")

                # cancel with the right token → 200
                r = await c.post("/admin/cancel_seat", json={"seat": "seat-rev"},
                                 headers={"Authorization": "Bearer admin-token-at-least-16-chars"})
                if r.status_code != 200:
                    f.append(f"admin cancel with token: expected 200, got {r.status_code} {r.text[:120]}")

                # now the same key is denied in real time
                r = await c.post("/introspect", json={"key": key})
                if r.json().get("active"):
                    f.append("key still active after seat cancellation (no real-time revocation)")

            await transport.aclose()

        asyncio.run(_run())
        _ = claims  # (claims fetched to assert jti shape exists)
        if not claims.get("jti"):
            f.append("minted token has no jti")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for m in [x for x in list(sys.modules) if x.startswith("hugr_auth.app")]:
            del sys.modules[m]
    return f


def test_authorize_revocation() -> None:
    assert not _authorize_checks(), "\n".join(_authorize_checks())


def test_revocation_persists() -> None:
    assert not _persistence_checks(), "\n".join(_persistence_checks())


def test_introspect_and_admin_endpoints() -> None:
    assert not _endpoint_checks(), "\n".join(_endpoint_checks())


def main() -> int:
    failures = _authorize_checks() + _persistence_checks() + _endpoint_checks()
    if failures:
        print(f"HuGR auth store: {len(failures)} check(s) FAILED")
        for x in failures:
            print(f"  FAIL  {x}")
        return 1
    print("HuGR auth store: revocation green — cancel seat / revoke key cut access "
          "in real time, survive restart, admin endpoints fail-closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
