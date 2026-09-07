"""Native OpenCode output boundary for Composer write tools."""

from __future__ import annotations

import os
from pathlib import Path


def output_dir(value: str) -> str:
    root_value = os.getenv("HUGR_WORKTREE_ROOT", "").strip()
    if not root_value:
        return value

    root = Path(root_value).resolve()
    target = Path(value).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"output_dir must stay inside HUGR_WORKTREE_ROOT: {root}") from exc
    return str(target)
