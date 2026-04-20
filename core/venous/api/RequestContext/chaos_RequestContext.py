"""Chaos / fault-injection for RequestContext.

Game-day scenarios: concurrent middleware writes, adversarial request_id
inputs, crashing handlers inside request_scope, large header maps, snapshot
contention, and repeated dispose.
"""

from __future__ import annotations

import json
import threading
import uuid

import pytest

from RequestContext import (
    FrozenRequestContext,
    MutableRequestContext,
    RequestContextError,
    request_scope,
)


def test_chaos_concurrent_put_same_value_is_safe() -> None:
    # Eight threads all race to put("k", "v"); RC-INV-03 makes this a no-op.
    ctx = MutableRequestContext(request_id="c-1")
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(500):
                ctx.put("k", "v")
        except BaseException as exc:  # pragma: no cover — any crash is a bug.
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert ctx.assigns == {"k": "v"}


def test_chaos_concurrent_put_different_values_deterministic() -> None:
    # Two threads race to put("k", different-values). Exactly one wins, the
    # other raises RequestContextError — never silent corruption.
    ctx = MutableRequestContext(request_id="c-2")
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(value: str) -> None:
        try:
            ctx.put("k", value)
            with lock:
                outcomes.append(f"ok:{value}")
        except RequestContextError:
            with lock:
                outcomes.append(f"rejected:{value}")

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert sorted(o.split(":")[0] for o in outcomes) == ["ok", "rejected"]


def test_chaos_request_id_log_injection_replaced_with_uuid() -> None:
    for bad in (
        "req\nX-Role: admin",
        "req\r\nADMIN=true",
        "req\x1b[31mFAKE\x1b[0m",
        "req\x00admin",
        "\u202euser",  # RTL override
        "\t",
    ):
        ctx = MutableRequestContext(request_id=bad)
        # Injection vector scrubbed — the id is a fresh UUIDv4 instead.
        parsed = uuid.UUID(ctx.request_id)
        assert parsed.version == 4


def test_chaos_handler_crash_still_disposes() -> None:
    captured: list[MutableRequestContext] = []

    class Boom(RuntimeError):
        pass

    with pytest.raises(Boom):
        with request_scope(request_id="c-3") as ctx:
            captured.append(ctx)
            raise Boom("kaboom")
    assert captured[0].is_disposed is True


def test_chaos_large_header_map_accepted() -> None:
    headers = {f"x-h-{i}": f"v-{i}" for i in range(5_000)}
    ctx = MutableRequestContext(request_id="c-4", headers=headers)
    assert len(ctx.headers) == 5_000
    # Look-up is O(1) — random probe.
    assert ctx.headers["x-h-2500"] == "v-2500"


def test_chaos_snapshot_isolated_from_parent_mutation() -> None:
    ctx = MutableRequestContext(request_id="c-5")
    ctx.put("k", "v1")
    snap = ctx.detached_snapshot()
    # Parent keeps mutating.
    ctx.put("k", "v2", overwrite=True)
    ctx.put("new", "added")
    ctx.halt()
    # Snapshot is frozen at the taking point.
    assert snap.assigns["k"] == "v1"
    assert "new" not in snap.assigns
    assert snap.is_halted is False


def test_chaos_snapshot_is_inert_under_write_attempts() -> None:
    ctx = MutableRequestContext(request_id="c-6")
    snap: FrozenRequestContext = ctx.detached_snapshot()
    with pytest.raises(RequestContextError):
        snap.put("k", "v")
    with pytest.raises(RequestContextError):
        snap.halt()
    # Returned assigns is a copy — external mutation is harmless.
    external = snap.assigns
    external["injected"] = True
    assert "injected" not in snap.assigns


def test_chaos_repeated_dispose_is_safe() -> None:
    ctx = MutableRequestContext(request_id="c-7")
    for _ in range(100):
        ctx.dispose()
    assert ctx.is_disposed is True


def test_chaos_header_value_newline_survives_but_does_not_break_log() -> None:
    # Header values can contain newlines (RFC 7230 folding is obsolete but
    # still seen in the wild); the primitive stores them verbatim. The
    # responsibility for log sanitisation lies with the log sink, NOT this
    # primitive — but we MUST ensure the primitive itself emits structured
    # output (dict) that a JSON serializer can escape safely.
    ctx = MutableRequestContext(
        request_id="c-8",
        headers={"x-weird": "value\nADMIN=true"},
    )
    payload = json.dumps(ctx.for_log(), sort_keys=True, default=str)
    # Newlines are escaped in JSON, so there is no literal injected line.
    assert "\\n" in payload or "\nADMIN=true" not in payload.replace("\\n", "")


def test_chaos_concurrent_snapshot_and_mutation() -> None:
    ctx = MutableRequestContext(request_id="c-9")
    snapshots: list[FrozenRequestContext] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def mutator() -> None:
        try:
            for i in range(200):
                ctx.put(f"k-{i}", i)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    def snapper() -> None:
        try:
            for _ in range(200):
                snap = ctx.detached_snapshot()
                with lock:
                    snapshots.append(snap)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    t1 = threading.Thread(target=mutator)
    t2 = threading.Thread(target=snapper)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert not errors
    assert len(snapshots) == 200
    # Every snapshot is a valid, consistent view — no torn reads.
    for s in snapshots:
        for k, v in s.assigns.items():
            assert k.startswith("k-")
            assert isinstance(v, int)


def test_chaos_halt_then_dispose_preserves_halt_flag_for_snapshot() -> None:
    ctx = MutableRequestContext(request_id="c-10")
    ctx.halt()
    snap = ctx.detached_snapshot()
    ctx.dispose()
    assert snap.is_halted is True
