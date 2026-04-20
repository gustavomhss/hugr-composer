"""Layer E — static: separate-bucket-per-class structure present."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _emitted_dir() -> Path:
    p = os.environ.get("BLIND_EMITTED_DIR")
    if not p:
        pytest.skip("BLIND_EMITTED_DIR not set")
    return Path(p)


def test_E_static__class_names_present_in_source() -> None:
    """Evidence that the three priority classes are first-class in the
    emitted code (naked agents often collapse everything to one bucket)."""
    root = _emitted_dir()
    all_text = "".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in root.rglob("*.py") if "__pycache__" not in p.parts
    )
    for tok in ("gold", "silver", "bronze"):
        assert tok in all_text, f"class label {tok!r} absent from emitted source"
    # There must be SOME form of per-class state/config — dict, mapping,
    # or three separate limiters.
    assert any(
        k in all_text for k in ("{\"gold\"", "'gold':", '"gold":', "gold_", "GOLD", "CLASS_")
    ), "no per-class bucket/config structure visible"
