"""Layer E — static: locking discipline or optimistic version tag."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _emitted_dir() -> Path:
    p = os.environ.get("BLIND_EMITTED_DIR")
    if not p:
        pytest.skip("BLIND_EMITTED_DIR not set")
    return Path(p)


def test_E_static__concurrency_control_primitive_present() -> None:
    root = _emitted_dir()
    text = "".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in root.rglob("*.py") if "__pycache__" not in p.parts
    )
    has_lock = any(k in text for k in
                   ("threading.Lock", "threading.RLock",
                    "asyncio.Lock", "OptimisticConcurrency"))
    assert has_lock, "no explicit concurrency primitive in emitted source"
