# Work Package Contract — `WP-13-evolve`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-13-specific content fills each section.
> Theme: **schema/code evolution** — data migrations, service extraction,
> SDK/admin/docs generation. 8 cohesive tools from `adapt/evolve/`.
>
> **Model elevation:** WP-13 runs on `opus`, not `sonnet`, because evolve tools
> drive irreversible state changes on the user's project (alembic migrations,
> service extraction with file moves, generated SDK/admin scaffolds that overwrite
> downstream artefacts). The byte-equivalence diff gate (§11) is mandatory per
> tool — a silent drift in a migration template can corrupt a real database.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-13-evolve` |
| **Title** | Migrate 8 evolve tools (migrations + service extraction + generation) to per-tool directory + externalized templates |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (PR #24, merged) · `WP-F1-base-and-golden` (PR #28, merged — `adapt/_base/` + golden `add_cursor_pagination/`) |
| **Blocks** | none (sibling WAVE-1 WPs are file-disjoint) |
| **Branch** | `wp/13-evolve` (off the post-dependency main, i.e. main with WP-F0 + WP-F1 merged) |
| **Isolation** | dedicated git worktree |
| **Model** | `opus` — irreversible-state blast radius (migrations + extraction + generated artefacts); byte-equivalence diff gate (§11) applies; honesty rules on `warnings` (no-rollback claims, SDK-as-source-of-truth claims) require opus reasoning |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/evolve/add_event_driven/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/evolve/add_i18n/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/evolve/add_migration_data/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/evolve/extract_service/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/evolve/generate_admin_panel/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/evolve/generate_docs/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/evolve/generate_sdk/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/evolve/refactor_model/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/evolve/add_event_driven.py       [DELETE]
  skills/SKILL-001-fastapi-production/adapt/evolve/add_i18n.py               [DELETE]
  skills/SKILL-001-fastapi-production/adapt/evolve/add_migration_data.py     [DELETE]
  skills/SKILL-001-fastapi-production/adapt/evolve/extract_service.py        [DELETE]
  skills/SKILL-001-fastapi-production/adapt/evolve/generate_admin_panel.py   [DELETE]
  skills/SKILL-001-fastapi-production/adapt/evolve/generate_docs.py          [DELETE]
  skills/SKILL-001-fastapi-production/adapt/evolve/generate_sdk.py           [DELETE]
  skills/SKILL-001-fastapi-production/adapt/evolve/refactor_model.py         [DELETE]
  ```
- **Golden reference (read-only, copy the pattern):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` (post WP-F1, PR #28) — this is the sole golden across WAVE 1; WP-13's evolve tools adapt the same orchestration shape (`discover → plan → write → patch → verify`) even though several emit alembic migrations or scaffolds rather than per-route patches.
- **Shared base/contract to import (read-only):** `skills/SKILL-001-fastapi-production/adapt/_base/` + `skills/SKILL-001-fastapi-production/adapt/contracts/`
- **Spec to follow:** `docs/tool-contract.md`, `docs/architecture.md`, `docs/adr/0001-architecture.md`
- **Staging pool (read-only reference, not a write surface):** `core/venous/_staging/` (renamed via WP-F0; see PR #24)

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-14 (Verify) tools** — the 6 tools listed in §1 of `docs/wp/WP-14-verify.md`. Read that manifest for the canonical list.
- **WP-15 (Hexagon Ports)** — `core/venous/_ports/` (proposed) + any audit/catalog of the 124 registered primitives is owned by WP-15. WP-13 reads `core/venous/<ns>/<Name>/<Name>.protocol.py` for context only.
- **Sibling WAVE-1 batches** — WP-Z2 (infra 04-06), WP-C (crud+auth 07-09), WP-D (rt/test/api 10-12), WP-F (engine-split 16-17). Read each sibling's §1 for canonical ownership.
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here. WP-13's tools wire into `core/venous/data/` (alembic helpers), `core/venous/api/` (CommandBus/QueryBus for event-driven) and `core/venous/events/` — read but never write.
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope.
- `adapt/evolve/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report** (registry update is a separate WP).
- `hugr_auth/` — license/auth gate is a separate service; touching it is an instant reject.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 8 evolve tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl`, route their `discover/patch` through `adapt/_base/`, AND pass the §11 byte-equivalence diff gate per tool.
- **Before:** Each tool is a single `<tool>.py` carrying embedded code-as-strings (alembic migration skeletons, FastAPI route additions, jinja-rendered SDK clients, admin scaffolds, OpenAPI exporters). Per-tool LOC measurements (raw, end of §8) range 360–925.
- **After:**
  - Each tool becomes `<tool>/__init__.py` + `templates/*.py.tmpl`.
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*.py.tmpl`. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.evolve.<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.
  - **Honesty-rule audit per tool:** any `warnings` string MUST honestly describe what the migrated code enforces. Specific overclaim risks for this batch:
    - `add_migration_data` — must NOT claim "reversible" if `downgrade()` is a no-op.
    - `extract_service` — must NOT claim "tests preserved" if it only copies files without re-running the suite.
    - `generate_sdk` — must NOT claim "source of truth" if the SDK is regenerated from a stale `openapi.json`.
    - `generate_admin_panel` — must NOT claim "RBAC enforced" if the scaffold ships an open admin.
    - `generate_docs` — must NOT claim "complete coverage" when only annotated routes are documented.
  - **§11 byte-equivalence diff gate** must pass for each tool.

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `add_event_driven` | `add_event_driven/{__init__.py, templates/}` | ≤ 290 | ≥ 7 (11 `dedent`, 54 triple-quote anchors) | `test_add_event_driven_emitted.py` |
| `add_i18n` | `add_i18n/{__init__.py, templates/}` | ≤ 290 | ≥ 7 (11 `dedent`, 52 triple-quote anchors) | `test_add_i18n_emitted.py` |
| `add_migration_data` | `add_migration_data/{__init__.py, templates/}` | ≤ 280 | ≥ 5 (7 `dedent`, 34 triple-quote anchors) | `test_add_migration_data_emitted.py` |
| `extract_service` | `extract_service/{__init__.py, templates/}` | ≤ 200 | ≥ 4 (6 `dedent`, 25 triple-quote anchors) | `test_extract_service_emitted.py` |
| `generate_admin_panel` | `generate_admin_panel/{__init__.py, templates/}` | ≤ 280 | ≥ 5 (7 `dedent`, 39 triple-quote anchors) | `test_generate_admin_panel_emitted.py` |
| `generate_docs` | `generate_docs/{__init__.py, templates/}` | ≤ 250 | ≥ 8 (13 `dedent`, 54 triple-quote anchors) | `test_generate_docs_emitted.py` |
| `generate_sdk` | `generate_sdk/{__init__.py, templates/}` | ≤ 230 | ≥ 4 (4 `dedent`, 30 triple-quote anchors) | `test_generate_sdk_emitted.py` |
| `refactor_model` | `refactor_model/{__init__.py, templates/}` | ≤ 200 | ≥ 3 (2 `dedent`, 18 triple-quote anchors) | `test_refactor_model_emitted.py` |

- **Out of scope:** behavior changes, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope. **Specifically:** the agent MUST NOT "fix" a missing `downgrade()` in `add_migration_data`, MUST NOT add RBAC to `generate_admin_panel`, MUST NOT widen coverage in `generate_docs`. Those are separate WPs in subsequent waves. The honesty-rule audit (§4) handles overclaims by adjusting `warnings` text only — never by changing behavior.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Same `ToolInput` → same `ToolResult` shape; same files emitted, byte-equivalent per §11 diff gate. Proven by GATE 1 + §11 diff.
- [ ] **Import paths stable.** `from adapt.evolve.<tool> import <tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep -E 'textwrap\.dedent|^\s*"""' <tool>/__init__.py | wc -l` returning 0 for emitted-code blocks (module/function docstrings are fine).
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused module-level constants left dangling after extraction.
- [ ] **Docstrings honest.** A tool that does not enforce something MUST say so in `warnings`. See §3 honesty-rule list (5 tools have known overclaim risk). No "guarantee", "complete", "atomic", "reversible" wording unless the emitted code actually delivers it.
- [ ] **No new dependencies.** No `pyproject.toml` change; no new top-level imports beyond what `adapt/_base/` already provides. Emitted deps (alembic, babel, openapi-python-client) go in the generated project's `requirements.txt`, not here.
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool.
- [ ] **§11 byte-equivalence diff gate passes per tool.**
- [ ] **Migration reversibility honesty.** `add_migration_data` MUST NOT emit alembic stubs whose `downgrade()` claims to reverse data backfill it cannot reverse — if the source did, the migrated `warnings` MUST flag it (text-level fix only; behavior unchanged).

## 5. Test emission (per P1 #15)
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy that format verbatim** (location: `{project}/tests/test_<tool>_emitted.py`).

For each of the 8 tools in §1, the migrated `__init__.py` MUST:
- Render an emitted test from `templates/test_<tool>_emitted.py.tmpl`.
- Place it at `{project_dir}/tests/test_<tool>_emitted.py`.
- Make it green under the emitted project's `pytest tests/` after compose.
- Cover at least one positive (added behavior fires) and one negative (boundary or off-path) assertion. Same skeleton as F1 golden.

Per-tool emitted-test asserts (positive case examples — adapt to the tool's actual emitted surface, never assert a guarantee the tool does not deliver):
- `add_event_driven` — publishing a domain event reaches a subscribed handler; an unsubscribed event type does not.
- `add_i18n` — a translated message resolves for a registered locale; an unknown locale falls back to default without raising.
- `add_migration_data` — `alembic upgrade head` applies cleanly on a fresh DB; second run is a no-op (NOT `downgrade()` reversibility unless the tool actually delivers it — see §4 honesty rule).
- `extract_service` — extracted service module imports and exposes its entrypoint; original call sites still resolve via the extracted re-export.
- `generate_admin_panel` — admin route returns 200 for an authenticated user; returns 401/403 for an unauthenticated request (NOT a claim of RBAC enforcement unless emitted code delivers it).
- `generate_docs` — generated `docs/` directory is non-empty and one route's docstring is rendered; an unannotated route is recorded as a coverage gap, NOT silently "documented".
- `generate_sdk` — generated SDK client imports; one method round-trips against a fake server (NOT a freshness guarantee — see §4).
- `refactor_model` — renamed field is referenced consistently in routes/schemas; old name returns the documented deprecation behaviour (warning header or 410, whichever the tool emits).

Failure to emit a test, OR an emitted test that asserts a guarantee the tool does not deliver, = WP rejected. Non-negotiable per P1 #15 + honesty rules. Note this is a stricter bar than WP-01 because evolve tools change irreversible state — a fictitious assertion can mask a corruption-class bug.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/evolve/{add_event_driven,add_i18n,add_migration_data,extract_service,generate_admin_panel,generate_docs,generate_sdk,refactor_model}
$PY -m ruff format --check adapt/evolve/{add_event_driven,add_i18n,add_migration_data,extract_service,generate_admin_panel,generate_docs,generate_sdk,refactor_model}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/evolve/test_{add_event_driven,add_i18n,add_migration_data,extract_service,generate_admin_panel,generate_docs,generate_sdk,refactor_model}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'add_event_driven|add_i18n|add_migration_data|extract_service|generate_admin_panel|generate_docs|generate_sdk|refactor_model'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (37/37)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7. Additionally, §11 byte-equivalence diff must be PASS per tool.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-13 owns (write surface):** the 8 directories under `adapt/evolve/<tool>/` listed in §1, plus the 8 legacy flat `.py` file deletions listed in §1.

**WP-13 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-14 Verify | the 6 tools listed in §1 of `docs/wp/WP-14-verify.md` |
| WP-15 Hexagon Ports | `core/venous/_ports/` (proposed), the 124 registered primitives' protocol stubs (read-only here), the port-catalog audit |
| WP-Z2 (04-06) | all infrastructure tools in `adapt/extend/infrastructure/` outside WP-01/02/03 |
| WP-C (07-09) | crud + auth-access tools owned by `wp/crud-auth` |
| WP-D (10-12) | realtime + testing-tools + api-design tools owned by `wp/rt-test-api` |
| WP-F (16-17) | engine-split tools owned by `wp/engine-split` |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Shared | `adapt/evolve/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI, `hugr_auth/` |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation (HEAD `bd634a5`); LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'` (each emitted block opens+closes, so divide by 2 for approximate block count); `glue` = `grep -c '_GLUE\|_TEMPLATE\|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `add_event_driven` | 925 | ≤ 290 (-69%) | 11 | 54 | 0 | 4.5 h | `opus` |
| `add_i18n` | 902 | ≤ 290 (-68%) | 11 | 52 | 0 | 4.0 h | `opus` |
| `add_migration_data` | 727 | ≤ 280 (-62%) | 7 | 34 | 0 | 4.0 h | `opus` |
| `extract_service` | 402 | ≤ 200 (-50%) | 6 | 25 | 0 | 2.5 h | `opus` |
| `generate_admin_panel` | 745 | ≤ 280 (-62%) | 7 | 39 | 0 | 3.5 h | `opus` |
| `generate_docs` | 620 | ≤ 250 (-60%) | 13 | 54 | 0 | 3.0 h | `opus` |
| `generate_sdk` | 470 | ≤ 230 (-51%) | 4 | 30 | 0 | 2.5 h | `opus` |
| `refactor_model` | 360 | ≤ 200 (-44%) | 2 | 18 | 0 | 2.0 h | `opus` |
| **TOTAL** | **5151** | **~2020 (-61%)** | **61** | **306** | **0** | **~26 h** | `opus` |

**Model recommendation: `opus`.** Evolve tools sit on top of state-changing operations: alembic migrations against a live database, service extraction that moves files and rewires imports, SDK/admin generation that overwrites downstream artefacts. The risk profile differs from WP-01/02 (mechanical refactor of resilience/observability middleware): a silent byte-level drift in a migration template can corrupt a real database. `opus` reasoning is required for the per-tool diff review (§11) and for the honesty-rule audit covering reversibility, freshness, and coverage claims (§4).

## 9. Failure modes (≥6 anticipated traps)

1. **F-01. Embedded f-string interpolation lost in template move.**
   - *Symptom:* emitted code refers to `${project_name}` literally instead of substituted value; `pytest tests/` in emitted project fails at import.
   - *Cause:* triple-quoted block in source used Python f-string interpolation (`f"""…{var}…"""`); `adapt/_base/render.py` uses `string.Template` (`$name` / `${name}`) — see render.py docstring.
   - *STOP-and-report rule:* before any extraction, dump the source's interpolation style for the tool. `_base.render` is strict-substitute (`.substitute`, not `.safe_substitute`) — a missing key raises `KeyError`. If a triple-quoted block uses any mechanism other than literal `$name`, **stop and report**.

2. **F-02. `MCP_TOOL` metadata lost in module split.**
   - *Symptom:* `engine.audit.contract_check` drops from 37/37 → 36/37 for the migrated tool.
   - *Cause:* `MCP_TOOL = {...}` constant lived at module top in the flat `.py` and was not copied into the new `__init__.py`.
   - *STOP-and-report rule:* after every per-tool migration, run `python -c "from adapt.evolve import <tool>; assert <tool>.MCP_TOOL"` — fail = stop and report.

3. **F-03. Idempotency regression — second run rewrites files / re-runs migrations.**
   - *Symptom:* `pytest` for `test_<tool>.py` fails on the second-run idempotency case; `ToolResult.status` returns `success` instead of `no_op`. For `add_migration_data`, second run produces a duplicate alembic revision file.
   - *Cause:* `discover()` skip-set lost when routing through `adapt/_base/discover.py`; or `add_migration_data` re-stamps the revision DAG instead of detecting an existing head.
   - *STOP-and-report rule:* if `adapt/_base/discover.py` does not expose the tool's required skip-set, **stop and report** — do NOT re-inline discovery. For migration heads, use `adapt.contracts.migration_helper.find_migration_head` (already imported by golden `add_cursor_pagination/__init__.py`); a missing head = stop and report.

4. **F-04. Honesty-rule violation — overclaiming irreversible state guarantees.**
   - *Symptom:* migrated `warnings` claim "downgrade reverses backfill" or "SDK regenerated from live API" when emitted code does neither.
   - *Cause:* author copy-pasted optimistic `warnings` from source without re-reading the emitted templates. The 5 tools with known overclaim risk are listed in §3.
   - *STOP-and-report rule:* per tool, read every emitted template, then read the `warnings`. Any unenforced claim = **stop and report, do NOT ship**. Fix the `warnings` to honest in this WP (behavior change is out of scope per §3).

5. **F-05. Migration template raw-string preservation broken.**
   - *Symptom:* `add_migration_data` emits a migration whose `op.execute("…")` SQL is mangled — single-quote escaping or `\n` literals leaking into the SQL.
   - *Cause:* triple-quoted SQL bodies include escape sequences that `string.Template` re-escapes when the body is fed through `.substitute`.
   - *STOP-and-report rule:* raw-string preservation is mandatory for emitted SQL. The template must keep `r"…"` semantics. If `_base/render.py` cannot pass raw strings unchanged, **stop and report** — joint amendment with WP-F1.

6. **F-06. Emitted-test missing or trivially-true (per P1 #15).**
   - *Symptom:* emitted test asserts only `True`, OR asserts a fictitious guarantee (e.g. asserts `add_migration_data` `downgrade()` reverses data when the emitted migration's downgrade is a no-op).
   - *Cause:* skeleton copied without honesty-adapted assertions.
   - *STOP-and-report rule:* every emitted test MUST cover ≥1 positive (added behavior fires per actual emitted code) + ≥1 negative (off-path or boundary). Mismatch with emitted behavior = stop and report. See §5 per-tool examples.

7. **F-07. `extract_service` orphaned re-export.**
   - *Symptom:* after extraction, the original module path still resolves but exposes a stub that raises `ImportError` at call time, breaking downstream callers.
   - *Cause:* the flat `.py` left a one-line `from .extracted import *` at the original path; the migrated tool drops it during template move.
   - *STOP-and-report rule:* if extraction leaves *any* import-time stub at the original path, that stub MUST resolve identically before/after the migration. Re-export drift = stop and report.

8. **F-08. `generate_sdk` / `generate_docs` openapi.json staleness.**
   - *Symptom:* emitted SDK/docs reflects a stale schema (the snapshot committed to the repo) even though the running app's `app.openapi()` has drifted.
   - *Cause:* the flat `.py` had logic that preferred the live `app.openapi()` over the snapshot in some code paths; template extraction loses the live-vs-snapshot branch.
   - *STOP-and-report rule:* the live-vs-snapshot decision MUST be preserved byte-equivalently per §11. Drift = stop and report; the §11 diff gate catches this.

9. **F-09. `add_event_driven` CommandBus/QueryBus import surface drift.**
   - *Symptom:* emitted event-driven code imports from a `core.venous.events.*` path that no longer exists or no longer carries the same surface.
   - *Cause:* the tool wires into 124 registered primitives via `core/venous/<ns>/<Name>/<Name>.protocol.py` and WP-15 is concurrently formalizing those ports — if WP-15 lands first with a rename, WP-13's emitted code breaks.
   - *STOP-and-report rule:* WP-13 is OFF WP-F0+WP-F1 main, NOT off WP-15. If `from core.venous.api.CommandBus` does not resolve at the WP-13 branch point, **stop and report** — WP-15 has prematurely landed without a compat shim.

10. **F-10. Hard-cap LOC breach (`__init__.py` > 500).**
    - *Symptom:* size invariant fails for the two heaviest tools (`add_event_driven` 925 LOC and `add_i18n` 902 LOC source).
    - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
    - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC of logic without inlining `_base/`, **stop and report** — a `_base` extension may be needed (joint amendment with WP-F1).

11. **F-11. §11 byte-equivalence diff gate fails for non-cosmetic reason.**
    - *Symptom:* diff shows a logic change (re-ordered alembic operations, dropped admin route, altered SDK method signature), not whitespace/comment drift.
    - *Cause:* extraction lost or re-ordered emitted content.
    - *STOP-and-report rule:* never normalize the diff away. **Stop and report** with the diff verbatim.

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** All 8 tool directories created under `adapt/evolve/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 8 legacy flat `.py` files removed (`git diff --name-only` shows 8 deletions).
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c 'textwrap.dedent' <tool>/__init__.py` → 0 for all 8).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not).
- [ ] **D-06.** All 8 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive + ≥1 negative assertion. Honesty-adapted per F-06 + §5 examples.
- [ ] **D-07.** §6 gate 1 (ruff) green for all 8 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 8 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke `tests/test_boot.py | grep`) returns a PASS line per tool name.
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 37/37.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface (no forbidden surface touched).
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`); for `add_migration_data` second run does NOT produce a duplicate alembic revision file.
- [ ] **D-14.** §11 byte-equivalence diff gate PASS for all 8 tools, diff output pasted in PR.
- [ ] **D-15.** Honesty-rule audit per tool: every `warnings` string re-read against actually emitted templates; the 5 tools with known overclaim risk (§3) explicitly re-verified; overclaims fixed to honest text.
- [ ] **D-16.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

## 11. Risk callout (WP-13-specific — irreversible-state blast radius)

**Why this section exists:** WP-01 and WP-02 are mechanical refactors against a well-understood pattern. WP-13 sits on top of code that drives irreversible state changes on the user's project. A subtle drift in any of these 8 tools can ship as:

- A migration whose `downgrade()` quietly stops reversing the backfill it claims to reverse — and the user only notices when a rollback corrupts production data.
- A `generate_sdk` rerun that overwrites a hand-edited client method with a stale-snapshot stub — silently breaking callers.
- A `generate_admin_panel` scaffold whose login route is reachable without auth in dev mode and the dev-mode check ships to prod.
- An `extract_service` that leaves a re-export stub which `import`s cleanly but raises at call time — passing module-level smoke tests, failing under real traffic.
- A `refactor_model` rename whose alembic op renames the column but leaves a route handler referencing the old name — 500s on every request to that route.
- An `add_event_driven` wiring that subscribes a handler at import time and silently fires on every boot (state leak across tests).
- An `add_i18n` middleware whose locale negotiation falls back to a hard-coded default instead of `Accept-Language`, silently mistranslating responses.
- An `add_migration_data` template whose SQL escape handling mangles a single-quote inside an `op.execute("INSERT … 'value'")` — succeeds in dev (no special chars), fails in prod.

**Mitigation: per-tool byte-equivalence diff gate.** Before declaring any tool migrated, the agent MUST:

```bash
# For each of the 8 tools:
# 1. Compose the tool against a fixed test project on main (pre-migration) → capture emitted files.
PY=.venv/bin/python
git checkout main -- skills/SKILL-001-fastapi-production/adapt/evolve/<tool>.py
$PY -m engine.compose --tool <tool> --project /tmp/pre/<tool>
# 2. Compose the migrated tool against the same fixed test project.
git checkout HEAD -- skills/SKILL-001-fastapi-production/adapt/evolve/<tool>
$PY -m engine.compose --tool <tool> --project /tmp/post/<tool>
# 3. Diff. Allowed drift: comment/whitespace only. Anything else = STOP and report.
diff -ruN /tmp/pre/<tool> /tmp/post/<tool> | grep -vE '^[+-]\s*(#|$)' | tee /tmp/diff_<tool>.txt
test ! -s /tmp/diff_<tool>.txt   # PASS = empty after comment/whitespace strip
```

Paste each tool's diff-gate result in §7. If the diff-gate is non-empty for non-cosmetic reasons, **stop and report — do NOT ship**.

**Migration-specific extra gate (only `add_migration_data`).** After §11 byte-equivalence passes, also verify the emitted alembic revision applies and reverts cleanly on an in-memory SQLite:

```bash
$PY -m engine.compose --tool add_migration_data --project /tmp/post/add_migration_data
cd /tmp/post/add_migration_data && PYTHONPATH=. .venv/bin/python -m alembic upgrade head
# Confirm downgrade() honesty: either reverses backfill OR `warnings` flags it as advisory-only.
.venv/bin/python -m alembic downgrade -1
```

If `downgrade()` raises or silently no-ops while `warnings` claims reversibility, **stop and report** — fix `warnings` text to honest (behavior change is out of scope per §3).

**Model elevation rationale:** `opus` reasoning is required to read the diff and judge "cosmetic" vs "behavioral" drift, especially for the migration-heavy tools (`add_migration_data` SQL escape handling, `add_event_driven` event-bus wiring, `extract_service` import-graph fidelity) and the generation tools whose output is consumed by humans (`generate_sdk`, `generate_admin_panel`, `generate_docs`). Running this gate on `sonnet` risks false-negative diff judgements on the irreversible-state side. P1 backlog item #15 mandates emitted-test honesty; the honesty audit on `warnings` + emitted-test assertions is the only line of defence against a corruption-class regression shipping silently.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
