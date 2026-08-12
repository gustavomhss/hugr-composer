"""Unit tests for ChangeDataCapture — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest
from ChangeDataCapture import (
    ChangeDataCaptureInvariantError,
    Connector,
    InMemoryChangeDataCapture,
)


def _row_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    return [e for e in events if e["op"] != "schema"]


# ---------------------------------------------------------------------------
# CDC_INV_01 — commit-order per transaction, no reordering
# ---------------------------------------------------------------------------
def test_inv_commit_order_confirms() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id", "total"])

    cdc.begin_tx("tx-A")
    cdc.stage_change("tx-A", "orders", "insert", 1, None, {"id": 1, "total": 10})
    cdc.stage_change("tx-A", "orders", "update", 1, {"id": 1, "total": 10}, {"id": 1, "total": 20})
    cdc.commit_tx("tx-A")

    cdc.begin_tx("tx-B")
    cdc.stage_change("tx-B", "orders", "insert", 2, None, {"id": 2, "total": 5})
    cdc.commit_tx("tx-B")

    events = _row_events(list(cdc.subscribe("orders", 0)))
    assert [(e["op"], e["key"], e["txid"]) for e in events] == [
        ("insert", 1, "tx-A"),
        ("update", 1, "tx-A"),
        ("insert", 2, "tx-B"),
    ]
    # Positions strictly increase and the tx-A block precedes tx-B.
    positions = [int(e["pos"]) for e in events]  # type: ignore[arg-type]
    assert positions == sorted(positions)
    assert positions == sorted(set(positions))


def test_inv_commit_order_prevents() -> None:
    # Cannot commit a transaction twice; cannot reuse a terminal txid.
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id"])
    cdc.begin_tx("tx-1")
    cdc.stage_change("tx-1", "orders", "insert", 1, None, {"id": 1})
    cdc.commit_tx("tx-1")

    with pytest.raises(ChangeDataCaptureInvariantError):
        cdc.commit_tx("tx-1")
    with pytest.raises(ChangeDataCaptureInvariantError):
        cdc.begin_tx("tx-1")


def test_inv_commit_order_under_failure() -> None:
    # Mid-transaction stage failure triggers rollback — no half-reads.
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id"])
    conn = Connector(cdc)

    bad_changes = [
        ("orders", "insert", 1, None, {"id": 1}),
        ("unknown_table", "insert", 2, None, {"id": 2}),  # table not registered -> stage fails
    ]
    with pytest.raises(ChangeDataCaptureInvariantError):
        conn.publish_transaction("tx-bad", bad_changes)
    # Nothing from the failed tx landed on the stream.
    events = _row_events(list(cdc.subscribe("orders", 0)))
    assert events == []


# ---------------------------------------------------------------------------
# CDC_INV_02 — monotonic position + resumable checkpoint
# ---------------------------------------------------------------------------
def test_inv_monotonic_position_confirms() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id"])
    for i in range(5):
        cdc.begin_tx(f"t{i}")
        cdc.stage_change(f"t{i}", "orders", "insert", i, None, {"id": i})
        cdc.commit_tx(f"t{i}")
    # Consumer reads everything, checkpoints, then resumes.
    events = list(cdc.subscribe("orders", 0))
    assert len(_row_events(events)) == 5
    last_pos = max(int(e["pos"]) for e in events)  # type: ignore[arg-type]
    cdc.checkpoint(last_pos)
    # Resume: no new events arrive.
    resumed = _row_events(list(cdc.subscribe("orders", cdc.checkpoint_of())))
    assert resumed == []


def test_inv_monotonic_position_prevents() -> None:
    # Checkpoint rewind is REJECTED so consumers cannot replay ack'd events.
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id"])
    cdc.begin_tx("t1")
    cdc.stage_change("t1", "orders", "insert", 1, None, {"id": 1})
    cdc.commit_tx("t1")
    cdc.checkpoint(10)
    with pytest.raises(ChangeDataCaptureInvariantError):
        cdc.checkpoint(5)
    # from_position must be a plain int >= 0.
    with pytest.raises(ChangeDataCaptureInvariantError):
        list(cdc.subscribe("orders", "not-an-int"))
    with pytest.raises(ChangeDataCaptureInvariantError):
        list(cdc.subscribe("orders", -1))


def test_inv_monotonic_position_under_failure() -> None:
    # Under concurrent appends, assigned positions remain monotonic and unique.
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    N = 20
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(tag: int) -> None:
        try:
            for i in range(N):
                txid = f"w{tag}-{i}"
                cdc.begin_tx(txid)
                cdc.stage_change(txid, "t", "insert", tag * 1000 + i, None, {"id": i})
                cdc.commit_tx(txid)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    events = _row_events(list(cdc.subscribe("t", 0)))
    assert len(events) == 4 * N
    positions = [int(e["pos"]) for e in events]  # type: ignore[arg-type]
    assert positions == sorted(positions)
    assert len(set(positions)) == len(positions)


# ---------------------------------------------------------------------------
# CDC_INV_03 — no dirty reads
# ---------------------------------------------------------------------------
def test_inv_no_dirty_reads_confirms() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id"])
    cdc.begin_tx("t1")
    cdc.stage_change("t1", "orders", "insert", 1, None, {"id": 1})
    # Subscriber sees NOTHING until commit.
    assert _row_events(list(cdc.subscribe("orders", 0))) == []
    cdc.commit_tx("t1")
    assert len(_row_events(list(cdc.subscribe("orders", 0)))) == 1


def test_inv_no_dirty_reads_prevents() -> None:
    # Rolled-back transaction NEVER surfaces to subscribers.
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id"])
    cdc.begin_tx("t1")
    cdc.stage_change("t1", "orders", "insert", 1, None, {"id": 1})
    cdc.stage_change("t1", "orders", "insert", 2, None, {"id": 2})
    cdc.rollback_tx("t1")
    assert _row_events(list(cdc.subscribe("orders", 0))) == []
    # Committing a rolled-back tx is FORBIDDEN.
    with pytest.raises(ChangeDataCaptureInvariantError):
        cdc.commit_tx("t1")


def test_inv_no_dirty_reads_under_failure() -> None:
    # Exception in the middle of staging rolls back; no partial events visible.
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id"])
    conn = Connector(cdc)

    def gen():  # type: ignore[no-untyped-def]
        yield ("orders", "insert", 1, None, {"id": 1})
        yield ("orders", "insert", 2, None, {"id": 2})
        raise RuntimeError("upstream crashed")

    with pytest.raises(RuntimeError):
        conn.publish_transaction("tx-crash", gen())
    assert _row_events(list(cdc.subscribe("orders", 0))) == []


# ---------------------------------------------------------------------------
# CDC_INV_04 — schema events surface before old-parser row events
# ---------------------------------------------------------------------------
def test_inv_schema_events_confirms() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id", "total"])
    cdc.begin_tx("t1")
    cdc.stage_change("t1", "orders", "insert", 1, None, {"id": 1, "total": 10})
    cdc.commit_tx("t1")

    new_v = cdc.evolve_schema("orders", ["id", "total", "currency"])
    assert new_v == 2

    cdc.begin_tx("t2")
    cdc.stage_change("t2", "orders", "insert", 2, None, {"id": 2, "total": 20, "currency": "USD"})
    cdc.commit_tx("t2")

    events = list(cdc.subscribe("orders", 0))
    # Schema events appear before the row events at the new version.
    schemas = [e for e in events if e["op"] == "schema"]
    assert [int(s["schema_version"]) for s in schemas] == [1, 2]  # type: ignore[arg-type]
    # Row events carry the schema_version captured at stage time.
    row_versions = [int(e["schema_version"]) for e in events if e["op"] != "schema"]  # type: ignore[arg-type]
    assert row_versions == [1, 2]
    assert cdc.schema("orders")["schema_version"] == 2


def test_inv_schema_events_prevents() -> None:
    # Double-registering a table is REJECTED — schema state cannot silently overwrite.
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    with pytest.raises(ChangeDataCaptureInvariantError):
        cdc.register_table("t", ["id", "x"])
    # Staging against an unregistered table is REJECTED — parsers cannot bind blindly.
    cdc.begin_tx("tx")
    with pytest.raises(ChangeDataCaptureInvariantError):
        cdc.stage_change("tx", "unknown", "insert", 1, None, {"id": 1})
    cdc.rollback_tx("tx")


def test_inv_schema_events_under_failure() -> None:
    # Concurrent consumers always observe a schema event before any row at the new version.
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id"])
    # Produce N row events at v1, then evolve, then more row events at v2.
    for i in range(5):
        cdc.begin_tx(f"a{i}")
        cdc.stage_change(f"a{i}", "orders", "insert", i, None, {"id": i})
        cdc.commit_tx(f"a{i}")
    cdc.evolve_schema("orders", ["id", "tax"])
    for i in range(5):
        cdc.begin_tx(f"b{i}")
        cdc.stage_change(f"b{i}", "orders", "insert", 100 + i, None, {"id": 100 + i, "tax": 1})
        cdc.commit_tx(f"b{i}")

    events = list(cdc.subscribe("orders", 0))
    # Track schema_version as we walk the log; any row event MUST carry a version
    # no greater than the most recent schema event's version.
    cur_schema_v = 0
    for ev in events:
        if ev["op"] == "schema":
            cur_schema_v = int(ev["schema_version"])  # type: ignore[arg-type]
        else:
            assert int(ev["schema_version"]) <= cur_schema_v  # type: ignore[arg-type]
            assert cur_schema_v >= 1
