"""Metamorphic + differential tests for MaterializedView.

Algebraic properties:
- apply-in-order = rebuild-from-same-source (idempotent projection)
- rebuild then same-stream apply = rebuild alone (monotonic seq filter)
- duplicate events collapse to single-application (dedupe law)
- query(empty) returns all rows equal to rows()
- two replicas processing the same ordered stream converge byte-identical
"""

from __future__ import annotations

from collections.abc import Mapping

from MaterializedView import InMemoryMaterializedView


def _counter_upsert(rows: dict[str, dict[str, object]], event: Mapping[str, object]) -> None:
    aid = str(event["aggregate_id"])
    payload = event.get("payload", {})
    assert isinstance(payload, Mapping)
    delta_raw = payload.get("delta", 0)
    delta = int(delta_raw) if isinstance(delta_raw, int) and not isinstance(delta_raw, bool) else 0
    existing = rows.get(aid, {"aggregate_id": aid, "count": 0})
    current_count_raw = existing.get("count", 0)
    current_count = int(current_count_raw) if isinstance(current_count_raw, int) and not isinstance(current_count_raw, bool) else 0
    existing["count"] = current_count + delta
    rows[aid] = existing


def _ev(seq: int, aid: str, delta: int, version: int = 1) -> dict[str, object]:
    return {
        "type": "counter.incr",
        "aggregate_id": aid,
        "seq": seq,
        "schema_version": version,
        "payload": {"delta": delta},
    }


def _build() -> InMemoryMaterializedView:
    v = InMemoryMaterializedView("counters")
    v.register_handler("counter.incr", _counter_upsert)
    return v


def test_metamorphic_apply_equals_rebuild() -> None:
    stream = [_ev(i, f"c{i % 3}", delta=i) for i in range(1, 21)]

    apply_view = _build()
    for e in stream:
        apply_view.apply(e)

    rebuild_view = _build()
    rebuild_view.rebuild(stream)

    assert apply_view.rows() == rebuild_view.rows()


def test_metamorphic_rebuild_then_replay_is_noop() -> None:
    stream = [_ev(i, "c1", delta=1) for i in range(1, 6)]
    view = _build()
    view.rebuild(stream)
    before = view.rows()
    # Replaying the same stream must not double-apply — seq filter dedupes.
    for e in stream:
        view.apply(e)
    assert view.rows() == before


def test_metamorphic_duplicate_events_collapse() -> None:
    view = _build()
    view.apply(_ev(1, "c1", 5))
    for _ in range(10):
        view.apply(_ev(1, "c1", 5))  # duplicates
    rows = list(view.query({"aggregate_id": "c1"}))
    assert rows == [{"aggregate_id": "c1", "count": 5}]


def test_metamorphic_query_empty_equals_all_rows() -> None:
    view = _build()
    for i in range(1, 6):
        view.apply(_ev(i, f"c{i}", delta=i))
    # query({}) and query(None) must both return every row.
    empty_query = sorted(
        [dict(r) for r in view.query({})],
        key=lambda r: str(r["aggregate_id"]),
    )
    none_query = sorted(
        [dict(r) for r in view.query(None)],
        key=lambda r: str(r["aggregate_id"]),
    )
    rows_snapshot = sorted(
        [dict(r) for r in view.rows()],
        key=lambda r: str(r["aggregate_id"]),
    )
    assert empty_query == none_query == rows_snapshot


def test_differential_two_replicas_converge() -> None:
    stream = [_ev(i, f"c{i % 4}", delta=1) for i in range(1, 41)]
    a = _build()
    b = _build()
    for e in stream:
        a.apply(e)
        b.apply(e)
    assert a.rows() == b.rows()
    assert a.last_applied_seq == b.last_applied_seq


def test_metamorphic_rebuild_drops_prior_state() -> None:
    # rebuild must be a pure function of the source — any prior applied events
    # must NOT leak into the post-rebuild view.
    view = _build()
    view.apply(_ev(1, "c1", 100))  # prior state: c1.count == 100
    assert list(view.query({"aggregate_id": "c1"})) == [{"aggregate_id": "c1", "count": 100}]
    # Rebuild from an unrelated source — c1 must vanish.
    view.rebuild([_ev(1, "c2", 7)])
    assert list(view.query({"aggregate_id": "c1"})) == []
    assert list(view.query({"aggregate_id": "c2"})) == [{"aggregate_id": "c2", "count": 7}]
