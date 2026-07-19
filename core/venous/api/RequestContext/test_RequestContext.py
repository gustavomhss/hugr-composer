"""Unit tests for RequestContext — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import uuid

import pytest
from RequestContext import (
    DefaultRequestContextProvider,
    FrozenRequestContext,
    MutableRequestContext,
    RequestContextError,
    request_scope,
)


# ---------------------------------------------------------------------------
# RC_INV_01 — lifecycle: constructed once per request, disposed at end
# ---------------------------------------------------------------------------
def test_inv_lifecycle_confirms() -> None:
    ctx = MutableRequestContext(request_id="req-1", headers={"x-trace": "t1"})
    assert ctx.is_disposed is False
    ctx.put("user_id", "u-1")
    assert ctx.assigns["user_id"] == "u-1"
    ctx.dispose()
    assert ctx.is_disposed is True
    # Read-side still works after dispose — late logger may emit.
    assert ctx.request_id == "req-1"
    assert ctx.assigns["user_id"] == "u-1"


def test_inv_lifecycle_prevents() -> None:
    ctx = MutableRequestContext(request_id="req-2")
    ctx.dispose()
    # put() on a disposed context is rejected.
    with pytest.raises(RequestContextError):
        ctx.put("k", "v")
    # halt() on a disposed context is rejected.
    with pytest.raises(RequestContextError):
        ctx.halt()


def test_inv_lifecycle_under_failure() -> None:
    # request_scope MUST dispose even if the handler raises.
    captured: dict[str, MutableRequestContext] = {}

    class Boom(RuntimeError):
        pass

    with pytest.raises(Boom), request_scope(request_id="req-3") as ctx:
        captured["ctx"] = ctx
        ctx.put("k", "v")
        raise Boom("handler exploded")
    assert captured["ctx"].is_disposed is True
    with pytest.raises(RequestContextError):
        captured["ctx"].put("late", "write")


# ---------------------------------------------------------------------------
# RC_INV_02 — no leak across request boundaries
# ---------------------------------------------------------------------------
def test_inv_no_leak_confirms() -> None:
    ctx = MutableRequestContext(request_id="req-4", headers={"a": "1"})
    ctx.put("user", "alice")
    snap = ctx.detached_snapshot()
    assert isinstance(snap, FrozenRequestContext)
    assert snap.request_id == "req-4"
    assert snap.headers["a"] == "1"
    assert snap.assigns["user"] == "alice"


def test_inv_no_leak_prevents() -> None:
    ctx = MutableRequestContext(request_id="req-5")
    snap = ctx.detached_snapshot()
    # Snapshot refuses put() — background worker MUST NOT mutate parent state.
    with pytest.raises(RequestContextError):
        snap.put("escalate", True)
    # Snapshot refuses halt().
    with pytest.raises(RequestContextError):
        snap.halt()


def test_inv_no_leak_under_failure() -> None:
    # After the parent is disposed, a previously-taken snapshot remains
    # usable but continues to be inert: mutating the parent's assigns via the
    # live dict does NOT retroactively rewrite the snapshot.
    ctx = MutableRequestContext(request_id="req-6")
    ctx.put("k", "v1")
    snap = ctx.detached_snapshot()
    ctx.put("k", "v1")  # idempotent no-op
    ctx.put("k", "v2", overwrite=True)
    ctx.dispose()
    assert snap.assigns["k"] == "v1"
    # Snapshot's .assigns returns a fresh dict copy — mutating it does not
    # change the snapshot's internal view.
    external = snap.assigns
    external["k"] = "tampered"
    assert snap.assigns["k"] == "v1"


# ---------------------------------------------------------------------------
# RC_INV_03 — put() idempotent, explicit overwrite
# ---------------------------------------------------------------------------
def test_inv_put_idempotent_confirms() -> None:
    ctx = MutableRequestContext(request_id="req-7")
    ctx.put("user_id", "u-1")
    # Same (k, v) is a no-op — no error, no change.
    ctx.put("user_id", "u-1")
    ctx.put("user_id", "u-1")
    assert ctx.assigns == {"user_id": "u-1"}


def test_inv_put_idempotent_prevents() -> None:
    ctx = MutableRequestContext(request_id="req-8")
    ctx.put("user_id", "u-1")
    # Attempt to overwrite with a different value WITHOUT overwrite=True.
    with pytest.raises(RequestContextError):
        ctx.put("user_id", "u-2")
    # Empty / whitespace / non-str keys rejected.
    with pytest.raises(RequestContextError):
        ctx.put("", "v")
    with pytest.raises(RequestContextError):
        ctx.put("  k  ", "v")
    with pytest.raises(RequestContextError):
        ctx.put(123, "v")  # type: ignore[arg-type]  # RC-INV-03: non-str key rejected.


def test_inv_put_idempotent_under_failure() -> None:
    ctx = MutableRequestContext(request_id="req-9")
    ctx.put("user_id", "u-1")
    # Explicit overwrite IS allowed.
    ctx.put("user_id", "u-2", overwrite=True)
    assert ctx.assigns["user_id"] == "u-2"
    # Chaining returns self.
    same = ctx.put("k1", "v1").put("k2", "v2")
    assert same is ctx
    assert ctx.assigns["k1"] == "v1"
    assert ctx.assigns["k2"] == "v2"


# ---------------------------------------------------------------------------
# RC_INV_04 — halt() signals skip, does not abort queued bytes
# ---------------------------------------------------------------------------
def test_inv_halt_skips_confirms() -> None:
    ctx = MutableRequestContext(request_id="req-10")
    assert ctx.is_halted is False
    ctx.halt()
    assert ctx.is_halted is True
    # halt() is idempotent — calling again does not flip or crash.
    ctx.halt()
    assert ctx.is_halted is True


def test_inv_halt_skips_prevents() -> None:
    # halt() does NOT freeze the context — middleware can still attach
    # diagnostic assigns before the response is emitted (RC-INV-04 carveout:
    # the primitive does not touch bytes).
    ctx = MutableRequestContext(request_id="req-11")
    ctx.halt()
    ctx.put("halt_reason", "unauthenticated")
    assert ctx.is_halted is True
    assert ctx.assigns["halt_reason"] == "unauthenticated"
    # halt() does NOT dispose — a disposed context is a separate state.
    assert ctx.is_disposed is False


def test_inv_halt_skips_under_failure() -> None:
    # A halted context still returns its request_id and headers for logging.
    ctx = MutableRequestContext(
        request_id="req-12",
        headers={"x-correlation-id": "corr-abc"},
    )
    ctx.halt()
    assert ctx.request_id == "req-12"
    assert ctx.headers["x-correlation-id"] == "corr-abc"
    # Detached snapshot of a halted context preserves the flag.
    snap = ctx.detached_snapshot()
    assert snap.is_halted is True


# ---------------------------------------------------------------------------
# RC_INV_05 — request_id populated, blank/control-char → UUIDv4
# ---------------------------------------------------------------------------
def test_inv_request_id_confirms() -> None:
    ctx = MutableRequestContext(request_id="req-abc-123")
    assert ctx.request_id == "req-abc-123"


def test_inv_request_id_prevents() -> None:
    # None → generated UUIDv4.
    ctx = MutableRequestContext(request_id=None)
    parsed = uuid.UUID(ctx.request_id)
    assert parsed.version == 4
    # Empty string → UUIDv4.
    ctx2 = MutableRequestContext(request_id="")
    uuid.UUID(ctx2.request_id)
    # Whitespace-only → UUIDv4.
    ctx3 = MutableRequestContext(request_id="   ")
    uuid.UUID(ctx3.request_id)
    # Control-char id → UUIDv4 replacement (no log injection).
    ctx4 = MutableRequestContext(request_id="req\ninjected")
    parsed4 = uuid.UUID(ctx4.request_id)
    assert parsed4.version == 4


def test_inv_request_id_under_failure() -> None:
    # Non-str id is rejected outright — this is a programming error, not
    # "user input" that can be salvaged.
    with pytest.raises(RequestContextError):
        MutableRequestContext(request_id=123)  # type: ignore[arg-type]  # RC-INV-05: non-str rejected.
    # Two back-to-back None ids yield distinct UUIDs (no state leaking).
    a = MutableRequestContext(request_id=None).request_id
    b = MutableRequestContext(request_id=None).request_id
    assert a != b


# ---------------------------------------------------------------------------
# Provider construction path
# ---------------------------------------------------------------------------
def test_provider_binds_context_with_defaults() -> None:
    provider = DefaultRequestContextProvider()
    ctx = provider.bind(request_id=None, headers={"x-key": "v"}, principal=None)
    assert ctx.request_id  # populated
    assert ctx.headers["x-key"] == "v"
    assert ctx.principal is None
