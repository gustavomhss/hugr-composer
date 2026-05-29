# Work Package Contract — `WP-01-resiliency-defense`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-01-specific content fills each section.
> Theme: **traffic-shaping, timeout discipline, failure isolation, degradation,
> hardening** — 9 cohesive tools from `adapt/extend/infrastructure/`.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-01-resiliency-defense` |
| **Title** | Migrate 9 resiliency/defense tools to per-tool directory + externalized templates |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (PR #24, merged) · `WP-F1-base-and-golden` (in flight — `adapt/_base/` + golden `add_cursor_pagination/`) |
| **Blocks** | none (sibling WPs are file-disjoint) |
| **Branch** | `wp/01-resiliency-defense` (off the post-dependency main, i.e. main with WP-F0 + WP-F1 merged) |
| **Isolation** | dedicated git worktree |
| **Model** | `sonnet` — mechanical refactor; pattern set by F1 golden tool |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_adaptive_throttle/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_adaptive_timeouts/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_bulkhead_isolation/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_circuit_breaker/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_graceful_shutdown/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_load_shedding/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_rate_limiting/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_response_armor/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_retry_budget/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_adaptive_throttle.py    [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_adaptive_timeouts.py    [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_bulkhead_isolation.py   [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_circuit_breaker.py      [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_graceful_shutdown.py    [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_load_shedding.py        [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_rate_limiting.py        [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_response_armor.py       [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_retry_budget.py         [DELETE]
  ```
- **Golden reference (read-only, copy the pattern):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` (post WP-F1)
- **Shared base/contract to import (read-only):** `skills/SKILL-001-fastapi-production/adapt/_base/` + `skills/SKILL-001-fastapi-production/adapt/contracts/`
- **Spec to follow:** `docs/tool-contract.md`, `docs/architecture.md`
- **Staging pool (read-only reference, not a write surface):** `core/venous/_staging/` (renamed via WP-F0; see PR #24)

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-02 (Observability/Diagnostics) tools** — the 9 tools listed in §1 of `docs/wp/WP-02-observability-diagnostics.md`. Read that manifest for the canonical list.
- **WP-03 (Security/Compliance) tools** — the 9 tools listed in §1 of `docs/wp/WP-03-security-compliance.md`. Read that manifest for the canonical list.
- **WP-04/05/06 (sibling Z2) tools** — the remaining 26 infrastructure tools owned by `wp/async-storage-payments`.
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here.
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope.
- `adapt/extend/infrastructure/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report** (registry update is a separate WP).

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 9 resiliency/defense tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl`, and route their `discover/patch` through `adapt/_base/`.
- **Before:** Each tool is a single `add_<tool>.py` carrying embedded code-as-strings (triple-quoted blocks, `textwrap.dedent`, `_GLUE`-style constants) plus per-tool ad-hoc discovery/patching. Per-tool LOC measurements (raw, end of §8) range 144–609.
- **After:**
  - Each tool becomes `add_<tool>/__init__.py` + `templates/*.py.tmpl`.
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*.py.tmpl`. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.extend.infrastructure.add_<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `add_adaptive_throttle` | `add_adaptive_throttle/{__init__.py, templates/}` | ≤ 240 | ≥ 3 (3 `dedent`, 44 triple-quote anchors) | `test_add_adaptive_throttle_emitted.py` |
| `add_adaptive_timeouts` | `add_adaptive_timeouts/{__init__.py, templates/}` | ≤ 220 | ≥ 6 (6 `_GLUE`/template consts) | `test_add_adaptive_timeouts_emitted.py` |
| `add_bulkhead_isolation` | `add_bulkhead_isolation/{__init__.py, templates/}` | ≤ 180 | ≥ 8 (8 `_GLUE`/template consts) | `test_add_bulkhead_isolation_emitted.py` |
| `add_circuit_breaker` | `add_circuit_breaker/{__init__.py, templates/}` | ≤ 100 | ≥ 2 | `test_add_circuit_breaker_emitted.py` |
| `add_graceful_shutdown` | `add_graceful_shutdown/{__init__.py, templates/}` | ≤ 120 | ≥ 2 | `test_add_graceful_shutdown_emitted.py` |
| `add_load_shedding` | `add_load_shedding/{__init__.py, templates/}` | ≤ 90 | ≥ 2 | `test_add_load_shedding_emitted.py` |
| `add_rate_limiting` | `add_rate_limiting/{__init__.py, templates/}` | ≤ 110 | ≥ 2 | `test_add_rate_limiting_emitted.py` |
| `add_response_armor` | `add_response_armor/{__init__.py, templates/}` | ≤ 240 | ≥ 3 (3 `dedent`, 47 triple-quote anchors) | `test_add_response_armor_emitted.py` |
| `add_retry_budget` | `add_retry_budget/{__init__.py, templates/}` | ≤ 110 | ≥ 2 | `test_add_retry_budget_emitted.py` |

- **Out of scope:** behavior changes, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Same `ToolInput` → same `ToolResult` shape; same files emitted (byte-equivalent after stripping comments/whitespace from emitted code). Proven by GATE 1.
- [ ] **Import paths stable.** `from adapt.extend.infrastructure.add_<tool> import add_<tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep -E 'textwrap\.dedent|^\s*"""' add_<tool>/__init__.py | wc -l` returning 0 for emitted-code blocks.
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused `_GLUE`/`_TEMPLATE` constants left dangling.
- [ ] **Docstrings honest.** A tool that does not enforce something MUST say so in `warnings`. No "guarantee" claims for advisory-only behavior.
- [ ] **No new dependencies.** No `pyproject.toml` change; no new top-level imports beyond what `adapt/_base/` already provides.
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool.

## 5. Test emission (per P1 #15)
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy that format verbatim** (location: `{project}/tests/test_<tool>_emitted.py`).

For each of the 9 tools in §1, the migrated `__init__.py` MUST:
- Render an emitted test from `templates/test_<tool>_emitted.py.tmpl`.
- Place it at `{project_dir}/tests/test_<tool>_emitted.py`.
- Make it green under the emitted project's `pytest tests/` after compose.
- Cover at least one positive (added behavior fires) and one negative (boundary or off-path) assertion. Same skeleton as F1 golden.

Failure to emit a test = WP rejected; this is non-negotiable per P1 #15.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/extend/infrastructure/add_{adaptive_throttle,adaptive_timeouts,bulkhead_isolation,circuit_breaker,graceful_shutdown,load_shedding,rate_limiting,response_armor,retry_budget}
$PY -m ruff format --check adapt/extend/infrastructure/add_{adaptive_throttle,adaptive_timeouts,bulkhead_isolation,circuit_breaker,graceful_shutdown,load_shedding,rate_limiting,response_armor,retry_budget}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/extend/infrastructure/test_add_{adaptive_throttle,adaptive_timeouts,bulkhead_isolation,circuit_breaker,graceful_shutdown,load_shedding,rate_limiting,response_armor,retry_budget}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'add_adaptive_throttle|add_adaptive_timeouts|add_bulkhead_isolation|add_circuit_breaker|add_graceful_shutdown|add_load_shedding|add_rate_limiting|add_response_armor|add_retry_budget'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (40/40)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-01 owns (write surface):** the 9 directories under `adapt/extend/infrastructure/add_<tool>/` listed in §1, plus the 9 legacy `.py` file deletions listed in §1.

**WP-01 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-02 Observability | the 9 tools listed in §1 of `docs/wp/WP-02-observability-diagnostics.md` |
| WP-03 Security | the 9 tools listed in §1 of `docs/wp/WP-03-security-compliance.md` |
| WP-04/05/06 Z2 | all 26 remaining `adapt/extend/infrastructure/add_*` tools NOT named in §1 of this manifest |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Shared | `adapt/extend/infrastructure/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation; LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'` (each emitted block opens+closes, so divide by 2 for approximate block count); `glue` = `grep -c '_GLUE\|_TEMPLATE\|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `add_adaptive_throttle` | 609 | ≤ 240 (-60%) | 3 | 44 | 0 | 3.0 h | `sonnet` |
| `add_adaptive_timeouts` | 504 | ≤ 220 (-56%) | 0 | 23 | 6 | 2.5 h | `sonnet` |
| `add_bulkhead_isolation` | 422 | ≤ 180 (-57%) | 0 | 24 | 8 | 2.5 h | `sonnet` |
| `add_circuit_breaker` | 156 | ≤ 100 (-36%) | 0 | 7 | 2 | 1.0 h | `sonnet` |
| `add_graceful_shutdown` | 201 | ≤ 120 (-40%) | 0 | 8 | 2 | 1.0 h | `sonnet` |
| `add_load_shedding` | 144 | ≤ 90 (-38%) | 0 | 7 | 2 | 1.0 h | `sonnet` |
| `add_rate_limiting` | 183 | ≤ 110 (-40%) | 0 | 7 | 2 | 1.0 h | `sonnet` |
| `add_response_armor` | 572 | ≤ 240 (-58%) | 3 | 47 | 0 | 3.0 h | `sonnet` |
| `add_retry_budget` | 187 | ≤ 110 (-41%) | 0 | 7 | 2 | 1.0 h | `sonnet` |
| **TOTAL** | **2978** | **~1410 (-53%)** | **6** | **174** | **22** | **~16 h** | `sonnet` |

**Model recommendation: `sonnet`.** This batch is mechanical (extract triple-quoted blobs → `.tmpl`, route discovery/patch through `_base`), pattern is set by F1 golden tool, no behavior-change reasoning required. Promotion to `opus` only if the agent hits a STOP-and-report rule in §9.

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
   - *Symptom:* boot smoke fails — `import adapt.extend.infrastructure.add_<tool>` raises.
   - *Cause:* the flat `.py` ran top-level code (e.g. eager template render, global registry mutation) that the new `__init__.py` no longer triggers.
   - *STOP-and-report rule:* never paper over with try/except; **stop and report** — top-level side-effects are an upstream bug that needs explicit migration.

5. **F-05. Template syntax drift — Jinja vs str.format.**
   - *Symptom:* templates render with literal `{var}` instead of values; emitted file is syntactically valid Python but semantically broken.
   - *Cause:* author used `str.format` placeholders in a `_base` Jinja renderer (or vice-versa).
   - *STOP-and-report rule:* before migration, confirm the renderer in `adapt/_base/render.py` and use **only** that syntax. Mixed syntax = stop and report.

6. **F-06. Emitted-test missing or trivially-true (per P1 #15).**
   - *Symptom:* `tests/test_<tool>_emitted.py` exists in emitted project but has zero `assert` statements, or asserts only `True`.
   - *Cause:* template author copied the golden skeleton without adapting the behavior assertions.
   - *STOP-and-report rule:* every emitted test MUST cover one positive and one negative case (§5); if the tool's behavior cannot be asserted (e.g. async-only side-effect, no observable surface), **stop and report** — do not ship a no-op test.

7. **F-07. `_GLUE`/`_TEMPLATE` constants pruned but still imported.**
   - *Symptom:* `ruff check` flags `F821` (undefined name) or import fails at boot.
   - *Cause:* externalization removed the constant but a sibling helper still references it.
   - *STOP-and-report rule:* run `python -m ruff check add_<tool>/` after every tool; non-empty output = stop and report (do NOT auto-fix without re-reading).

8. **F-08. Hard-cap LOC breach (`__init__.py` > 500).**
   - *Symptom:* size invariant fails for `add_adaptive_throttle` or `add_response_armor` (the two heaviest tools).
   - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
   - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC of logic without inlining `_base/`, **stop and report** — a `_base` extension may be needed (joint amendment with WP-F1).

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** All 9 tool directories created under `adapt/extend/infrastructure/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 9 legacy flat `.py` files removed (`git diff --name-only` shows 9 deletions).
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c 'textwrap.dedent' add_<tool>/__init__.py` → 0 for all 9).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not).
- [ ] **D-06.** All 9 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive + ≥1 negative assertion.
- [ ] **D-07.** §6 gate 1 (ruff) green for all 9 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 9 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke `tests/test_boot.py | grep`) returns a PASS line per tool name.
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 40/40.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface (no forbidden surface touched).
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`).
- [ ] **D-14.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

---

## Appendix A — Composition notes for this batch (read-only context)

The 9 tools in this WP frequently compose together in a typical FastAPI production
stack: rate limiting in front of bulkhead isolation, retry budget around circuit
breakers, adaptive timeouts feeding adaptive throttle, response armor and graceful
shutdown as middleware bookends. None of these compositions add behavior in
*this* WP — the migration is structural — but the agent SHOULD be aware:

- After WP-01 merges, downstream composition tests (`tests/test_boot_chains.py`)
  exercise these tools as a group. A regression in any one tool surfaces in the
  chain test, not just the per-tool test.
- The `__init__.py` orchestration MUST be import-cheap (no top-level work) so
  that `tests/test_boot.py` boot-time per tool stays under its current budget.
- If `adapt/_base/discover.py` adds a new helper between WP-F1 merge and this WP's
  execution, the agent SHOULD use it rather than re-deriving discovery logic.
  Stop-and-report only if the helper is missing for a specific tool's needs (F-03).

## Appendix B — Why theme-grouping (not size-balanced batches)

WP-01 carries 9 tools that share a defensive-stack mental model. An agent reading
the manifest gets the same conceptual frame for every tool in the batch, which
reduces cross-tool reasoning cost. Size-balanced batches would have mixed
resiliency with security or telemetry, forcing the executor to switch contexts
between every tool. The trade-off (uneven LOC across WP-01/02/03) is accepted
for cohesion gains. See sibling WPs (WP-04/05/06) for the Async/Storage/Payments
themed partitions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
