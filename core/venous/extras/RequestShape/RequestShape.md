# RequestShape

## What it does (plain language)

RequestShape is a single immutable record that every request carries from
edge to worker to queue and back. It captures four load-bearing facts about
the request: WHO it is (request_id, origin), HOW URGENT it is (priority),
WHEN it must be done by (deadline_ns), and WHETHER this is a retry of a
logical operation already in flight (idempotency_key, attempt). Every
downstream resiliency primitive — load shedding, bulkheading, timeouts,
circuit breaking, retries — relies on this context being consistent across
every hop. Without it, retries amplify, priority inversion appears, and
idempotency keys get dropped.

## Purpose

Capture a request's resiliency context (priority class, deadline,
idempotency key, retry-count-so-far) in a single immutable record
propagated across boundaries.

## When to use and when NOT to use

- USE: at every network boundary (HTTP handler, gRPC interceptor, queue
  consumer) to parse inbound context and propagate on outbound calls.
- USE: as the canonical input to LoadShedder, TimeoutBudget, RetryPolicy,
  CircuitBreaker, and FallbackChain.
- DO NOT USE: for request BODY inspection — RequestShape captures the
  TYPE of the request (route pattern, size class, priority), not its
  contents. Use explicit domain types for payload fields.
- DO NOT USE: for audit trails — spans / AuditEvent are the tamper-evident
  primitives.

## API surface

The catalog `api_signature` in `RequestShape.contract.json` is the sole
authority. The reference implementation `ImmutableRequestShape` is a
frozen `@dataclass` with two load-bearing methods:

- `to_headers() -> dict[str, str]` — serialise to a flat header dict. The
  wire format is versioned via `x-shape-version` so adopters can upgrade
  without breaking in-flight traffic.
- `from_headers(headers) -> RequestShape` — parse a header dict,
  preserving unknown entries in `extras`. Case-insensitive per HTTP spec.

Two non-Protocol convenience methods support common retry flows:
`with_incremented_attempt()` and `with_next_attempt(n, next_idempotency_key)`.

A `shape_hash(method, route_pattern, header_keys, body_bytes)` helper
computes a coarse fingerprint over the REQUEST TYPE (method, route, header
key-set, size bucket, priority) — not a model, just a SHA-256 over a
canonical string. Downstream anomaly detection uses this hash to answer:
"is this request shaped like what this route usually handles?"

## Invariants

| ID | Rule |
|---|---|
| RSHP_INV_01 | Fields on a RequestShape instance MUST be immutable after construction; in-place mutation is FORBIDDEN. |
| RSHP_INV_02 | A request without an explicit priority SHALL default to normal and NEVER silently to critical. |
| RSHP_INV_03 | The attempt counter MUST monotonically increase; a decrement CANNOT occur and breaks retry accounting. |
| RSHP_INV_04 | to_headers and from_headers SHALL be mutual inverses on the defined fields, round-tripping without loss. |
| RSHP_INV_05 | An idempotency_key once set MUST NEVER be altered across retries of the same logical request. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

Immutability (RSHP-INV-01) makes RequestShape trivially safe to share across
threads and async tasks. `with_next_attempt` / `with_incremented_attempt`
return NEW instances, so retry loops cannot corrupt a shape held by a peer.

## Operational characteristics (for SRE)

- Construction is O(1) and allocates a single frozen dataclass plus one
  small dict (`extras`). No I/O, no hidden caches.
- `to_headers` is O(n) in the number of extras; typical 6 fields.
- `from_headers` is O(n) in header count and allocates one lowercase-keyed
  dict internally.
- `shape_hash` is O(n) in the number of header keys plus one SHA-256 of
  a short canonical string.
- Self-observability: counters for `request.shape.constructed`,
  `request.shape.reject` (labelled by violated invariant id), and a
  histogram `request.shape.attempt` that feeds retry-budget dashboards.

## Security considerations

- RequestShape MUST NOT carry credentials. `idempotency_key` is a client-
  chosen identifier, not a secret; treat it as low-entropy and log-safe.
  Adopters that derive it from user input should hash-prefix with a salt.
- The priority field is derived by a `PriorityPolicy` hook from the
  authenticated principal / tenant / route. NEVER trust an incoming
  `x-priority` header from an unauthenticated source to claim `critical`
  tier without policy enforcement at the edge.
- `from_headers` rejects malformed input (non-str keys/values, bad
  deadline, negative attempt, unknown priority) rather than silently
  coercing — this keeps parser-differential attacks off the table.
- Unknown vendor extras are preserved verbatim; callers MUST NOT include
  sensitive data in arbitrary extras because downstream systems may log
  them for trace correlation.

## Provenance

- Source agent: Agent #4 RESILIENCY
  (`docs/research/outputs/AGENT_4_RESILIENCY.json`).
- Primary sources:
  - Google SRE Workbook (Beyer et al., O'Reilly, 2018) — chapter 21
    "Managing Load" on criticality and client-side throttling.
  - Envoy proxy docs — HTTP connection manager, `x-envoy-expected-rq-timeout-ms`.
  - Nygard, *Release It!* 2nd ed. (2018) — chapter 8 on request-context
    propagation.

## Alternatives considered and rejected

- Ad-hoc headers per client — rejected: names diverge, cannot be validated
  end-to-end, and idempotency-key naming collisions appear on the wire.
- Thread-local storage only — rejected: breaks across async boundaries
  (contextvars help but still don't cross worker processes or queues).
- Rebuild context per layer — rejected: wastes CPU and NEVER preserves
  idempotency keys reliably across hops.

## Extension contract

Adopters register a `HeaderAdapter` per transport (HTTP, gRPC metadata,
queue attributes) and a `PriorityPolicy` hook that derives priority from
authenticated principal / route / tenant tier. The wire format is versioned
(`x-shape-version` header) so unknown fields are preserved, not dropped.
Extensions MUST preserve all five invariants above.

## Usage

```python
# Inbound: parse a request's context from its transport headers.
shape = ImmutableRequestShape.from_headers(incoming.headers)

# Guard downstream work on the attempt counter.
if shape.attempt > 3:
    raise TooManyAttempts(shape.request_id)

# Outbound: propagate the same context to the next hop.
outgoing_headers = dict(outgoing.headers)
outgoing_headers.update(shape.to_headers())

# Retry: bump the counter, preserve the idempotency key.
retry_shape = shape.with_next_attempt(
    shape.attempt + 1,
    next_idempotency_key=shape.idempotency_key,
)
```

## Compose with:

- **Deadline propagation** → `TimeoutBudget` + `MiddlewarePipeline`
  The shape carries the remaining budget; every downstream call reads the same deadline — no handler extends the budget by accident.

- **Priority-aware shedding** → `LoadShedder` + `Bulkhead`
  Shed/admit decisions are driven by the request's priority class — high-priority work survives overload without retries becoming a feedback loop.

- **Idempotent retries** → `RetryPolicy` + `IdempotentConsumer`
  Retries reuse the request's idempotency key; the downstream consumer dedupes — at-least-once transport never doubles effects.
