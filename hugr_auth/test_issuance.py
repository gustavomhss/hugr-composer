"""Tests for license issuance — the /admin/issue endpoint, the CLI, and the
full subscribe→issue→use→cancel lifecycle.

Run standalone or via pytest::

    PYTHONPATH=. python3 hugr_auth/test_issuance.py
    PYTHONPATH=. pytest hugr_auth/test_issuance.py -v
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import secrets as _secrets
import sys

from hugr_auth.license import introspect_license

_SECRET = _secrets.token_bytes(32)
_ADMIN = "admin-token-at-least-16-chars"


def _endpoint_checks() -> list[str]:
    import httpx

    f: list[str] = []
    saved = {k: os.environ.get(k) for k in
             ("HUGR_LICENSE_SIGNING_SECRET", "HUGR_ADMIN_TOKEN", "HUGR_STORE_PATH")}
    os.environ["HUGR_LICENSE_SIGNING_SECRET"] = _SECRET.hex()
    os.environ["HUGR_ADMIN_TOKEN"] = _ADMIN
    os.environ.pop("HUGR_STORE_PATH", None)
    try:
        for m in [x for x in list(sys.modules) if x.startswith("hugr_auth.app")]:
            del sys.modules[m]
        from hugr_auth import app as app_mod

        admin_h = {"Authorization": f"Bearer {_ADMIN}"}

        async def _run() -> None:
            transport = httpx.ASGITransport(app=app_mod.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://auth") as c:
                # issue without admin token → 403
                r = await c.post("/admin/issue", json={"seat": "acme"})
                if r.status_code != 403:
                    f.append(f"issue without token: expected 403, got {r.status_code}")

                # issue with admin token → 200 + a usable key
                r = await c.post("/admin/issue",
                                 json={"seat": "acme", "plan": "team", "ttl_days": 7},
                                 headers=admin_h)
                if r.status_code != 200:
                    f.append(f"issue: expected 200, got {r.status_code} {r.text[:120]}")
                    return
                body = r.json()
                key = body["key"]
                if not body.get("jti") or not body.get("expires_at"):
                    f.append(f"issue response missing jti/exp: {body}")

                # the freshly-issued key introspects active for that seat
                r = await c.post("/introspect", json={"key": key})
                ib = r.json()
                if not ib.get("active"):
                    f.append("freshly-issued key not active")
                elif (ib.get("claims") or {}).get("seat") != "acme":
                    f.append(f"issued key seat wrong: {ib.get('claims')}")
                elif (ib.get("claims") or {}).get("plan") != "team":
                    f.append(f"issued key plan wrong: {ib.get('claims')}")

                # LIFECYCLE: cancel the seat → the issued key dies in real time
                r = await c.post("/admin/cancel_seat", json={"seat": "acme"}, headers=admin_h)
                if r.status_code != 200:
                    f.append(f"cancel after issue: {r.status_code}")
                r = await c.post("/introspect", json={"key": key})
                if r.json().get("active"):
                    f.append("issued key still active after seat cancellation")

            await transport.aclose()

        asyncio.run(_run())
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for m in [x for x in list(sys.modules) if x.startswith("hugr_auth.app")]:
            del sys.modules[m]
    return f


def _cli_checks() -> list[str]:
    f: list[str] = []
    saved = os.environ.get("HUGR_LICENSE_SIGNING_SECRET")
    os.environ["HUGR_LICENSE_SIGNING_SECRET"] = _SECRET.hex()
    try:
        from hugr_auth.cli import main as cli_main

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli_main(["issue", "--seat", "cli-seat", "--plan", "pro", "--ttl-days", "5"])
        if rc != 0:
            f.append(f"cli issue exited {rc}")
        key = out.getvalue().strip().splitlines()[0] if out.getvalue().strip() else ""
        claims = introspect_license(_SECRET, key)
        if claims is None:
            f.append("cli-issued key did not introspect")
        elif claims.get("seat") != "cli-seat":
            f.append(f"cli-issued key seat wrong: {claims}")
    finally:
        if saved is None:
            os.environ.pop("HUGR_LICENSE_SIGNING_SECRET", None)
        else:
            os.environ["HUGR_LICENSE_SIGNING_SECRET"] = saved
    return f


def test_issue_endpoint_and_lifecycle() -> None:
    assert not _endpoint_checks(), "\n".join(_endpoint_checks())


def test_cli_issue() -> None:
    assert not _cli_checks(), "\n".join(_cli_checks())


def main() -> int:
    failures = _endpoint_checks() + _cli_checks()
    if failures:
        print(f"HuGR issuance: {len(failures)} check(s) FAILED")
        for x in failures:
            print(f"  FAIL  {x}")
        return 1
    print("HuGR issuance: green — /admin/issue mints usable keys, CLI issues, "
          "and subscribe→issue→use→cancel cuts access.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
