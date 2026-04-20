"""Metamorphic + differential tests for RequestContext.

Algebraic properties:
- put(k, v) is idempotent under repeated application with the same v.
- put(k, v) order independence for distinct keys — the assigns mapping is
  insensitive to which of {k1, k2, k3} was put first.
- halt() is idempotent — calling halt() twice equals calling it once.
- detached_snapshot() is a projection: snapshot after put(k, v) observes v.
- dispose() is idempotent — calling dispose() twice is a no-op.
- for_log() is pure for a given state (same state → same output).
- header casing is normalised: {Authorization: x} and {authorization: x} yield
  equal header maps.
"""

from __future__ import annotations

from RequestContext import MutableRequestContext, request_scope


def test_metamorphic_put_idempotent_repeated() -> None:
    ctx = MutableRequestContext(request_id="m-1")
    ctx.put("k", "v")
    snap1 = dict(ctx.assigns)
    for _ in range(10):
        ctx.put("k", "v")
    assert dict(ctx.assigns) == snap1


def test_metamorphic_put_order_independent_for_distinct_keys() -> None:
    a = MutableRequestContext(request_id="m-2a")
    a.put("k1", "v1")
    a.put("k2", "v2")
    a.put("k3", "v3")

    b = MutableRequestContext(request_id="m-2b")
    b.put("k3", "v3")
    b.put("k1", "v1")
    b.put("k2", "v2")

    assert dict(a.assigns) == dict(b.assigns)


def test_metamorphic_halt_idempotent() -> None:
    ctx = MutableRequestContext(request_id="m-3")
    ctx.halt()
    first = ctx.is_halted
    ctx.halt()
    ctx.halt()
    assert ctx.is_halted == first == True  # noqa: E712 — explicit True parity check.


def test_metamorphic_snapshot_projects_current_state() -> None:
    ctx = MutableRequestContext(request_id="m-4")
    ctx.put("k", "v1")
    snap1 = ctx.detached_snapshot()
    ctx.put("k", "v1")  # idempotent — no change
    snap2 = ctx.detached_snapshot()
    assert snap1.assigns == snap2.assigns
    ctx.put("k", "v2", overwrite=True)
    snap3 = ctx.detached_snapshot()
    # snap1 still shows pre-overwrite value — snapshots are independent.
    assert snap1.assigns["k"] == "v1"
    assert snap3.assigns["k"] == "v2"


def test_metamorphic_dispose_idempotent() -> None:
    with request_scope(request_id="m-5") as ctx:
        pass
    # ctx is disposed exactly once by the context manager; calling again is safe.
    ctx.dispose()
    ctx.dispose()
    assert ctx.is_disposed is True


def test_metamorphic_for_log_pure() -> None:
    ctx = MutableRequestContext(request_id="m-6")
    ctx.put("k", "v")
    first = ctx.for_log()
    second = ctx.for_log()
    assert first == second


def test_metamorphic_header_casing_normalised() -> None:
    a = MutableRequestContext(request_id="m-7a", headers={"Authorization": "x"})
    b = MutableRequestContext(request_id="m-7b", headers={"authorization": "x"})
    c = MutableRequestContext(request_id="m-7c", headers={"AUTHORIZATION": "x"})
    assert dict(a.headers) == dict(b.headers) == dict(c.headers)


def test_differential_is_halted_matches_halt_call() -> None:
    # Running halt() is the only way to set is_halted.
    ctx = MutableRequestContext(request_id="m-8")
    assert ctx.is_halted is False
    ctx.halt()
    assert ctx.is_halted is True


def test_metamorphic_distinct_contexts_have_distinct_ids() -> None:
    # Two None-id contexts MUST get distinct UUIDs.
    ids: set[str] = set()
    for _ in range(100):
        ctx = MutableRequestContext(request_id=None)
        ids.add(ctx.request_id)
    assert len(ids) == 100  # every one is unique


def test_metamorphic_chained_put_returns_self() -> None:
    ctx = MutableRequestContext(request_id="m-9")
    same = ctx.put("a", 1).put("b", 2).halt()
    assert same is ctx
    assert ctx.assigns == {"a": 1, "b": 2}
    assert ctx.is_halted
