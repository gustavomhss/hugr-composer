"""Layer E — static: hash-chain evidence."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _emitted_dir() -> Path:
    p = os.environ.get("BLIND_EMITTED_DIR")
    if not p:
        pytest.skip("BLIND_EMITTED_DIR not set")
    return Path(p)


def test_E_static__hash_chain_primitive_or_sha256_used() -> None:
    root = _emitted_dir()
    text = "".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in root.rglob("*.py") if "__pycache__" not in p.parts
    )
    assert "sha256" in text.lower() or "TamperEvident" in text or "AuditChain" in text, (
        "no hash-chain / sha256 evidence in emitted source"
    )
    # Must reference prev_hash concept in some form
    assert any(k in text for k in ("prev_hash", "previous_hash", "chain_hash", "this_hash")), (
        "no prev/chain hash field in emitted source"
    )
