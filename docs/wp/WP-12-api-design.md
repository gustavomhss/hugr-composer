# Work Package Contract — `WP-12-api-design`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-12-specific content fills each section.
> Theme: **API surface evolution — versioning, deprecation, alternative
> paradigms (CQRS, GraphQL, GraphQL subscriptions, batch endpoints, long-running
> tasks)** — 7 cohesive tools from `adapt/extend/api_design/`.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-12-api-design` |
| **Title** | Migrate 7 api_design tools to per-tool directory + externalized templates |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (merged) · `WP-F1-base-and-golden` (in flight — `adapt/_base/` + golden `add_cursor_pagination/`) |
| **Blocks** | none (sibling WPs are file-disjoint) |
| **Branch** | `wp/12-api-design` (off the post-dependency main, i.e. main with WP-F0 + WP-F1 merged) |
| **Isolation** | dedicated git worktree |
| **Model** | `sonnet` — mechanical refactor; pattern set by F1 golden tool. `add_graphql` (908 LOC, 14 dedent, 68 triple) is the heaviest, with mixed-language schema/SDL blobs analogous to WP-02's `add_request_tracing_ui` (see F-09). |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_api_deprecation/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_api_versioning/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_batch_endpoint/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_cqrs/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_graphql/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_graphql_subscriptions/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_long_running_task/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_api_deprecation.py        [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_api_versioning.py         [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_batch_endpoint.py         [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_cqrs.py                   [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_graphql.py                [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_graphql_subscriptions.py  [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/api_design/add_long_running_task.py      [DELETE]
  ```
- **Golden reference (read-only, copy the pattern):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` (post WP-F1)
- **Shared base/contract to import (read-only):** `skills/SKILL-001-fastapi-production/adapt/_base/` + `skills/SKILL-001-fastapi-production/adapt/contracts/`
- **Spec to follow:** `docs/tool-contract.md`, `docs/architecture.md`, `docs/adr/0001-architecture.md`
- **Staging pool (read-only reference, not a write surface):** `core/venous/_staging/` (renamed via WP-F0)

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-10 (Realtime) targets** — the 5 tools listed in §1 of `docs/wp/WP-10-realtime.md`.
- **WP-11 (Testing tools) targets** — the 9 tools listed in §1 of `docs/wp/WP-11-testing-tools.md`.
- **WP-01/02/03 (infrastructure) tools** — all 27 tools owned by those manifests.
- **WP-Z2 / WP-C / WP-E / WP-F sibling targets** — infrastructure 04-06, crud+auth 07-09, evolve/verify/hex 13-15, engine 16-17.
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here.
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope.
- `adapt/extend/api_design/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report** (registry update is a separate WP).
- All other `adapt/extend/<cat>/__init__.py` files — read-only.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 7 api_design tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl`, and route their `discover/patch` through `adapt/_base/`.
- **Before:** Each tool is a single `add_<tool>.py` carrying embedded code-as-strings (triple-quoted blocks, `textwrap.dedent`, occasional `_GLUE`-style constants) plus per-tool ad-hoc discovery/patching. These tools ship surface-evolution boilerplate: version-routing middleware, deprecation headers + `Sunset` semantics, batch-coalescing, CQRS command/query split, Strawberry/Ariadne GraphQL resolvers + SDL, GraphQL subscription transport (WS), Celery/RQ task-status polling. Per-tool LOC measurements (raw, end of §8) range 254–908.
- **After:**
  - Each tool becomes `add_<tool>/__init__.py` + `templates/*.py.tmpl`.
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*.py.tmpl`. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC of logic (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.extend.api_design.add_<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `add_api_deprecation` | `add_api_deprecation/{__init__.py, templates/}` | ≤ 260 | ≥ 4 (4 `dedent`, 28 triple-quote anchors) | `test_add_api_deprecation_emitted.py` |
| `add_api_versioning` | `add_api_versioning/{__init__.py, templates/}` | ≤ 250 | ≥ 5 (5 `dedent`, 32 triple-quote anchors) | `test_add_api_versioning_emitted.py` |
| `add_batch_endpoint` | `add_batch_endpoint/{__init__.py, templates/}` | ≤ 270 | ≥ 4 (4 `dedent`, 29 triple-quote anchors) | `test_add_batch_endpoint_emitted.py` |
| `add_cqrs` | `add_cqrs/{__init__.py, templates/}` | ≤ 260 | ≥ 6 (6 `dedent`, 24 triple-quote anchors) | `test_add_cqrs_emitted.py` |
| `add_graphql` | `add_graphql/{__init__.py, templates/}` | ≤ 290 | ≥ 14 (14 `dedent`, 68 triple-quote anchors, includes SDL/.graphql blob — see F-09) | `test_add_graphql_emitted.py` |
| `add_graphql_subscriptions` | `add_graphql_subscriptions/{__init__.py, templates/}` | ≤ 260 | ≥ 6 (6 `dedent`, 34 triple-quote anchors) | `test_add_graphql_subscriptions_emitted.py` |
| `add_long_running_task` | `add_long_running_task/{__init__.py, templates/}` | ≤ 160 | ≥ 4 (4 triple-quote blocks, 2 `_GLUE`) | `test_add_long_running_task_emitted.py` |

- **Out of scope:** behavior changes, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope, touching any sibling WP's tools.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Same `ToolInput` → same `ToolResult` shape; same files emitted (byte-equivalent after stripping comments/whitespace from emitted code). Proven by GATE 1.
- [ ] **Import paths stable.** `from adapt.extend.api_design.add_<tool> import add_<tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep -E 'textwrap\.dedent|^\s*"""' add_<tool>/__init__.py | wc -l` returning 0 for emitted-code blocks.
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused `_GLUE`/`_TEMPLATE` constants left dangling.
- [ ] **Docstrings honest.** A tool that does not enforce something MUST say so in `warnings`. Specifically: a versioning tool that does not route by header MUST say so; a deprecation tool that only adds `Sunset` header without `410 Gone` MUST say so; a batch endpoint that does not parallelize MUST say so; a CQRS tool that does not separate read/write models MUST say so; a long-running-task tool that does not persist task state MUST say so.
- [ ] **No new dependencies.** No `pyproject.toml` change in the kit. (GraphQL deps — `strawberry-graphql`, `ariadne`, etc. — are emitted into the generated project's `requirements.txt`.)
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool.

## 5. Test emission (per P1 #15)
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy that format verbatim** (location: `{project}/tests/test_<tool>_emitted.py`).

For each of the 7 tools in §1, the migrated `__init__.py` MUST:
- Render an emitted test from `templates/test_<tool>_emitted.py.tmpl`.
- Place it at `{project_dir}/tests/test_<tool>_emitted.py`.
- Make it green under the emitted project's `pytest tests/` after compose.
- Cover at least one positive (added behavior fires: e.g. `/v2/foo` route resolves while `/v1/foo` still 200s, `Sunset` header present on deprecated route, batch endpoint returns N results for N inputs, CQRS command emits an event, GraphQL query returns expected shape, GraphQL subscription delivers ≥1 frame, long-running task transitions `pending → success`) and one negative (boundary or off-path: unknown version → 406, deprecated route past sunset → 410, batch over limit → 413, CQRS write into read endpoint → 405, GraphQL malformed query → 400, subscription auth missing → close, task-status for unknown id → 404) assertion.

Failure to emit a test = WP rejected; this is non-negotiable per P1 #15.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/extend/api_design/add_{api_deprecation,api_versioning,batch_endpoint,cqrs,graphql,graphql_subscriptions,long_running_task}
$PY -m ruff format --check adapt/extend/api_design/add_{api_deprecation,api_versioning,batch_endpoint,cqrs,graphql,graphql_subscriptions,long_running_task}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/extend/api_design/test_add_{api_deprecation,api_versioning,batch_endpoint,cqrs,graphql,graphql_subscriptions,long_running_task}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'add_api_deprecation|add_api_versioning|add_batch_endpoint|add_cqrs|add_graphql|add_graphql_subscriptions|add_long_running_task'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (40/40)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-12 owns (write surface):** the 7 directories under `adapt/extend/api_design/add_<tool>/` listed in §1, plus the 7 legacy flat `.py` file deletions listed in §1.

**WP-12 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-10 Realtime | the 5 tools listed in §1 of `docs/wp/WP-10-realtime.md` |
| WP-11 Testing tools | the 9 tools listed in §1 of `docs/wp/WP-11-testing-tools.md` |
| WP-01/02/03 | all 27 `adapt/extend/infrastructure/add_*` tools listed in those manifests |
| WP-Z2 / WP-C / WP-E / WP-F (sibling) | infra 04-06, crud+auth 07-09, evolve/verify/hex 13-15, engine 16-17 |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Shared | `adapt/extend/api_design/__init__.py`, all other `adapt/extend/<cat>/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation; LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'`; `glue` = `grep -cE '_GLUE|_TEMPLATE|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `add_api_deprecation` | 708 | ≤ 260 (-63%) | 4 | 28 | 0 | 3.0 h | `sonnet` |
| `add_api_versioning` | 670 | ≤ 250 (-63%) | 5 | 32 | 0 | 3.0 h | `sonnet` |
| `add_batch_endpoint` | 806 | ≤ 270 (-66%) | 4 | 29 | 0 | 3.0 h | `sonnet` |
| `add_cqrs` | 688 | ≤ 260 (-62%) | 6 | 24 | 0 | 3.0 h | `sonnet` |
| `add_graphql` | 908 | ≤ 290 (-68%) | 14 | 68 | 0 | 4.0 h | `sonnet` |
| `add_graphql_subscriptions` | 725 | ≤ 260 (-64%) | 6 | 34 | 0 | 3.0 h | `sonnet` |
| `add_long_running_task` | 254 | ≤ 160 (-37%) | 0 | 13 | 2 | 1.5 h | `sonnet` |
| **TOTAL** | **4759** | **~1750 (-63%)** | **39** | **228** | **2** | **~20.5 h** | `sonnet` |

**Model recommendation: `sonnet`.** This batch is mechanical (extract triple-quoted blobs → `.tmpl`, route discovery/patch through `_base`); pattern is set by F1 golden tool. `add_graphql` is the heaviest (908 LOC, 14 dedent, 68 triple) with mixed-language SDL/`.graphql` content — see F-09 for the analogue of WP-02's `add_request_tracing_ui` UI-blob trap. Promotion to `opus` only if the agent hits a STOP-and-report rule in §9.

## 9. Failure modes (≥6 anticipated traps)

1. **F-01. Embedded f-string interpolation lost in template move.**
   - *Symptom:* emitted code refers to `${project_name}` literally instead of substituted value; `pytest tests/` in emitted project fails at import.
   - *Cause:* triple-quoted block in source used Python f-string interpolation; template renderer in `_base` uses different placeholder syntax.
   - *STOP-and-report rule:* before any extraction, dump the source's interpolation style for the tool; if it does not match F1 golden's template syntax, **stop and report**.

2. **F-02. `MCP_TOOL` metadata lost in module split.**
   - *Symptom:* `engine.audit.contract_check` drops from 40/40 → 36/37 for the migrated tool.
   - *Cause:* `MCP_TOOL = {...}` constant lived at module top in the flat `.py` and was not copied into the new `__init__.py`.
   - *STOP-and-report rule:* after every per-tool migration, run `python -c "from adapt.extend.api_design import add_<tool>; assert add_<tool>.MCP_TOOL"` — fail = stop and report.

3. **F-03. Idempotency regression — second run rewrites files.**
   - *Symptom:* `pytest` for `test_add_<tool>.py` fails on the second-run idempotency case; `ToolResult.status` returns `success` instead of `no_op`.
   - *Cause:* `discover()` was inlined per tool with custom skip-set; replacing with `adapt/_base/discover.py` lost a skip entry.
   - *STOP-and-report rule:* if `adapt/_base/discover.py` does not expose the tool's required skip-set, **stop and report**.

4. **F-04. Hidden behavior leak via `__init__.py` side-effects.**
   - *Symptom:* boot smoke fails — `import adapt.extend.api_design.add_<tool>` raises.
   - *Cause:* the flat `.py` ran top-level code (eager Strawberry/Ariadne schema build, global router mutation, Celery app init).
   - *STOP-and-report rule:* never paper over with try/except; **stop and report**.

5. **F-05. Template syntax drift — Jinja vs str.format.**
   - *Symptom:* templates render with literal `{var}` instead of values.
   - *Cause:* author used `str.format` placeholders in a `_base` Jinja renderer (or vice-versa).
   - *STOP-and-report rule:* before migration, confirm the renderer in `adapt/_base/render.py` and use **only** that syntax.

6. **F-06. Emitted-test missing or trivially-true (per P1 #15).**
   - *Symptom:* `tests/test_<tool>_emitted.py` exists in emitted project but has zero `assert` statements or asserts only `True`.
   - *Cause:* template author copied the golden skeleton without adapting the behavior assertions.
   - *STOP-and-report rule:* every emitted test MUST cover one positive and one negative case (§5); if the tool's behavior cannot be asserted (e.g. async-only side-effect, no observable surface), **stop and report**.

7. **F-07. Versioning / deprecation header-vs-path routing drift.**
   - *Symptom:* emitted `test_add_api_versioning_emitted.py` asserts header-based routing but the emitted code routes by path prefix (or vice-versa).
   - *Cause:* the flat `.py` shipped both strategies behind a config switch; author externalized only one path.
   - *STOP-and-report rule:* if the source supports multiple routing strategies, the template MUST preserve all; if any strategy would silently drop, **stop and report**.

8. **F-08. GraphQL subscription emitted-test non-determinism.**
   - *Symptom:* `test_add_graphql_subscriptions_emitted.py` passes locally but flakes in CI; depends on event-loop / WS handshake timing.
   - *Cause:* test awaits a frame without explicit timeout, or relies on subscription delivery before assert.
   - *STOP-and-report rule:* if a deterministic, in-process assertion is not possible, **stop and report** — do NOT add `time.sleep` or `@flaky`.

9. **F-09. `add_graphql` ships a mixed-language SDL / `.graphql` blob.**
   - *Symptom:* template extraction breaks because the SDL contains `{` / `}` literals that collide with the template engine's syntax. Analogous to WP-02 F-09 (`add_request_tracing_ui`).
   - *Cause:* the source file embeds a GraphQL SDL in a triple-quoted string with literal braces.
   - *STOP-and-report rule:* if the SDL blob cannot be cleanly extracted to `templates/_schema.graphql.tmpl` without escaping every `{` and `}`, **stop and report** — a `_base` raw-passthrough mode may be needed (joint amendment with WP-F1).

10. **F-10. Long-running-task state honesty.**
    - *Symptom:* `add_long_running_task` ships warnings claiming durable task state (Redis-backed, survives restart) but emitted code uses an in-process dict.
    - *Cause:* honesty rule violation carried over from source.
    - *STOP-and-report rule:* if migrated `warnings` overstate enforcement, **stop and report** — fix the warnings to honest in this WP (not the behavior).

11. **F-11. Hard-cap LOC breach (`__init__.py` > 500).**
    - *Symptom:* size invariant fails for `add_graphql` (908 LOC), `add_batch_endpoint` (806), or `add_graphql_subscriptions` (725) — the three heaviest tools.
    - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
    - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC of logic without inlining `_base/`, **stop and report**.

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** All 7 tool directories created under `adapt/extend/api_design/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 7 legacy flat `.py` files removed (`git diff --name-only` shows 7 deletions).
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c 'textwrap.dedent' add_<tool>/__init__.py` → 0 for all 7).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not).
- [ ] **D-06.** All 7 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive + ≥1 negative assertion, deterministic.
- [ ] **D-07.** §6 gate 1 (ruff) green for all 7 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 7 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke `tests/test_boot.py | grep`) returns a PASS line per tool name.
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 40/40.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface (no sibling WP surface touched).
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`).
- [ ] **D-14.** `add_graphql` SDL blob successfully extracted to `templates/_schema.graphql.tmpl` (F-09 cleared) OR explicit stop-and-report posted.
- [ ] **D-15.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

---

## Appendix A — Composition notes for this batch (read-only context)

The 7 tools in this WP frequently compose together in a typical FastAPI
API-evolution stack: `add_api_versioning` defines the version axis,
`add_api_deprecation` ships sunset signals along it, `add_batch_endpoint`
provides bulk-write under both versions, `add_cqrs` separates read from write
inside each version, `add_graphql` and `add_graphql_subscriptions` ship an
alternative paradigm alongside REST, and `add_long_running_task` provides the
202+poll pattern for any tool above whose latency budget can't fit a single
request. None of these compositions add behavior in *this* WP — the migration
is structural — but the agent SHOULD be aware:

- After WP-12 merges, downstream composition tests (`tests/test_boot_chains.py`)
  exercise these tools as a group. A regression in any one tool surfaces in the
  chain test.
- The `__init__.py` orchestration MUST be import-cheap (no Strawberry schema
  build, no Celery `app` init at module scope).
- `add_graphql_subscriptions` composes with the websocket transport in
  `adapt/extend/realtime/` (sibling WP-10). The migration MUST NOT touch
  WP-10's surface; if the composition contract changes, **report** it (do not
  fix it — that is another WP).

## Appendix B — Why theme-grouping (not size-balanced batches)

WP-12 carries 7 tools that share an API-surface-evolution mental model. An
agent reading the manifest gets the same conceptual frame for every tool
(versioning, deprecation, alternative paradigms), which reduces cross-tool
reasoning cost. Size-balanced batches would have mixed API-design with
realtime or test infra, forcing context switches. The trade-off (7 tools,
4759 LOC total, one heavy `add_graphql` with mixed-language SDL) is accepted
for cohesion gains. See WP-10/11 for the cohesion principle applied to the
realtime and testing-tools partitions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
