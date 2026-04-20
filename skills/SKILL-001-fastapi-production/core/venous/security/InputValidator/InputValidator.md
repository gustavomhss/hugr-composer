# InputValidator

## What it does (plain language)

InputValidator parses an untrusted request body against a schema you declare
up front, then hands your handler a fully typed, fully bounded value. Unknown
fields, oversize strings, malformed Unicode, forbidden characters, and
type-confused payloads are all rejected at the edge with a typed error that
cites the offending field path — before any business rule touches the value.

## Purpose

Parse and constrain inbound payloads against a declared schema with typed
coercion, length and range bounds, and rejection of unknown fields.

## When to use and when NOT to use

- USE: every HTTP handler that accepts a request body, every background-job
  message consumer, every webhook ingress.
- DO NOT USE: server-generated internal DTOs that never cross a trust
  boundary; those should be `@dataclass(frozen=True)` with no parser.
- DO NOT USE: raw-binary upload endpoints — pair this with a byte-stream
  size limiter; the validator operates on decoded structured payloads.

## API surface

See `InputValidator.contract.json` for the verbatim Protocol. The module
ships `SchemaValidator`, a reference implementation with hard-coded global
limits on depth, collection size, string length, and total node count.

```python
from collections.abc import Mapping
from InputValidator import SchemaField, SchemaModel, SchemaValidator

class OrderCreate(SchemaModel):
    __fields__: Mapping[str, SchemaField] = {
        "sku": SchemaField(type_=str, max_length=32, pattern=r"[A-Z0-9\-]+"),
        "quantity": SchemaField(type_=int, min_value=1, max_value=1000),
    }

validator = SchemaValidator()
order = validator.parse(request.json, OrderCreate)
```

## Invariants

| ID | Rule |
|---|---|
| IV_INV_01 | parse() MUST reject payloads with unknown fields unless the schema explicitly opts into extras; silent field drop is FORBIDDEN. |
| IV_INV_02 | Length, range, and pattern bounds MUST be enforced before any business rule touches the value; unbounded strings CANNOT be accepted. |
| IV_INV_03 | Type coercion MUST be narrowing (string->int only when digits-only); widening coercion (int->string for structured ids) SHALL require explicit opt-in. |
| IV_INV_04 | parse() MUST raise a typed validation error containing the offending field path; error payloads MUST NEVER include attacker-controlled content verbatim in structured logs. |
| IV_INV_05 | Recursion depth and collection size MUST be bounded; payloads exceeding the configured limits SHALL be rejected before parsing. |

## Invariant -> test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json`.

## Thread and async safety

`SchemaValidator` is a frozen dataclass; every `parse()` call creates its own
per-call counters. Safe to share a single validator across threads, async
tasks, and worker processes.

## Operational characteristics (for SRE)

- `parse()` rejects on `ValidationError` (subclass of `ValueError`); surface
  as HTTP 400 with a stable code, never 500.
- The default hard limits (depth 16, 1024 items per collection, 65 536 chars
  per string, 50 000 total nodes) stop depth-bomb and amplification DoS
  vectors at the edge.
- Alert on a sustained spike in `input_validator.rejections{reason="..."}`
  grouped by reason — mass `unknown_field` is a mass-assignment probe; mass
  `pattern_mismatch` on a single schema is usually a credential-stuffing or
  fuzzing campaign.

## Security considerations

- The error carries only a stable `reason` code and a structural
  `field_path` — attacker-controlled bytes are NEVER echoed (IV_INV_04).
- Disallowed characters include all C0/C1 controls except TAB/LF/CR and
  every Unicode bidirectional override (U+202A..U+202E, U+2066..U+2069),
  which defeats RTL-override filename and log-injection attacks.
- `bool` is rejected where `int`/`str`/`float` are expected; Python's
  `isinstance(True, int) == True` pitfall is explicitly handled.
- NaN and +/-inf are rejected for `float` fields.
- String-to-int coercion requires `allow_coerce=True` AND a digits-only
  match; int-to-string widening requires `allow_widen=True`.
- The adapter registry (`register_adapter`) refuses to bind any third-party
  schema library that defaults to `extra='allow'` or that lacks size/depth
  limits — the only way to plug pydantic/attrs+cattrs/msgspec in is to
  honour the Protocol invariants.

## Provenance

- Source agent: Agent #5 SECURITY
- Primary sources: OWASP ASVS 4.0.3 V5.1; OWASP Top 10 2021 A03 Injection.

## Alternatives considered and rejected

- Manual `dict.get()` per endpoint — inconsistent bounds and accepts extras
  silently.
- Framework body-parsing with default permissive mode — admits unbounded
  nested structures.
- Regex-only validation — cannot express structural constraints.

## Extension contract

Schema libraries register as validator adapters (pydantic, attrs+cattrs,
msgspec) implementing the Protocol. The registry (`register_adapter`)
refuses to bind an adapter that defaults to `extra='allow'` or that lacks
size/depth limits.

## Usage

```python
def create_order(validator: InputValidator, raw_body: object, handler):
    order = validator.parse(raw_body, schema=OrderCreate)
    return handler(order)
```

## Compose with:

- **Parse-don't-validate** → `ValueTransform` + `ValueObject`
  Schema coercion produces typed value objects; the domain never sees a dict — invalid shapes are unrepresentable past the validator.

- **Round-trip safety** → `OutputEncoder` + `ContentSecurityPolicy`
  Inbound validation + outbound encoding form the canonical-form contract; XSS and smuggling are closed at both edges.

- **Authorization-ready** → `RequestGuard` + `CurrentPrincipal`
  Validated payloads carry principal-scoped identifiers; the guard authorizes the typed action, not the raw request.

- **Persisted-query pre-flight gate** → `PersistedQueryRegistry` + `RequestGuard`
  `InputValidator` checks the persisted-id format (64 lowercase hex chars) before `PersistedQueryRegistry.contains()` is queried; `RequestGuard` refuses ids that fail either check. Invariant gained: arbitrary-query surface is closed at the edge, not in the resolver.
