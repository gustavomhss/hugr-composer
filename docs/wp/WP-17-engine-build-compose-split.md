# Work Package Contract — `WP-17-engine-build-compose-split`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-17-specific content fills each section.
> Theme: **cohesion-driven decomposition of `engine/audit/_build_compose.py`**
> (2 584 LOC superfile, of which ~2 370 LOC are curated compose-data) into
> ≥4 cohesive modules each ≤500 LOC. The public surface
> (`python -m engine.audit._build_compose`) is preserved via a thin facade.
>
> **Model elevation:** WP-17 runs on `opus`, not `sonnet`, because
> `_build_compose.py` builds the §B1.1 `primitives_by_concern.yaml` registry
> AND appends the §B1.2 `## Compose with:` section to every production
> primitive `.md`. A drift in either output mutates the engine's source of
> truth for "what primitive composes with what" — the data every recipe
> retrieval (`fastapi_meta_search_composition`, recipe catalog, INTERFACES.md
> §2.3 contract) reads. See §11 for the byte-equivalent diff-gate mandated
> for this WP.
>
> **This is a refactor-WP, not a tool-migration.** `add_cursor_pagination`
> (the WP-F1 golden) is cited only as a *pattern reference* for cohesive
> per-domain module layout. It is **not** a template for this WP — there are
> no `discover/plan/write/patch/verify` phases here; `_build_compose.py` is a
> single `build()` entrypoint over curated data tables.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-17-engine-build-compose-split` |
| **Title** | Split `engine/audit/_build_compose.py` (2584 LOC) into ≥4 cohesive sub-modules, public surface preserved |
| **Wave** | `1` |
| **Depends on** | none (engine surface is self-contained; not blocked by the WAVE 1 tool migrations) |
| **Blocks** | none — sibling WPs (WP-01..03, WP-Z2/C/D/E, WP-16) are file-disjoint |
| **Branch** | `wp/17-engine-build-compose-split` (off the post-dependency main) |
| **Isolation** | dedicated git worktree |
| **Model** | `opus` — registry + `.md` appender outputs are the source of truth for primitive composition; a single dropped entry mutates §B1.2's grep-validated surface (§11) |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/engine/audit/_build_compose.py     [REWRITE → thin facade]
  skills/SKILL-001-fastapi-production/engine/audit/compose_data/
    __init__.py
    _constants.py
    _assembly.py
    _build.py
    entries/
      __init__.py
      api.py
      auth.py
      cache.py
      compliance.py
      data.py
      events.py
      extras_flags_jobs.py
      llm.py
      obs.py
      policy_resiliency.py
      security.py
      emerging.py
  ```
- **Golden reference (pattern only, NOT a template):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` — cited solely as the "per-domain cohesion" idiom. This WP does NOT migrate a tool; it splits an engine superfile whose surface area is curated data tables. Do not over-extrapolate the golden.
- **Shared base/contract to import (read-only):** none — `_build_compose.py` imports only `json` from stdlib + the `pathlib.Path` constants for `SKILL_ROOT`/`VENOUS`/`REGISTRY`. No `adapt/_base/` involvement.
- **Spec to follow:** `docs/repo-standard.md` §3 (file-size cap), `docs/architecture.md` (engine layer), CONTRACT.md §B1.1 + §B1.2 (the rules whose outputs this script produces), this manifest.
- **Outputs (read-only reference — must not change):**
  - `skills/SKILL-001-fastapi-production/engine/primitives_by_concern.yaml` — §B1.1 registry (124 production primitives, sorted by `(namespace, name)`).
  - `core/venous/<namespace>/<Name>/<Name>.md` — every production `.md` gains a `## Compose with:` section if absent (§B1.2).
- **Behavior oracles (read-only):**
  - `engine.audit.contract_check --item B1.1` (registry sync + half-extracted-dir check).
  - `engine.audit.contract_check --item B1.2` (Compose-with coverage: section present + ≥3 bullets per `.md`).
  - `engine/tests/test_delivery_contract.py` (985 LOC; covers the engine layer end-to-end).

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-16 (`contract_check.py` split)** — the sibling engine superfile and its `engine/audit/contract_rules/` sub-package. WP-17 must not touch a byte.
- **WP-01/02/03 (resiliency / observability / security) tools** — every `adapt/extend/infrastructure/add_<tool>/` directory.
- **WP-Z2/C/D/E (sibling WAVE 1 WPs in flight)** — every `adapt/extend/<category>/add_<tool>/` directory for those WPs.
- **`engine/primitives_by_concern.yaml`** — the OUTPUT of `_build_compose.py`. The file is regenerated by running the script; the WP-17 agent NEVER hand-edits it. If the post-split run produces a different `primitives_by_concern.yaml` than pre-split, **stop and report** — that is the §11 failure mode.
- **`core/venous/<ns>/<Name>/<Name>.md`** — append-only target of §B1.2. The split MUST NOT cause new `.md` edits, drop any existing `## Compose with:` section, or reorder bullets. The `if "## Compose with:" in body: already += 1; continue` short-circuit in `build()` is the idempotency contract; preserve it byte-for-byte.
- **`engine/tests/test_delivery_contract.py`** — behavior-preservation oracle (read-only).
- **`/CONTRACT.md`** — §B1.1 + §B1.2 are the rule definitions; do not edit.
- **`pyproject.toml`, CI config, `.pre-commit-config.yaml`** — out of scope.
- **`engine/audit/__init__.py`** — stays empty.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)

### Goal
Decompose the 2 584-LOC `engine/audit/_build_compose.py` into a cohesion-driven
set of ≥4 sub-modules — each ≤500 LOC — under a new `engine/audit/compose_data/`
package, while:
1. Preserving `python -m engine.audit._build_compose` as the entrypoint.
2. Preserving the `build()` function's input → output mapping: the script
   reads every `*.manifest.json` under `core/venous/` (excluding `_staging/`),
   writes `engine/primitives_by_concern.yaml` sorted by `(namespace, name)`,
   and appends `## Compose with:` to every primitive `.md` that lacks one.
3. Yielding byte-identical `primitives_by_concern.yaml` pre vs post (§11).
4. Yielding zero new `## Compose with:` appends on a clean post-split run
   against a tree that's already had `build()` run on it (the idempotency
   contract: `already` count == total targets; `appended` count == 0).
5. Keeping `engine.audit.contract_check --item B1.1` + `--item B1.2` green
   identically (the rules whose outputs this script produces).

### Before
`engine/audit/_build_compose.py` is a single 2 584-LOC module carrying:
- Module constants: `SKILL_ROOT`, `VENOUS`, `REGISTRY`.
- Two taxonomy dicts: `CONCERN_BY_NS` (13 namespace→concern entries) and `DATA_CONCERN` (17 data-namespace splits).
- The mega-dict `E: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]]` (lines 78–2135, ~2 058 LOC) containing curated `(purpose, compose_with, [(pattern, siblings, invariant), ...])` entries for ~124 production primitives, grouped by 14 namespace section headers (`# === api`, `# === auth`, …, `# === security`).
- `EMERGING: dict[str, list[...]]` (lines 2144–2451, ~308 LOC) containing compose-pattern-only entries for ~18 non-manifest primitives that have a `.md` but no `.manifest.json`.
- `E.pop("TokenIntrospectorX", None)` placeholder cleanup (line 2456).
- Helper `concern_for(namespace, name)` (lines 2464–2467, 4 LOC).
- The `build()` function (lines 2470–2580, ~111 LOC) — manifest scan, dangling-ref validation, YAML emission, `.md` appender with idempotency check.
- `if __name__ == "__main__": build()` shim.

The file is 5.2× the sweet-spot LOC cap; the curated data block dominates
(~92% of the file). The `data` and `obs` namespaces each weigh ~358 LOC on
their own.

### After
- Package `engine/audit/compose_data/` exists with the modules in §3
  Decomposition.
- `engine/audit/_build_compose.py` becomes a thin facade: imports `build`
  (and `E`, `EMERGING`, `CONCERN_BY_NS`, `DATA_CONCERN`, `concern_for` for
  re-export — preserving every public name) and keeps the
  `if __name__ == "__main__": build()` shim.
- `engine/audit/_build_compose.py` final LOC ≤ 35 (facade only). It is
  EXPLICITLY kept (not deleted) so `python -m engine.audit._build_compose`
  + any `from engine.audit._build_compose import …` consumer sees no churn.
- No public name added or removed. No primitive entry dropped, re-keyed, or
  reordered within its namespace section. The 14 source section markers
  (`# === api`, … `# === security`) become 14 separate module boundaries
  (with the small namespaces `extras` + `flags` + `jobs` grouped into one
  module to stay above the meaningful-cohesion threshold, and `policy` +
  `resiliency` grouped similarly — see decomposition).

### Decomposition (mandatory — invariant I2)

| # | Module path (under `engine/audit/compose_data/`) | Est. LOC | Responsibilities (data scope + functions) | Depends on (modules) |
|---:|---|---:|---|---|
| 1 | `_constants.py` | ~75 | `SKILL_ROOT`, `VENOUS`, `REGISTRY` path constants. Taxonomy dicts: `CONCERN_BY_NS` (13 entries), `DATA_CONCERN` (17 entries). Helper `concern_for(namespace, name)`. **Cohesion:** the small invariant taxonomy — every entries-module and `_build` reads it. | stdlib only |
| 2 | `entries/api.py` | ~130 | 6 `E` entries for namespace `api`: `CommandQuerySeparator`, `ContextMap`, `MiddlewarePipeline`, `RequestContext`, `RouterPipeline`, `ValueTransform`. **Cohesion:** all six are HTTP/request-edge primitives with overlapping `compose_with` siblings (each cites ≥2 of the others). | none |
| 3 | `entries/auth.py` | ~160 | 7 `E` entries for namespace `auth`: `AuthorizationCodeFlow`, `CurrentPrincipal`, `RequestGuard`, `SessionStore`, `TokenIntrospector`, `TotpVerifier`, `WebAuthnAuthenticator`. Includes the `TokenIntrospectorX` placeholder (popped at assembly time — see `_assembly.py`). **Cohesion:** identity + access-control primitives; siblings reference each other heavily. | none |
| 4 | `entries/cache.py` | ~50 | 2 `E` entries: `DistributedLock`, `KeyValueBucket`. **Cohesion:** the small cache namespace; both primitives explicitly cross-link in their compose patterns. | none |
| 5 | `entries/compliance.py` | ~155 | ~7 `E` entries for namespace `compliance` (lines 402-549). **Cohesion:** compliance/audit primitives — `AuditEvent`, `TamperEvidentAuditLog`, `LegalHold`, `BreachNotificationQueue`, etc. | none |
| 6 | `entries/data.py` | ~365 | ~17 `E` entries for namespace `data` (lines 550-907) — the largest single namespace. Covers data.persistence (Repository, UnitOfWork, IdentityMap, DataMapper, TransactionalBatch, ChangeDataCapture, MaterializedView), data.modelling (Aggregate, ValueObject, Specification, BoundedContext, AntiCorruptionLayer), data.schema (ConfigBinding, DiContainer, LifetimeScope, PiiClassification, LegalHold). **Cohesion:** the entire `data` namespace; concern split is honored by `_constants.DATA_CONCERN` but the curated entries naturally cluster. | none |
| 7 | `entries/events.py` | ~240 | ~13 `E` entries for namespace `events` (lines 908-1139). **Cohesion:** EventBus, DomainEvent, EventEnvelope, IdempotentConsumer, InboxDeduplicator, OutboundBinding, SagaOrchestrator, StreamSubject, TopicBus, TransactionalOutbox, etc. | none |
| 8 | `entries/extras_flags_jobs.py` | ~180 | Combined module for 3 small namespaces: `extras` (lines 1140-1224, ~5 entries), `flags` (lines 1225-1246, ~1 entry: `FeatureToggle`), `jobs` (lines 1247-1310, ~3 entries: `WorkflowRun`, `ActivityCall`, `DurableTimer`). **Cohesion:** none individually large enough; the three are grouped because they all describe lifecycle/operational primitives that compose with each other (jobs gate on flags; extras helpers wrap both). Splitting them into 3 sub-100-LOC files would create churn without cohesion value. | none |
| 9 | `entries/llm.py` | ~90 | ~4 `E` entries for namespace `llm` (lines 1311-1395): `LlmTrace`, `PromptTemplate`, `EmbeddingIndex`, etc. | none |
| 10 | `entries/obs.py` | ~365 | ~17 `E` entries for namespace `obs` (lines 1396-1753) — second-largest single namespace. StructuredLogger, Tracer, MetricMeter, CorrelationContext, AccessLog, HealthProbe, ErrorSink, etc. **Cohesion:** the entire observability namespace. | none |
| 11 | `entries/policy_resiliency.py` | ~220 | Combined module for 2 namespaces: `policy` (lines 1754-1838, ~4 entries: `PolicyDecisionPoint`, `RateLimiter`, etc.) + `resiliency` (lines 1839-1965, ~14 entries: `CircuitBreaker`, `TimeoutBudget`, `RetryPolicy`, `LoadShedder`, `Bulkhead`, `LifecycleHook`, etc.). **Cohesion:** policy primitives are the "decision" half of resiliency's "shedding/throttling/retry" half; they compose tightly (e.g. RetryBudget × RetryPolicy, RateLimiter × LoadShedder). | none |
| 12 | `entries/security.py` | ~175 | ~8 `E` entries for namespace `security` (lines 1966-2135): `SignatureVerifier`, `SecretsVault`, `PasswordHasher`, `CsrfGuard`, `KeyRotationSchedule`, etc. | none |
| 13 | `entries/emerging.py` | ~315 | The `EMERGING` dict (lines 2144-2451, ~18 entries: BatchCore, CommandBus, DeprecationEntry, DeprecationRegistry, DeprecationReporter, IdempotencyStore, InboundVerifier, MemoryPubSubBackend, QueryBus, FeatureFlagCache, SchemaComparator, CostTracker, ExcelExporter, GracefulShutdown, ModelRegistry, Redactor, TracingBuffer, RetryBudget). **Cohesion:** non-manifest primitives sharing the property "no `.manifest.json` yet"; the `EMERGING` dict carries `[patterns]` only (no `purpose` / `compose_with` tuple shape). Split from `E` because the data shape differs. | none |
| 14 | `_assembly.py` | ~50 | `from .entries import …` imports + merges every entries dict into a single `E: dict[str, …]`; pops the `TokenIntrospectorX` placeholder; merges every entries-emerging fragment into `EMERGING`. Single source of truth for "the whole assembled curated dataset". Exposed names: `E`, `EMERGING`. | every `entries/*.py` |
| 15 | `_build.py` | ~140 | The `build()` function: manifest scan over `core/venous/`, dangling-ref validation, `(namespace, name)` sort, hand-rolled YAML emission to `REGISTRY`, idempotent `## Compose with:` appender. Imports `E`, `EMERGING` from `_assembly`; imports `concern_for`, `VENOUS`, `REGISTRY`, `SKILL_ROOT` from `_constants`. **Cohesion:** the I/O + validation surface — the only module that touches the filesystem. | `_constants`, `_assembly` |
| 16 | `__init__.py` (`compose_data/`) | ~15 | Re-exports: `from ._constants import CONCERN_BY_NS, DATA_CONCERN, concern_for, SKILL_ROOT, VENOUS, REGISTRY`; `from ._assembly import E, EMERGING`; `from ._build import build`. Single import surface. | every module above |
| 17 | `entries/__init__.py` | ~25 | Re-exports each namespace dict (`api`, `auth`, `cache`, `compliance`, `data`, `events`, `extras_flags_jobs`, `llm`, `obs`, `policy_resiliency`, `security`, `emerging`) so `_assembly` imports cleanly. | each `entries/*.py` |

**Surviving facade:** `engine/audit/_build_compose.py` shrinks to ≤35 LOC:

```python
"""§B1.1 + §B1.2 one-shot builder (facade).

Implementation moved to ``engine.audit.compose_data`` (split per WP-17).
This module preserves the historic public surface:

    python -m engine.audit._build_compose
    from engine.audit._build_compose import build, E, EMERGING
    from engine.audit._build_compose import CONCERN_BY_NS, DATA_CONCERN, concern_for
"""
from __future__ import annotations
from engine.audit.compose_data import (
    CONCERN_BY_NS,
    DATA_CONCERN,
    E,
    EMERGING,
    REGISTRY,
    SKILL_ROOT,
    VENOUS,
    build,
    concern_for,
)

__all__ = [
    "CONCERN_BY_NS", "DATA_CONCERN", "E", "EMERGING",
    "REGISTRY", "SKILL_ROOT", "VENOUS", "build", "concern_for",
]

if __name__ == "__main__":
    build()
```

### Dependency graph (cycle-free — invariant I12)

```
                  ┌───────────────────┐
                  │   _constants.py   │ stdlib only
                  └─────────┬─────────┘
                            │
       ┌────────────────────┼─────────────────────┐
       │                    │                     │
       ▼                    ▼                     ▼
  entries/*.py        (none — entries        _build.py
  (12 namespace        are pure data)        (filesystem +
   modules)                                   YAML I/O)
       │
       │ imported by
       ▼
  entries/__init__.py  (re-exports each namespace dict)
       │
       ▼
  _assembly.py  (merges into E + EMERGING, pops placeholder)
       │
       ▼
  _build.py  ← also imports _constants
       │
       ▼
  compose_data/__init__.py  (re-exports build, E, EMERGING, constants)
       │
       ▼
  engine/audit/_build_compose.py  (facade)
```

No back-edges. `_constants` has zero in-package edges. `entries/*` are pure
data modules with NO imports of any other compose_data module (this is the
key invariant: keep entries free of intra-package coupling). `_assembly`
imports only `entries/`; `_build` imports `_constants` + `_assembly`.
Topological sort: `_constants, entries/* → entries/__init__ → _assembly →
_build → __init__ → facade`.

### Out of scope
- Adding, removing, renaming, or re-keying any entry in `E` or `EMERGING`.
- Editing any `purpose` string, any `compose_with` list, any pattern name /
  siblings / invariant string. The curated text is the SOURCE OF TRUTH for
  §B1.2 retrieval-friendliness; touching it is a separate WP.
- Changing the YAML emission shape (quoting, key order, sort key) — would
  break §11 byte-equivalence on `primitives_by_concern.yaml`.
- Changing the `.md` appender output shape — would break §B1.2 grep
  validation in `_r_compose_with_coverage`.
- Touching `core/venous/*/<Name>/<Name>.manifest.json` or `<Name>.md`.
- Touching `engine/primitives_by_concern.yaml` by hand. It is regenerated;
  do not commit hand edits.
- Re-organizing the namespace section boundaries to match a "neater" file
  layout. The 14 source section markers + the `EMERGING` boundary are the
  cohesion seams; respect them.
- Removing the `TokenIntrospectorX` placeholder pop — historically used to
  exclude a stub-entry. Keep the `.pop("TokenIntrospectorX", None)` in
  `_assembly.py` verbatim.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Running `python -m engine.audit._build_compose` against a clean checkout produces a byte-identical `primitives_by_concern.yaml` pre vs post (§11 diff gate). Proven by §6 gate 1, not by claim.
- [ ] **Public surface preserved.** `from engine.audit._build_compose import build, E, EMERGING, CONCERN_BY_NS, DATA_CONCERN, concern_for, SKILL_ROOT, VENOUS, REGISTRY` all resolve to objects with the same shape and content as pre-split (§6 gate 4).
- [ ] **No module exceeds 500 LOC.** Hard cap per `docs/repo-standard.md` §3. Verified by `scripts/checks/file_size.py`.
- [ ] **`engine/audit/_build_compose.py` ≤ 35 LOC** (facade only) — verified by `wc -l`.
- [ ] **No new dependencies.** No `pyproject.toml` change.
- [ ] **Entries are pure data modules.** No `entries/*.py` imports any other module from `compose_data/` or from `engine/audit/`. Verified by `grep -nE "^(import|from)" engine/audit/compose_data/entries/*.py` showing only `from __future__ import annotations`.
- [ ] **Idempotency contract preserved.** A second `python -m engine.audit._build_compose` run against an already-built tree reports `appended=0` and `already=<total targets>` (line: `[§B1.2] appended 0 sections; N already present`). Same as pre-split.
- [ ] **§B1.1 + §B1.2 audit rules green identically.** `python -m engine.audit.contract_check --item B1.1` PASS; `--item B1.2` PASS.
- [ ] **`pytest engine/tests/test_delivery_contract.py` green identically.** Same pass count pre vs post (§6 gate 5).
- [ ] **`E` cardinality preserved.** `len(E)` post-split equals `len(E)` pre-split (124 entries after the placeholder pop).
- [ ] **`EMERGING` cardinality preserved.** `len(EMERGING)` post-split equals pre-split (~18 entries).
- [ ] **No stale staging-directory references.** The staging tree is `_staging/` (renamed in PR #24). The `build()` function's `"_staging" not in m.parts` filter STAYS as-is.
- [ ] **Docstrings honest.** Each new module's docstring states its scope (namespace covered or build-stage owned).
- [ ] **Cycle-free dependency graph.** `python -c "import engine.audit._build_compose"` succeeds; explicit topo sort holds.

## 5. Behavior-preservation oracle (per §3 of the WP scope)

The behavior-preservation oracle for this WP is **NOT** a new emitted-test
(this is a refactor-WP, not a tool migration — per the WP-scope manifest §D-G
+ I8). The oracle is the EXISTING outputs + the EXISTING audit run:

1. **`primitives_by_concern.yaml`** byte-equivalence pre vs post (§11).
2. **`engine.audit.contract_check --item B1.1`** PASS (registry sync + half-extracted-dir check) — identical message text.
3. **`engine.audit.contract_check --item B1.2`** PASS (`## Compose with:` coverage + ≥3 bullets) — identical message text.
4. **`engine.tests.test_delivery_contract`** PASS at the same green count.
5. **Idempotency contract:** a second run of the script reports `appended=0`; same count pre vs post.

If any of (1)–(5) drift, **stop and report** — do not paper over.

**This WP does NOT emit a new test under P1 #15.** P1 #15 governs tool
migrations; this WP is an engine-internal refactor.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local

# Mandatory gate 1 — byte-equivalent primitives_by_concern.yaml pre/post (§11)
git stash                                  # park current split
$PY -m engine.audit._build_compose 2>&1 | tee /tmp/bc_pre.log
cp engine/primitives_by_concern.yaml /tmp/pbcc_pre.yaml
# also capture every potentially-mutated .md
cd core/venous && tar -cf /tmp/md_pre.tar $(find . -name "*.md" -not -path "*/_staging/*" -not -path "*/__pycache__/*") && cd -
git stash pop                              # restore split
$PY -m engine.audit._build_compose 2>&1 | tee /tmp/bc_post.log
cp engine/primitives_by_concern.yaml /tmp/pbcc_post.yaml
diff -u /tmp/pbcc_pre.yaml /tmp/pbcc_post.yaml    # PASS = empty
# verify NO new .md changes occurred (idempotency)
cd core/venous && tar -cf /tmp/md_post.tar $(find . -name "*.md" -not -path "*/_staging/*" -not -path "*/__pycache__/*") && cd -
diff <(tar -tvf /tmp/md_pre.tar | sort) <(tar -tvf /tmp/md_post.tar | sort)  # tar metadata equal
# stdout log shape equality
diff /tmp/bc_pre.log /tmp/bc_post.log              # PASS = empty

# Mandatory gate 2 — file-size cap (docs/repo-standard.md §3 hard cap 500 LOC)
$PY scripts/checks/file_size.py engine/audit/_build_compose.py engine/audit/compose_data/

# Mandatory gate 3 — ruff (lint + format)
$PY -m ruff check engine/audit/_build_compose.py engine/audit/compose_data/
$PY -m ruff format --check engine/audit/_build_compose.py engine/audit/compose_data/

# Mandatory gate 4 — public surface + cardinalities
$PY -c "
from engine.audit._build_compose import (
    build, E, EMERGING, CONCERN_BY_NS, DATA_CONCERN,
    concern_for, SKILL_ROOT, VENOUS, REGISTRY,
)
assert callable(build), 'build not callable'
assert isinstance(E, dict) and len(E) >= 120, f'E shape: {len(E)}'
assert isinstance(EMERGING, dict) and len(EMERGING) >= 15, f'EMERGING: {len(EMERGING)}'
assert 'TokenIntrospectorX' not in E, 'placeholder leaked into E'
assert isinstance(CONCERN_BY_NS, dict) and len(CONCERN_BY_NS) == 13
assert isinstance(DATA_CONCERN, dict) and len(DATA_CONCERN) == 17
assert concern_for('api', 'CommandQuerySeparator') == 'api'
assert concern_for('data', 'Repository') == 'data.persistence'
print(f'public surface ok: E={len(E)}, EMERGING={len(EMERGING)}')
"

# Mandatory gate 5 — §B1.1 + §B1.2 audit rules + delivery_contract
$PY -m engine.audit.contract_check --item B1.1
$PY -m engine.audit.contract_check --item B1.2
$PY -m pytest engine/tests/test_delivery_contract.py -q -p no:cacheprovider
```

All five gates must be GREEN. Paste verbatim tails in §7. Additionally, §11
byte-equivalence diff on `primitives_by_concern.yaml` MUST be PASS (zero-length).

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-17 owns (write surface):**
- `engine/audit/_build_compose.py` — rewritten as ≤35-LOC facade.
- `engine/audit/compose_data/` — NEW package per §1, 17 files.

**WP-17 must NOT touch (forbidden):**

| Owner | Forbidden paths |
|---|---|
| WP-16 | `engine/audit/contract_check.py` + new `engine/audit/contract_rules/` sub-package created by WP-16 |
| WP-01/02/03 | every `adapt/extend/infrastructure/add_<tool>/` listed in their §1 |
| WP-Z2/C/D/E | every `adapt/extend/<category>/add_<tool>/` |
| Output (DO NOT hand-edit) | `engine/primitives_by_concern.yaml`, every `core/venous/<ns>/<Name>/<Name>.md` |
| Behavior oracle | `engine/tests/test_delivery_contract.py` |
| Source of truth | `/CONTRACT.md` (§B1.1, §B1.2) |
| Shared | `pyproject.toml`, CI workflows, `.pre-commit-config.yaml`, `hugr_auth/`, `adapt/`, `generators/`, `modules/` |

`git diff --name-only main..HEAD` MUST list only paths inside §1 write surface
(1 rewritten facade + 17 new files under `compose_data/`).

## 8. Estimated effort

Measurements taken on `main` at branch creation; LOC = `wc -l`.

| Source file | Current LOC | Target post-split modules (count + cumulative LOC) | Wall-clock | Model |
|---|---:|---|---:|---|
| `engine/audit/_build_compose.py` | 2 584 | 1 facade (≤35) + 17 new files under `compose_data/` (~2 575 total, range 50–365 per module) | 5 – 7 h | `opus` |

**Model recommendation: `opus`.** The data is curated prose; an unintentional
character drift in any `purpose` string OR `compose_with` list OR pattern
invariant rewrites the engine's source of truth for primitive composition.
`sonnet` historically auto-"cleaned" prose during code moves; `opus` is the
caliber required to copy ~2 370 LOC of curated text BYTE-FOR-BYTE while
splitting it into 12 namespace modules. The §11 diff gate
(`primitives_by_concern.yaml` byte equivalence) is the safety net, but the
manual move discipline must catch errors before the gate runs — at 124
entries × 3 patterns × 3 siblings each, the search space dwarfs the diff.

## 9. Failure modes (≥8 anticipated traps — engine compose-data risk profile)

1. **F-01. Curated text drift during the move.**
   - *Symptom:* §11 diff reports a `purpose` string differs by one character (autocomplete substitution, smart-quotes auto-conversion, whitespace normalization).
   - *Cause:* IDE / `ruff format` "cleaned" the curated dict literal during the move.
   - *STOP-and-report rule:* every entries-module is moved with `git mv`-style copy-paste preserving bytes. Run `ruff format --diff entries/` BEFORE committing — the prose strings MUST be unchanged. Any text-content drift = stop and report (revert the format, fix the source pattern instead).

2. **F-02. Entry placement ambiguity — primitive belongs to two namespaces.**
   - *Symptom:* `LegalHold` appears in both `entries/compliance.py` (its namespace per `CONCERN_BY_NS`) and `entries/data.py` (the section header it sits under in the source file). Assembly produces a duplicate key warning OR silently overwrites.
   - *Cause:* the source file's section headers (`# === data`) are by primitive namespace (the `manifest.json` `namespace` field), NOT by `CONCERN_BY_NS` concern. Cross-check both during the move.
   - *STOP-and-report rule:* every entry lives in the entries-module matching the **source section header** (the `# === <ns>` comment block it sits under in the pre-split file). DO NOT re-bin based on `concern_for()`. The split mirrors the source layout, not the concern taxonomy. Mismatch = stop and report.

3. **F-03. Import cycle between `_assembly` and an entries module.**
   - *Symptom:* `python -c "import engine.audit._build_compose"` raises `ImportError` from a circular import.
   - *Cause:* an entries module accidentally imports from `_assembly` (e.g. to reference a sibling-namespace primitive name).
   - *STOP-and-report rule:* entries are pure data; the only allowed import in `entries/*.py` is `from __future__ import annotations`. Reference-by-string (the curated text mentions sibling names) is fine — those strings are validated at `build()` time, not at import time. Violation = stop and report.

4. **F-04. `_assembly` merges entries with overlapping keys silently.**
   - *Symptom:* the same primitive name appears in two entries-modules (e.g. data + extras both define `LegalHold`); the last-imported wins; `build()` succeeds but with the wrong `purpose` text.
   - *Cause:* author forgot the `concern_for(namespace='data', name='LegalHold')` quirk where data.schema entries reach back into compliance prose.
   - *STOP-and-report rule:* `_assembly.py` asserts no key collision when merging: `assert not (entries_a.keys() & entries_b.keys())`. Triggered assert = stop and report; the collision is the bug.

5. **F-05. `TokenIntrospectorX` placeholder NOT popped.**
   - *Symptom:* `build()` raises `KeyError` because the placeholder entry has an empty `purpose` string and the manifest scan tries to write it.
   - *Cause:* author moved the `entries/auth.py` block but forgot the `E.pop("TokenIntrospectorX", None)` line at line 2456.
   - *STOP-and-report rule:* `_assembly.py` contains the `.pop("TokenIntrospectorX", None)` line VERBATIM. Tests assert `'TokenIntrospectorX' not in E` post-assembly (gate 4).

6. **F-06. Idempotency contract regression — `.md` files re-appended.**
   - *Symptom:* second run of `build()` reports `appended=124` instead of `appended=0`.
   - *Cause:* the `if "## Compose with:" in body: already += 1; continue` short-circuit in the appender loop was lost during the move into `_build.py`.
   - *STOP-and-report rule:* `_build.py` preserves the short-circuit byte-for-byte. Gate 1 (idempotency contract) catches this in CI.

7. **F-07. YAML emission shape drift.**
   - *Symptom:* `primitives_by_concern.yaml` diff shows different quoting (`"` vs `'`), different indentation (2 vs 4 spaces), different key order (`name` before `namespace` flips to `namespace` before `name`), or different sort key.
   - *Cause:* author "modernized" the hand-rolled YAML emission in `_build.py` to use `yaml.safe_dump`.
   - *STOP-and-report rule:* the hand-rolled `yaml_str()` quoting helper + the exact `lines.append(...)` sequence in `build()` is preserved character-for-character. Switching to `yaml.safe_dump` = stop and report (it would flip every quoting decision).

8. **F-08. Sort-key drift.**
   - *Symptom:* `primitives_by_concern.yaml` orders entries differently (e.g. `(concern, name)` instead of `(namespace, name)`).
   - *Cause:* author moved sort logic into a sibling helper and changed the tuple.
   - *STOP-and-report rule:* the sort is `primitives.sort(key=lambda p: (p["namespace"], p["name"]))`. Preserve verbatim.

9. **F-09. `EMERGING` cross-ref validation regression.**
   - *Symptom:* a sibling name in an `EMERGING` pattern (e.g. `BatchCore` cites `IdempotencyStore`) no longer resolves; `build()` raises `SystemExit("dangling refs ...")` against a previously-valid tree.
   - *Cause:* `EMERGING` lives in `entries/emerging.py`; `E` lives split across 12 files. The cross-ref `known_all = set(known_names) | set(EMERGING.keys())` in `build()` requires both sides to be fully assembled. A split that left one entries module unimported (e.g. `entries/__init__.py` typo) silently drops a name and validation fails AT BUILD TIME, not at import time.
   - *STOP-and-report rule:* gate 5 (`contract_check --item B1.1`) catches this in CI. The integration is: `entries/__init__.py` re-exports ALL 12 namespace modules; `_assembly.py` merges them all; `_build.py` validates against the full set.

10. **F-10. Hard-cap LOC breach for `entries/data.py` or `entries/obs.py`.**
    - *Symptom:* `entries/data.py` or `entries/obs.py` weighs ≥ 365 LOC at split time; future small additions (1-2 entries) push past 500.
    - *Cause:* both source-section blocks are ~358 LOC of curated data.
    - *STOP-and-report rule:* the §3 budget targets ~365 LOC for each, with ~135 LOC of headroom under the 500 cap. If post-split LOC lands ≥ 470, flag in PR body. If ≥ 500, **stop and report** — a sub-split (e.g. `entries/data_persistence.py` + `entries/data_modelling.py` + `entries/data_schema.py`) becomes the right shape but is its own follow-up WP.

11. **F-11. Hidden behavior leak via top-level pop / mutation.**
    - *Symptom:* `import engine.audit.compose_data.entries.auth` triggers `E.pop(...)` at import time, mutating a module-level dict that other imports see in a different state.
    - *Cause:* author moved `E.pop("TokenIntrospectorX", None)` into `entries/auth.py` instead of `_assembly.py`.
    - *STOP-and-report rule:* `entries/*.py` modules MUST be pure data — no statements at module top beyond the dict literal definition. Pops + merges live in `_assembly.py`. Violation = stop and report.

12. **F-12. Test-time discovery breaks under pytest's working directory.**
    - *Symptom:* `pytest engine/tests/test_delivery_contract.py` passes when run from `skills/SKILL-001-fastapi-production` but fails under CI's working dir because `SKILL_ROOT` resolution flipped.
    - *Cause:* `SKILL_ROOT = Path(__file__).resolve().parents[2]` lives in `_constants.py` — the `parents` index changed because the package nesting depth changed.
    - *STOP-and-report rule:* gate 5 (`pytest`) runs from the standard interpreter cwd. `_constants.py` lives at `engine/audit/compose_data/_constants.py` → `parents[3]` reaches `skills/SKILL-001-fastapi-production/`. If the new path requires `parents[3]` instead of `parents[2]`, **update it deliberately and document in the docstring**. Silent re-derivation = stop and report.

13. **F-13. Stale staging-directory token re-introduced.**
    - *Symptom:* grep finds the pre-PR-#24 staging-tree token in any new file (manifest, code, comment).
    - *Cause:* author copied from an older brief that pre-dated PR #24's staging-tree rename.
    - *STOP-and-report rule:* the only legal staging-tree token in this WP is `_staging/`. Any other staging-tree name in `docs/wp/WP-17*` or `engine/audit/compose_data/` = stop and report. The `_staging` filter in `_build.py` stays as `"_staging" not in m.parts`.

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** `engine/audit/compose_data/` package created with 17 files per §3.
- [ ] **D-02.** `engine/audit/_build_compose.py` rewritten as ≤35-LOC facade.
- [ ] **D-03.** Every new file ≤500 LOC (gate 2). No file exceeds the hard cap.
- [ ] **D-04.** Entries-modules are pure data — only `from __future__ import annotations`; no other imports anywhere (gate 4 + grep audit).
- [ ] **D-05.** `_assembly.py` pops `TokenIntrospectorX` placeholder; `'TokenIntrospectorX' not in E` after assembly (gate 4).
- [ ] **D-06.** `python -m engine.audit._build_compose` produces byte-identical `primitives_by_concern.yaml` pre vs post (§11 + gate 1).
- [ ] **D-07.** Idempotency contract intact: second run reports `appended=0` (gate 1).
- [ ] **D-08.** Zero new `.md` edits triggered by the post-split run against an already-built tree (gate 1 tar diff).
- [ ] **D-09.** `python -m engine.audit.contract_check --item B1.1` PASS; `--item B1.2` PASS (gate 5).
- [ ] **D-10.** `pytest engine/tests/test_delivery_contract.py -q` PASS — same count green pre vs post (gate 5).
- [ ] **D-11.** Ruff (check + format --check) green for the facade + every new module (gate 3).
- [ ] **D-12.** No stale staging-tree token anywhere in the WP-17 diff (only `_staging/` is legal post PR #24).
- [ ] **D-13.** `git diff --name-only main..HEAD` lists only paths in §1 write surface.
- [ ] **D-14.** Cross-namespace `EMERGING` references resolve (gate 5 `--item B1.1` catches dangling).
- [ ] **D-15.** YAML emission shape preserved character-for-character (gate 1 byte diff).
- [ ] **D-16.** Each new module's docstring states its scope (namespace covered or build-stage owned).
- [ ] **D-17.** Self-review: agent re-read its own diff as an adversarial reviewer (looking specifically for F-01..F-13 traps) and pasted findings in PR body.

## 11. Risk callout (WP-17-specific — engine compose-data blast radius)

**Why this section exists:** `engine/audit/_build_compose.py` produces two
outputs that the WHOLE skill kit treats as source-of-truth:

- `engine/primitives_by_concern.yaml` — read by §B1.1 / §B1.2 / §B1.3 audit
  rules; read by `engine.discovery.compose` (the
  `fastapi_meta_search_composition` MCP tool); read by every recipe lookup
  in the kit. A single key dropped here removes a primitive from the
  the agent's visible surface.
- `core/venous/<ns>/<Name>/<Name>.md` `## Compose with:` sections — read by
  §A5 "compose-with ≥3" inviolable rule and the recipe retrieval index. A
  silent re-append from this WP would duplicate bullets in 124 production
  `.md` files.

A subtle drift can ship as:

- A `purpose` string with one extra word (silent autocomplete substitution
  during the move) — the YAML diff catches this immediately.
- A `compose_with` list missing one sibling (a copy-paste deletion of one
  list element) — the `len(compose_with) ≥ 2` validation in `build()`
  catches the obvious case; a 4-element → 3-element trim is harder to spot
  without the §11 gate.
- A pattern `invariant` rephrased (cosmetic re-flow during the move) — the
  `.md` files would gain re-appended sections because the `if "## Compose
  with:" in body:` idempotency check still triggers, but the YAML diff
  surfaces the prose drift.
- The hand-rolled YAML emission re-quoted (the `yaml_str()` helper replaced
  by `yaml.safe_dump`) — flips every quoting decision in 124 entries.
- A re-ordered `lines.append(...)` sequence in YAML emission — flips the
  key order in every emitted entry (`name → namespace → concern → purpose
  → compose_with` is the source-of-truth order).
- A sort-key change (`(namespace, name)` → `(concern, name)`) — reorders
  the entire YAML file, breaking downstream consumers that scan by
  position.
- A regression where `_staging/` is no longer filtered out of the manifest
  scan — admits ~175 staged primitives + 42 quarantined into the registry,
  silently breaking the B1.1 production-only contract.

**Mitigation: byte-equivalent pre/post `primitives_by_concern.yaml` gate.**
Before declaring this WP done, the agent MUST capture both outputs and diff
them:

```bash
# Pre-split capture (on main, BEFORE the WP branch)
git checkout main
PY=.venv/bin/python
$PY -m engine.audit._build_compose 2>&1 | tee /tmp/bc_pre.log
cp engine/primitives_by_concern.yaml /tmp/pbcc_pre.yaml

# Post-split capture (on the WP branch, AFTER the split)
git checkout wp/17-engine-build-compose-split
$PY -m engine.audit._build_compose 2>&1 | tee /tmp/bc_post.log
cp engine/primitives_by_concern.yaml /tmp/pbcc_post.yaml

# Byte-equivalent OR rule-by-rule pre/post comparison gate
diff -u /tmp/pbcc_pre.yaml /tmp/pbcc_post.yaml      # PASS = empty
diff -u /tmp/bc_pre.log    /tmp/bc_post.log          # PASS = empty (idempotent log)
# Verify idempotency: second post-run reports `appended=0`
$PY -m engine.audit._build_compose 2>&1 | grep -E "appended 0 sections"
```

PASS criteria (all three must hold):
- `primitives_by_concern.yaml` byte-equivalent AND
- stdout log byte-equivalent AND
- second post-split run reports `appended=0` (idempotency).

Any non-empty diff for non-cosmetic reasons = **stop and report — do NOT
ship**. Paste the diff verbatim in the PR body. Cosmetic diffs (e.g.
trailing whitespace) MUST also be reported, not silently normalized.

Run the same gate against `pytest engine/tests/test_delivery_contract.py -q`:
the pass/fail count + per-test name list MUST match.

**Model elevation rationale:** `opus` reasoning is required because ~2 370
LOC of this file is curated prose (the `E` and `EMERGING` data tables); a
character-level diff is the only way to catch silent text drift, and
`sonnet`-class auto-cleanup has historically rewritten prose during code
moves. The split discipline must hold to the rule: **copy bytes, do not
edit**. `opus` is the model that catches the boundary between "moved as-is"
and "subtly reformatted" in the §11 review.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
