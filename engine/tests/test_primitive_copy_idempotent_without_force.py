"""Idempotency contract for ``action="primitive"`` (Codex 3 F-002).

The pre-fix behaviour was destructive: re-running ``action="primitive"``
on an existing target ``shutil.rmtree``-d the user's customizations
without warning, flag, or backup. The fix introduces a ``force`` flag
that defaults to ``False`` and short-circuits with ``status="skipped"``
when the target already has content.

These tests EXERCISE the corrected behaviour across all three tree
dispatchers in scope of the F-002 fix (auth / data / realtime). A
second consecutive call without ``force`` MUST NOT touch the target.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_tools.tree.auth import fastapi_auth
from mcp_tools.tree.data import fastapi_data
from mcp_tools.tree.realtime import fastapi_realtime

# (dispatcher, primitive_name, namespace_folder)
DISPATCHERS = (
    (fastapi_auth, "SessionStore", "auth"),
    (fastapi_data, "Aggregate", "data"),
    (fastapi_realtime, "CausalReorderBuffer", "events"),
)


@pytest.mark.parametrize(("dispatcher", "primitive", "ns"), DISPATCHERS)
def test_second_call_returns_skipped_without_force(
    dispatcher, primitive: str, ns: str, tmp_path: Path
) -> None:
    """Two back-to-back calls: the second one must report ``skipped``."""
    params = {"name": primitive, "output_dir": str(tmp_path)}

    first = dispatcher(action="primitive", params=params)
    assert first["ok"] is True
    assert first["result"]["status"] == "copied"
    first_files = list(first["result"]["files_created"])
    assert first_files, "first call must populate the target"

    # Mutate one of the freshly-copied files to simulate user customisation.
    target_root = tmp_path / "core" / "venous" / ns / primitive
    user_file = target_root / "user_customisation.py"
    user_file.write_text("# user code")

    second = dispatcher(action="primitive", params=params)
    assert second["ok"] is True, second
    assert second["result"]["status"] == "skipped"
    assert second["result"]["files_created"] == []
    # The user's customisation must survive.
    assert user_file.exists(), f"second call destroyed user code at {user_file}; F-002 regressed."
    # And the originally-copied file must still be there.
    payload = target_root / f"{primitive}.py"
    assert payload.exists(), "skip path must not delete any files"


@pytest.mark.parametrize(("dispatcher", "primitive", "ns"), DISPATCHERS)
def test_force_true_overwrites_after_skip(
    dispatcher, primitive: str, ns: str, tmp_path: Path
) -> None:
    """``force=True`` MUST overwrite the previously-skipped target."""
    params = {"name": primitive, "output_dir": str(tmp_path)}

    dispatcher(action="primitive", params=params)
    target_root = tmp_path / "core" / "venous" / ns / primitive
    user_file = target_root / "user_customisation.py"
    user_file.write_text("# user code")

    forced = dispatcher(
        action="primitive",
        params={**params, "force": True},
    )
    assert forced["ok"] is True
    assert forced["result"]["status"] == "copied"
    # force=True wipes the target → user file is gone (documented destructive
    # opt-in, surfaced as a warning in the result dict).
    assert not user_file.exists(), "force=True must re-create a clean target"
    assert "warnings" in forced["result"], "destructive overwrite must warn"
