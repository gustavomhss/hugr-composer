# Work Package Contract — `WP-07-crud-data`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-07-specific content fills each section.
> Theme: **persistence, mutation lifecycle, bulk transfer, search, audit, soft
> deletion** — 9 cohesive tools from `adapt/extend/crud_data/`. The 10th tool
> in that category (`add_cursor_pagination`) is the F1 golden reference and is
> already migrated; it is intentionally excluded (see §11 trade-off T-04).
>
> **Model elevation:** WP-07 runs on `opus`, not `sonnet`, because data-integrity
> primitives carry one of the two highest behavior-change blast radii in WAVE 1
> (the other being authorization — WP-08/09). A silent drift in soft-delete
> filtering, bulk-operation transaction boundaries, or event-sourcing append
> order can corrupt the emitted application's data model in ways that survive
> compose and only surface in production. See §11 for the WP-specific risk
> callout and the two P1 backlog items (#14, #15) folded into this WP.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-07-crud-data` |
| **Title** | Migrate 9 crud_data tools to per-tool directory + externalized templates (golden `add_cursor_pagination` already migrated) |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (PR #24, merged) · `WP-F1-base-and-golden` (golden `add_cursor_pagination/` already on main via PR #28) |
| **Blocks** | none (sibling WPs are file-disjoint) |
| **Branch** | `wp/07-crud-data` (off the post-dependency main) |
| **Isolation** | dedicated git worktree |
| **Model** | `opus` — data-integrity primitives carry highest blast radius alongside authz; P1 #14 + P1 #15 folded into this WP require subtle judgement on UoW deletion + emitted-test honesty |

> **Phase 4 split note (2026-05-29).** WP-07 estimates ~37 h / 7 011 LOC across 9 tools — too heavy for a single agent session. Execute as **3 sub-WPs**:
> - **WP-07a crud-data-light (3 tools)** — `add_audit_log` + `add_event_sourcing` + `add_soft_delete`. Includes folded P1 #14 (`add_soft_delete` patches CRUDBase.delete + drops orphan UoW). Smallest tools + the architectural P1 fold. ~10-11 h.
> - **WP-07b crud-data-heavy-1 (3 tools)** — `add_bulk_operations` + `add_data_export` + `add_data_import`. ~15 h.
> - **WP-07c crud-data-heavy-2 (3 tools)** — `add_data_versioning` + `add_file_upload` + `add_search`. Includes F-08 raw-SQL preservation for `add_search`. ~15 h.
> P1 #14 status: already shipped via PR #36 (`fix(p1#14): soft_delete patches CRUDBase + drops orphan UoW`). WP-07a's `add_soft_delete` migration is structural-only — the patch is in main. P1 #15 (emitted tests honest, ≥1 pos + ≥1 neg per tool) folds into each sub-WP for the 3 tools it owns. Sub-WP ids: `WP-07a`, `WP-07b`, `WP-07c`. Branches: `wp/07a-crud-light`, `wp/07b-crud-heavy-1`, `wp/07c-crud-heavy-2`.

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_audit_log/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_bulk_operations/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_data_export/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_data_import/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_data_versioning/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_event_sourcing/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_file_upload/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_search/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_soft_delete/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_audit_log.py          [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_bulk_operations.py    [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_data_export.py        [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_data_import.py        [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_data_versioning.py    [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_event_sourcing.py     [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_file_upload.py        [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_search.py             [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_soft_delete.py        [DELETE]
  ```
- **Golden reference (read-only, copy the pattern):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` (already on main via PR #28; this is the canonical F1 golden, NOT a write surface)
- **Shared base/contract to import (read-only):** `skills/SKILL-001-fastapi-production/adapt/_base/` + `skills/SKILL-001-fastapi-production/adapt/contracts/`
- **Spec to follow:** `docs/tool-contract.md`, `docs/architecture.md`
- **Staging pool (read-only reference, not a write surface):** `core/venous/_staging/` (renamed via WP-F0; see PR #24)
- **CRUDBase target (read-only context for §11 P1 #14):** the emitted `app/crud/base.py` produced by the generator — referenced from `add_soft_delete` for the soft-delete patch point.

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-01/02/03 (infrastructure WAVE 1) tools** — all 27 tools owned by the three sibling infrastructure manifests.
- **WP-04/05/06 (sibling Z2 async/storage/payments) tools** — the 26 remaining `adapt/extend/infrastructure/add_*` tools.
- **WP-08 (Auth identity) tools** — `add_api_key_auth`, `add_dpop_tokens`, `add_mfa`, `add_oauth2_provider`, `add_passkey_auth`, `add_request_signing`, `add_sms_otp`, `add_social_login`.
- **WP-09 (Auth policy) tools** — `add_bola_guard`, `add_cedar_policies`, `add_feature_flags`, `add_feature_toggles_api`, `add_multi_tenancy`, `add_opa_integration`, `add_rbac`.
- **WP-D/E/F sibling agents** — tools under `realtime/`, `testing_tools/`, `api_design/`, evolve/verify/hex/engine-split work surfaces.
- **`add_cursor_pagination/`** — the F1 golden; read-only reference, no edits, no re-migration.
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here.
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope. (Note: P1 #14 wants `app/soft_delete.py` orphan UoW deleted at the *emitted* layer; that change happens inside `add_soft_delete/templates/` + its `__init__.py`, NOT in `generators/` or `tests/`.)
- `adapt/extend/crud_data/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report**.
- `hugr_auth/` — license gate; touching it is an instant reject.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 9 crud_data tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl`, route their `discover/patch` through `adapt/_base/`, AND execute the two folded P1s (#14 soft-delete CRUDBase patch + orphan UoW removal; #15 emitted-test per tool — both gated and explicit in §5 / §11).
- **Before:** Each tool is a single `add_<tool>.py` carrying embedded code-as-strings (CRUD mixins, audit hooks, export/import streamers, versioning mappers, event-sourcing append loops, file-upload multipart handlers, search SQL builders, soft-delete query filters) plus per-tool ad-hoc discovery/patching. Per-tool LOC measurements (raw, end of §8) range 150–1870.
- **After:**
  - Each tool becomes `add_<tool>/__init__.py` + `templates/*.py.tmpl`.
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*.py.tmpl`. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.extend.crud_data.add_<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.
  - **P1 #14 fold (`add_soft_delete`):** the migrated tool MUST patch the emitted `app/crud/base.py` `CRUDBase.delete` to soft-delete by default rather than shadow-overriding per-model, AND it MUST stop emitting the orphan `app/soft_delete.py` Unit-of-Work file. The pre-migration source emits a `_soft_delete_flush` UoW into `app/soft_delete.py` that no caller imports — that path is dead and was the root cause of "deletes still hard-delete" behavior under the previous always-False guards. See §11 for the patch point + delete point.
  - **P1 #15 fold (every tool):** each migrated tool MUST emit a per-tool behavior test at `{project}/tests/test_<tool>_emitted.py`, matching the golden `add_cursor_pagination` skeleton, with ≥1 positive + ≥1 negative assertion. See §5.

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `add_audit_log` | `add_audit_log/{__init__.py, templates/}` | ≤ 160 | ≥ 2 (10 triple-quote anchors → ~5 code blocks, 2 `_GLUE`) | `test_add_audit_log_emitted.py` |
| `add_bulk_operations` | `add_bulk_operations/{__init__.py, templates/}` | ≤ 290 | ≥ 7 (7 `dedent`, 36 triple-quote anchors) | `test_add_bulk_operations_emitted.py` |
| `add_data_export` | `add_data_export/{__init__.py, templates/}` | ≤ 290 | ≥ 8 (8 `dedent`, 41 triple-quote anchors) | `test_add_data_export_emitted.py` |
| `add_data_import` | `add_data_import/{__init__.py, templates/}` | ≤ 290 | ≥ 9 (9 `dedent`, 46 triple-quote anchors) | `test_add_data_import_emitted.py` |
| `add_data_versioning` | `add_data_versioning/{__init__.py, templates/}` | ≤ 290 | ≥ 8 (8 `dedent`, 42 triple-quote anchors) | `test_add_data_versioning_emitted.py` |
| `add_event_sourcing` | `add_event_sourcing/{__init__.py, templates/}` | ≤ 130 | ≥ 2 (6 triple-quote anchors → ~3 code blocks, 2 `_GLUE`) | `test_add_event_sourcing_emitted.py` |
| `add_file_upload` | `add_file_upload/{__init__.py, templates/}` | ≤ 290 | ≥ 12 (12 `dedent`, 62 triple-quote anchors) | `test_add_file_upload_emitted.py` |
| `add_search` | `add_search/{__init__.py, templates/}` | ≤ 290 | ≥ 4 (4 `dedent`, 28 triple-quote anchors) | `test_add_search_emitted.py` |
| `add_soft_delete` | `add_soft_delete/{__init__.py, templates/}` | ≤ 280 | ≥ 2 (2 `dedent`, 28 triple-quote anchors, 2 `_GLUE`) + CRUDBase patch fragment + **deletion of `app/soft_delete.py` emission** | `test_add_soft_delete_emitted.py` |

- **Out of scope:** behavior changes outside the two folded P1s, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope, *re-migration of `add_cursor_pagination`* (it is the golden — read it, copy the pattern, do not edit it).

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change** outside the two explicit P1 folds (§3 + §11). Same `ToolInput` → same `ToolResult` shape; same files emitted (byte-equivalent after stripping comments/whitespace) except for the deliberate `add_soft_delete` CRUDBase patch + `app/soft_delete.py` removal. Proven by GATE 1 + targeted diff in §11.
- [ ] **Import paths stable.** `from adapt.extend.crud_data.add_<tool> import add_<tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep`.
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused `_GLUE`/`_TEMPLATE` constants left dangling. **Specifically:** the emitted `app/soft_delete.py` UoW shim is dead code in the source — `add_soft_delete` MUST stop emitting it (P1 #14).
- [ ] **Docstrings honest.** A tool that does not enforce something MUST say so in its `warnings`. Examples: `add_audit_log` warning if append-only is advisory; `add_data_export` warning if streaming is best-effort vs guaranteed; `add_search` warning if SQL builder is naïve (no FTS) — never imply success it doesn't deliver.
- [ ] **No new dependencies.** No `pyproject.toml` change. Emitted deps go in generated `requirements.txt`.
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool.
- [ ] **P1 #14 verified.** `add_soft_delete` patches `app/crud/base.py` CRUDBase (not per-model shadow), AND `app/soft_delete.py` is no longer in the emitted file tree. Verified by diff on a clean compose.
- [ ] **P1 #15 verified.** Every one of the 9 tools emits `{project}/tests/test_<tool>_emitted.py` and the emitted file's `pytest tests/` is green.

## 5. Test emission (per P1 #15)
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy that format verbatim** (location: `{project}/tests/test_<tool>_emitted.py`). This WP propagates the pattern to 9 more tools; it is the canonical example for **the entire WAVE 1 P1 #15 rollout** and downstream WPs (WP-08, WP-09, WP-D, etc.) cite this WP as precedent.

For each of the 9 tools in §1, the migrated `__init__.py` MUST:
- Render an emitted test from `templates/test_<tool>_emitted.py.tmpl`.
- Place it at `{project_dir}/tests/test_<tool>_emitted.py`.
- Make it green under the emitted project's `pytest tests/` after compose.
- Cover at least one positive (added behavior fires: e.g. `add_audit_log` records a mutation row, `add_bulk_operations` commits-or-rolls-back as a single tx, `add_data_export` streams the right rowcount, `add_data_import` validates schema and skips bad rows, `add_data_versioning` writes a new version on update, `add_event_sourcing` appends in order, `add_file_upload` persists and retrieves, `add_search` returns ranked results, `add_soft_delete` excludes deleted rows from list AND `CRUDBase.delete` sets `deleted_at` instead of issuing SQL DELETE) and one negative (boundary or off-path) assertion. Same skeleton as F1 golden.
- **Honesty rule:** if the tool's behavior is advisory (e.g. `add_audit_log` without a downstream sink), the emitted test asserts the advisory signal — never a fictitious enforcement.

Failure to emit a test, OR an emitted test that asserts a guarantee the tool does not deliver, = WP rejected. Non-negotiable per P1 #15.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7. These are the 5 mandatory WAVE 1 gates established by WP-01 §6.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/extend/crud_data/add_{audit_log,bulk_operations,data_export,data_import,data_versioning,event_sourcing,file_upload,search,soft_delete}
$PY -m ruff format --check adapt/extend/crud_data/add_{audit_log,bulk_operations,data_export,data_import,data_versioning,event_sourcing,file_upload,search,soft_delete}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/extend/crud_data/test_add_{audit_log,bulk_operations,data_export,data_import,data_versioning,event_sourcing,file_upload,search,soft_delete}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'add_audit_log|add_bulk_operations|add_data_export|add_data_import|add_data_versioning|add_event_sourcing|add_file_upload|add_search|add_soft_delete'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (40/40)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7. Additionally, the §11 P1 #14 verification diff MUST show `app/soft_delete.py` absent from the post-migration compose and `app/crud/base.py` `CRUDBase.delete` patched.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-07 owns (write surface):** the 9 directories under `adapt/extend/crud_data/add_<tool>/` listed in §1, plus the 9 legacy flat `.py` file deletions listed in §1.

**WP-07 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-01 Resiliency | the 9 tools in `docs/wp/WP-01-resiliency-defense.md` §1 |
| WP-02 Observability | the 9 tools in `docs/wp/WP-02-observability-diagnostics.md` §1 |
| WP-03 Security | the 9 tools in `docs/wp/WP-03-security-compliance.md` §1 |
| WP-04/05/06 Z2 | all 26 remaining `adapt/extend/infrastructure/add_*` tools |
| WP-08 Auth identity | `add_api_key_auth`, `add_dpop_tokens`, `add_mfa`, `add_oauth2_provider`, `add_passkey_auth`, `add_request_signing`, `add_sms_otp`, `add_social_login` |
| WP-09 Auth policy | `add_bola_guard`, `add_cedar_policies`, `add_feature_flags`, `add_feature_toggles_api`, `add_multi_tenancy`, `add_opa_integration`, `add_rbac` |
| WP-D/E/F | `adapt/extend/realtime/`, `adapt/extend/testing_tools/`, `adapt/extend/api_design/`, evolve/verify/hex/engine-split tools |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Shared | `adapt/extend/crud_data/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI, `hugr_auth/` |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation; LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'` (each emitted block opens+closes; divide by 2 for approximate block count); `glue` = `grep -c '_GLUE\|_TEMPLATE\|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `add_audit_log` | 215 | ≤ 160 (-26%) | 0 | 10 | 2 | 1.5 h | `opus` |
| `add_bulk_operations` | 1131 | ≤ 290 (-74%) | 7 | 36 | 0 | 5.0 h | `opus` |
| `add_data_export` | 1204 | ≤ 290 (-76%) | 8 | 41 | 0 | 5.0 h | `opus` |
| `add_data_import` | 1053 | ≤ 290 (-72%) | 9 | 46 | 0 | 5.0 h | `opus` |
| `add_data_versioning` | 1163 | ≤ 290 (-75%) | 8 | 42 | 0 | 5.0 h | `opus` |
| `add_event_sourcing` | 150 | ≤ 130 (-13%) | 0 | 6 | 2 | 1.0 h | `opus` |
| `add_file_upload` | 1870 | ≤ 290 (-84%) | 12 | 62 | 0 | 6.0 h | `opus` |
| `add_search` | 968 | ≤ 290 (-70%) | 4 | 28 | 0 | 4.0 h | `opus` |
| `add_soft_delete` | 640 | ≤ 280 (-56%) | 2 | 28 | 2 | 4.5 h (+P1 #14 patch) | `opus` |
| **TOTAL** | **8394** | **~2310 (-72%)** | **50** | **299** | **6** | **~37 h** | `opus` |

**Model recommendation: `opus`.** Three forces drive elevation. (1) Data-integrity blast radius: a silent drift in `add_bulk_operations` transaction boundaries or `add_event_sourcing` append order corrupts data in ways tests do not surface in the kit but do surface in production. (2) P1 #14 requires architectural judgement — replacing per-model shadow patching with a single CRUDBase patch AND deleting the orphan `app/soft_delete.py` emission is non-mechanical. (3) P1 #15 emitted-test honesty (no fictitious assertions, no trivially-true tests) needs `opus`-level reading of every emitted template against the asserted behavior.

## 9. Failure modes (≥6 anticipated traps)

1. **F-01. Embedded f-string interpolation lost in template move.**
   - *Symptom:* emitted code refers to `${project_name}` literally; `pytest tests/` in emitted project fails at import.
   - *Cause:* triple-quoted block used Python f-strings; renderer uses a different placeholder syntax.
   - *STOP-and-report rule:* before extraction, dump source's interpolation style; mismatch with F1 golden = stop and report.

2. **F-02. `MCP_TOOL` metadata lost in module split.**
   - *Symptom:* `engine.audit.contract_check` drops from 40/40 → 36/37.
   - *Cause:* `MCP_TOOL = {...}` not copied into the new `__init__.py`.
   - *STOP-and-report rule:* per-tool sanity import check (`python -c "from adapt.extend.crud_data import add_<tool>; assert add_<tool>.MCP_TOOL"`); fail = stop and report.

3. **F-03. Idempotency regression — second run rewrites files.**
   - *Symptom:* second-run case in `test_add_<tool>.py` fails; `ToolResult.status` returns `success` instead of `no_op`.
   - *Cause:* `discover()` skip-set lost when routing through `adapt/_base/discover.py`. crud_data tools historically skip `audit_log`, `event_sourcing`, `version`, `tenant`, `mixins`, `outbox`.
   - *STOP-and-report rule:* missing skip-set entry = stop and report; do NOT re-inline discovery.

4. **F-04. Soft-delete CRUDBase patch (P1 #14) breaks per-model overrides.**
   - *Symptom:* after migration, a model that legitimately needs hard delete (e.g. ephemeral session, password reset token) now soft-deletes and leaks PII / blocks token rotation.
   - *Cause:* the CRUDBase-level patch is too aggressive; per-model opt-out (`__soft_delete__ = False` or equivalent) was not preserved.
   - *STOP-and-report rule:* the migrated `add_soft_delete` MUST honor a per-model opt-out marker AND must emit a test asserting that opt-out hard-deletes. If the opt-out hook is missing from `CRUDBase`, **stop and report** — joint amendment with the generator owner.

5. **F-05. Orphan `app/soft_delete.py` UoW removal (P1 #14) breaks an unanticipated import.**
   - *Symptom:* boot smoke fails on emitted project because `from app.soft_delete import get_uow` is referenced by another tool's emitted code.
   - *Cause:* the `_soft_delete_flush` UoW is dead in the kit's hand-tested universe but some sibling tool may import it.
   - *STOP-and-report rule:* before deleting the emission, `grep -rn 'from app.soft_delete\|import soft_delete' skills/SKILL-001-fastapi-production/adapt/extend/` across the entire kit. Any reference = stop and report.

6. **F-06. Emitted-test missing or trivially-true (per P1 #15).**
   - *Symptom:* `tests/test_<tool>_emitted.py` has zero `assert` or asserts only `True`. Or — worse — asserts a guarantee the tool does not deliver (e.g. `add_audit_log` asserts immutability when the tool only appends).
   - *Cause:* skeleton copied without honesty-adapted assertions.
   - *STOP-and-report rule:* every emitted test MUST cover ≥1 positive + ≥1 negative; if the behavior cannot be asserted from the emitted surface, **stop and report**.

7. **F-07. `add_file_upload` 12 `dedent` blocks form a multipart graph, not a list.**
   - *Symptom:* extracting one template breaks another (e.g. the upload handler depends on the storage backend stub which depends on the file-type validator).
   - *Cause:* 1870 LOC source assembles emitted code from interdependent fragments.
   - *STOP-and-report rule:* before extraction, draw the dependency graph of the 12 dedent blocks. If extraction requires re-inlining, **stop and report** — `_base` fragment-composition helper may be needed.

8. **F-08. `add_search` SQL builder + parameterization drift.**
   - *Symptom:* migrated emitted code uses string-concatenated SQL or breaks parameter binding; emitted-test detects an SQL-injection regression (sibling round-2 panel already flagged search autocomplete SQLi).
   - *Cause:* the emitted SQL block was re-formatted during extraction and a `?`/`$N` placeholder was lost.
   - *STOP-and-report rule:* raw-string preservation mandatory; emitted test MUST include an SQL-injection negative assertion; failure = **stop and report**.

9. **F-09. Hard-cap LOC breach (`__init__.py` > 500).**
   - *Symptom:* size invariant fails for `add_file_upload` or `add_data_*` (the four heaviest tools).
   - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
   - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC without inlining `_base/`, **stop and report**.

10. **F-10. `add_event_sourcing` append-order semantics lost.**
    - *Symptom:* events arrive but out-of-order under concurrency; downstream projectors yield wrong state.
    - *Cause:* the append loop's `INSERT ... RETURNING` clause or the row-level lock was lost during template extraction.
    - *STOP-and-report rule:* the emitted test MUST assert order under 2 concurrent writers; failure = stop and report.

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** All 9 tool directories created under `adapt/extend/crud_data/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 9 legacy flat `.py` files removed (`git diff --name-only` shows 9 deletions).
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c` → 0 for all 9).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not).
- [ ] **D-06.** All 9 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive + ≥1 negative assertion. Honesty-adapted per F-06.
- [ ] **D-07.** §6 gate 1 (ruff) green for all 9 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 9 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke) returns a PASS line per tool name.
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 40/40.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface.
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`).
- [ ] **D-14.** **P1 #14 verified.** `add_soft_delete` patches `app/crud/base.py` `CRUDBase.delete`, emits NO `app/soft_delete.py`, and emitted test asserts `CRUDBase.delete` sets `deleted_at` instead of issuing SQL DELETE. Diff pasted in PR.
- [ ] **D-15.** **P1 #15 verified.** All 9 emitted tests pass under the emitted project's `pytest tests/`; output pasted.
- [ ] **D-16.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

## 11. Risk callout (WP-07-specific — data-integrity blast radius + folded P1 #14 + P1 #15)

**Why this section exists:** WP-07 is the highest-blast-radius data WP in WAVE 1. A silent drift in any of these 9 tools can ship as:

- An audit log that drops events under contention (compliance failure).
- A bulk operation that partially commits (data corruption).
- A data export that truncates rows under back-pressure (silent loss).
- A data import that silently skips validation failures (poisoned dataset).
- A versioning tool that loses the previous row on conflict (history loss).
- An event-sourcing append that goes out-of-order (projector divergence).
- A file upload that double-writes or never cleans up (storage leak).
- A search builder that exposes SQL injection in autocomplete (already flagged by sibling round-2 external panel — see memory `external_eval_panel_round2.md`).
- A soft-delete tool that does not actually soft-delete (the exact bug P1 #14 closes).

### P1 #14 — `add_soft_delete` MUST patch `CRUDBase`, not per-model; orphan `app/soft_delete.py` UoW MUST be deleted

**P1 #14** documents that the current `add_soft_delete` shadow-patches per-model CRUD methods AND emits an orphan `app/soft_delete.py` Unit-of-Work shim (`_soft_delete_flush` + `make_dependency`) that no caller imports. Source evidence (read-only context):

- `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_soft_delete.py` line ~`glue_file = app_dir / "soft_delete.py"` — the orphan emission point.
- The same source comment-strip notes: *"guards in soft_delete.py were therefore always-False, meaning deletes still hard-delete."*

**Mandatory fix executed inside this WP (NOT a sibling WP):**

1. The migrated `add_soft_delete/__init__.py` MUST patch the emitted `app/crud/base.py` so `CRUDBase.delete` sets `deleted_at = now()` by default. Per-model opt-out (e.g. `__soft_delete__ = False`) is honored, with a no-op `# hard delete by design` comment emitted in opted-out models.
2. The migrated tool MUST STOP emitting `app/soft_delete.py`. Search the entire kit (`grep -rn 'from app.soft_delete\|import soft_delete'`) before removal; any caller = STOP and report (F-05).
3. The emitted test (`test_add_soft_delete_emitted.py`) MUST assert: (a) `CRUDBase.delete` on an opt-in model sets `deleted_at` and the row remains queryable via `get_with_deleted`; (b) list endpoints exclude soft-deleted rows by default; (c) per-model opt-out hard-deletes — i.e. row count drops by 1 after delete.
4. The verification diff in §7 MUST show `app/soft_delete.py` absent from a clean compose post-migration AND `app/crud/base.py` `CRUDBase.delete` patched.

**Why fold P1 #14 into WP-07 (not a standalone fix PR):** the per-model shadow patch lives entirely inside `add_soft_delete`'s emitted templates. Extracting them in WP-07 without fixing the architecture re-paints the bug into the new layout. Fixing once, here, is one unit of work; splitting would force two passes over the same templates. T-03 below documents this trade-off.

### P1 #15 — every tool MUST emit a behavior test

**P1 #15** documents that compose tools MUST emit a per-tool behavior test in the generated project, matching the golden `add_cursor_pagination` skeleton. WP-07 is the canonical propagation point for the **entire WAVE 1 P1 #15 rollout**: the 9 tools here, the 8 tools in WP-08, the 7 tools in WP-09, and the downstream sibling WPs (WP-D, WP-E) all cite this WP as the precedent.

**Mandatory fix executed inside this WP (per §5):**

1. Every one of the 9 migrated tools renders an emitted test template at `templates/test_<tool>_emitted.py.tmpl`.
2. Each emitted test covers ≥1 positive + ≥1 negative assertion against the actual emitted behavior — NEVER a fictitious enforcement (honesty rule).
3. Each emitted test is green under the emitted project's `pytest tests/` (verified by §6 gate 2 propagation into the emitted project's run).
4. `add_search` MUST additionally include an SQL-injection negative assertion (the autocomplete SQLi confirmed by the round-2 external panel; F-08).

**Why fold P1 #15 into WP-07 (not a standalone fix PR):** the emitted-test template is itself a template, and adding one to every tool *while* migrating that tool's other templates is a single coherent pass. Adding emitted tests as a separate WP would require re-opening every per-tool directory after WP-07 lands; the cost is paid twice. T-03 below documents this trade-off.

### Trade-offs declared

- **T-01.** Theme partition (crud_data) over alphabetical — keeps the data-integrity mental model intact across the 9 tools.
- **T-02.** All `opus`, not `sonnet` — data integrity is one of two highest-blast-radius domains in WAVE 1 (the other is authz, WP-08/09 also `opus`).
- **T-03.** P1 #14 + #15 folded into WP-07 §11 + §5 instead of standalone PRs — keeps the blast radius scoped to the WAVE 1 unit of change.
- **T-04.** `add_cursor_pagination` deliberately excluded from this WP — it is the F1 golden (already migrated via PR #28). Re-migrating it would be churn against the canonical reference.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
