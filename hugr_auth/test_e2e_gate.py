"""END-TO-END proof of the HuGR gate across real processes.

Ties the three bricks (gate · auth API · revocation) into one system test that
spins up REAL servers and drives a REAL MCP client:

    [auth service]  uvicorn hugr_auth.app  (holds the signing secret)
          ▲ /introspect, /admin/cancel_seat
          │
    [gated MCP]  mcp_server.py over HTTP, HUGR_GATE=1, HUGR_AUTH_URL→auth
          ▲ MCP streamable-http + bearer
          │
    [client]  raw mcp SDK ClientSession.list_tools()

Asserts the product claim end-to-end:
  - no key      → access denied (0 tools)
  - bad key     → access denied (0 tools)
  - valid key   → N > 0 tools
  - cancel seat → access denied again, in real time (0 tools)

(Uses the raw `mcp` SDK client because fastmcp.Client is import-broken against
the installed mcp version — irrelevant to the product, where the client is the
user's own agent.)

Run::

    PYTHONPATH=. python3 hugr_auth/test_e2e_gate.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from hugr_auth.license import mint_license

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "SKILL-001-fastapi-production"
VENV_PY = SKILL / ".venv" / "bin" / "python"
_SIGNING = secrets.token_bytes(32)
_ADMIN = "admin-token-at-least-16-chars"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_tcp(port: int, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(1.0)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


async def _count_tools(mcp_url: str, token: str | None) -> int:
    """Return tool count via a real MCP client, or 0 if access is denied."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with streamablehttp_client(mcp_url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.list_tools()
                return len(res.tools)
    except Exception:
        return 0  # auth failure / rejected handshake → no access


def main() -> int:
    auth_port, mcp_port = _free_port(), _free_port()
    mcp_url = f"http://127.0.0.1:{mcp_port}/mcp/"
    failures: list[str] = []
    procs: list[subprocess.Popen] = []

    base_env = {**os.environ, "PYTHONPATH": str(REPO)}

    # --- start auth service ---
    auth_env = {
        **base_env,
        "HUGR_LICENSE_SIGNING_SECRET": _SIGNING.hex(),
        "HUGR_ADMIN_TOKEN": _ADMIN,
    }
    procs.append(subprocess.Popen(
        [str(VENV_PY), "-m", "uvicorn", "hugr_auth.app:app",
         "--host", "127.0.0.1", "--port", str(auth_port), "--log-level", "warning"],
        cwd=str(REPO), env=auth_env,
    ))
    if not _wait_tcp(auth_port):
        print("  FAIL  auth service did not start")
        _cleanup(procs)
        return 1

    # --- start gated MCP server (HTTP) ---
    mcp_env = {
        **base_env,
        "PYTHONPATH": str(SKILL),
        "HUGR_GATE": "1",
        "HUGR_AUTH_URL": f"http://127.0.0.1:{auth_port}",
        "HUGR_MCP_HOST": "127.0.0.1",
        "HUGR_MCP_PORT": str(mcp_port),
        "SECRET_KEY": "ci-test-secret-key-must-be-32-chars-long!!!",
        "RATE_LIMITING_ENABLED": "false",
        "ENVIRONMENT": "local",
    }
    procs.append(subprocess.Popen(
        [str(VENV_PY), "mcp_server.py"], cwd=str(SKILL), env=mcp_env,
    ))
    if not _wait_tcp(mcp_port, timeout=90):
        print("  FAIL  gated MCP server did not start")
        _cleanup(procs)
        return 1
    time.sleep(2)  # let the HTTP app finish binding routes

    seat = "demo-seat"
    good = mint_license(_SIGNING, seat=seat, plan="pro")

    try:
        # 1. no key → denied
        n = asyncio.run(_count_tools(mcp_url, None))
        print(f"  no key       → {n} tools")
        if n != 0:
            failures.append(f"no key exposed {n} tools (expected 0)")

        # 2. bad key → denied
        n = asyncio.run(_count_tools(mcp_url, "not-a-real-license"))
        print(f"  bad key      → {n} tools")
        if n != 0:
            failures.append(f"bad key exposed {n} tools (expected 0)")

        # 3. valid key → N tools
        n_valid = asyncio.run(_count_tools(mcp_url, good))
        print(f"  valid key    → {n_valid} tools")
        if n_valid <= 0:
            failures.append("valid key exposed 0 tools (expected N > 0)")

        # 4. cancel seat → denied again, in real time
        r = httpx.post(
            f"http://127.0.0.1:{auth_port}/admin/cancel_seat",
            json={"seat": seat},
            headers={"Authorization": f"Bearer {_ADMIN}"},
            timeout=5,
        )
        if r.status_code != 200:
            failures.append(f"admin cancel failed: {r.status_code}")
        n = asyncio.run(_count_tools(mcp_url, good))
        print(f"  after cancel → {n} tools")
        if n != 0:
            failures.append(f"cancelled seat still exposed {n} tools (expected 0)")

    finally:
        _cleanup(procs)

    print("=" * 60)
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print(f"E2E gate: FAILED ({len(failures)})")
        return 1
    print(f"E2E gate: PASS — no/bad key → 0, valid → {n_valid}, cancel → 0 "
          "(real processes, real MCP client).")
    return 0


def _cleanup(procs: list[subprocess.Popen]) -> None:
    for p in procs:
        with contextlib.suppress(Exception):
            p.terminate()
    for p in procs:
        with contextlib.suppress(Exception):
            p.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
