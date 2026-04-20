"""Layer E — static: idempotency key evidence."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _emitted_dir() -> Path:
    p = os.environ.get("BLIND_EMITTED_DIR")
    if not p:
        pytest.skip("BLIND_EMITTED_DIR not set")
    return Path(p)


def test_E_static__per_pair_dedup_structure_present() -> None:
    root = _emitted_dir()
    text = "".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in root.rglob("*.py") if "__pycache__" not in p.parts
    )
    # Either an explicit IdempotencyStore, or something keyed by the pair.
    assert any(k in text for k in ("IdempotencyStore", "IdempotentConsumer",
                                    "(customer_id", "customer_id, cycle_id",
                                    "already_charged", "_charges[", "_charged")), (
        "no per-pair dedup structure detected"
    )
    assert "customer_id" in text and "cycle_id" in text, "identifiers not used"
