# CorrelationId

## What it does (plain language)

A CorrelationId is the single opaque string that stitches one user action
together across every log, every metric exemplar, and every outbound call.
Without it, debugging a payment failure that spans 12 services is an
archaeology project; with it, one query returns the whole timeline.

## Purpose

Opaque string that travels with a request across services and log lines so
a reader can stitch together the work done for one user action.

## When to use and when NOT to use

- USE: at every ingress point (HTTP middleware, queue consumer, scheduled
  job) to either propagate an upstream id or mint a fresh one.
- USE: on every outbound call (`inject`) so the downstream can join.
- DO NOT USE: as a cryptographic nonce — the id is opaque but not secret.
- DO NOT USE: to carry business data — it is a join key, not a payload.

## Invariants

| ID | Rule |
|---|---|
| CORRID_INV_01 | MUST be populated for every inbound request before the first log line. |
| CORRID_INV_02 | NEVER regenerates a present upstream id; propagates `traceparent` / `X-Request-Id` verbatim when valid. |
| CORRID_INV_03 | Generated ids use a CSPRNG, 16+ bytes encoded as lowercase hex; sequential counters are forbidden. |
| CORRID_INV_04 | MUST appear in every outbound HTTP request header set (`x-request-id`). |
| CORRID_INV_05 | CANNOT be mutated mid-request — frozen `NewType[str]`, a new id means a new logical request. |

## Thread / async safety

Stateless. `generate()` is a pure function wrapping `secrets.token_hex`, safe
from any number of threads or tasks. `extract()` / `inject()` do not touch
shared state.

## Operational characteristics

- Generation cost: one `secrets.token_hex(16)` call (≪ 1 µs).
- Parse cost: a single regex match.
- Memory: a single 32-char string per id.
- Self-observability: `correlation_id.generated.count`,
  `correlation_id.propagated.count{source_header}`,
  `correlation_id.rejected.count{reason}`.

## Security considerations

- Values are CSPRNG-random; 2¹²⁸ space rules out collisions and guessing.
- Inbound headers with CRLF, non-hex, or wrong length are rejected rather
  than propagated — blocks header-injection reflection.
- The id is opaque; it is NOT an authentication token and has no authority.

## Provenance

- ASP.NET Core 8.0 — `HttpContext.TraceIdentifier`.
- Ruby on Rails 7 — `ActiveSupport::CurrentAttributes#request_id`.
- Plug 1.x — `Plug.RequestId` (`x-request-id` header).

## Alternatives considered and rejected

- Only OpenTelemetry trace-id — misses requests outside the tracer.
- Per-service random ids — breaks cross-hop correlation.
- Autoincrementing request counter — leaks traffic volume and collides
  across nodes.

## Extension contract

A middleware / plug / interceptor calls `extract(request.headers)` at
ingress, binds the id to the request context and the logger MDC, and
`inject(cid, outbound.headers)` before every outbound call. Structured-log
formatters subscribe via a filter or hook to inject it automatically.

## Usage

```python
from CorrelationId import extract, inject, to_str

async def on_request(headers: dict[str, str]) -> None:
    cid = extract(headers)          # CORRID_INV_01 / CORRID_INV_02
    log.bind(request_id=to_str(cid))
    await downstream_call(inject(cid, {"accept": "application/json"}))
```

## Compose with:

- **Cross-service trail** → `RpcInterceptor` + `CorrelationContext`
  Outbound RPCs inject the id; inbound middleware adopts it — the same string threads every hop regardless of transport.

- **Log-trace bridge** → `StructuredLogger` + `Tracer`
  Logs and traces share the id; an SRE pivots between the two without re-querying by timestamp.

- **Audit correlation** → `AuditEvent` + `AccessLog`
  Audit and access records carry the same id — forensic reconstruction is a join, not a reconstruction.
