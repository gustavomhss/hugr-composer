# Migration — v0.x → v1.0.0

This guide documents breaking changes between the `v0.x` series and
`v1.0.0`. Follow the sections in order when upgrading a project that
consumed the skill before v1.0.

Latest pre-v1.0 tag: `v0.1.0` (first public tag).
Current interim version: `v0.2.0` (internal, unreleased).
Target: `v1.0.0`.

---

## 1. Scope of "breaking"

v1.0.0 is the first release with a semver commitment (CONTRACT §A10).
Pre-v1.0 internal iterations were fluid. The changes below are the
deltas a v0.x consumer will see at v1.0 — not every internal change
between versions.

Where a change is backwards-compatible, it is listed in CHANGELOG
under `### Added` / `### Changed`, not here.

---

## 2. Tool naming — canonical scheme locked

All Maestro-facing tools now follow `fastapi_<domain>_<verb>_<noun>`
with closed vocabularies (10 domains × 9 verbs).

**Before (v0.x, any snapshot):**

    add_auth_jwt
    add_rate_limiting
    add_health_endpoint

**After (v1.0.0):**

    fastapi_auth_add_auth_jwt
    fastapi_resiliency_add_rate_limiting
    fastapi_observability_add_health_endpoint

Legacy names are preserved only in the `legacy_name` field of each
catalog entry (`engine/index/catalog.json`) for cross-reference;
they are NOT registered with the MCP server. Callers using a legacy
name receive a "tool not found" response.

**Fix:** update any Maestro prompt / downstream script to use the
canonical name. Look up the new name via
`fastapi_meta_search "<concept>"` or by reading catalog.json.

---

## 3. Tier-1 meta tools — seven canonical, named

v0.x had an ad-hoc assortment of "root" tools. v1.0.0 commits to
exactly seven tier-1 meta tools:

    fastapi_meta_home
    fastapi_meta_search
    fastapi_meta_describe
    fastapi_meta_scaffold
    fastapi_meta_compose
    fastapi_meta_audit
    fastapi_meta_verify

These are always-loaded, registered outside the catalog, and their
names / return shapes are frozen.

**Fix:** if a v0.x script invoked a different meta name (e.g.
`fastapi_home`), rename to the `fastapi_meta_*` form above.

---

## 4. Primitive namespaces consolidated

v0.x shipped some primitives with inconsistent namespace prefixes
(e.g. `infra.Bulkhead` in one snapshot, `resiliency.Bulkhead` in
another). v1.0.0 locks 10 namespaces:

    api, auth, cache, compliance, cost, data, events, extras,
    flags, jobs, llm, obs, policy, resiliency, security

Every registered primitive lives under exactly one. The module path
is `core.venous.<namespace>.<Name>.<Name>`.

**Fix:** grep your generated projects for stale imports like
`from core.venous.infra.Bulkhead` → update to
`from core.venous.resiliency.Bulkhead.Bulkhead`.

---

## 5. Adapter pattern introduced

v0.x let tools emit FastAPI-specific code inline alongside the primitive
import. v1.0.0 introduces the adapter layer (ADR 0003): primitives are
framework-free; FastAPI glue lives in
`core/venous/_adapters/fastapi/<Name>Adapter.py`.

Affected primitives at v1.0.0 (16 adapters): AuditLog, CircuitBreaker,
CostTracker, EventSourcedStore, FeatureToggle, GracefulShutdown,
LoadShedder, OAuth2, RateLimiter, RequestGuard, RetryPolicy, Saga,
TotpVerifier, UnitOfWork, WebhookReceiver, Workflow. `Bulkhead` is
deferred to post-v1.0 per FREEZE §1.6 — its adapter lands in a
post-release sprint alongside the 2 pre-existing bulkhead test fixes
(FREEZE §2.8).

**Fix:** generated code should import from the primitive AND from its
adapter. Example (Bulkhead):

    # v0.x — inline FastAPI coupling
    from core.venous.resiliency.Bulkhead import BulkheadMiddleware

    # v1.0.0 — explicit adapter
    from core.venous.resiliency.Bulkhead.Bulkhead import Bulkhead
    from core.venous._adapters.fastapi.BulkheadAdapter import install as install_bulkhead

---

## 6. Staged primitives — discoverability, not promotion

v0.x surfaced `_extracted/` primitives with the same status as
registered ones. v1.0.0 distinguishes:

- **`status="stable"`** — registered primitive, production-ready.
- **`status="staged"`** — present in `_extracted/`, discoverable but
  NOT production-ready. Maestro should only cite staged primitives
  after human review AND a §A12(b) signal.

**Fix:** any Maestro prompt that filtered primitives by name-only
must now filter by `status="stable"` to avoid suggesting unfinished
code. See INTERFACES.md §2.2.

---

## 7. Catalog schema — new fields, stable hash

`engine/index/catalog.json` at v1.0.0 carries:

- `stable_hash` — SHA-256 content hash for session pinning (NEW).
- `status` on each tool: `stable` / `beta` / `deprecated` / `experimental`.
- `tier` on each tool: 1 (scaffold) / 2 (slice).
- `primitives_used` — ground truth for what the tool imports.

**Fix:** if you parse catalog.json, add tolerant handling for the
new `stable_hash` top-level field (ignore if not needed).

---

## 8. Promotion pipeline — new module

`engine/promotion/` is new in v1.0.0. It does not break existing
callers (no renames), but introduces:

- `engine/promotion/classify.py` — ledger generation from `_extracted/`.
- `engine/promotion/promote.py` — approved-action executor.
- `engine/promotion/ledger.py` + `LEDGER.md` — human-facing approval
  artefact.

No migration required — the module is additive.

---

## 9. CONTRACT — new rules

v1.0.0 lands two new CONTRACT items:

- **§A12** — amended text on when `_extracted/` items may be promoted
  (added triage-pass clause). Not a behavioural change for existing
  callers, but formalises the escape hatch.
- **§B1.8** — tier-lite eligibility check. Vacuously satisfied while
  no lite primitives are registered; activates the moment one is.

Contract rule count: 33 → 34. CI gates unchanged.

---

## 10. Removed items

Nothing removed in v1.0.0. v0.x consumers see strict supersets of
previous behaviour. Removals would require a MAJOR bump beyond v1.0
(v2.0.0+).

---

## 11. Verifying the migration

Once you updated callers:

    # 1. Regenerate the skill catalog
    cd skills/SKILL-001-fastapi-production
    PYTHONPATH=. .venv/bin/python -m engine.index.manifest verify

    # 2. Run the contract check
    PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check

    # 3. Run your Maestro session against the skill
    #    and confirm tool names resolve.

If any step fails, file an issue — include the failing step's full
output.
