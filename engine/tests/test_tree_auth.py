"""Unit tests for mcp_tools.tree.auth — the POC domain dispatcher."""

from __future__ import annotations

from pathlib import Path

from mcp_tools.tree.auth import (
    BUNDLE_SLICES,
    PRIMITIVES,
    SLICES,
    fastapi_auth,
)

# ---------------------------------------------------------------------------
# Contract of the dispatcher itself
# ---------------------------------------------------------------------------


def test_list_returns_full_tree() -> None:
    r = fastapi_auth(action="list")
    assert r["ok"] is True
    assert r["result"]["domain"] == "auth"
    assert len(r["result"]["slices"]) == len(SLICES)
    assert len(r["result"]["primitives"]) == len(PRIMITIVES)
    assert len(r["result"]["bundle"]["slices_installed"]) == len(BUNDLE_SLICES)
    assert r["next_steps"], "list must carry breadcrumbs"


def test_unknown_action_returns_ok_false_with_valid_list() -> None:
    r = fastapi_auth(action="bogus")
    assert r["ok"] is False
    valid = r["result"]["valid_actions"]
    assert "list" in valid and "bundle" in valid and "primitive" in valid
    for slice_name in SLICES:
        assert slice_name in valid


def test_envelope_shape_uniform_across_all_actions() -> None:
    required_keys = {"ok", "what_happened", "result", "next_steps", "elapsed_ms"}
    for call in (
        lambda: fastapi_auth(action="list"),
        lambda: fastapi_auth(action="bogus"),
        lambda: fastapi_auth(action="primitive"),
        lambda: fastapi_auth(action="bundle"),
    ):
        r = call()
        assert required_keys <= r.keys()
        assert isinstance(r["next_steps"], list)
        assert len(r["next_steps"]) <= 5


# ---------------------------------------------------------------------------
# Primitive action
# ---------------------------------------------------------------------------


def test_primitive_requires_name_and_output_dir() -> None:
    r = fastapi_auth(action="primitive", params={"name": "SessionStore"})
    assert r["ok"] is False
    assert "output_dir" in r["what_happened"]


def test_primitive_rejects_unknown_name() -> None:
    r = fastapi_auth(action="primitive", params={"name": "DoesNotExist", "output_dir": "/tmp/x"})
    assert r["ok"] is False
    assert "unknown primitive" in r["what_happened"].lower()


def test_primitive_copies_session_store_files(tmp_path: Path) -> None:
    r = fastapi_auth(
        action="primitive",
        params={
            "name": "SessionStore",
            "output_dir": str(tmp_path),
        },
    )
    assert r["ok"] is True
    files = r["result"]["files_created"]
    assert any(f.endswith("SessionStore.py") for f in files)
    assert any(f.endswith("SessionStore.md") for f in files)
    # F-003: target layout is `core/venous/<ns>/<Name>/` (no `app/` prefix)
    # so that `from core.venous.auth.SessionStore.SessionStore import …`
    # resolves at runtime in the emitted project.
    target = tmp_path / "core" / "venous" / "auth" / "SessionStore" / "SessionStore.py"
    assert target.exists()
    # Emitted next_steps must advertise the matching nested import.
    assert any(
        "from core.venous.auth.SessionStore.SessionStore import SessionStore" in step
        for step in r["next_steps"]
    )


def test_primitive_copy_skips_pycache(tmp_path: Path) -> None:
    # Seed the source with a bogus __pycache__ file to verify exclusion.
    from mcp_tools.tree.auth import VENOUS_AUTH

    cache = VENOUS_AUTH / "SessionStore" / "__pycache__"
    cache.mkdir(exist_ok=True)
    bogus = cache / "test_exclusion.pyc"
    bogus.write_bytes(b"\x00")
    try:
        fastapi_auth(
            action="primitive",
            params={
                "name": "SessionStore",
                "output_dir": str(tmp_path),
            },
        )
        target_pycache = tmp_path / "core" / "venous" / "auth" / "SessionStore" / "__pycache__"
        assert not target_pycache.exists(), "pycache should have been excluded"
    finally:
        bogus.unlink(missing_ok=True)


def test_primitive_overwrites_existing_dir_only_with_force(tmp_path: Path) -> None:
    """F-002: copy is non-destructive by default; ``force=True`` opts in."""
    target = tmp_path / "core" / "venous" / "auth" / "SessionStore"
    target.mkdir(parents=True)
    (target / "stale.txt").write_text("old")

    # First call: default (force=False) → must SKIP and preserve stale.txt.
    r_skip = fastapi_auth(
        action="primitive",
        params={"name": "SessionStore", "output_dir": str(tmp_path)},
    )
    assert r_skip["ok"] is True
    assert r_skip["result"]["status"] == "skipped"
    assert (target / "stale.txt").exists(), "default must NOT destroy user code"

    # Second call: force=True → wipes + repopulates.
    r_force = fastapi_auth(
        action="primitive",
        params={"name": "SessionStore", "output_dir": str(tmp_path), "force": True},
    )
    assert r_force["ok"] is True
    assert r_force["result"]["status"] == "copied"
    assert not (target / "stale.txt").exists(), "force=True must wipe previous state"


# ---------------------------------------------------------------------------
# Bundle + slice actions (smoke — the slice tools themselves are tested
# under adapt/extend/auth_access/test_*.py)
# ---------------------------------------------------------------------------


def test_bundle_requires_output_dir() -> None:
    r = fastapi_auth(action="bundle")
    assert r["ok"] is False
    assert "output_dir" in r["what_happened"]


def test_slice_requires_output_dir() -> None:
    r = fastapi_auth(action="add_oauth2")
    assert r["ok"] is False
    assert "output_dir" in r["what_happened"]


# ---------------------------------------------------------------------------
# Registration smoke
# ---------------------------------------------------------------------------


def test_fastapi_auth_registered_in_mcp_discovery() -> None:
    import asyncio

    from mcp_tools.discovery import discover_and_register
    from mcp_tools.server import mcp as _mcp

    discover_and_register(_mcp)
    names = {t.name for t in asyncio.run(_mcp.list_tools())}
    assert "fastapi_auth" in names
