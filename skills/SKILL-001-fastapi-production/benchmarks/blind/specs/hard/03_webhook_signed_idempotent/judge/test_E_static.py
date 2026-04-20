"""Layer E — static scan: constant-time HMAC compare + idempotency store."""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest


def _emitted_dir() -> Path:
    p = os.environ.get("BLIND_EMITTED_DIR")
    if not p:
        pytest.skip("BLIND_EMITTED_DIR not set")
    return Path(p)


def _py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if p.is_file() and "__pycache__" not in p.parts]


def test_E_static__hmac_compared_with_compare_digest() -> None:
    """Signature comparison must use hmac.compare_digest (or secrets.compare_digest),
    not `==`. Naïve `==` leaks timing.
    """
    root = _emitted_dir()
    has_safe = False
    has_naive_eq = False
    for py in _py_files(root):
        text = py.read_text(encoding="utf-8", errors="ignore")
        if "compare_digest" in text:
            has_safe = True
        # Flag the literal pattern `signature == ...` or `sig == ...`:
        for line in text.splitlines():
            s = line.strip()
            if (("signature" in s.lower() and "==" in s) or
                (s.lower().startswith("if sig") and "==" in s)):
                if "compare_digest" not in s:
                    has_naive_eq = True
    assert has_safe, "no hmac.compare_digest / secrets.compare_digest found"
    assert not has_naive_eq, "naive `signature == ...` comparison detected"


def test_E_static__idempotency_data_structure_present() -> None:
    """Emitted code must store processed event_ids. A pure module-level
    counter without per-event deduplication is NOT acceptable.
    """
    root = _emitted_dir()
    has_store = False
    for py in _py_files(root):
        text = py.read_text(encoding="utf-8", errors="ignore")
        if ("event_id" in text and
            any(k in text for k in ("dict[", "set(", "{}", "Dict", "Set", "IdempotencyStore"))):
            has_store = True
    assert has_store, "no per-event_id store detected"
