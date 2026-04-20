"""Behavioral end-to-end scenarios for RequestContext — proves invariants at runtime."""

from __future__ import annotations

import json
import uuid

import pytest

from RequestContext import (
    FrozenRequestContext,
    MutableRequestContext,
    RequestContextError,
    request_scope,
)


def test_scenario_middleware_pipeline_threads_state() -> None:
    # A request enters, auth middleware stamps a principal, tenant middleware
    # stamps the tenant, handler reads both. No globals, no thread-locals.
    with request_scope(request_id="req-pipeline-1") as ctx:
        ctx.put("principal", "alice")
        ctx.put("tenant", "acme")
        assert ctx.assigns["principal"] == "alice"
        assert ctx.assigns["tenant"] == "acme"
        assert ctx.is_halted is False
    # After the `with` block, the context is disposed (RC-INV-01).
    assert ctx.is_disposed is True


def test_scenario_auth_plug_halts_missing_authorization() -> None:
    # Exact parity with the catalog `consumption_example`.
    with request_scope(request_id="req-auth-1", headers={}) as ctx:
        if "authorization" not in ctx.headers:
            ctx.halt()
        assert ctx.is_halted is True

    with request_scope(
        request_id="req-auth-2",
        headers={"Authorization": "Bearer x"},
    ) as ctx2:
        # Header casing is normalised to lower-case.
        assert "authorization" in ctx2.headers
        ctx2.put("principal", {"sub": "alice"})
        assert ctx2.is_halted is False


def test_scenario_background_task_receives_snapshot() -> None:
    # A handler kicks off a worker and MUST pass the snapshot, not the live
    # context — RC-INV-02.
    def worker(snapshot: FrozenRequestContext) -> str:
        # Worker observes the value at the time of the snapshot.
        return f"{snapshot.request_id}:{snapshot.assigns.get('user', '?')}"

    with request_scope(request_id="req-bg-1") as ctx:
        ctx.put("user", "alice")
        snap = ctx.detached_snapshot()
        # Parent goes on; worker uses snapshot.
        ctx.put("user", "bob", overwrite=True)
        result = worker(snap)
    assert result == "req-bg-1:alice"
    # Attempting to run the worker with the live context is a type-level
    # option, but the snapshot is the safe contract.
    with pytest.raises(RequestContextError):
        snap.put("escalate", True)


def test_scenario_idempotent_middleware_rebinding() -> None:
    # A correlation-id middleware re-runs because of a retry and rebinds the
    # same value — it MUST be a no-op (RC-INV-03).
    with request_scope(request_id="req-idem-1") as ctx:
        ctx.put("correlation_id", "corr-1")
        ctx.put("correlation_id", "corr-1")  # no-op
        # A bug would overwrite silently; the primitive raises on intent.
        with pytest.raises(RequestContextError):
            ctx.put("correlation_id", "corr-2")


def test_scenario_request_id_generated_when_client_omits() -> None:
    # Client did not send a correlation header; the primitive MUST synthesise
    # one so every log line has an id (RC-INV-05).
    with request_scope(request_id=None) as ctx:
        uuid.UUID(ctx.request_id)
    # Two concurrent requests get distinct ids.
    with request_scope(request_id=None) as a, request_scope(request_id=None) as b:
        assert a.request_id != b.request_id


def test_scenario_log_line_never_leaks_sensitive_assigns() -> None:
    with request_scope(request_id="req-log-1") as ctx:
        ctx.put("user", "alice")
        ctx.put("authorization", "Bearer sk-live-LEAK")
        ctx.put("api_key", "AKIA-LEAK")
        line = json.dumps(ctx.for_log(), sort_keys=True, default=str)
    assert "sk-live-LEAK" not in line
    assert "AKIA-LEAK" not in line
    # Non-sensitive assigns survive verbatim so operators can debug.
    assert "alice" in line


def test_scenario_halt_does_not_abort_response_bytes() -> None:
    # RC-INV-04: halt() is a flag, not a kill switch. A handler that has
    # already started streaming bytes MUST complete the stream even if halt()
    # fires mid-way. The primitive never touches those bytes.
    emitted: list[bytes] = []
    with request_scope(request_id="req-halt-1") as ctx:
        emitted.append(b"header")
        ctx.halt()
        # Subsequent middleware observes is_halted and skips — but the handler
        # that is already emitting can keep emitting.
        if not ctx.is_halted:  # pragma: no cover — the branch not taken proves skip semantics.
            emitted.append(b"skipped-body")
        emitted.append(b"already-queued-body")
    assert emitted == [b"header", b"already-queued-body"]


def test_scenario_context_not_mistakenly_reused_across_requests() -> None:
    # A buggy handler kept a reference to last request's ctx and tries to use
    # it for the next request — the disposed flag MUST stop all writes.
    with request_scope(request_id="req-boundary-1") as first:
        first.put("user", "alice")
    # Simulated "next request" reusing the old reference.
    with pytest.raises(RequestContextError):
        first.put("user", "mallory", overwrite=True)
    # A fresh context for the new request is the only safe path.
    with request_scope(request_id="req-boundary-2") as second:
        second.put("user", "bob")
        assert second.request_id != first.request_id


def test_scenario_headers_are_case_insensitive_snapshot() -> None:
    # HTTP/2 uses lower-case headers; the primitive normalises on intake so
    # plugs do not have to guess casing.
    with request_scope(
        request_id="req-hdr-1",
        headers={"Authorization": "Bearer x", "X-Trace-Id": "t-1"},
    ) as ctx:
        assert ctx.headers["authorization"] == "Bearer x"
        assert ctx.headers["x-trace-id"] == "t-1"


def test_scenario_context_is_instance_of_protocol() -> None:
    # MutableRequestContext and FrozenRequestContext both satisfy the catalog
    # Protocol via runtime_checkable, so framework adapters can depend on the
    # Protocol and not the concrete class.
    from RequestContext import RequestContext as RequestContextProto
    ctx = MutableRequestContext(request_id=None)
    assert isinstance(ctx, RequestContextProto)
    snap = ctx.detached_snapshot()
    assert isinstance(snap, RequestContextProto)
