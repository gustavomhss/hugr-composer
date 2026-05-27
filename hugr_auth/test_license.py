"""Tests for the HuGR license core + introspection endpoint.

Proves the authority side of the gate contract: a validly-minted key
introspects to active+claims; a tampered, expired, or wrong-secret key is
inactive; and the /introspect endpoint returns the {active, claims} JSON the
MCP gate consumes.

Run standalone or via pytest::

    PYTHONPATH=. python3 hugr_auth/test_license.py
    PYTHONPATH=. pytest hugr_auth/test_license.py -v
"""

from __future__ import annotations

import asyncio
import os
import secrets as _secrets
import sys
import time

from hugr_auth.license import (
    LicenseError,
    introspect_license,
    mint_license,
)

_SECRET = _secrets.token_bytes(32)


def _core_checks() -> list[str]:
    f: list[str] = []

    # valid mint → introspect returns claims
    key = mint_license(_SECRET, seat="seat-123", plan="pro", scopes=["hugr:tools"])
    claims = introspect_license(_SECRET, key)
    if claims is None:
        f.append("valid key did not introspect")
    else:
        if claims["client_id"] != "seat-123":
            f.append(f"client_id wrong: {claims['client_id']}")
        if "hugr:tools" not in claims["scopes"]:
            f.append(f"scopes wrong: {claims['scopes']}")

    # LIC-INV-01: tampered signature → None
    if introspect_license(_SECRET, key[:-2] + ("aa" if not key.endswith("aa") else "bb")) is not None:
        f.append("tampered signature accepted")
    # tampered payload → None
    body, sig = key.rsplit(".", 1)
    if introspect_license(_SECRET, body + "x." + sig) is not None:
        f.append("tampered payload accepted")
    # wrong secret → None
    if introspect_license(_secrets.token_bytes(32), key) is not None:
        f.append("key verified under a different secret")

    # LIC-INV-02: expired → None
    expired = mint_license(_SECRET, seat="s", ttl_seconds=-10)
    if introspect_license(_SECRET, expired) is not None:
        f.append("expired key accepted")
    # not-yet-expired stays valid relative to an explicit now
    fresh = mint_license(_SECRET, seat="s", ttl_seconds=60, now=time.time())
    if introspect_license(_SECRET, fresh) is None:
        f.append("fresh key rejected")

    # LIC-INV-03: weak secret rejected
    try:
        mint_license(b"short", seat="s")
        f.append("weak secret accepted by mint")
    except LicenseError:
        pass

    # garbage inputs
    for bad in ("", "no-dot", "a.b.c"):
        if introspect_license(_SECRET, bad) is not None:
            f.append(f"garbage key accepted: {bad!r}")

    return f


def _endpoint_checks() -> list[str]:
    """Drive the FastAPI /introspect endpoint in-process via httpx ASGITransport."""
    import httpx

    f: list[str] = []
    saved = os.environ.get("HUGR_LICENSE_SIGNING_SECRET")
    os.environ["HUGR_LICENSE_SIGNING_SECRET"] = _SECRET.hex()
    try:
        # import AFTER env is set; app reads the secret per-request anyway.
        from hugr_auth.app import app

        key = mint_license(_SECRET, seat="seat-xyz", plan="team")

        async def _run() -> None:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://auth") as c:
                r = await c.post("/introspect", json={"key": key})
                if r.status_code != 200:
                    f.append(f"/introspect status {r.status_code}")
                else:
                    body = r.json()
                    if not body.get("active"):
                        f.append(f"valid key reported inactive: {body}")
                    elif (body.get("claims") or {}).get("client_id") != "seat-xyz":
                        f.append(f"claims wrong: {body.get('claims')}")

                r = await c.post("/introspect", json={"key": "bogus"})
                if r.json().get("active"):
                    f.append("bogus key reported active")

                h = await c.get("/healthz")
                if h.status_code != 200:
                    f.append(f"/healthz status {h.status_code}")

        asyncio.run(_run())

        # fail-closed when no secret configured
        os.environ["HUGR_LICENSE_SIGNING_SECRET"] = ""

        async def _run_nosecret() -> None:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://auth") as c:
                r = await c.post("/introspect", json={"key": key})
                if r.json().get("active"):
                    f.append("introspect active with no signing secret configured")

        asyncio.run(_run_nosecret())
    finally:
        if saved is None:
            os.environ.pop("HUGR_LICENSE_SIGNING_SECRET", None)
        else:
            os.environ["HUGR_LICENSE_SIGNING_SECRET"] = saved
    return f


def test_license_core() -> None:
    assert not _core_checks(), "\n".join(_core_checks())


def test_introspect_endpoint() -> None:
    assert not _endpoint_checks(), "\n".join(_endpoint_checks())


def main() -> int:
    failures = _core_checks() + _endpoint_checks()
    if failures:
        print(f"HuGR auth: {len(failures)} check(s) FAILED")
        for x in failures:
            print(f"  FAIL  {x}")
        return 1
    print("HuGR auth: license core + /introspect endpoint all green "
          "(mint→introspect, tamper/expire/wrong-secret denied, fail-closed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
