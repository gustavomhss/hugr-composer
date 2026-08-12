"""Unit tests for MaterializedView — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from MaterializedView import (
    InMemoryMaterializedView,
    MaterializedViewInvariantError,
)


def _user_upsert(rows: dict[str, dict[str, object]], event: Mapping[str, object]) -> None:
    aid = str(event["aggregate_id"])
    payload = event.get("payload", {})
    assert isinstance(payload, Mapping)
    rows[aid] = {"aggregate_id": aid, **dict(payload)}


def _user_delete(rows: dict[str, dict[str, object]], event: Mapping[str, object]) -> None:
    rows.pop(str(event["aggregate_id"]), None)


def _wire_user_view(view: InMemoryMaterializedView) -> None:
    view.register_handler("user.upserted", _user_upsert)
    view.register_handler("user.deleted", _user_delete)


def _ev(seq: int, etype: str, aid: str, payload: dict[str, object] | None = None, version: int = 1) -> dict[str, object]:
    return {
        "type": etype,
        "aggregate_id": aid,
        "seq": seq,
        "schema_version": version,
        "payload": payload or {},
    }


# ---------------------------------------------------------------------------
# MV_INV_01 — determinism under ordered replay
# ---------------------------------------------------------------------------
def test_inv_determinism_confirms() -> None:
    stream = [
        _ev(1, "user.upserted", "u1", {"name": "Alice", "ready_to_serve": True}),
        _ev(2, "user.upserted", "u2", {"name": "Bob", "ready_to_serve": False}),
        _ev(3, "user.upserted", "u1", {"name": "Alice2", "ready_to_serve": True}),
        _ev(4, "user.deleted", "u2"),
    ]
    v1 = InMemoryMaterializedView("users")
    _wire_user_view(v1)
    for e in stream:
        v1.apply(e)

    v2 = InMemoryMaterializedView("users")
    _wire_user_view(v2)
    for e in stream:
        v2.apply(e)

    assert v1.rows() == v2.rows()
    assert list(v1.query({"ready_to_serve": True})) == list(v2.query({"ready_to_serve": True}))


def test_inv_determinism_prevents() -> None:
    # Duplicate registration of a handler is refused — would make apply() non-deterministic.
    view = InMemoryMaterializedView("users")
    view.register_handler("user.upserted", _user_upsert)
    with pytest.raises(MaterializedViewInvariantError):
        view.register_handler("user.upserted", _user_upsert)


def test_inv_determinism_under_failure() -> None:
    # At-least-once delivery: duplicate / reordered (lower-seq) events MUST be deduped.
    view = InMemoryMaterializedView("users")
    _wire_user_view(view)
    view.apply(_ev(1, "user.upserted", "u1", {"name": "A"}))
    view.apply(_ev(2, "user.upserted", "u1", {"name": "B"}))
    # Duplicate of seq=2 — ignored.
    view.apply(_ev(2, "user.upserted", "u1", {"name": "C"}))
    # Out-of-order older seq — ignored.
    view.apply(_ev(1, "user.upserted", "u1", {"name": "D"}))
    assert view.applied_event_count == 2
    rows = list(view.query({"aggregate_id": "u1"}))
    assert rows == [{"aggregate_id": "u1", "name": "B"}]


# ---------------------------------------------------------------------------
# MV_INV_02 — rebuild regenerates state from source
# ---------------------------------------------------------------------------
def test_inv_rebuild_from_source_confirms() -> None:
    source = [
        _ev(1, "user.upserted", "u1", {"name": "Alice"}),
        _ev(2, "user.upserted", "u2", {"name": "Bob"}),
        _ev(3, "user.deleted", "u1"),
    ]
    view = InMemoryMaterializedView("users")
    _wire_user_view(view)
    view.rebuild(source)
    assert view.rows() == ({"aggregate_id": "u2", "name": "Bob"},)
    assert view.last_applied_seq == 3


def test_inv_rebuild_from_source_prevents() -> None:
    # Rebuild on a handler-less view rejects unknown event types — cannot silently
    # backfill, even during rebuild.
    view = InMemoryMaterializedView("users")
    with pytest.raises(MaterializedViewInvariantError):
        view.rebuild([_ev(1, "user.upserted", "u1", {"name": "Alice"})])


def test_inv_rebuild_from_source_under_failure() -> None:
    # Mid-rebuild failure MUST NOT leave a half-filled view claiming schema-complete status.
    view = InMemoryMaterializedView("users")
    _wire_user_view(view)
    # First rebuild succeeds.
    view.rebuild([_ev(1, "user.upserted", "u1", {"name": "A"})])
    # Second rebuild hits an invalid event — the view is cleared before replay begins,
    # so query() MUST refuse until a valid rebuild lands.
    with pytest.raises(MaterializedViewInvariantError):
        view.rebuild([_ev(1, "unknown.type", "u1")])
    with pytest.raises(MaterializedViewInvariantError):
        list(view.query(None))


# ---------------------------------------------------------------------------
# MV_INV_03 — bounded staleness surfaced to callers
# ---------------------------------------------------------------------------
def test_inv_bounded_staleness_confirms() -> None:
    fake_time = [1000.0]

    def clock() -> float:
        return fake_time[0]

    view = InMemoryMaterializedView("users", max_age_s=5.0, clock=clock)
    _wire_user_view(view)
    view.apply(_ev(1, "user.upserted", "u1", {"name": "A"}))
    assert view.is_fresh()
    fake_time[0] += 3.0
    assert view.is_fresh()
    fake_time[0] += 10.0
    # Staleness now exceeds max_age_s — is_fresh() reports the truth rather than lie.
    assert not view.is_fresh()
    assert view.staleness_s() >= 13.0


def test_inv_bounded_staleness_prevents() -> None:
    # query() on a never-applied view reports +inf staleness so callers can refuse.
    view = InMemoryMaterializedView("users", max_age_s=0.1)
    _wire_user_view(view)
    assert view.staleness_s() == float("inf")
    assert not view.is_fresh()


def test_inv_bounded_staleness_under_failure() -> None:
    # Staleness never claims linearizability even if the clock jumps back
    # (monotonic clock is enforced by time.monotonic by default; here we
    # simulate a clock that goes backward to prove the view clamps to 0).
    fake_time = [1000.0]

    def clock() -> float:
        return fake_time[0]

    view = InMemoryMaterializedView("users", max_age_s=5.0, clock=clock)
    _wire_user_view(view)
    view.apply(_ev(1, "user.upserted", "u1", {"name": "A"}))
    fake_time[0] -= 100.0  # adversarial clock regression
    assert view.staleness_s() == 0.0  # clamped — never negative, never linearizable


# ---------------------------------------------------------------------------
# MV_INV_04 — schema evolution forces rebuild
# ---------------------------------------------------------------------------
def test_inv_schema_evolution_confirms() -> None:
    view = InMemoryMaterializedView("users", schema_version=1)
    _wire_user_view(view)
    view.rebuild([_ev(1, "user.upserted", "u1", {"name": "A"}, version=1)])
    assert list(view.query({"aggregate_id": "u1"})) == [{"aggregate_id": "u1", "name": "A"}]

    view.evolve_schema(2)
    # query() MUST refuse until rebuild at v2
    with pytest.raises(MaterializedViewInvariantError):
        list(view.query(None))
    view.rebuild([_ev(1, "user.upserted", "u1", {"name": "A2"}, version=2)])
    assert list(view.query({"aggregate_id": "u1"})) == [{"aggregate_id": "u1", "name": "A2"}]


def test_inv_schema_evolution_prevents() -> None:
    # Applying a mismatched-schema event is REJECTED — silent backfill is FORBIDDEN.
    view = InMemoryMaterializedView("users", schema_version=2)
    _wire_user_view(view)
    with pytest.raises(MaterializedViewInvariantError):
        view.apply(_ev(1, "user.upserted", "u1", {"name": "A"}, version=1))


def test_inv_schema_evolution_under_failure() -> None:
    # After evolve_schema, a rebuild source that still carries old-version events fails —
    # the view refuses to half-materialize across versions.
    view = InMemoryMaterializedView("users", schema_version=1)
    _wire_user_view(view)
    view.rebuild([_ev(1, "user.upserted", "u1", {"name": "A"}, version=1)])
    view.evolve_schema(2)
    with pytest.raises(MaterializedViewInvariantError):
        view.rebuild([_ev(1, "user.upserted", "u1", {"name": "A"}, version=1)])
    # After the failure, query MUST still refuse.
    with pytest.raises(MaterializedViewInvariantError):
        list(view.query(None))


# ---------------------------------------------------------------------------
# MV_INV_05 — handler registration / unknown events rejected
# ---------------------------------------------------------------------------
def test_inv_handler_registration_confirms() -> None:
    view = InMemoryMaterializedView("users")

    @view.on("user.upserted")
    def handler(rows: dict[str, dict[str, object]], event: Mapping[str, object]) -> None:
        _user_upsert(rows, event)

    view.apply(_ev(1, "user.upserted", "u1", {"name": "A"}))
    assert list(view.query({"aggregate_id": "u1"})) == [{"aggregate_id": "u1", "name": "A"}]
    assert handler is not None


def test_inv_handler_registration_prevents() -> None:
    view = InMemoryMaterializedView("users")
    _wire_user_view(view)
    # Unknown type → rejected, not silently swallowed.
    with pytest.raises(MaterializedViewInvariantError):
        view.apply(_ev(1, "payment.settled", "p1"))


def test_inv_handler_registration_under_failure() -> None:
    # Malformed events (missing required keys / wrong shape) are rejected even
    # when a handler exists for the type.
    view = InMemoryMaterializedView("users")
    _wire_user_view(view)
    with pytest.raises(MaterializedViewInvariantError):
        view.apply({"type": "user.upserted", "aggregate_id": "u1"})  # missing seq/schema_version
    with pytest.raises(MaterializedViewInvariantError):
        view.apply("not a mapping")
