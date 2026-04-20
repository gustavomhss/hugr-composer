"""Tests for the BI export service example."""
from __future__ import annotations

import threading

import pytest

from app import Exporter, SnapshotView


def test_same_day_export_produces_identical_bytes() -> None:
    view = SnapshotView()
    view.write_live({"id": 1, "amount": 10})
    view.write_live({"id": 2, "amount": 20})
    view.capture("2026-04-20")
    exp = Exporter(view)
    r1 = exp.run("orders", "2026-04-20")
    r2 = exp.run("orders", "2026-04-20")
    assert r1.content_hash == r2.content_hash
    assert r1.bytes_written == r2.bytes_written


def test_writers_during_export_see_no_lock_contention() -> None:
    view = SnapshotView()
    for i in range(100):
        view.write_live({"id": i})
    view.capture("2026-04-20")

    errors: list[str] = []
    done = threading.Event()

    def write_worker():
        while not done.is_set():
            try:
                view.write_live({"id": 9999})
            except Exception as e:  # pragma: no cover
                errors.append(repr(e))

    t = threading.Thread(target=write_worker, daemon=True)
    t.start()
    try:
        exp = Exporter(view)
        # Run 20 exports in quick succession — writers never block.
        for _ in range(20):
            exp.run("orders", "2026-04-20")
    finally:
        done.set()
        t.join(timeout=1.0)
    assert errors == []


def test_third_retry_failure_surfaces_yesterday_and_pages_once() -> None:
    view = SnapshotView()
    view.capture("2026-04-19")
    view.capture("2026-04-20")
    exp = Exporter(view, max_attempts=3)
    # Yesterday succeeds first.
    exp.run("orders", "2026-04-19")
    assert exp.health.last_success_by_table["orders"] == "2026-04-19"

    # Today: force every attempt to fail.
    def always_fail(attempt: int) -> None:
        raise RuntimeError(f"transient error, attempt {attempt}")

    with pytest.raises(RuntimeError):
        exp.run("orders", "2026-04-20", attempt_action=always_fail)

    # Health reports yesterday's success; exactly one page fired.
    assert exp.health.last_success_by_table["orders"] == "2026-04-19"
    assert exp.health.pages_sent == 1


def test_adhoc_older_date_does_not_block_scheduled() -> None:
    view = SnapshotView()
    view.capture("2026-04-10")
    view.capture("2026-04-20")
    exp = Exporter(view)
    # Both exports share the same exporter but different (table, date) keys.
    exp.run("orders", "2026-04-10")
    exp.run("orders", "2026-04-20")
    assert exp.output_for("orders", "2026-04-10") is not None
    assert exp.output_for("orders", "2026-04-20") is not None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
