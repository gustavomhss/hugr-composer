# Work Package Contract — `WP-04-async-workflow`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-04-specific content fills each section.
> Theme: **background work, scheduled jobs, sagas, tenant lifecycle, billing
> meters** — 9 cohesive tools from `adapt/extend/infrastructure/`.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-04-async-workflow` |
| **Title** | Migrate 9 async/workflow tools to per-tool directory + externalized templates |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (PR #24, merged) · `WP-F1-base-and-golden` (in flight — `adapt/_base/` + golden `add_cursor_pagination/`) |
| **Blocks** | none (sibling WPs are file-disjoint) |
| **Branch** | `wp/04-async-workflow` (off the post-dependency main, i.e. main with WP-F0 + WP-F1 merged) |
| **Isolation** | dedicated git worktree |
| **Model** | `sonnet` — mechanical refactor with heavy template heft; pattern set by F1 golden tool |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_arq_worker/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_celery_beat/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_outbox_pattern/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_saga/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_scheduled_tasks/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_temporal_workflow/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_tenant_onboarding/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_api_monetization/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_cost_tracker/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_arq_worker.py          [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_celery_beat.py         [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_outbox_pattern.py      [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_saga.py                [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_scheduled_tasks.py     [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_temporal_workflow.py   [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_tenant_onboarding.py   [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_api_monetization.py    [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_cost_tracker.py        [DELETE]
  ```
- **Golden reference (read-only, copy the pattern):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` (post WP-F1)
- **Shared base/contract to import (read-only):** `skills/SKILL-001-fastapi-production/adapt/_base/` + `skills/SKILL-001-fastapi-production/adapt/contracts/`
- **Spec to follow:** `docs/tool-contract.md`, `docs/architecture.md`
- **Staging pool (read-only reference, not a write surface):** `core/venous/_staging/` (renamed via WP-F0; see PR #24)

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-01 (Resiliency/Defense) tools** — the 9 tools listed in §1 of `docs/wp/WP-01-resiliency-defense.md`.
- **WP-02 (Observability/Diagnostics) tools** — the 9 tools listed in §1 of `docs/wp/WP-02-observability-diagnostics.md`.
- **WP-03 (Security/Compliance) tools** — the 9 tools listed in §1 of `docs/wp/WP-03-security-compliance.md`.
- **WP-05 (Storage/Deployment) tools** — the 9 tools listed in §1 of `docs/wp/WP-05-storage-deployment.md`.
- **WP-06 (Payments/Notifications/ML) tools** — the 8 tools listed in §1 of `docs/wp/WP-06-payments-notif-ml.md`.
- **WP-07..17 (sibling Wave-1 tools)** — `crud_data`, `auth_access` (×2), `realtime`, `testing_tools`, `api_design`, `evolve`, `verify`, `hexagon-ports`, `engine-split`. Out of scope.
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here. (`core/venous/jobs/`, `core/venous/events/`, `core/venous/billing/` host the registered primitives some of these tools wire into — read but never write.)
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope.
- `adapt/extend/infrastructure/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report**.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 9 async/workflow tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl`, and route their `discover/patch` through `adapt/_base/`.
- **Before:** Each tool is a single `add_<tool>.py` carrying embedded code-as-strings (triple-quoted blocks + `textwrap.dedent` blobs). These tools ship workflow scaffolds, message buses, and tenant/billing wiring — `add_arq_worker.py` is the heaviest in the WAVE-1 async batch at 1483 LOC, with the multi-step `add_temporal_workflow` and `add_api_monetization` close behind. Per-tool LOC measurements (raw, end of §8) range 153–1483.
- **After:**
  - Each tool becomes `add_<tool>/__init__.py` + `templates/*.py.tmpl`.
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*.py.tmpl`. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.extend.infrastructure.add_<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `add_arq_worker` | `add_arq_worker/{__init__.py, templates/}` | ≤ 290 | ≥ 9 (9 `dedent`, 57 triple-quote anchors) | `test_add_arq_worker_emitted.py` |
| `add_celery_beat` | `add_celery_beat/{__init__.py, templates/}` | ≤ 260 | ≥ 6 (6 `dedent`, 37 triple-quote anchors) | `test_add_celery_beat_emitted.py` |
| `add_outbox_pattern` | `add_outbox_pattern/{__init__.py, templates/}` | ≤ 290 | ≥ 6 (6 `dedent` + 2 `_GLUE` consts) | `test_add_outbox_pattern_emitted.py` |
| `add_saga` | `add_saga/{__init__.py, templates/}` | ≤ 110 | ≥ 2 (2 templates, 2 `_GLUE` consts) | `test_add_saga_emitted.py` |
| `add_scheduled_tasks` | `add_scheduled_tasks/{__init__.py, templates/}` | ≤ 240 | ≥ 3 (3 `dedent`, 41 triple-quote anchors) | `test_add_scheduled_tasks_emitted.py` |
| `add_temporal_workflow` | `add_temporal_workflow/{__init__.py, templates/}` | ≤ 290 | ≥ 7 (7 `dedent`, 40 triple-quote anchors) | `test_add_temporal_workflow_emitted.py` |
| `add_tenant_onboarding` | `add_tenant_onboarding/{__init__.py, templates/}` | ≤ 280 | ≥ 4 (4 `dedent` + 2 `_GLUE` consts) | `test_add_tenant_onboarding_emitted.py` |
| `add_api_monetization` | `add_api_monetization/{__init__.py, templates/}` | ≤ 290 | ≥ 7 (7 `dedent`, 32 triple-quote anchors) | `test_add_api_monetization_emitted.py` |
| `add_cost_tracker` | `add_cost_tracker/{__init__.py, templates/}` | ≤ 120 | ≥ 2 (2 templates, 2 `_GLUE` consts) | `test_add_cost_tracker_emitted.py` |

- **Out of scope:** behavior changes, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Same `ToolInput` → same `ToolResult` shape; same files emitted (byte-equivalent after stripping comments/whitespace from emitted code). Proven by GATE 1.
- [ ] **Import paths stable.** `from adapt.extend.infrastructure.add_<tool> import add_<tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep -E 'textwrap\.dedent|^\s*"""' add_<tool>/__init__.py | wc -l` returning 0 for emitted-code blocks.
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused `_GLUE`/`_TEMPLATE` constants left dangling.
- [ ] **Docstrings honest.** Async-batch specific: a tool that does not provide an exactly-once guarantee MUST say so in `warnings` (e.g. `add_outbox_pattern` is at-least-once with consumer idempotency required; `add_saga` compensations are best-effort). A scheduled-tasks tool that emits a single-process scheduler MUST warn it is NOT clustered.
- [ ] **No new dependencies.** No `pyproject.toml` change. (arq/Celery/Temporal/APScheduler dependencies are emitted into the generated project's `requirements.txt`, not into the kit.)
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool.

## 5. Test emission (per P1 #15)
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy that format verbatim** (location: `{project}/tests/test_<tool>_emitted.py`).

For each of the 9 tools in §1, the migrated `__init__.py` MUST:
- Render an emitted test from `templates/test_<tool>_emitted.py.tmpl`.
- Place it at `{project_dir}/tests/test_<tool>_emitted.py`.
- Make it green under the emitted project's `pytest tests/` after compose.
- Cover at least one positive (added behavior fires: e.g. job enqueued and processed, scheduled task run, outbox row inserted within transaction, saga compensation triggers on failure, tenant onboarded with row in tenants table, monetization meter increments, cost tracker accumulates spend) and one negative (boundary or off-path: e.g. missing queue does not crash boot, beat schedule with empty list is a no-op, saga happy-path skips compensation, tenant onboarding rejects duplicate slug) assertion. Same skeleton as F1 golden.
- **Honesty rule:** async semantics MUST be asserted only at the level the tool actually delivers. If a tool wires an at-least-once queue, the emitted test MUST NOT assert exactly-once; it should assert idempotent consumer behavior instead. Overclaiming = F-06.

Failure to emit a test = WP rejected; this is non-negotiable per P1 #15.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/extend/infrastructure/add_{arq_worker,celery_beat,outbox_pattern,saga,scheduled_tasks,temporal_workflow,tenant_onboarding,api_monetization,cost_tracker}
$PY -m ruff format --check adapt/extend/infrastructure/add_{arq_worker,celery_beat,outbox_pattern,saga,scheduled_tasks,temporal_workflow,tenant_onboarding,api_monetization,cost_tracker}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/extend/infrastructure/test_add_{arq_worker,celery_beat,outbox_pattern,saga,scheduled_tasks,temporal_workflow,tenant_onboarding,api_monetization,cost_tracker}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'add_arq_worker|add_celery_beat|add_outbox_pattern|add_saga|add_scheduled_tasks|add_temporal_workflow|add_tenant_onboarding|add_api_monetization|add_cost_tracker'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (40/40)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-04 owns (write surface):** the 9 directories under `adapt/extend/infrastructure/add_<tool>/` listed in §1, plus the 9 legacy `.py` file deletions listed in §1.

**WP-04 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-01 Resiliency | the 9 tools listed in §1 of `docs/wp/WP-01-resiliency-defense.md` |
| WP-02 Observability | the 9 tools listed in §1 of `docs/wp/WP-02-observability-diagnostics.md` |
| WP-03 Security | the 9 tools listed in §1 of `docs/wp/WP-03-security-compliance.md` |
| WP-05 Storage/Deployment | the 9 tools listed in §1 of `docs/wp/WP-05-storage-deployment.md` |
| WP-06 Payments/Notif/ML | the 8 tools listed in §1 of `docs/wp/WP-06-payments-notif-ml.md` |
| WP-07..17 | all infrastructure/crud_data/auth_access/realtime/testing_tools/api_design/evolve/verify tools NOT named in §1 of this manifest |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Shared | `adapt/extend/infrastructure/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation; LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'`; `glue` = `grep -cE '_GLUE|_TEMPLATE|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `add_arq_worker` | 1483 | ≤ 290 (-80%) | 9 | 57 | 0 | 5.0 h | `sonnet` |
| `add_celery_beat` | 738 | ≤ 260 (-65%) | 6 | 37 | 0 | 3.0 h | `sonnet` |
| `add_outbox_pattern` | 945 | ≤ 290 (-69%) | 6 | 38 | 2 | 4.0 h | `sonnet` |
| `add_saga` | 153 | ≤ 110 (-28%) | 0 | 6 | 2 | 1.0 h | `sonnet` |
| `add_scheduled_tasks` | 590 | ≤ 240 (-59%) | 3 | 41 | 0 | 2.5 h | `sonnet` |
| `add_temporal_workflow` | 1235 | ≤ 290 (-77%) | 7 | 40 | 0 | 4.5 h | `sonnet` |
| `add_tenant_onboarding` | 723 | ≤ 280 (-61%) | 4 | 20 | 2 | 3.0 h | `sonnet` |
| `add_api_monetization` | 1086 | ≤ 290 (-73%) | 7 | 32 | 0 | 4.0 h | `sonnet` |
| `add_cost_tracker` | 178 | ≤ 120 (-33%) | 0 | 7 | 2 | 1.0 h | `sonnet` |
| **TOTAL** | **7131** | **~2170 (-70%)** | **42** | **278** | **6** | **~28 h** | `sonnet` |

**Model recommendation: `sonnet`.** This batch is mechanical (extract triple-quoted blobs → `.tmpl`, route discovery/patch through `_base`). It is the heaviest WAVE-1 batch by raw LOC because `add_arq_worker`, `add_temporal_workflow`, and `add_api_monetization` ship multi-file worker scaffolds — but the transformation pattern is identical to the F1 golden tool. Promotion to `opus` only if the agent hits a STOP-and-report rule in §9 (particularly F-07 for the multi-file worker scaffolds or F-08 for outbox/saga atomicity-claim drift).

## 9. Failure modes (≥6 anticipated traps)

1. **F-01. Embedded f-string interpolation lost in template move.**
   - *Symptom:* emitted code refers to `${project_name}` literally instead of substituted value; `pytest tests/` in emitted project fails at import.
   - *Cause:* triple-quoted block in source used Python f-string interpolation (`f"""…{var}…"""`); template renderer in `_base` uses different placeholder syntax (e.g. `{{ var }}`).
   - *STOP-and-report rule:* before any extraction, dump the source's interpolation style for the tool; if it does not match F1 golden's template syntax, **stop and report** — joint amendment with WP-F1 needed.

2. **F-02. `MCP_TOOL` metadata lost in module split.**
   - *Symptom:* `engine.audit.contract_check` drops from 40/40 → 36/37 for the migrated tool.
   - *Cause:* `MCP_TOOL = {...}` constant lived at module top in the flat `.py` and was not copied into the new `__init__.py`.
   - *STOP-and-report rule:* after every per-tool migration, run `python -c "from adapt.extend.infrastructure import add_<tool>; assert add_<tool>.MCP_TOOL"` — fail = stop and report.

3. **F-03. Idempotency regression — second run rewrites files.**
   - *Symptom:* `pytest` for `test_add_<tool>.py` fails on the second-run idempotency case; `ToolResult.status` returns `success` instead of `no_op`.
   - *Cause:* `discover()` was inlined per tool with custom skip-set; replacing with `adapt/_base/discover.py` lost a skip entry (e.g. `tenant`, `mixins`).
   - *STOP-and-report rule:* if `adapt/_base/discover.py` does not expose the tool's required skip-set, **stop and report** — do NOT re-inline discovery.

4. **F-04. Hidden behavior leak via `__init__.py` side-effects.**
   - *Symptom:* boot smoke fails — `import adapt.extend.infrastructure.add_<tool>` raises (worker imports trigger eager broker connection, eager Temporal client init, eager APScheduler start).
   - *Cause:* the flat `.py` ran top-level code (e.g. eager broker handshake, global registry mutation).
   - *STOP-and-report rule:* never paper over with try/except; **stop and report** — top-level side-effects are an upstream bug that needs explicit migration.

5. **F-05. Template syntax drift — Jinja vs str.format.**
   - *Symptom:* templates render with literal `{var}` instead of values; emitted file is syntactically valid Python but semantically broken.
   - *Cause:* author used `str.format` placeholders in a `_base` Jinja renderer (or vice-versa).
   - *STOP-and-report rule:* before migration, confirm the renderer in `adapt/_base/render.py` and use **only** that syntax. Mixed syntax = stop and report.

6. **F-06. Honesty-rule violation — overclaiming async guarantees.**
   - *Symptom:* migrated `warnings` claim "exactly-once delivery" or "guaranteed compensation" when emitted code wires at-least-once / best-effort semantics.
   - *Cause:* author copy-pasted optimistic `warnings` from source without re-reading the emitted templates.
   - *STOP-and-report rule:* per tool, read every emitted template, then read the `warnings`. Any unenforced claim = **stop and report, do NOT ship**. Fix the `warnings` to honest in this WP (behavior change is out of scope per §3).

7. **F-07. Multi-file worker scaffold split breaks under template engine.**
   - *Symptom:* `add_arq_worker` / `add_temporal_workflow` emit a `worker/` package plus a `tasks/` package; one template's filename includes a substituted token (e.g. `tasks_{module}.py.tmpl`) and the renderer cannot map template → emitted-path 1:1.
   - *Cause:* the flat `.py` looped over `for module in detected_modules: emit f"tasks/tasks_{module}.py"` with the source embedded in a single triple-quoted block.
   - *STOP-and-report rule:* if the renderer in `adapt/_base/render.py` does not support per-iteration filename substitution, **stop and report** — a `_base` multi-emit helper may be needed (joint amendment with WP-F1).

8. **F-08. Outbox/saga atomicity-claim drift.**
   - *Symptom:* emitted code inserts the outbox row OUTSIDE the unit-of-work transaction after migration, breaking the "atomic with business write" guarantee; or `add_saga` compensation hooks no longer fire on failure.
   - *Cause:* discovery moved the patch site (e.g. session-scope vs request-scope) when routed through `_base`.
   - *STOP-and-report rule:* `add_outbox_pattern` and `add_saga` are atomicity-critical; verify the emitted `INSERT INTO outbox` is INSIDE the session.commit() block in the emitted code AND the emitted test asserts atomicity. If not, **stop and report**.

9. **F-09. `_GLUE` constants pruned but still imported.**
   - *Symptom:* `ruff check` flags `F821` (undefined name) or import fails at boot.
   - *Cause:* externalization removed the constant but a sibling helper still references it.
   - *STOP-and-report rule:* run `python -m ruff check add_<tool>/` after every tool; non-empty output = stop and report (do NOT auto-fix without re-reading).

10. **F-10. Hard-cap LOC breach (`__init__.py` > 500).**
    - *Symptom:* size invariant fails for `add_arq_worker` (1483 LOC source) or `add_temporal_workflow` (1235 LOC source).
    - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
    - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC of logic without inlining `_base/`, **stop and report** — a `_base` extension may be needed (joint amendment with WP-F1).

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** All 9 tool directories created under `adapt/extend/infrastructure/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 9 legacy flat `.py` files removed (`git diff --name-only` shows 9 deletions).
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c 'textwrap.dedent' add_<tool>/__init__.py` → 0 for all 9).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not).
- [ ] **D-06.** All 9 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive + ≥1 negative assertion. Honesty-adapted per F-06.
- [ ] **D-07.** §6 gate 1 (ruff) green for all 9 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 9 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke `tests/test_boot.py | grep`) returns a PASS line per tool name.
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 40/40.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface (no forbidden surface touched).
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`).
- [ ] **D-14.** Outbox/saga atomicity: emitted-test for `add_outbox_pattern` asserts row insert is rolled back when business commit fails (F-08 cleared) OR explicit stop-and-report posted.
- [ ] **D-15.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

---

## Appendix A — Composition notes for this batch (read-only context)

The 9 tools in WP-04 form the **async backbone** of a typical emitted project:
- `add_arq_worker` / `add_celery_beat` provide the queue + scheduler runtime.
- `add_outbox_pattern` + `add_saga` provide eventually-consistent cross-aggregate workflows.
- `add_scheduled_tasks` layers cron-like jobs on top of the queue.
- `add_temporal_workflow` provides durable workflow execution as an alternative to outbox/saga for projects that adopt Temporal.
- `add_tenant_onboarding` orchestrates the multi-step lifecycle that creates a tenant row + provisioned schema + welcome email enqueue.
- `add_api_monetization` + `add_cost_tracker` meter usage and accumulate spend — they ride on top of the queue (`add_arq_worker`) to flush meter batches.

After WP-04 merges, downstream composition tests exercise these tools as a group. A regression in any one tool surfaces in the chain test, not just the per-tool test. The `__init__.py` orchestration MUST be import-cheap (no top-level broker/Temporal/APScheduler handshake) so that `tests/test_boot.py` boot-time per tool stays under its current budget.

## Appendix B — Why theme-grouping (not size-balanced batches)

WP-04 carries 9 tools that share the **async/workflow mental model**: queues, schedulers, sagas, tenant lifecycle, billing meters. An agent reading the manifest gets the same conceptual frame for every tool in the batch, which reduces cross-tool reasoning cost. Size-balanced batches would have mixed async work with storage or payments, forcing the executor to switch contexts between every tool. The trade-off (uneven LOC across WP-04/05/06 — WP-04 is the heaviest at ~7131 raw LOC) is accepted for cohesion gains. See sibling WPs for the Storage and Payments-Notif-ML themed partitions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
