"""Layer E — static: evidence of event-store + outbox data structures."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _emitted_dir() -> Path:
    p = os.environ.get("BLIND_EMITTED_DIR")
    if not p:
        pytest.skip("BLIND_EMITTED_DIR not set")
    return Path(p)


def test_E_static__event_and_outbox_structures_present() -> None:
    root = _emitted_dir()
    text = "".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in root.rglob("*.py") if "__pycache__" not in p.parts
    )
    assert any(k in text for k in ("OrderCreated", "OrderConfirmed", "event_type", "events")), (
        "no event-type names visible in source"
    )
    assert "outbox" in text.lower(), "no outbox data structure referenced"


def test_E_static__no_naive_dual_write() -> None:
    """A common naked anti-pattern: write state THEN try to emit an event,
    with no atomicity guarantee. Detect the most obvious form: a function
    that calls state_mutation() and OUTBOX_APPEND on separate lines with
    no explicit ordering comment or lock.

    Heuristic: at least one function must reference BOTH `_events` /
    `events` AND `outbox` / `_outbox` in the same module — evidence of
    co-located bookkeeping.
    """
    root = _emitted_dir()
    ok = False
    for py in root.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        has_events = any(k in text for k in ("_events", "events", "EventStream", "event_store"))
        has_outbox = "outbox" in text.lower()
        if has_events and has_outbox:
            ok = True
            break
    assert ok, "no module co-locates events + outbox (likely dual write)"
