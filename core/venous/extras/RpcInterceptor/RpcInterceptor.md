# RpcInterceptor

## What it does (plain language)

An RpcInterceptor is middleware that wraps every remote procedure call on its
way in or out. It reads or mutates metadata (auth headers, trace ids), enforces
deadlines, and translates exceptions into a uniform status shape. Multiple
interceptors compose into an ordered chain so auth, tracing, rate limiting,
and deadline discipline apply once, consistently, across every service call —
without editing each generated RPC stub.

## Purpose

Define the single middleware seam for remote calls, specifying what an
interceptor may do (call `next` once; shorten a deadline; short-circuit with
a status) and what it MUST NEVER do (extend a deadline; swallow cancellation;
inject reserved metadata prefixes).

## When to use and when NOT to use

- USE: auth/tracing/metrics/deadline enforcement applied across an entire RPC
  surface.
- DO NOT USE: per-method business validation (put that in the handler).
- DO NOT USE: cross-service workflow orchestration (use `jobs.WorkflowRun`).

## API surface

See `RpcInterceptor.contract.json` for the verbatim catalog Protocol. The
implementation `RpcInterceptor.py` re-declares it, provides three reference
interceptors (`CountingInterceptor`, `DeadlineEnforcingInterceptor`,
`CancellationAwareInterceptor`), and a `compose(chain, terminal)` helper that
folds an ordered list of interceptors into a single `Handler`.

## Invariants

| ID | Rule |
|---|---|
| RPCI_INV_01 | An interceptor MUST call `next` exactly once unless it deliberately short-circuits. |
| RPCI_INV_02 | Metadata keys ending with `-bin` ALWAYS carry binary values and CANNOT be compared as plain strings. |
| RPCI_INV_03 | Keys starting with `grpc-` are FORBIDDEN for user metadata; that prefix is reserved by the runtime. |
| RPCI_INV_04 | A deadline MUST NOT be extended; an interceptor SHALL only shorten or respect it. |
| RPCI_INV_05 | Cancellation signals NEVER cross interceptor boundaries silently; each interceptor SHALL honor cancel or raise a cancellation error. |

## Invariant -> test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- `intercept` is `async` and non-blocking; one interceptor instance MAY serve
  many concurrent calls. The reference interceptors keep mutable counters but
  rely on the GIL + `asyncio`'s single-threaded loop for visibility; under a
  multi-threaded runtime the counter access is not atomic by design (tests only
  assert outcomes, not counter linearizability).
- `compose` is pure: the returned `Handler` holds closures over the argument
  list; no global state.

## Operational characteristics (for SRE)

- One `rpc.interceptor.calls` counter label `outcome` tracks `{ok, short_circuit, cancelled, error}`.
- `rpc.interceptor.duration` histogram (ms) attributes `method` + `outcome`.
- A sustained spike in `outcome=cancelled` or `outcome=error` is the primary
  symptom of an upstream deadline too tight or a downstream service failing.
- Chain depth is bounded by configuration; composition is linear in depth.

## Security considerations

- Interceptors are the canonical enforcement point for auth + authz. A missing
  `authorization` entry SHOULD result in a short-circuit with PERMISSION_DENIED.
- Metadata MUST NOT contain secrets in plaintext logs. Combine with
  `obs.StructuredLogger` scrubbing rules before emitting `rpc.interceptor.entered`.
- RPCI-INV-03 prevents user code from masquerading as runtime-reserved keys;
  accepting those keys would let a client override trace ids or deadlines.

## Provenance

- Source agent: Agent #2 DISTRIBUTED
  (`docs/research/outputs/AGENT_2_DISTRIBUTED.json`).
- Primary sources:
  - gRPC Core Concepts guide — Metadata and Deadlines/Timeouts paragraphs.
  - gRPC Interceptors guide — Client vs Server, Interceptor ordering sections.

## Alternatives considered and rejected

- Per-method decorators — rejected because the logic is duplicated at every
  endpoint and drifts over time.
- Global monkey-patching of the RPC client — rejected because it breaks every
  upgrade of the generated stubs and hides the middleware surface.

## Extension contract

Plug an interceptor into the chain by registering it on the channel at
construction time; compose multiple interceptors as an ordered list where
earlier entries sit closer to the network and later entries closer to the
handler. The `compose(list, terminal)` helper is the canonical composition
mechanism; external adapters implement the `RpcInterceptor` Protocol and
remain swappable across gRPC, Connect, and Twirp backends.

## Schema of `RpcInterceptor.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`. See
`docs/research/CONTRACT_STANDARDS.md` section 2 (PrimitiveSpec).

## Usage

```python
class AuthInterceptor(RpcInterceptor):
    async def intercept(self, ctx: RpcContext, payload: bytes, next: Handler) -> bytes:
        if "authorization" not in ctx.metadata:
            raise PermissionError("missing token")
        return await next(ctx, payload)
```

## Compose with:

- **Symmetric middleware** → `MiddlewarePipeline` + `OutboundBinding`
  Inbound pipeline and outbound interceptors share a contract — one mental model governs every hop in and out of the service.

- **Correlation propagation** → `CorrelationContext` + `Tracer`
  Interceptors inject correlation id and trace context on every RPC; distributed traces stitch end-to-end without handler code.

- **Policy injection** → `CircuitBreaker` + `RetryPolicy`
  Resiliency policies mount as interceptors; swapping policy per call is a registration change, not a rewrite.
