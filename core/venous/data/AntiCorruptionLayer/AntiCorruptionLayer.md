# AntiCorruptionLayer

## What it does (plain language)

An AntiCorruptionLayer (ACL) is the single, narrow translator between a
local BoundedContext and a foreign or legacy model. Every inbound payload
is guarded and translated into a local shape BEFORE any domain logic sees
it; every outbound value is translated into the foreign shape on the way
out. Foreign types never leak into the local model, the translator is
stateless, and every foreign contract carries an explicit version so
schema drift is a loud, observable event rather than a silent bug.

## Glossary (for readers new to DDD)

- **BoundedContext** — a named boundary inside which one ubiquitous
  language and one set of invariants apply.
- **Foreign model** — the shape used by an upstream, legacy, or
  third-party system. We intentionally do NOT import its types into our
  domain.
- **Local model** — the shape our domain owns. Aggregates, value objects,
  and repositories all speak this language.
- **Schema drift** — the foreign system changes its payload shape or
  version without telling us. The ACL's versioning contract (ACL-INV-04)
  turns drift into a detectable error.
- **Guard** — the precondition check that runs BEFORE translation; any
  payload that fails the guard is rejected and never touches an aggregate.
- **Maturity: battle_tested** — this primitive has passed all 10 tier
  gates (static, behavioral, formal TLA+, state-machine, metamorphic,
  concurrency, adversarial, observability, chaos, meta).

## Five-minute walkthrough

A retailer consumes orders from a legacy ERP. The ERP emits payloads
shaped `{"legacy_id": int, "legacy_name": str}`. Internally the domain
speaks `{"id": int, "name": str}`. We never want the legacy keys in the
domain.

1. Declare a version: `v = ContractVersion("legacy.erp", "2024-01")`.
2. Build a versioned ACL:
   `acl = VersionedAntiCorruptionLayer(default_version=v)`.
3. Register translators:
   `acl.register_version(v, inbound=..., outbound=..., guard=...)`.
4. Consume a message:
   ```python
   acl.guard(msg)
   local = acl.to_local(msg)
   repo.add(local)  # domain side runs AFTER translation
   ```
5. When the ERP ships version `2024-06`, register the new version on the
   SAME ACL instance — old and new payloads keep working. Any payload that
   carries an unknown version raises `SchemaDriftError` instead of
   silently falling through.

## Purpose

Translate between a local model and a foreign or legacy model so upstream
semantics cannot leak into the local BoundedContext.

## When to use and when NOT to use

- USE: whenever the domain consumes or produces data for a system whose
  vocabulary we do not own — legacy mainframes, third-party SDKs,
  acquisition integrations, external partners.
- USE: whenever the foreign contract is versioned and may drift without
  coordination.
- DO NOT USE: for intra-context DTO conversion — a `DataMapper` is the
  right tool inside one context. ACL is strictly between contexts.
- DO NOT USE: to hide genuinely shared ownership. If two contexts truly
  share an aggregate, fix the context boundary, don't paper over it with
  a translator.

## API surface

The catalog `api_signature` in `AntiCorruptionLayer.contract.json` is the
authority:

```python
class AntiCorruptionLayer(Protocol):
    def to_local(self, foreign: Foreign) -> Local: ...
    def to_foreign(self, local: Local) -> Foreign: ...
    def guard(self, foreign: Foreign) -> None: ...
```

Callers:

- Validate inbound payloads with `guard(foreign)` — raises
  `ForeignPayloadRejectedError` on invalid input (ACL-INV-02).
- Translate inbound with `to_local(foreign)` — returns a local value that
  is guaranteed NOT to be a foreign envelope (ACL-INV-01).
- Translate outbound with `to_foreign(local)` — returns a foreign value
  that is guaranteed NOT to be a local type (ACL-INV-01).

The `VersionedAntiCorruptionLayer` reference implementation adds:

- `register_version(version, *, inbound, outbound, guard)` — registers a
  versioned translator triple (ACL-INV-04).
- `known_versions()` — returns the registered versions for observability.
- `default_version` — the current foreign-contract version used when an
  incoming payload is NOT wrapped in a `ForeignPayload`.

## Invariants

| ID | Rule |
|---|---|
| ACL_INV_01 | Foreign types MUST NEVER cross the boundary of the local BoundedContext; all inbound payloads SHALL be translated through to_local before entering domain logic. |
| ACL_INV_02 | guard MUST reject inbound payloads that violate local invariants and raise before the payload reaches any local aggregate. |
| ACL_INV_03 | Translation SHALL be stateless with respect to the local domain; the ACL CANNOT read or mutate local repositories during translation. |
| ACL_INV_04 | Versioning of the foreign contract MUST be explicit; unversioned ACLs are FORBIDDEN. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- The version registry is protected by a lock; `register_version` is
  safe to call from multiple threads.
- The re-entry guard uses `threading.local`, so concurrent translations
  on the SAME ACL from different threads do NOT interfere — each thread
  has its own depth counter (ACL-INV-03).
- Translators MUST themselves be pure; the ACL cannot prove purity, it
  only detects the specific failure mode of a translator calling BACK
  into the ACL.

## Operational characteristics (for SRE)

- A sustained rise in `acl.schema.drift.events` ALWAYS indicates an
  upstream change we have not adapted to. Runbook: register the new
  version on the ACL with a tested translator, then deploy.
- `acl.guard.rejections` spikes mean either (a) an upstream bug producing
  malformed payloads or (b) an attacker probing the boundary. Correlate
  with the source-IP label on upstream ingress.
- The registered-versions gauge is bounded — an unbounded rise means a
  deploy is leaving old versions registered forever; prune in the next
  release.

## Security considerations

- `guard` is the ONLY trusted boundary for inbound validation. Do NOT
  rely on callers to pre-validate — the ACL enforces the invariant even
  if the caller is buggy.
- The reference `DictAntiCorruptionLayer` is a TEST double; real ACLs
  MUST implement domain-specific validation (types, ranges, allow-lists,
  cryptographic authenticity where relevant).
- `ForeignPayload` envelopes are opaque by design — the body is typed as
  `object` so static typing cannot accidentally leak foreign methods into
  local code.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Evans — *Domain-Driven Design* (2003), Chapter 14, Anticorruption
    Layer, pp. 364–368.
  - Vernon — *Implementing Domain-Driven Design* (2013), Chapter 3,
    Context Maps, Anticorruption Layer, pp. 106–111.

## Alternatives considered and rejected

- Direct consumer against upstream SDK — couples domain to upstream
  release cadence.
- One central translation service — bottleneck and ownership ambiguity.
- Shared kernel with upstream — violates the exact coupling the ACL
  exists to prevent.

## Extension contract

New integrations extend `AntiCorruptionLayer` by implementing an adapter
per external system and registering the facade with the local
`BoundedContext`; versioned schemas plug in via decorator over `to_local`
/ `to_foreign` so older payloads continue to be handled.

## Schema of `AntiCorruptionLayer.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from AntiCorruptionLayer import (
    ContractVersion,
    DictAntiCorruptionLayer,
    ForeignPayload,
)

acl = DictAntiCorruptionLayer()

def consume(msg, acl, repo):
    acl.guard(msg)
    local = acl.to_local(msg)
    repo.add(local)

# Versioned payload from a new upstream release:
envelope = ForeignPayload(ContractVersion("legacy.example", "2024-06"), msg)
# Raises SchemaDriftError if the new version has not been registered yet.
local = acl.to_local(envelope)
```

## Compose with:

- **Upstream translation** → `ContextMap` + `OutboundBinding`
  The ACL owns the inbound mapping declared by the context map; upstream schema churn stays contained to one adapter file.

- **Conformist escape hatch** → `BoundedContext` + `ValueObject`
  Foreign DTOs are turned into local value objects at the boundary — downstream code never imports upstream types.

- **Legacy strangulation** → `OutboundBinding` + `CircuitBreaker`
  Calls to the legacy system go through the ACL behind a breaker so the new context degrades predictably when the legacy is down.
