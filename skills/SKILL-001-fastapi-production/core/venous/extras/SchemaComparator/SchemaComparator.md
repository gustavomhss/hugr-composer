# SchemaComparator

**Namespace:** `extras`
**Maturity:** `emerging`
**Source tool:** `adapt/extend/testing_tools/add_schema_evolution_guard.py`

## Purpose

`SchemaComparator` diffs two OpenAPI 3.x schema documents (JSON-loaded
dicts) and returns a `ComparisonResult` that classifies every change as
**breaking**, **compatible**, or **additive**. It is designed to be the
gate inside a CI schema-evolution check: a non-empty breaking list MUST
fail the pipeline.

## Invariants

- **SCHEMA_COMPARATOR_INV_01** — Determinism: `compare(b, c)` always
  yields the same classification and violation lists for the same input.
- **SCHEMA_COMPARATOR_INV_02** — Severity precedence: when any breaking
  change exists, `classification == "breaking"`; additives can never
  outvote a breaking change.
- **SCHEMA_COMPARATOR_INV_03** — Reflexivity: `compare(x, x)` is the
  empty diff — identity is always a no-op.

Tests: see `test_SchemaComparator.py`.

## Compose with:

- **Compat gate for CI** → `DeprecationEntry` + `DeprecationRegistry`
  Breaking changes turn into DeprecationEntries in the registry automatically; CI fails if a breaking change ships without a sunset plan.

- **Canary rollout** → `FeatureToggle` + `RequestGuard`
  Behavioral changes are gated behind a toggle; the guard reads toggle state per request — old and new shapes coexist until the toggle is retired.

- **Audit of schema evolution** → `AuditEvent` + `TamperEvidentAuditLog`
  Every OpenAPI release seals a diff hash into the audit log; auditors verify 'what shape was public on date X' cryptographically.
