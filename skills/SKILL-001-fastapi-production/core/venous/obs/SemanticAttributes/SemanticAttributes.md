# SemanticAttributes

## What it does (plain language)

SemanticAttributes pins the names of shared telemetry attributes. Every service
reports the same concept (`http.request.method`, `db.system`) under the same key,
so cross-service dashboards do not break and analytics stay queryable when the
fleet grows. Product impact: faster cross-service queries, lower incident
time-to-diagnosis, zero "per-team renamed the field" outages.

## Purpose

Expose the OpenTelemetry semantic-convention attribute keys as typed constants
and enforce that primitives populate required keys for HTTP, database,
messaging, and GenAI operations.

## When to use and when NOT to use

- USE: naming attributes on spans, metrics, and log records.
- DO NOT USE: non-telemetry configuration keys — those belong in a settings
  primitive.
- DO NOT USE: tenant-specific or product-domain keys without a namespaced
  prefix; the registered SemConv surface is for cross-vendor interop.

## Invariants

| ID | Rule |
|---|---|
| SEM_INV_01 | Attribute keys MUST use lowercase dotted notation; NEVER aliased to custom names. |
| SEM_INV_02 | Required keys per domain MUST be populated before span end. |
| SEM_INV_03 | Enum values (db.system, messaging.system) MUST come from SemConv registry. |
| SEM_INV_04 | Deprecated keys SHALL be aliased to current with a one-time warning. |
| SEM_INV_05 | db.statement MUST be redacted in production; literal parameter values FORBIDDEN. |
| SEM_INV_06 | SemanticAttributes class keys are immutable at runtime. |

## Thread safety

Constants are immutable class attributes. All helpers are pure functions with
no shared mutable state. Safe for concurrent callers.

## Operational characteristics

- Validation is O(1) string regex per key. A typical HTTP span incurs < 10 µs.
- Warning budget: deprecated-key warnings are emitted once per process per key
  via a shared counter (`semattr.deprecated.warnings`), so log volume is bounded.

## Security considerations

- `redact_db_statement` is a *defence in depth* helper, not a replacement for
  parameterised queries. Upstream code MUST still use prepared statements.
- Avoid high-cardinality keys: `http.url` carries full URL including query
  string and is excluded from the default surface. Use `http.route` instead.

## Provenance

- Source agent: Agent #7 OBSERVABILITY.
- OpenTelemetry Semantic Conventions 1.27 — General, HTTP, GenAI sections.

## Alternatives considered and rejected

- Free-form string keys — rejected: every team spells the same concept
  differently and dashboards cannot be shared.
- Per-tool attribute modules — rejected: drift from upstream SemConv updates
  and miss required-key enforcement.
- OpenTracing tag taxonomy — rejected: frozen in 2019, lacks HTTP, DB,
  messaging, and GenAI coverage.

## Extension contract

New domains extend the attribute set by subclassing `SemanticAttributes` and
adding `Final`-typed constants that track a specific SemConv version. Each
subclass is registered to a namespace so linting tools can enforce that domain
spans carry the subclass's required keys.

## Schema of `SemanticAttributes.contract.json`

Verbatim PrimitiveSpec from the research catalog.

## Usage

```python
def annotate_http_span(span, method: str, route: str, status: int) -> None:
    span.set_attribute(SemanticAttributes.HTTP_REQUEST_METHOD, method)
    span.set_attribute(SemanticAttributes.HTTP_ROUTE, route)
    span.set_attribute(SemanticAttributes.HTTP_RESPONSE_STATUS_CODE, status)
```

## Compose with:

- **Convention-over-string** → `Tracer` + `MetricMeter`
  Every span/metric uses typed keys (http.request.method, db.system.name); a typo is a compile error, not a dashboard mystery.

- **Portable dashboards** → `StructuredLogger` + `TelemetryExporter`
  Logs, spans, and metrics agree on attribute names across services; dashboards migrate between backends without rewrites.

- **Cardinality-safe by construction** → `CardinalityGuard` + `HistogramBuckets`
  Each typed key declares its cardinality budget — review happens at the source, not on the billing page.
