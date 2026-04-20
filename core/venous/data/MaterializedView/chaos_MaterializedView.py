"""Chaos / game-day tests for MaterializedView.

Simulates:
- handler crash mid-apply: subsequent apply CANNOT silently resume past the crash;
  the view MUST remain consistent with the last successfully applied seq.
- malformed event flood: every malformed event rejected, view state unchanged.
- interleaved schema evolution + live apply: post-evolution apply at old schema rejected.
- massive rebuild: 10_000-event source replays to a stable, finite view.
- duplicate / out-of-order flood: seq filter holds, view count matches distinct seqs.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from MaterializedView import (
    InMemoryMaterializedView,
    MaterializedViewInvariantError,
)


def _safe_upsert(rows: dict[str, dict[str, object]], event: Mapping[str, object]) -> None:
    aid = str(event["aggregate_id"])
    rows[aid] = {"aggregate_id": aid, "seq": event["seq"]}


def _ev(seq: int, etype: str, aid: str, version: int = 1) -> dict[str, object]:
    return {"type": etype, "aggregate_id": aid, "seq": seq, "schema_version": version}


def _mk() -> InMemoryMaterializedView:
    v = InMemoryMaterializedView("chaos")
    v.register_handler("x", _safe_upsert)
    return v


def test_chaos_handler_crash_mid_apply() -> None:
    view = InMemoryMaterializedView("chaos")
    calls = [0]

    def flaky(rows: dict[str, dict[str, object]], event: Mapping[str, object]) -> None:
        calls[0] += 1
        if calls[0] == 3:
            raise RuntimeError("handler crashed")
        aid = str(event["aggregate_id"])
        rows[aid] = {"aggregate_id": aid, "seq": event["seq"]}

    view.register_handler("x", flaky)
    view.apply(_ev(1, "x", "a1"))
    view.apply(_ev(2, "x", "a2"))
    with pytest.raises(RuntimeError):
        view.apply(_ev(3, "x", "a3"))
    # Post-crash: view still consistent at seq 2, next apply from seq 4 proceeds.
    assert view.last_applied_seq == 2
    view.apply(_ev(4, "x", "a4"))
    assert view.last_applied_seq == 4


def test_chaos_malformed_event_flood_unchanged_view() -> None:
    view = _mk()
    view.apply(_ev(1, "x", "a1"))
    snapshot = view.rows()
    malformed_inputs: list[object] = [
        "string-not-mapping",
        123,
        {"type": "x"},  # missing keys
        {"type": "x", "aggregate_id": "a", "seq": 2},  # missing schema_version
        {"type": "unknown", "aggregate_id": "a", "seq": 2, "schema_version": 1},
    ]
    rejected = 0
    for raw in malformed_inputs:
        try:
            view.apply(raw)
        except MaterializedViewInvariantError:
            rejected += 1
    assert rejected == len(malformed_inputs)
    assert view.rows() == snapshot


def test_chaos_post_evolution_apply_at_old_schema_rejected() -> None:
    view = _mk()
    view.apply(_ev(1, "x", "a1", version=1))
    view.evolve_schema(2)
    with pytest.raises(MaterializedViewInvariantError):
        view.apply(_ev(2, "x", "a1", version=1))


def test_chaos_massive_rebuild_stable() -> None:
    view = _mk()
    source = [_ev(i, "x", f"k{i % 50}") for i in range(1, 10_001)]
    view.rebuild(source)
    # 50 distinct aggregates, each overwritten by the last-seen seq for that key.
    rows = list(view.query(None))
    assert len(rows) == 50
    assert view.last_applied_seq == 10_000


def test_chaos_duplicate_and_out_of_order_flood() -> None:
    view = _mk()
    # Apply seq 1..100 normally, then re-apply every seq 3 times + inject old seqs.
    for i in range(1, 101):
        view.apply(_ev(i, "x", f"k{i}"))
    for i in range(1, 101):
        for _ in range(3):
            view.apply(_ev(i, "x", f"k{i}"))  # duplicate
        view.apply(_ev(max(1, i - 5), "x", f"k{i}"))  # out-of-order older
    # Only 100 events ever actually applied.
    assert view.applied_event_count == 100
    assert view.last_applied_seq == 100


def test_chaos_rebuild_on_empty_source_is_clean_slate() -> None:
    view = _mk()
    view.apply(_ev(1, "x", "a1"))
    view.rebuild([])
    assert view.rows() == ()
    assert view.last_applied_seq == -1
    assert view.applied_event_count == 0


def test_chaos_pending_schema_refuses_query_even_under_load() -> None:
    view = _mk()
    view.apply(_ev(1, "x", "a1", version=1))
    view.evolve_schema(2)
    # Many reads under pending schema: every one must refuse, never serve stale rows.
    for _ in range(50):
        with pytest.raises(MaterializedViewInvariantError):
            list(view.query(None))
