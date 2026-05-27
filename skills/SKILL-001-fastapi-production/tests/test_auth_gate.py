"""Tests for the HuGR subscription gate on the MCP server.

Proves the gate's core guarantee at the unit level: an unlicensed token yields
NO access (None → FastMCP auth failure → zero tools), a configured license
yields an AccessToken, and the gate is inert unless explicitly enabled.

Runs standalone (this is how audit_l1 / make test invokes it) or via pytest::

    PYTHONPATH=. python3 tests/test_auth_gate.py
    PYTHONPATH=. pytest tests/test_auth_gate.py -v
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp_tools.auth_gate import HugrTokenVerifier, gate_enabled


def _verify(token: str):
    """Run the async verify_token synchronously and return the result."""
    return asyncio.run(HugrTokenVerifier().verify_token(token))


def _checks() -> list[str]:
    """Return a list of failure strings; empty means all gate checks pass."""
    failures: list[str] = []

    # Snapshot env we mutate so the suite stays hermetic.
    saved = {k: os.environ.get(k) for k in ("HUGR_GATE", "HUGR_DEV_LICENSE_KEYS")}
    try:
        # --- gate_enabled reflects the flag ---
        os.environ.pop("HUGR_GATE", None)
        if gate_enabled():
            failures.append("gate_enabled() True with HUGR_GATE unset")
        for val in ("1", "true", "YES", "on"):
            os.environ["HUGR_GATE"] = val
            if not gate_enabled():
                failures.append(f"gate_enabled() False for HUGR_GATE={val!r}")
        os.environ["HUGR_GATE"] = "0"
        if gate_enabled():
            failures.append("gate_enabled() True for HUGR_GATE='0'")

        # --- fail-closed: no configured keys → everything denied ---
        os.environ.pop("HUGR_DEV_LICENSE_KEYS", None)
        if _verify("anything") is not None:
            failures.append("verify_token accepted a token with no keys configured")
        if _verify("") is not None:
            failures.append("verify_token accepted an empty token")

        # --- a configured license key is accepted, unknown ones are not ---
        os.environ["HUGR_DEV_LICENSE_KEYS"] = "good-key-1, good-key-2"
        tok = _verify("good-key-1")
        if tok is None:
            failures.append("verify_token rejected a configured license key")
        else:
            if tok.token != "good-key-1":
                failures.append(f"AccessToken.token wrong: {tok.token!r}")
            if "hugr:tools" not in tok.scopes:
                failures.append(f"AccessToken missing hugr:tools scope: {tok.scopes}")
        if _verify("bad-key") is not None:
            failures.append("verify_token accepted an unlisted key")

        # --- required_scopes are enforced ---
        v = HugrTokenVerifier(required_scopes=["hugr:enterprise"])
        if asyncio.run(v.verify_token("good-key-1")) is not None:
            failures.append("verify_token ignored an unmet required_scope")

    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    return failures


# ---------------------------------------------------------------------------
# pytest entrypoints
# ---------------------------------------------------------------------------

def test_gate_enabled_reflects_flag() -> None:
    """Covered within the consolidated gate checks."""
    assert not _checks(), "\n".join(_checks())


def test_unlicensed_is_denied_and_licensed_is_allowed() -> None:
    """Fail-closed for unknown tokens; AccessToken for a configured key."""
    assert not _checks(), "\n".join(_checks())


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

def main() -> int:
    failures = _checks()
    if failures:
        print(f"Auth gate: {len(failures)} check(s) FAILED")
        for f in failures:
            print(f"  FAIL  {f}")
        return 1
    print("Auth gate: all checks pass — unlicensed denied, licensed allowed, "
          "gate inert unless HUGR_GATE set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
