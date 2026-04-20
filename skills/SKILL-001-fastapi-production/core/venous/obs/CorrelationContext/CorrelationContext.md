# CorrelationContext

## What it does (plain language)

CorrelationContext ties every log line, span, and downstream call back to the
originating request. Async tasks, queue consumers, and scheduled jobs all
inherit the same identity. Product impact: "find every operation for
request X" becomes one query instead of an archaeology project.

## Purpose

Propagate a stable request identifier and optional baggage across threads,
async tasks, and network hops so every downstream record can be joined back
to the originating request.

## When to use and when NOT to use

- USE: inbound request entry points (HTTP middleware, queue consumer), any
  outbound call that crosses a process boundary.
- DO NOT USE: to transport credentials — the authentication-reserved keys are
  stripped on ingest.
- DO NOT USE: as a general-purpose state bag — baggage is small and bounded.

## Invariants

| ID | Rule |
|---|---|
| CORR_INV_01 | request_id MUST be lowercase hex/ULID ≥ 16 chars; stable for the request. |
| CORR_INV_02 | Baggage values MUST be ASCII; ≤ 8192 bytes per entry (W3C). |
| CORR_INV_03 | activate() MUST restore prior context on exit, even under exception. |
| CORR_INV_04 | Invalid traceparent SHALL generate a fresh trace_id; NEVER empty. |
| CORR_INV_05 | Auth-reserved baggage keys FORBIDDEN; SHALL be stripped on ingest. |
| CORR_INV_06 | Context NEVER leaks across event loops; uses contextvars. |

## Thread / async safety

Based on `contextvars.ContextVar` — activation is per-task, copies on asyncio
task spawn. Concurrent threads get independent contexts.

## Operational characteristics

- Activation cost: O(1) token push; restore is O(1).
- Memory: ~few hundred bytes per context; baggage bounded to 8192 B per entry.
- Self-observability: `correlation.contexts.created`,
  `correlation.baggage.rejected.count{reason}`,
  `correlation.activations.depth`.

## Security considerations

- Authentication-reserved keys (password, authorization, cookie,
  set-cookie, proxy-authorization) are silently stripped to prevent leaks
  into shared headers.
- Baggage is ASCII-only + size-capped per W3C — oversized entries are dropped
  on ingest rather than truncated.

## Provenance

- Source agent: Agent #7 OBSERVABILITY.
- W3C Baggage Recommendation sections 3.2 and 3.3.
- OpenTelemetry Specification 1.32 — Context and Propagation.
- *Observability Engineering* (2022), chapter 4.

## Alternatives considered and rejected

- Thread-local storage — rejected: does not survive async/await.
- Manual threading through every function signature — rejected: does not
  survive framework callbacks.
- Attaching context only to the root span — rejected: logs outside the span
  lose correlation.

## Extension contract

Downstream tools register a middleware that extracts the context from inbound
transport headers (HTTP, gRPC, SQS message attributes) and compose a
propagator adapter that re-injects the context into outbound calls. Baggage
keys are extended by registering a namespaced key prefix through the bind
method.

## Usage

```python
async def enqueue_job(ctx: CorrelationContext, payload: dict, queue) -> None:
    headers = dict(ctx.to_headers())
    headers["x-request-id"] = ctx.request_id
    await queue.send(body=payload, attributes=headers)
    current = CorrelationContext.current()
    assert current.request_id == ctx.request_id
```

## Compose with:

- **End-to-end stitching** → `CorrelationId` + `StructuredLogger`
  Every log line inherits the active correlation id; one grep reconstructs the full causal chain of a request.

- **Trace-log correlation** → `Tracer` + `StructuredLogger`
  Trace id and correlation id travel together; jumping from a slow span to its logs is one click, not a timestamp search.

- **Async-safe propagation** → `MiddlewarePipeline` + `RequestContext`
  Context survives task spawning and executor handoffs — handler code never re-threads identifiers by hand.

- **Cross-shard write correlation** → `ShardedCounter` + `MetricMeter`
  Each `ShardedCounter.increment` and `reset` carries the current correlation id onto the emitted metric and audit event, so hot-key investigations can pivot from a spike straight to the originating request. Invariant gained: per-request attribution of counter mutations.
