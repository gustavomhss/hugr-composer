"""Behavioral end-to-end scenarios for EventSourcedStore — proves invariants at runtime.

Each scenario picks a realistic domain aggregate (bank account, shopping
cart, order lifecycle) and drives the store through append, load, snapshot,
and replay. The invariants surface implicitly through the asserted
post-conditions: if any are violated, the scenario blows up loudly.
"""

from __future__ import annotations

import pytest

from EventSourcedStore import (
    ConcurrencyError,
    InMemoryEventSourcedStore,
    replay,
    replay_from_snapshot,
)


# ---------------------------------------------------------------------------
# Fold functions for scenarios
# ---------------------------------------------------------------------------
def _account_fold(state: object, event: object) -> dict[str, int]:
    assert isinstance(event, dict)
    base: dict[str, int] = (
        {"balance": 0, "txn_count": 0}
        if state is None
        else dict(state)  # type: ignore[arg-type]  # ESS-INV-04: state is dict
    )
    etype = event["type"]
    amount = int(event.get("amount", 0))
    if etype == "deposited":
        base["balance"] += amount
    elif etype == "withdrawn":
        base["balance"] -= amount
    base["txn_count"] += 1
    return base


def _cart_fold(state: object, event: object) -> dict[str, int]:
    assert isinstance(event, dict)
    base: dict[str, int] = {} if state is None else dict(state)  # type: ignore[arg-type]
    etype = event["type"]
    sku = str(event["sku"])
    if etype == "added":
        base[sku] = base.get(sku, 0) + int(event["qty"])
    elif etype == "removed":
        current = base.get(sku, 0)
        new_qty = current - int(event["qty"])
        if new_qty <= 0:
            base.pop(sku, None)
        else:
            base[sku] = new_qty
    return base


# ---------------------------------------------------------------------------
# Scenario 1: end-to-end bank account lifecycle with replay and snapshot
# ---------------------------------------------------------------------------
def test_scenario_account_lifecycle_with_snapshot() -> None:
    store = InMemoryEventSourcedStore()
    agg = "acct-42"
    store.append(agg, expected_version=0, events=[{"type": "deposited", "amount": 100}])
    store.append(agg, expected_version=1, events=[{"type": "deposited", "amount": 50}])
    store.append(agg, expected_version=2, events=[{"type": "withdrawn", "amount": 30}])
    state, v = replay(store, agg, _account_fold)
    assert state == {"balance": 120, "txn_count": 3}
    assert v == 3
    store.snapshot(agg, version=v, state=state)
    store.append(agg, expected_version=3, events=[{"type": "deposited", "amount": 5}])
    state2, v2 = replay_from_snapshot(store, agg, _account_fold)
    state_pure, _ = replay(store, agg, _account_fold)
    assert state2 == state_pure == {"balance": 125, "txn_count": 4}
    assert v2 == 4


# ---------------------------------------------------------------------------
# Scenario 2: two concurrent writers — one loses, MUST reload + retry
# ---------------------------------------------------------------------------
def test_scenario_two_writers_must_reload_on_conflict() -> None:
    store = InMemoryEventSourcedStore()
    agg = "cart-7"
    store.append(agg, expected_version=0, events=[{"type": "added", "sku": "A", "qty": 1}])
    writer_a_version = store.current_version(agg)
    writer_b_version = store.current_version(agg)
    # Writer A commits first.
    store.append(agg, expected_version=writer_a_version, events=[
        {"type": "added", "sku": "B", "qty": 2},
    ])
    # Writer B tries with stale version → conflict.
    with pytest.raises(ConcurrencyError):
        store.append(agg, expected_version=writer_b_version, events=[
            {"type": "added", "sku": "C", "qty": 5},
        ])
    # Writer B reloads and retries with fresh version.
    fresh = store.current_version(agg)
    store.append(agg, expected_version=fresh, events=[
        {"type": "added", "sku": "C", "qty": 5},
    ])
    cart, _ = replay(store, agg, _cart_fold)
    assert cart == {"A": 1, "B": 2, "C": 5}


# ---------------------------------------------------------------------------
# Scenario 3: append-batch all-or-nothing atomicity
# ---------------------------------------------------------------------------
def test_scenario_batch_append_is_all_or_nothing() -> None:
    store = InMemoryEventSourcedStore()
    agg = "acct-batch"
    batch = [
        {"type": "deposited", "amount": 10},
        {"type": "deposited", "amount": 20},
        {"type": "withdrawn", "amount": 5},
    ]
    new_v = store.append(agg, expected_version=0, events=batch)
    assert new_v == 3
    # Now try a batch that races — whole batch MUST be rejected.
    with pytest.raises(ConcurrencyError):
        store.append(agg, expected_version=0, events=[{"type": "deposited", "amount": 99}])
    state, _ = replay(store, agg, _account_fold)
    assert state == {"balance": 25, "txn_count": 3}


# ---------------------------------------------------------------------------
# Scenario 4: loading an unknown aggregate yields empty stream, not error
# ---------------------------------------------------------------------------
def test_scenario_unknown_aggregate_loads_empty() -> None:
    store = InMemoryEventSourcedStore()
    events = list(store.load("never-seen"))
    assert events == []
    snap = store.latest_snapshot("never-seen")
    assert snap is None
    # Fresh aggregate's first append expects version 0.
    store.append("never-seen", expected_version=0, events=[{"type": "deposited", "amount": 1}])
    assert store.current_version("never-seen") == 1


# ---------------------------------------------------------------------------
# Scenario 5: snapshot matches pure replay across a long stream
# ---------------------------------------------------------------------------
def test_scenario_snapshot_matches_pure_replay() -> None:
    store = InMemoryEventSourcedStore()
    agg = "acct-long"
    for i in range(1, 51):
        store.append(agg, expected_version=i - 1, events=[{"type": "deposited", "amount": i}])
    state_full, v_full = replay(store, agg, _account_fold)
    # Take a snapshot at an interior point.
    store.snapshot(agg, version=25, state={
        "balance": sum(range(1, 26)),
        "txn_count": 25,
    })
    state_cached, v_cached = replay_from_snapshot(store, agg, _account_fold)
    assert state_full == state_cached
    assert v_full == v_cached == 50


# ---------------------------------------------------------------------------
# Scenario 6: event immutability across audit replay
# ---------------------------------------------------------------------------
def test_scenario_audit_replay_sees_pristine_events() -> None:
    store = InMemoryEventSourcedStore()
    agg = "audit-1"
    seed = [
        {"type": "deposited", "amount": 100},
        {"type": "withdrawn", "amount": 40},
    ]
    store.append(agg, expected_version=0, events=seed)
    # Caller mutates the list AFTER append — stored events MUST NOT change.
    seed[0]["amount"] = 0
    seed[1]["amount"] = 9999
    loaded = list(store.load(agg))
    assert loaded[0] == {"type": "deposited", "amount": 100}
    assert loaded[1] == {"type": "withdrawn", "amount": 40}
