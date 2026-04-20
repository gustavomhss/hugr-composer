# ValueTransform

## What it does (plain language)

`ValueTransform` is the typed "door-check" that converts the raw strings and
JSON fragments arriving over HTTP into the typed Python values (ints, bools,
UUIDs, decimals, datetimes, domain records) that the handler actually wants.
It does exactly one job: parse + validate. Failure is a typed exception the
framework maps to a 400. One reusable contract replaces ad-hoc parsing
scattered across every route, so error shapes stay consistent, cross-field
rules live in one place, and the handler never sees a raw `str` again.

## Purpose

Strongly-typed parse/validate step that converts a raw inbound argument
(body/query/param) into the typed value the handler expects.

## When to use and when NOT to use

- USE: at the boundary between HTTP (body/query/param) and the domain — every
  route parameter and every request-body field.
- USE: cross-field validation (e.g. `end_date > start_date`) via a custom
  `Validation` predicate composed after the coercion step.
- DO NOT USE: for business-rule decisioning that requires database lookups —
  transforms are pure (VTRANSFORM-INV-02); do the lookup in the handler.
- DO NOT USE: for authorization — that belongs to `RequestGuard`.
- DO NOT USE: as a logging filter or redaction layer — transforms return
  values, they do not emit signals.

## API surface

The catalog `api_signature` is the sole authority; see
`ValueTransform.contract.json` for the verbatim Protocol declaration. The
implementation `ValueTransform.py` re-declares the Protocol and provides five
reference transforms:

- `ParseInt`, `ParseBool`, `ParseUUID` — coercions. Lazy-import `uuid`.
- `Validation(predicate, message=...)` — semantic rule enforcement.
- `Compose([t1, t2, ...])` — left-to-right pipeline (VTRANSFORM-INV-04).

Every transform implements `transform(value, meta: ArgumentMetadata) -> T`;
`ArgumentMetadata` carries `kind` (body|query|param|custom), `metatype`
(the declared type — drives coercion), and `data` (opaque tag / field name).

## Invariants

| ID | Rule |
|---|---|
| VTRANSFORM_INV_01 | `transform()` MUST raise a typed error (`ValueTransformError` subclass) on bad input; NEVER returns None to signal invalid. |
| VTRANSFORM_INV_02 | A ValueTransform MUST be pure — same `(value, meta)` yields the same output with no observable side effects. |
| VTRANSFORM_INV_03 | `metatype` MUST drive the coercion target; a disagreement raises `MetatypeMismatchError`, never a silent ignore. |
| VTRANSFORM_INV_04 | Composed transforms apply left-to-right in declaration order; swapping order requires constructing a new `Compose`. |
| VTRANSFORM_INV_05 | NEVER mutates the incoming value in place; mutable inputs are deep-copied and the returned value is always fresh. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- Every reference transform is stateless (no instance attributes beyond the
  frozen predicate/message in `Validation` and the frozen tuple in `Compose`).
  Callers MAY share a single instance across threads and async tasks without
  locking (VTRANSFORM-INV-02).
- `Compose._transforms` is a `tuple`, so the declared order cannot be mutated
  after construction (VTRANSFORM-INV-04).

## Operational characteristics (for SRE)

- Hot-path latency: single `ParseInt` call is O(len(str)) in pure Python int
  parsing — well under 10us for typical payloads. Longer pipelines scale
  linearly in `len(transforms)`.
- Self-observability: `value_transform.calls`, `value_transform.duration`,
  `value_transform.errors` metrics; `value_transform.coercion.failed`,
  `value_transform.validation.failed`, `value_transform.metatype.mismatch`
  log events. See `observability_schema.json` and `dashboard.json`.
- Failure policy: a `ValueTransformError` is expected to be caught by the
  framework adapter and mapped to HTTP 400 with the `field`, `received`, and
  `expected` attributes carried into the response body. Transforms NEVER
  translate to 5xx — coercion/validation failure is always the client's.

## Security considerations

- Transforms are pure (VTRANSFORM-INV-02), so an attacker-controlled input
  cannot alter module-level state or create a replay / cache-poisoning vector.
- `ParseInt` refuses `bool` input to avoid silent `True→1` coercion leaking
  type information from upstream middleware.
- `ParseBool` accepts a closed set of literals (`1/0/true/false/yes/no/on/off`)
  and rejects every other string — no heuristic "truthiness" reasoning.
- `ParseUUID` rejects any string that is not a valid RFC 4122 textual UUID,
  preventing SQL-injection via opaque identifier fields.
- `MetatypeMismatchError` (VTRANSFORM-INV-03) prevents a developer from
  silently coercing the wrong type, which would otherwise let an attacker
  exploit type confusion (e.g. sending a string where an int was expected).
- Deep-copy on mutable inputs (VTRANSFORM-INV-05) defeats
  time-of-check-to-time-of-use (TOCTOU) attacks against validator predicates.

## Provenance

- Source agent: Agent #1 FRAMEWORKS
  (`docs/research/outputs/AGENT_1_FRAMEWORKS.json`).
- Primary sources:
  - Nest.js 10 — Pipes (`PipeTransform`, `ArgumentMetadata`);
    `docs.nestjs.com/pipes` — `transform(value, metadata: ArgumentMetadata)`
    where `kind ∈ body | query | param | custom`.
  - ASP.NET Core 8.0 — Model binding and validation
    (`learn.microsoft.com/aspnet/core/mvc/models/model-binding` —
    `ModelBinder`, `[FromBody]` / `[FromQuery]`).

## Alternatives considered and rejected

- Validation inside each handler — rejected: duplicated logic, inconsistent
  error shapes, and every cross-cutting rule must be re-implemented per route.
- Manual parsing with framework helpers only (e.g. `int(request.query["x"])`)
  — rejected: no composition of custom rules, and every handler re-derives
  the error-to-HTTP mapping.
- JSON-Schema only — rejected: cannot express cross-field rules cleanly,
  forcing two validation layers and inconsistent error paths.

## Extension contract

Downstream tools implement the `ValueTransform` Protocol (e.g. a
ZodValidationPipe-style class) and bind it with a decorator/register call on
a parameter or handler. Built-in transforms (`ParseInt`, `ParseBool`,
`ParseUUID`, `Validation`) satisfy the same Protocol and compose cleanly with
user-defined transforms under `Compose`. Every extension MUST uphold the five
invariants above; they are enforced at runtime by the reference
implementations and at test time by the invariant harness.

## Schema of `ValueTransform.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`. See
`docs/research/CONTRACT_STANDARDS.md` section 2 (PrimitiveSpec) for the full
standards governing each field.

## Usage

```python
from ValueTransform import (
    ArgumentMetadata, ParseInt, Validation, Compose,
)

pipeline = Compose([
    ParseInt(),
    Validation(lambda x: isinstance(x, int) and 1 <= x <= 100, message="1..100"),
])

meta = ArgumentMetadata(kind="query", metatype=int, data="page_size")
page_size = pipeline.transform("42", meta)  # => 42

# On invalid input the framework adapter catches the typed error and returns
# 400 with the `field`, `received`, and `expected` attributes as context.
```

## Compose with:

- **Schema-to-domain coercion** → `InputValidator` + `ValueObject`
  Raw JSON is validated by the schema then coerced into frozen value objects before the handler sees it — domain code never touches a dict.

- **Typed path/query params** → `MiddlewarePipeline` + `RequestContext`
  Each route declares transforms for its params; a failure raises one well-typed exception the pipeline maps to 400 — handlers never check types.

- **Canonical on-the-wire** → `InputValidator` + `OutputEncoder`
  Inbound ValueTransform + outbound OutputEncoder form a round-trip contract: the same canonical form crosses the edge in both directions.
