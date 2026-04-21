"""Unit tests for mcp_tools.tree.testing — domain tree dispatcher."""
from __future__ import annotations

from pathlib import Path

import pytest

from mcp_tools.tree.testing import (
    BUNDLE_SLICES, PRIMITIVES, SLICES,
    fastapi_testing,
)

# ---------------------------------------------------------------------------
# Contract of the dispatcher itself
# ---------------------------------------------------------------------------

def test_list_returns_full_tree() -> None:
    r = fastapi_testing(action="list")
    assert r["ok"] is True
    assert r["result"]["domain"] == "testing"
    assert len(r["result"]["slices"]) == len(SLICES)
    assert len(r["result"]["bundle"]["slices_installed"]) == len(BUNDLE_SLICES)
    assert r["next_steps"], "list must carry breadcrumbs"

def test_unknown_action_returns_ok_false_with_valid_list() -> None:
    r = fastapi_testing(action="bogus")
    assert r["ok"] is False
    valid = r["result"]["valid_actions"]
    assert "list" in valid
    assert "bundle" in valid
    for slice_name in SLICES:
        assert slice_name in valid

def test_envelope_shape_uniform_across_all_actions() -> None:
    required_keys = {"ok", "what_happened", "result", "next_steps", "elapsed_ms"}
    for call in (
        lambda: fastapi_testing(action="list"),
        lambda: fastapi_testing(action="bogus"),
        lambda: fastapi_testing(action="primitive"),
        lambda: fastapi_testing(action="bundle"),
    ):
        r = call()
        assert required_keys <= r.keys()
        assert isinstance(r["next_steps"], list)
        assert len(r["next_steps"]) <= 5

# ---------------------------------------------------------------------------
# Primitive action
# ---------------------------------------------------------------------------

def test_primitive_action_returns_informative_error() -> None:
    r = fastapi_testing(action="primitive", params={"name": "Anything", "output_dir": "/tmp/x"})
    assert r["ok"] is False
    assert "no core.venous primitives" in r["what_happened"]

# ---------------------------------------------------------------------------
# Bundle + slice actions
# ---------------------------------------------------------------------------

def test_bundle_requires_output_dir() -> None:
    r = fastapi_testing(action="bundle")
    assert r["ok"] is False
    assert "output_dir" in r["what_happened"]

def test_slice_requires_output_dir() -> None:
    r = fastapi_testing(action="add_api_fuzzer")
    assert r["ok"] is False
    assert "output_dir" in r["what_happened"]

# ---------------------------------------------------------------------------
# Registration smoke
# ---------------------------------------------------------------------------

def test_fastapi_testing_registered_in_mcp_discovery() -> None:
    import asyncio
    from mcp_tools.server import mcp as _mcp
    from mcp_tools.discovery import discover_and_register
    discover_and_register(_mcp)
    names = {t.name for t in asyncio.run(_mcp.list_tools())}
    assert "fastapi_testing" in names
