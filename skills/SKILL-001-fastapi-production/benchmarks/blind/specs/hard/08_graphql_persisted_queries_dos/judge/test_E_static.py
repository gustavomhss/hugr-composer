"""Layer E — static: sha256-based registry evidence."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _emitted_dir() -> Path:
    p = os.environ.get("BLIND_EMITTED_DIR")
    if not p:
        pytest.skip("BLIND_EMITTED_DIR not set")
    return Path(p)


def test_E_static__sha256_persistence_registry() -> None:
    root = _emitted_dir()
    text = "".join(
        p.read_text(encoding="utf-8", errors="ignore").lower()
        for p in root.rglob("*.py") if "__pycache__" not in p.parts
    )
    assert "sha256" in text, "no SHA-256 hashing present in emitted source"
    assert "depth_limit" in text, "depth_limit not referenced in emitted source"
