"""Layer E — static: export registry structure."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _emitted_dir() -> Path:
    p = os.environ.get("BLIND_EMITTED_DIR")
    if not p:
        pytest.skip("BLIND_EMITTED_DIR not set")
    return Path(p)


def test_E_static__dataset_validation_present() -> None:
    root = _emitted_dir()
    text = "".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in root.rglob("*.py") if "__pycache__" not in p.parts
    )
    for ds in ("orders", "users", "events"):
        assert ds in text, f"dataset {ds!r} not referenced in emitted source"
    assert "partition" in text, "'partition' concept not in emitted source"
