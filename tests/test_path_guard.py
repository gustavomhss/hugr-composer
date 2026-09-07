from __future__ import annotations

import pytest

from mcp_tools.path_guard import output_dir


def test_output_dir_stays_inside_native_worktree(tmp_path, monkeypatch):
    root = tmp_path / "worktree"
    root.mkdir()
    monkeypatch.setenv("HUGR_WORKTREE_ROOT", str(root))

    assert output_dir(str(root / "generated")) == str(root / "generated")
    with pytest.raises(ValueError, match="HUGR_WORKTREE_ROOT"):
        output_dir(str(tmp_path / "outside"))
