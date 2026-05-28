# Work Package Contract — `WP-09-auth-policy`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-09-specific content fills each section.
> Theme: **server-side authorization, isolation, gating — what the request is
> allowed to do** — 7 cohesive tools from `adapt/extend/auth_access/`. Disjoint
> from WP-08 (which migrates the *credential* surface — what the client presents).
>
> **Model elevation:** WP-09 runs on `opus`, not `sonnet`, because authorization
> primitives carry the highest *silent-bypass* blast radius in WAVE 1. A subtle
> drift in RBAC role resolution, BOLA owner check, multi-tenancy row filter,
> Cedar/OPA policy evaluation, or feature-flag fallback ships as cross-tenant
> data leakage or BOLA — exactly the bug classes the round-2 external panel
> already convicted on the unfixed compose layer (memory `external_eval_panel_round2.md`).
> See §11 for the WP-specific risk callout and the folded P1 #16 (BOLA
> secure-default).

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-09-auth-policy` |
| **Title** | Migrate 7 auth policy / authorization tools to per-tool directory + externalized templates (folds P1 #16 BOLA secure-default) |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (PR #24, merged) · `WP-F1-base-and-golden` (golden `add_cursor_pagination/` already on main via PR #28) |
| **Blocks** | none (sibling WPs are file-disjoint) |
| **Branch** | `wp/09-auth-policy` (off the post-dependency main) |
| **Isolation** | dedicated git worktree |
| **Model** | `opus` — authz primitives carry highest silent-bypass blast radius; P1 #16 (BOLA secure-default) folded into this WP requires subtle judgement on generator-emitted ownership guards |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_bola_guard/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_cedar_policies/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_feature_flags/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_feature_toggles_api/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_multi_tenancy/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_opa_integration/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_rbac/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_bola_guard.py            [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_cedar_policies.py        [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_feature_flags.py         [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_feature_toggles_api.py   [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_multi_tenancy.py         [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_opa_integration.py       [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_rbac.py                  [DELETE]
  ```
- **Golden reference (read-only, copy the pattern):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` (already on main via PR #28; canonical F1 golden)
- **Shared base/contract to import (read-only):** `skills/SKILL-001-fastapi-production/adapt/_base/` + `skills/SKILL-001-fastapi-production/adapt/contracts/`
- **Spec to follow:** `docs/tool-contract.md`, `docs/architecture.md`
- **Staging pool (read-only reference, not a write surface):** `core/venous/_staging/` (renamed via WP-F0; see PR #24)
- **BOLA guard generator (read-only context for §11 P1 #16):** `skills/SKILL-001-fastapi-production/generators/endpoints/crud_routes.py:219` and `skills/SKILL-001-fastapi-production/orchestrator.py` — referenced from `add_bola_guard` for the secure-default emission point.

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-01/02/03 (infrastructure WAVE 1) tools** — all 27 tools owned by the three sibling infrastructure manifests.
- **WP-04/05/06 (sibling Z2) tools** — the 26 remaining `adapt/extend/infrastructure/add_*` tools.
- **WP-07 (CRUD data) tools** — `add_audit_log`, `add_bulk_operations`, `add_cursor_pagination` (golden), `add_data_export`, `add_data_import`, `add_data_versioning`, `add_event_sourcing`, `add_file_upload`, `add_search`, `add_soft_delete`.
- **WP-08 (Auth identity) tools** — `add_api_key_auth`, `add_dpop_tokens`, `add_mfa`, `add_oauth2_provider`, `add_passkey_auth`, `add_request_signing`, `add_sms_otp`, `add_social_login`. These are the *credential* surface — disjoint from this WP's *authorization* surface.
- **WP-D/E/F sibling agents** — tools under `realtime/`, `testing_tools/`, `api_design/`, evolve/verify/hex/engine-split surfaces.
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here.
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope. **Critical for P1 #16:** even though the BOLA secure-default lives conceptually at `generators/endpoints/crud_routes.py:219` and `orchestrator.py`, the fix is executed by the migrated `add_bola_guard/__init__.py` patching the emitted route templates — NOT by editing `generators/` or `orchestrator.py` directly. See §11 for the precise patch point.
- `adapt/extend/auth_access/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report**.
- `hugr_auth/` — HuGR license/auth gate (the kit's own service); touching it is an instant reject. (Note: WP-09 migrates *emitted-app* authorization tools — `add_bola_guard` is the BOLA guard *for the emitted FastAPI project*, not for the HuGR gate.)

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 7 auth policy / authorization tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl`, route their `discover/patch` through `adapt/_base/`, AND execute the folded P1 #16 (BOLA secure-default emission — see §11) inside `add_bola_guard`.
- **Before:** Each tool is a single `add_<tool>.py` carrying embedded code-as-strings (BOLA per-object owner check, Cedar policy bundle + evaluator, feature-flag store + middleware, feature-toggle CRUD API, multi-tenant row filter + tenant-bootstrap, OPA sidecar integration + policy fetch, RBAC role + permission resolver). Per-tool LOC measurements (raw, end of §8) range 152–1825. `add_multi_tenancy` at 1825 LOC is the heaviest tool in WAVE 1's auth surface.
- **After:**
  - Each tool becomes `add_<tool>/__init__.py` + `templates/*.py.tmpl`.
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*.py.tmpl`. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.extend.auth_access.add_<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.
  - **Honesty-rule audit per tool:** any `warnings` string MUST honestly describe what the migrated code enforces. Carry-over of overclaiming from the source is an instant reject (authz overclaiming = silent bypass).
  - **P1 #16 fold (`add_bola_guard`):** the migrated tool MUST emit a per-object ownership guard on ALL owner-bearing models by default, with `shared_models={...}` as the opt-out, AND every opt-out model MUST emit a test documenting the open-access decision. The emission point patches the route templates fed by `generators/endpoints/crud_routes.py:219` (read-only context — the migrated tool patches the *templates*, not the generator).
  - **§11 byte-equivalence diff gate** must pass for each tool *except* `add_bola_guard` (P1 #16 is a deliberate behavior change; see §11 for the targeted diff).

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `add_bola_guard` | `add_bola_guard/{__init__.py, templates/}` | ≤ 290 | ≥ 2 (2 `dedent`, 27 triple-quote anchors) + secure-default route patch | `test_add_bola_guard_emitted.py` |
| `add_cedar_policies` | `add_cedar_policies/{__init__.py, templates/}` | ≤ 290 | ≥ 8 (8 `dedent`, 40 triple-quote anchors) | `test_add_cedar_policies_emitted.py` |
| `add_feature_flags` | `add_feature_flags/{__init__.py, templates/}` | ≤ 290 | ≥ 10 (8 `dedent` + 2 `_GLUE` consts, 48 triple-quote anchors) | `test_add_feature_flags_emitted.py` |
| `add_feature_toggles_api` | `add_feature_toggles_api/{__init__.py, templates/}` | ≤ 130 | ≥ 2 (5 triple-quote anchors → ~2 code blocks, 2 `_GLUE`) | `test_add_feature_toggles_api_emitted.py` |
| `add_multi_tenancy` | `add_multi_tenancy/{__init__.py, templates/}` | ≤ 290 | ≥ 14 (14 `dedent`, 72 triple-quote anchors) | `test_add_multi_tenancy_emitted.py` |
| `add_opa_integration` | `add_opa_integration/{__init__.py, templates/}` | ≤ 290 | ≥ 8 (8 `dedent`, 40 triple-quote anchors) | `test_add_opa_integration_emitted.py` |
| `add_rbac` | `add_rbac/{__init__.py, templates/}` | ≤ 230 | ≥ 2 (10 triple-quote anchors → ~5 code blocks, 2 `_GLUE`) | `test_add_rbac_emitted.py` |

- **Out of scope:** behavior changes outside the explicit P1 #16 fold, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope. **Specifically:** the agent MUST NOT "improve" the authz posture of any tool beyond P1 #16 (e.g. tighten an RBAC role-hierarchy, force OPA into deny-by-default, swap tenant header for sub-domain). Those are separate WPs.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change** outside the explicit P1 #16 fold (§3 + §11). Same `ToolInput` → same `ToolResult` shape; same files emitted, byte-equivalent per §11 diff gate (with `add_bola_guard` as the deliberate exception). Proven by GATE 1 + §11 diff.
- [ ] **Import paths stable.** `from adapt.extend.auth_access.add_<tool> import add_<tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep`.
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused `_GLUE`/`_TEMPLATE` constants left dangling.
- [ ] **Docstrings honest.** Authz-specific: a tool that does NOT enforce a guarantee MUST lead its `warnings` with `⚠ … IS NOT ENFORCED`. Examples: `add_rbac` warning if role hierarchy is advisory; `add_cedar_policies` warning if Cedar bundle is sample-only; `add_feature_flags` warning if default-on/default-off behavior diverges from documented; `add_multi_tenancy` warning if tenant isolation is best-effort (the round-2 external panel already convicted the unfixed version on tenant isolation — see memory `external_eval_panel_round2.md`); `add_opa_integration` warning if OPA bundle is a placeholder; `add_bola_guard` warning describing exactly which models are owner-scoped vs `shared_models` opt-out.
- [ ] **No new dependencies.** No `pyproject.toml` change. Emitted deps go in generated `requirements.txt`.
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool.
- [ ] **§11 byte-equivalence diff gate passes for 6 of 7 tools.** `add_bola_guard` has a targeted P1 #16 diff (see §11) — diff is NOT empty but is *expected and reviewed*.
- [ ] **P1 #16 verified.** `add_bola_guard` emits owner-scoped check on ALL owner-bearing models by default; `shared_models={...}` opt-out emits a test documenting open access.

## 5. Test emission (per P1 #15)
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy that format verbatim** (location: `{project}/tests/test_<tool>_emitted.py`). WP-07 is the canonical propagation precedent for the WAVE 1 P1 #15 rollout; WP-09 follows it.

For each of the 7 tools in §1, the migrated `__init__.py` MUST:
- Render an emitted test from `templates/test_<tool>_emitted.py.tmpl`.
- Place it at `{project_dir}/tests/test_<tool>_emitted.py`.
- Make it green under the emitted project's `pytest tests/` after compose.
- Cover at least one positive (authz primitive fires: e.g. `add_bola_guard` rejects an owner-A read of an owner-B object AND emits an explicit "open access" test for every `shared_models` entry; `add_cedar_policies` denies a forbidden action; `add_feature_flags` returns the off branch when flag is disabled; `add_feature_toggles_api` accepts a write from an authorized actor and rejects from an unauthorized one; `add_multi_tenancy` filters a list query by tenant and rejects a cross-tenant read by ID; `add_opa_integration` proxies to OPA and returns deny for a forbidden input; `add_rbac` resolves `permissions(role)` and denies an action the role lacks) and one negative (allowed action passes through unchanged) assertion. Same skeleton as F1 golden.
- **Honesty rule:** if the tool's behavior is advisory-only (e.g. `add_feature_flags` does not enforce a kill-switch on running requests), the emitted test asserts the advisory signal (log line / decision record), NOT a fictitious enforcement. **Authz overclaiming is an instant reject.**

Failure to emit a test, OR an emitted test that asserts a guarantee the tool does not deliver, = WP rejected. Non-negotiable per P1 #15 + honesty rules.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7. These are the 5 mandatory WAVE 1 gates established by WP-01 §6.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/extend/auth_access/add_{bola_guard,cedar_policies,feature_flags,feature_toggles_api,multi_tenancy,opa_integration,rbac}
$PY -m ruff format --check adapt/extend/auth_access/add_{bola_guard,cedar_policies,feature_flags,feature_toggles_api,multi_tenancy,opa_integration,rbac}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/extend/auth_access/test_add_{bola_guard,cedar_policies,feature_flags,feature_toggles_api,multi_tenancy,opa_integration,rbac}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'add_bola_guard|add_cedar_policies|add_feature_flags|add_feature_toggles_api|add_multi_tenancy|add_opa_integration|add_rbac'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (37/37)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7. Additionally, §11 byte-equivalence diff must be PASS per tool (6 of 7 empty; `add_bola_guard` has a reviewed P1 #16 diff).

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-09 owns (write surface):** the 7 directories under `adapt/extend/auth_access/add_<tool>/` listed in §1, plus the 7 legacy flat `.py` file deletions listed in §1.

**WP-09 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-01 Resiliency | the 9 tools in `docs/wp/WP-01-resiliency-defense.md` §1 |
| WP-02 Observability | the 9 tools in `docs/wp/WP-02-observability-diagnostics.md` §1 |
| WP-03 Security | the 9 tools in `docs/wp/WP-03-security-compliance.md` §1 |
| WP-04/05/06 Z2 | all 26 remaining `adapt/extend/infrastructure/add_*` tools |
| WP-07 CRUD data | `add_audit_log`, `add_bulk_operations`, `add_cursor_pagination` (golden), `add_data_export`, `add_data_import`, `add_data_versioning`, `add_event_sourcing`, `add_file_upload`, `add_search`, `add_soft_delete` |
| WP-08 Auth identity | `add_api_key_auth`, `add_dpop_tokens`, `add_mfa`, `add_oauth2_provider`, `add_passkey_auth`, `add_request_signing`, `add_sms_otp`, `add_social_login` |
| WP-D/E/F | `adapt/extend/realtime/`, `adapt/extend/testing_tools/`, `adapt/extend/api_design/`, evolve/verify/hex/engine-split tools |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Generator surface (read-only for P1 #16 context) | `generators/endpoints/crud_routes.py:219`, `orchestrator.py` — read for context, NEVER edit (the patch lives in `add_bola_guard/templates/`) |
| Shared | `adapt/extend/auth_access/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI, `hugr_auth/` |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation; LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'`; `glue` = `grep -c '_GLUE\|_TEMPLATE\|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `add_bola_guard` | 722 | ≤ 290 (-60%) | 2 | 27 | 0 | 5.0 h (+P1 #16 patch) | `opus` |
| `add_cedar_policies` | 744 | ≤ 290 (-61%) | 8 | 40 | 0 | 4.0 h | `opus` |
| `add_feature_flags` | 1519 | ≤ 290 (-81%) | 8 | 48 | 2 | 5.5 h | `opus` |
| `add_feature_toggles_api` | 152 | ≤ 130 (-14%) | 0 | 5 | 2 | 1.0 h | `opus` |
| `add_multi_tenancy` | 1825 | ≤ 290 (-84%) | 14 | 72 | 0 | 6.5 h | `opus` |
| `add_opa_integration` | 897 | ≤ 290 (-68%) | 8 | 40 | 0 | 4.5 h | `opus` |
| `add_rbac` | 326 | ≤ 230 (-29%) | 0 | 10 | 2 | 2.5 h | `opus` |
| **TOTAL** | **6185** | **~1810 (-71%)** | **40** | **242** | **6** | **~29 h** | `opus` |

**Model recommendation: `opus`.** Three forces drive elevation. (1) Authz blast radius: a silent drift in BOLA owner check, multi-tenant row filter, RBAC permission resolution, or Cedar/OPA policy evaluation ships as cross-tenant data leakage. The round-2 external panel UNANIMOUSLY convicted the unfixed multi-tenancy + RBAC + BOLA on exactly these classes of bug (memory `external_eval_panel_round2.md`). (2) P1 #16 (BOLA secure-default) requires architectural judgement — flipping the emitted default from "open" to "owner-scoped on every model" with explicit `shared_models={...}` opt-out is non-mechanical. (3) Honesty audit on authz `warnings` (e.g. multi-tenancy "isolation" claim vs "best-effort filter") needs `opus`-level reading of every template against the asserted guarantee.

## 9. Failure modes (≥6 anticipated traps)

1. **F-01. Embedded f-string interpolation lost in template move.**
   - *Symptom:* emitted code refers to `${project_name}` literally; `pytest tests/` in emitted project fails at import.
   - *Cause:* triple-quoted block used Python f-strings; renderer uses a different placeholder syntax.
   - *STOP-and-report rule:* before extraction, dump source's interpolation style; mismatch with F1 golden = stop and report.

2. **F-02. `MCP_TOOL` metadata lost in module split.**
   - *Symptom:* `engine.audit.contract_check` drops from 37/37 → 36/37.
   - *Cause:* `MCP_TOOL = {...}` not copied into the new `__init__.py`.
   - *STOP-and-report rule:* per-tool sanity import check; fail = stop and report.

3. **F-03. Idempotency regression — second run rewrites files.**
   - *Symptom:* second-run case fails; `ToolResult.status` returns `success` instead of `no_op`.
   - *Cause:* `discover()` skip-set lost when routing through `adapt/_base/discover.py`. authz tools historically skip `user`, `superuser`, `tenant`, `rbac`, `role`, `permission`, `policy`.
   - *STOP-and-report rule:* missing skip-set entry = stop and report; do NOT re-inline discovery.

4. **F-04. P1 #16 secure-default leaks to `shared_models` table.**
   - *Symptom:* migrated `add_bola_guard` emits owner-scoped check on a model the caller explicitly listed in `shared_models={...}`, breaking a legitimately-shared resource (e.g. a public-catalog endpoint).
   - *Cause:* the per-object guard fires before the `shared_models` opt-out check, OR the opt-out list is consulted with a name mismatch (singular vs plural).
   - *STOP-and-report rule:* emitted test MUST include a positive case for every `shared_models` entry (asserting that owner-A can read owner-B's row when the model is in the opt-out list). If the asserted behavior diverges from the guard, **stop and report**.

5. **F-05. P1 #16 secure-default missed on a model without an `owner` FK.**
   - *Symptom:* migrated `add_bola_guard` skips a model that has ownership semantics via a different FK (e.g. `created_by_id`, `tenant_id`); BOLA still reachable.
   - *Cause:* the owner-detection heuristic only looks for the literal `owner_id` column.
   - *STOP-and-report rule:* the migrated tool MUST document its owner-detection rule in `warnings` and the emitted test MUST exercise it on a model with a non-`owner_id` FK. If detection is ambiguous, **stop and report** — do NOT silently widen.

6. **F-06. Honesty-rule violation — overclaiming authz guarantees.**
   - *Symptom:* migrated `warnings` claim "multi-tenant isolated" when the emitted code only adds a header-derived `tenant_id` filter (no row-level security); "RBAC enforced" when the resolver returns a flat permission set with no hierarchy; "OPA deny-by-default" when the OPA fetch falls open on a network error.
   - *Cause:* author copy-pasted optimistic `warnings` from source without re-reading emitted templates. The round-2 external panel found "fail-open tenant isolation" as a 4/4 unanimous bug — the migrated `warnings` MUST NOT carry over that overclaim.
   - *STOP-and-report rule:* per tool, read every emitted template, then read the `warnings`. Any unenforced authz claim = **stop and report, do NOT ship**. Fix the `warnings` to honest in this WP (behavior change is out of scope per §3, except P1 #16).

7. **F-07. Emitted-test missing or trivially-true (per P1 #15).**
   - *Symptom:* emitted test asserts `True`, OR asserts a guarantee the tool does not deliver.
   - *Cause:* skeleton copied without honesty-adapted assertions.
   - *STOP-and-report rule:* every emitted test MUST cover ≥1 positive + ≥1 negative against the actual emitted behavior. Mismatch = stop and report.

8. **F-08. `add_multi_tenancy` 14 `dedent` blocks form a tenant-bootstrap graph.**
   - *Symptom:* extracting one template breaks tenant-creation flow (e.g. the bootstrap endpoint depends on the tenant-context middleware which depends on the tenant-resolver dependency).
   - *Cause:* 1825 LOC source assembles emitted code from interdependent fragments; the round-2 panel already convicted this layer on tenant-bootstrap deadlock + multi_tenancy-breaks-test-suite (4/4 + 2/2).
   - *STOP-and-report rule:* before extraction, draw the dependency graph of the 14 dedent blocks. If extraction requires re-inlining, **stop and report** — `_base` fragment-composition helper may be needed.

9. **F-09. `add_feature_flags` default-on/default-off carry-over drift.**
   - *Symptom:* a flag's default flipped during template extraction (e.g. a kill-switch default-on became default-off); emitted app's behavior diverges silently.
   - *Cause:* the source's `_GLUE`/dedent block held the default literal; extraction re-typed it.
   - *STOP-and-report rule:* snapshot every flag's default pre-migration; grep emitted output post-migration; mismatch = stop and report.

10. **F-10. `add_opa_integration` fail-open on OPA unavailable.**
    - *Symptom:* migrated emitted middleware swallows the OPA HTTP exception and allows the request (fail-open).
    - *Cause:* the source has a fail-open `try/except` pattern; carrying it forward is a security regression even though it's "no behavior change". Honesty rule MUST flag it in `warnings`.
    - *STOP-and-report rule:* the migrated `warnings` MUST say `⚠ FAILS OPEN ON OPA UNAVAILABLE` if the emitted code does; emitted test MUST exercise the OPA-down path and assert the (admittedly insecure) observed behavior. Behavior change is out of scope; the `warnings` honesty is not.

11. **F-11. Hard-cap LOC breach (`__init__.py` > 500).**
    - *Symptom:* size invariant fails for `add_multi_tenancy` (1825 LOC source, 14 `dedent`) or `add_feature_flags` (1519 LOC, 8 `dedent`).
    - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
    - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC without inlining `_base/`, **stop and report**.

12. **F-12. §11 byte-equivalence diff gate fails for non-cosmetic reason (non-bola tools).**
    - *Symptom:* diff shows a logic change (re-ordered policy eval, dropped tenant filter, altered role-hierarchy walk) on a tool other than `add_bola_guard`.
    - *Cause:* extraction lost or re-ordered emitted content.
    - *STOP-and-report rule:* never normalize the diff away. **Stop and report** with the diff verbatim. (`add_bola_guard` is the *only* tool with an expected diff per P1 #16; everything else is byte-equivalent.)

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** All 7 tool directories created under `adapt/extend/auth_access/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 7 legacy flat `.py` files removed (`git diff --name-only` shows 7 deletions).
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c` → 0 for all 7).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not).
- [ ] **D-06.** All 7 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive + ≥1 negative assertion. Honesty-adapted per F-06. `add_bola_guard` additionally emits a per-`shared_models`-entry "open access" assertion per F-04.
- [ ] **D-07.** §6 gate 1 (ruff) green for all 7 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 7 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke) returns a PASS line per tool name.
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 37/37.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface (no `generators/` or `orchestrator.py` edits).
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`).
- [ ] **D-14.** §11 byte-equivalence diff gate empty for 6 of 7 tools; `add_bola_guard` shows ONLY the targeted P1 #16 secure-default diff, reviewed and pasted in PR.
- [ ] **D-15.** **P1 #16 verified.** `add_bola_guard` emits owner-scoped check on ALL owner-bearing models by default; every `shared_models={...}` entry emits an explicit open-access test; the route-template patch matches the contract derived from `generators/endpoints/crud_routes.py:219` semantics.
- [ ] **D-16.** Honesty-rule audit per tool: every `warnings` string re-read against actually emitted templates; authz overclaims fixed to honest.
- [ ] **D-17.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

## 11. Risk callout (WP-09-specific — authz blast radius + folded P1 #16 BOLA secure-default)

**Why this section exists:** WP-09 sits on top of the code that decides "may this request do this thing". A subtle drift in any of these 7 tools can ship as:

- A BOLA where owner-A reads owner-B's row (the bug class P1 #16 closes).
- A multi-tenant row filter that fails open on missing header (round-2 panel 4/4 unanimous).
- An RBAC role-hierarchy walk that resolves recursively but caches the leaf permission (privilege escalation under flag flip).
- A Cedar policy bundle that evaluates the wrong action because of a string-canonicalization mismatch.
- An OPA integration that fails open on network error (already flagged in F-10).
- A feature-flag default flip that toggles a kill-switch silently.
- A feature-toggles API that writes without an authz check (RBAC inert — round-2 panel 3/3 convicted).

### P1 #16 — `add_bola_guard` MUST emit owner-scoped check on ALL models by default

**P1 #16** documents that the current `add_bola_guard` is opt-in per model — a generator default for "owner-scoped check" lives implicitly at `skills/SKILL-001-fastapi-production/generators/endpoints/crud_routes.py:219` (the BUG-BOLA fix area) and at `skills/SKILL-001-fastapi-production/orchestrator.py` where the model list is assembled. A model that has an `owner_id` FK but is not explicitly enrolled in `add_bola_guard` ships *without* the per-object check; the result is a BOLA reachable from any authenticated user.

**Mandatory fix executed inside this WP (NOT a sibling WP):**

1. The migrated `add_bola_guard/__init__.py` MUST patch the emitted route templates so that **every** model with an owner-bearing FK emits a per-object ownership guard by default. The owner-detection rule MUST be documented in `warnings` (default rule: `owner_id` column present and FK-pointing at the user table; F-05 covers ambiguity).
2. `shared_models={...}` is the explicit opt-out. Every entry in `shared_models` MUST emit a per-entry test documenting the open-access decision (F-04 STOP rule). The opt-out is *deliberately verbose* — the test makes the open-access decision auditable.
3. The patch point lives in the migrated tool's templates, NOT in `generators/endpoints/crud_routes.py:219` or `orchestrator.py`. The generator is read-only context — the migrated tool patches the emitted routes via its own template fragments, and `orchestrator.py` is consulted (read-only) to confirm the model-discovery order matches.
4. The emitted test (`test_add_bola_guard_emitted.py`) MUST assert:
   - **Positive (default secure):** for every owner-bearing model NOT in `shared_models`, owner-A receives 403/404 when reading owner-B's row by ID.
   - **Negative (opt-out):** for every entry in `shared_models`, owner-A receives 200 when reading owner-B's row.
   - **Positive (RBAC interaction):** a superuser reads any row regardless of opt-in (matches `crud_routes.py:219` documented "Access policy: regular users may only fetch records they own; superusers have unrestricted access.").
5. The §11 byte-equivalence diff for `add_bola_guard` is **expected to be non-empty** — it MUST show the secure-default patch on emitted `app/api/endpoints/*_routes.py` and nothing else. Any drift outside the secure-default patch = STOP and report.

**Why fold P1 #16 into WP-09 (not a standalone fix PR):** the BOLA secure-default lives entirely inside `add_bola_guard`'s emitted templates (with `generators/endpoints/crud_routes.py:219` + `orchestrator.py` as read-only context for the contract). Extracting `add_bola_guard`'s templates in WP-09 without also flipping the default re-paints the bug into the new layout. Fixing once, here, is one unit of work; splitting would force two passes over the same templates. T-03 below documents this trade-off.

### Mitigation: per-tool byte-equivalence diff gate (carried over from WP-03 §11, with `add_bola_guard` exception)

Before declaring any tool migrated, the agent MUST:

```bash
# For each of the 7 tools:
PY=.venv/bin/python
git checkout main -- skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_<tool>.py
$PY -m engine.compose --tool add_<tool> --project /tmp/pre/<tool>
git checkout HEAD -- skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_<tool>
$PY -m engine.compose --tool add_<tool> --project /tmp/post/<tool>
diff -ruN /tmp/pre/<tool> /tmp/post/<tool> | grep -vE '^[+-]\s*(#|$)' | tee /tmp/diff_<tool>.txt
# For 6 of 7 tools: PASS = empty after comment/whitespace strip.
# For add_bola_guard: PASS = diff contains ONLY the secure-default patch on
#   emitted app/api/endpoints/*_routes.py (per P1 #16) and nothing else.
test ! -s /tmp/diff_<tool>.txt   # for the 6 non-bola tools
```

Paste each tool's diff-gate result in §7. If a non-bola tool's diff-gate is non-empty for non-cosmetic reasons, OR if `add_bola_guard`'s diff contains anything outside the secure-default patch, **stop and report — do NOT ship**.

### Honesty-rule audit (authz overclaims = instant reject)

For each tool, after migration, the agent MUST:

1. Read every emitted template.
2. Read the `warnings` string in the migrated `__init__.py`.
3. Cross-check: does every claim in `warnings` map to an enforced behavior? Examples of carry-over overclaims to catch (several of which the round-2 external panel already convicted on the unfixed compose layer):
   - `add_multi_tenancy` `warnings` claiming "isolation" when the filter is header-derived and falls open on missing header (4/4 panel).
   - `add_rbac` claiming "role hierarchy enforced" when the resolver returns a flat permission set (3/3 panel).
   - `add_bola_guard` claiming "all models guarded" when the source-pre-P1#16 version was opt-in.
   - `add_opa_integration` claiming "deny-by-default" when the OPA fetch fails open (F-10).
   - `add_feature_flags` claiming "kill-switch enforced" when the flag is read once at startup and cached.

Any unenforced claim = fix the `warnings` to honest in this WP. Behavior changes are out of scope per §3 (except P1 #16).

### Model elevation rationale

`opus` reasoning is required to (a) execute the P1 #16 fold without breaking the `shared_models` opt-out semantics, (b) read the §11 diff and judge cosmetic vs behavioral drift for the 6 non-bola tools, and (c) audit honesty on authz `warnings` against actually emitted templates. The round-2 external panel UNANIMOUSLY convicted the unfixed compose layer on exactly these classes of bug — running this WP on `sonnet` risks re-shipping the same bugs in the new layout.

### Trade-offs declared

- **T-01.** Theme partition (authz / policy) over alphabetical — keeps the "what is the request allowed to do" mental model intact across the 7 tools; the credential side (what the client presents) is the disjoint sibling WP-08.
- **T-02.** All `opus`, not `sonnet` — authz is one of two highest-blast-radius domains in WAVE 1 (the other is data integrity, WP-07).
- **T-03.** P1 #16 folded into WP-09 §11 + §5 instead of standalone PR — keeps the blast radius scoped to the WAVE 1 unit of change.
- **T-04.** Identity/policy split (8 + 7 across WP-08 and WP-09) — the two halves have different review cadences (identity = byte-equivalence on token-verification; policy = secure-default + emitted-test audit on authz decisions). Splitting halves cognitive load per agent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
