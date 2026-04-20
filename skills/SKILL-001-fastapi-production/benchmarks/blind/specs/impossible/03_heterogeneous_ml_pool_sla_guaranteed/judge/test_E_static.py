"""Layer E — static: pool + capacity semantics referenced."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _emitted_dir() -> Path:
    p = os.environ.get("BLIND_EMITTED_DIR")
    if not p:
        pytest.skip("BLIND_EMITTED_DIR not set")
    return Path(p)


def test_E_static__pool_and_capacity_concepts_present() -> None:
    root = _emitted_dir()
    text = "".join(
        p.read_text(encoding="utf-8", errors="ignore").lower()
        for p in root.rglob("*.py") if "__pycache__" not in p.parts
    )
    assert "cpu" in text and "gpu" in text, "worker classes not differentiated"
    assert any(k in text for k in ("capacity", "in_flight", "semaphore", "bulkhead")), (
        "no capacity / semaphore concept in emitted source"
    )
