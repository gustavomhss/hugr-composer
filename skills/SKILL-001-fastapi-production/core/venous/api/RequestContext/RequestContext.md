# RequestContext

## What it does (plain language)

RequestContext is the single per-request carrier for identity, headers,
correlation id, and free-form assigns. Middleware binds it once at the edge of
an inbound request; every downstream layer reads from it (and writes via
`put()`) without reaching for thread-locals or module globals. When the
response is sent, the context is disposed — so no background task can keep
mutating state that was supposed to die with the request.

## Purpose

Per-request bag that carries identity, headers, correlation id, and free-form
assigns through the handler stack without global state.

## When to use and when NOT to use

- USE: as the one place middleware attaches cross-cutting data (principal,
  tenant, trace id, deadline) for the current request.
- USE: to pass scoped state between plugs / interceptors / handlers without
  exploding signatures or relying on globals.
- DO NOT USE: as a long-lived application-level store — the context dies with
  the response.
- DO NOT USE: in background workers — take a `detached_snapshot()` and pass
  the explicit values your worker needs.

## API surface

The catalog `api_signature` is the sole authority (see
`RequestContext.contract.json`). In this repo the Protocol is backed by two
concrete classes — `MutableRequestContext` (live, per-request) and
`FrozenRequestContext` (inert, background-safe snapshot):

```python
from typing import Any, Mapping, Protocol

class RequestContext(Protocol):
    request_id: str
    principal: object | None
    headers: Mapping[str, str]
    assigns: dict[str, Any]

    def put(self, key: str, value: Any) -> 'RequestContext': ...
    def halt(self) -> 'RequestContext': ...
```

Helpers:

- `request_scope(...)` — context manager that builds and guarantees disposal.
- `DefaultRequestContextProvider.bind(...)` — the extension point a framework
  adapter implements.
- `MutableRequestContext.detached_snapshot()` — RC-INV-02 carrier for workers.
- `MutableRequestContext.for_log()` — log-safe dict with sensitive-key
  redaction.

## Invariants

| ID | Rule |
|---|---|
| RC_INV_01 | MUST be constructed once per inbound request and disposed when the response is sent. Post-dispose mutations raise. |
| RC_INV_02 | NEVER leaks across request boundaries; a background task gets a frozen `detached_snapshot()` whose `put()` / `halt()` raise. |
| RC_INV_03 | `put()` MUST be idempotent for the same (k, v); overwriting requires `overwrite=True` or raises. |
| RC_INV_04 | `halt()` MUST set `is_halted` so subsequent middleware skips; it does NOT abort already-queued response bytes. |
| RC_INV_05 | `request_id` MUST be populated; missing / blank / control-char ids are replaced with a fresh UUIDv4. |

## Invariant → test mapping

Each invariant has three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- `MutableRequestContext` protects every write with a per-instance lock; reads
  of `request_id` / `principal` / `headers` are lock-free (fields are set
  once at construction and headers is a `MappingProxyType`).
- `FrozenRequestContext` is fully immutable; sharing an instance across
  threads or asyncio tasks is safe without locking.
- `dispose()` is idempotent and safe to call from a `finally` block that may
  already have been torn down by the framework.

## Operational characteristics (for SRE)

- Zero I/O at import; a `bind()` is a dict-copy plus a UUID generation at
  worst. No network, no disk.
- Dashboards track `api.request.started` (per route), `api.request.halted`
  (per reason) and `api.request.assign_count` (histogram). Alert when halt
  rate exceeds baseline by 3σ or when p99 assign count drifts — both
  indicate a middleware regression.
- No log line emitted by this primitive contains raw sensitive-key values;
  redaction is enforced at the source (`for_log()`).

## Security considerations

- **No log injection via request_id.** CR, LF, null, C0 controls, and Unicode
  format/bidi characters trigger a UUIDv4 replacement (RC_INV_05). An
  attacker controlling an upstream `X-Request-Id` header cannot forge log
  lines.
- **Sensitive assigns redacted by default.** `for_log()` redacts values whose
  key matches `SENSITIVE_ASSIGN_KEYS` (authorization, token, api_key, …);
  `repr()` never prints values.
- **No cross-request leak.** Background workers MUST receive a
  `detached_snapshot()`; the live context's lifecycle ends with the response.
- **No silent overwrite.** `put(key, different_value)` without
  `overwrite=True` raises, so a middleware ordering bug is loud, not quiet.
- **Header casing normalised.** All headers are stored lower-case so a plug
  cannot be bypassed by an upstream that sends `AUTHORIZATION` vs
  `Authorization`.

## Provenance

- Source agent: Agent #1 FRAMEWORKS
  (`docs/research/outputs/AGENT_1_FRAMEWORKS.json`).
- Primary sources:
  - ASP.NET Core 8.0 — `HttpContext` (`.User`, `.TraceIdentifier`, `.Items`).
  - Plug 1.x (Elixir) — `Plug.Conn` (assigns, req_headers, halt/1).
  - Ruby on Rails 7 — `ActiveSupport::CurrentAttributes`.

## Alternatives considered and rejected

- Thread-local globals — break under asyncio and thread-pool executors;
  cross-request contamination is invisible.
- Per-call argument threading — explodes handler signatures and makes
  middleware composition ad-hoc.
- Plain `dict` everywhere — loses type discipline and lifecycle guarantees;
  no redaction hook; no halt flag.

## Extension contract

A framework adapter implements `RequestContextProvider.bind(...)` and attaches
the returned `RequestContext` to its framework-native request state. Handlers
read the context via dependency injection (`request.state.ctx`, a FastAPI
`Depends`, or a Plug/Conn lookup) and call `.put()` / `.halt()` as the request
threads through. The Protocol is additive: new fields MAY be exposed via
`assigns`, existing consumers keep working.

## Schema of `RequestContext.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from RequestContext import request_scope

# Edge of inbound request:
with request_scope(
    request_id=inbound_headers.get("x-request-id"),
    headers=inbound_headers,
) as ctx:
    # Auth plug:
    if "authorization" not in ctx.headers:
        ctx.halt()
    else:
        ctx.put("principal", parse_token(ctx.headers["authorization"]))

    # Tenant plug (runs only if not halted):
    if not ctx.is_halted:
        ctx.put("tenant", resolve_tenant(ctx.assigns["principal"]))

    # Handler:
    if not ctx.is_halted:
        reply = handler(ctx)

# Background worker — pass the frozen snapshot, not the live ctx:
snap = ctx.detached_snapshot()  # taken before dispose
executor.submit(audit_worker, snap)
```

## Compose with:

- **Principal propagation** → `CurrentPrincipal` + `RequestGuard`
  Authn middleware resolves the principal once and stamps the context; downstream RequestGuard reads the same frozen identity — no re-validation, no drift.

- **Cross-cutting correlation** → `CorrelationContext` + `StructuredLogger`
  Every log line emitted inside a handler inherits the request's correlation id via the context, so a single grep stitches the whole call graph.

- **Deadline-aware handlers** → `RequestShape` + `TimeoutBudget`
  The context carries the remaining budget and priority class; handlers query it before issuing downstream calls rather than racing an invisible timer.

- **Scoped per-request loader** → `DataLoader` + `RouterPipeline`
  `RequestContext` owns the request-scoped `DataLoader` instance; handlers pull it from the context rather than threading it through function signatures. Invariant gained: no cross-request cache leak and no ambient singleton DataLoader.

- **Session binding** → `SessionCache` + `CurrentPrincipal`
  The edge middleware resolves the session through SessionCache once and pins the result into `RequestContext`; handlers read one canonical identity per request regardless of which node served it.
