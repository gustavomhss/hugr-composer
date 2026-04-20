# FeatureToggle

## What it does (plain language)

FeatureToggle lets product and engineering ship code dark, turn on features
per tenant or environment, and roll back without a deploy. Every evaluation
is recorded, so there is always an audit trail that proves who saw what.

## Purpose

Named boolean (or variant) predicate, evaluated against the current context,
that controls whether a code path is live for a given request.

## When to use and when NOT to use

- USE: gradual rollouts, per-tenant pilots, kill switches, A/B tests wired to
  a context-aware predicate.
- DO NOT USE: secrets (use `ConfigBinding`), routing rules (use
  `RouterPipeline`), or one-time migrations (use `LifecycleHook`).
- DO NOT USE: hot-loop predicates where microsecond cost matters — evaluation
  synchronously appends an audit entry.

## API surface

See `FeatureToggle.contract.json` for the verbatim Protocol. The
implementation exposes `ToggleContext` (frozen dataclass with
`principal_id`, `tenant_id`, `environment`), a `FeatureToggle` Protocol,
a reference `FeatureToggleRegistry`, and an immutable `AuditEntry` record.

## Invariants

| ID | Rule |
|---|---|
| FT_INV_01 | `is_active()` MUST be pure for the same (key, ctx); no I/O leaks. |
| FT_INV_02 | Evaluation defaults to False when the backing store is unreachable. |
| FT_INV_03 | Toggle keys MUST be unique and match the naming convention. |
| FT_INV_04 | Every evaluation MUST append an audit entry. |
| FT_INV_05 | Removal is two-step: `mark_stale` then `delete`. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json`.

## Thread and async safety

`FeatureToggleRegistry` guards its toggles, stale-set, and audit list with
an internal lock. Registration, deletion, and evaluation are safe under
concurrent callers (tested in `chaos_FeatureToggle.py` with 50 threads).

## Operational characteristics (for SRE)

- Fail-closed: any exception raised by an underlying toggle implementation
  resolves to False and is still audited. A surge in the
  `toggle.failures` counter is the primary symptom of a broken provider.
- Audit list grows per evaluation. Long-running processes MUST periodically
  flush or cap the audit buffer via an observability pipeline rather than
  relying on the in-memory list.
- `toggle.registry.size` is a gauge; it SHOULD move only on deploy. A
  runtime change suggests an unintended dynamic registration.

## Security considerations

- Keys MUST match `^[a-z][a-z0-9_]{2,63}$`; this rejects path-traversal,
  whitespace, and over-long identifiers at registration time.
- `AuditEntry` intentionally omits raw claim values; only
  `principal_id`, `tenant_id`, and `environment` are captured. Do not
  serialize `AuditEntry` dicts into logs that also include credentials.
- Fail-closed semantics protect against store compromise: an attacker who
  breaks the evaluation path cannot force a feature on.

## Provenance

- Source agent: Agent #1 FRAMEWORKS
  (`docs/research/outputs/AGENT_1_FRAMEWORKS.json`).
- Primary sources: Togglz 4.x, Spring Boot `@ConditionalOnProperty`, Spring
  `@Profile`.

## Alternatives considered and rejected

- If-statements on env vars — no per-user rollout, no audit.
- Runtime config reloads only — no context-aware evaluation.
- Manual DNS / traffic splits — operates on infrastructure, not logic.

## Extension contract

Downstream tools implement the `FeatureToggle` Protocol (any class with a
`key: str` attribute and `is_active(ctx: ToggleContext) -> bool` method) and
register via `registry.register(toggle)`. Alternative providers (Togglz,
OpenFeature, LaunchDarkly) plug in as adapter classes that forward to the
vendor SDK inside `is_active` while preserving the five invariants.

## Schema of `FeatureToggle.contract.json`

Verbatim copy of the catalog `PrimitiveSpec` dict.

## Usage

```python
class HotFeature:
    key = "hot_feature"
    def is_active(self, ctx: ToggleContext) -> bool:
        return ctx.environment == "prod" and ctx.tenant_id == "acme"

registry = FeatureToggleRegistry()
registry.register(HotFeature())

ctx = ToggleContext(principal_id="u1", tenant_id="acme", environment="prod")
if registry.is_active("hot_feature", ctx):
    run_new_code_path()
else:
    run_legacy_path()
```

## Compose with:

- **Gradual rollout** → `CurrentPrincipal` + `AuditEvent`
  Toggle evaluation keys on principal cohort; every activation and deactivation is audited so 'who saw the new path' is always answerable.

- **Kill switch** → `CircuitBreaker` + `RequestGuard`
  A toggle flipped off short-circuits the feature before the breaker trips; an ops team can stop the bleed without a redeploy.

- **Config-vs-flag boundary** → `ConfigBinding` + `AuditEvent`
  Static shape lives in config; per-cohort variability lives in toggles — two distinct change-management paths, both auditable.

- **Per-session evaluation context** → `SessionCache` + `ConfigBinding`
  Flags evaluate against the cached session payload (`session["plan"]`, cohort, etc.); node-agnostic SessionCache means toggle decisions stay consistent across the stateless tier within TTL.
