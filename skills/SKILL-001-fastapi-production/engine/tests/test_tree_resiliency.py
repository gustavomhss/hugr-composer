"""Unit tests for mcp_tools.tree.resiliency — domain tree dispatcher."""

from __future__ import annotations

from pathlib import Path

from mcp_tools.tree.resiliency import (
    BUNDLE_SLICES,
    PRIMITIVES,
    SLICES,
    fastapi_resiliency,
)

# ---------------------------------------------------------------------------
# Contract of the dispatcher itself
# ---------------------------------------------------------------------------


def test_list_returns_full_tree() -> None:
    r = fastapi_resiliency(action="list")
    assert r["ok"] is True
    assert r["result"]["domain"] == "resiliency"
    assert len(r["result"]["slices"]) == len(SLICES)
    assert len(r["result"]["primitives"]) == len(PRIMITIVES)
    assert len(r["result"]["bundle"]["slices_installed"]) == len(BUNDLE_SLICES)
    assert r["next_steps"], "list must carry breadcrumbs"


def test_unknown_action_returns_ok_false_with_valid_list() -> None:
    r = fastapi_resiliency(action="bogus")
    assert r["ok"] is False
    valid = r["result"]["valid_actions"]
    assert "list" in valid
    assert "bundle" in valid
    assert "primitive" in valid
    for slice_name in SLICES:
        assert slice_name in valid


def test_envelope_shape_uniform_across_all_actions() -> None:
    required_keys = {"ok", "what_happened", "result", "next_steps", "elapsed_ms"}
    for call in (
        lambda: fastapi_resiliency(action="list"),
        lambda: fastapi_resiliency(action="bogus"),
        lambda: fastapi_resiliency(action="primitive"),
        lambda: fastapi_resiliency(action="bundle"),
    ):
        r = call()
        assert required_keys <= r.keys()
        assert isinstance(r["next_steps"], list)
        assert len(r["next_steps"]) <= 5


# ---------------------------------------------------------------------------
# Primitive action
# ---------------------------------------------------------------------------


def test_primitive_requires_name_and_output_dir() -> None:
    r = fastapi_resiliency(action="primitive", params={"name": "Bulkhead"})
    assert r["ok"] is False
    assert "output_dir" in r["what_happened"]


def test_primitive_rejects_unknown_name() -> None:
    r = fastapi_resiliency(
        action="primitive", params={"name": "DoesNotExist", "output_dir": "/tmp/x"}
    )
    assert r["ok"] is False
    assert "unknown primitive" in r["what_happened"].lower()


def test_primitive_copies_files(tmp_path: Path) -> None:
    r = fastapi_resiliency(
        action="primitive",
        params={
            "name": "Bulkhead",
            "output_dir": str(tmp_path),
        },
    )
    assert r["ok"] is True, r
    files = r["result"]["files_created"]
    assert any(f.endswith("Bulkhead.py") for f in files), files
    # F-003: target layout matches compose + scaffold_venous (no `app/`).
    target = tmp_path / "core" / "venous" / "resiliency" / "Bulkhead" / "Bulkhead.py"
    assert target.exists()
    assert any(
        "from core.venous.resiliency.Bulkhead.Bulkhead import Bulkhead" in step
        for step in r["next_steps"]
    )


def test_primitive_overwrites_existing_dir_only_with_force(tmp_path: Path) -> None:
    """F-002: copy is non-destructive by default; ``force=True`` opts in."""
    target = tmp_path / "core" / "venous" / "resiliency" / "Bulkhead"
    target.mkdir(parents=True)
    (target / "stale.txt").write_text("old")

    r_skip = fastapi_resiliency(
        action="primitive",
        params={"name": "Bulkhead", "output_dir": str(tmp_path)},
    )
    assert r_skip["ok"] is True
    assert r_skip["result"]["status"] == "skipped"
    assert (target / "stale.txt").exists(), "default must NOT destroy user code"

    r_force = fastapi_resiliency(
        action="primitive",
        params={
            "name": "Bulkhead",
            "output_dir": str(tmp_path),
            "force": True,
        },
    )
    assert r_force["ok"] is True
    assert r_force["result"]["status"] == "copied"
    assert not (target / "stale.txt").exists(), "force=True must wipe previous state"


# ---------------------------------------------------------------------------
# Bundle + slice actions
# ---------------------------------------------------------------------------


def test_bundle_requires_output_dir() -> None:
    r = fastapi_resiliency(action="bundle")
    assert r["ok"] is False
    assert "output_dir" in r["what_happened"]


def test_slice_requires_output_dir() -> None:
    r = fastapi_resiliency(action="add_adaptive_throttle")
    assert r["ok"] is False
    assert "output_dir" in r["what_happened"]


# ---------------------------------------------------------------------------
# Registration smoke
# ---------------------------------------------------------------------------


def test_fastapi_resiliency_registered_in_mcp_discovery() -> None:
    import asyncio

    from mcp_tools.discovery import discover_and_register
    from mcp_tools.server import mcp as _mcp

    discover_and_register(_mcp)
    names = {t.name for t in asyncio.run(_mcp.list_tools())}
    assert "fastapi_resiliency" in names
