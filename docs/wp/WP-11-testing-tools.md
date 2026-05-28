# Work Package Contract — `WP-11-testing-tools`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-11-specific content fills each section.
> Theme: **test infra emitted into projects** — fuzzing, contracts, factories,
> migrations CI, schema guards, SBOM, load profiles, data seeders — 9 cohesive
> tools from `adapt/extend/testing_tools/`.
>
> **Meta:** this WP migrates the tools that emit test infrastructure into the
> generated project. The structural pattern (`__init__.py` + `templates/`) is
> identical to WP-01/02/10/12. The reflexive semantic question — "does each
> tool emit a test that asserts its emitted test infra actually fires?" — is
> raised as an open question in §11 for tech-lead resolution **before**
> execution. Do not pre-decide it.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-11-testing-tools` |
| **Title** | Migrate 9 testing-infra tools to per-tool directory + externalized templates |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (merged) · `WP-F1-base-and-golden` (in flight — `adapt/_base/` + golden `add_cursor_pagination/`) · **§11 open question resolved** by tech-lead |
| **Blocks** | none (sibling WPs are file-disjoint) |
| **Branch** | `wp/11-testing-tools` (off the post-dependency main, i.e. main with WP-F0 + WP-F1 merged) |
| **Isolation** | dedicated git worktree |
| **Model** | `sonnet` — mechanical refactor; pattern set by F1 golden tool. Promotion to `opus` only if §11 open question resolves toward a semantic redesign of emitted tests for self-referential tools. |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_api_fuzzer/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_contract_tests/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_data_seeder/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_database_migrations_ci/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_factory/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_load_profile/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_sbom_guardian/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_schema_enforcer/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_schema_evolution_guard/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_api_fuzzer.py              [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_contract_tests.py          [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_data_seeder.py             [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_database_migrations_ci.py  [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_factory.py                 [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_load_profile.py            [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_sbom_guardian.py           [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_schema_enforcer.py         [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/testing_tools/add_schema_evolution_guard.py  [DELETE]
  ```
- **Golden reference (read-only, copy the pattern):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` (post WP-F1)
- **Shared base/contract to import (read-only):** `skills/SKILL-001-fastapi-production/adapt/_base/` + `skills/SKILL-001-fastapi-production/adapt/contracts/`
- **Spec to follow:** `docs/tool-contract.md`, `docs/architecture.md`, `docs/adr/0001-architecture.md`
- **Staging pool (read-only reference, not a write surface):** `core/venous/_staging/` (renamed via WP-F0)

**Excluded from this WP (sibling-owned):** `adapt/extend/testing_tools/add_e2e_test_suite.py` is NOT in this WP's surface. If the catalog assigns it elsewhere, treat it as forbidden here.

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-10 (Realtime) targets** — the 5 tools listed in §1 of `docs/wp/WP-10-realtime.md`.
- **WP-12 (API design) targets** — the 7 tools listed in §1 of `docs/wp/WP-12-api-design.md`.
- **WP-01/02/03 (infrastructure) tools** — all 27 tools owned by those manifests.
- **WP-Z2 / WP-C / WP-E / WP-F sibling targets** — infrastructure 04-06, crud+auth 07-09, evolve/verify/hex 13-15, engine 16-17.
- **`add_e2e_test_suite`** in `testing_tools/` — NOT in this WP; sibling-owned (see §1 note).
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here.
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope.
- `adapt/extend/testing_tools/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report** (registry update is a separate WP).
- All other `adapt/extend/<cat>/__init__.py` files — read-only.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 9 testing-infra tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl`, and route their `discover/patch` through `adapt/_base/`.
- **Before:** Each tool is a single `add_<tool>.py` carrying embedded code-as-strings (triple-quoted blocks, `textwrap.dedent`, occasional `_GLUE`-style constants) plus per-tool ad-hoc discovery/patching. These tools ship Hypothesis strategies, contract assertions, factory-boy boilerplate, Alembic migration runners, JSON-schema enforcers, SBOM diff tooling, locust profiles, seed-data fixtures. Per-tool LOC measurements (raw, end of §8) range 526–939.
- **After:**
  - Each tool becomes `add_<tool>/__init__.py` + `templates/*.py.tmpl`.
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*.py.tmpl`. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC of logic (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.extend.testing_tools.add_<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `add_api_fuzzer` | `add_api_fuzzer/{__init__.py, templates/}` | ≤ 260 | ≥ 4 (4 `dedent`, 24 triple-quote anchors) | `test_add_api_fuzzer_emitted.py` |
| `add_contract_tests` | `add_contract_tests/{__init__.py, templates/}` | ≤ 250 | ≥ 10 (10 `dedent`, 43 triple-quote anchors) | `test_add_contract_tests_emitted.py` |
| `add_data_seeder` | `add_data_seeder/{__init__.py, templates/}` | ≤ 270 | ≥ 5 (5 `dedent`, 30 triple-quote anchors) | `test_add_data_seeder_emitted.py` |
| `add_database_migrations_ci` | `add_database_migrations_ci/{__init__.py, templates/}` | ≤ 260 | ≥ 4 (4 `dedent`, 24 triple-quote anchors) | `test_add_database_migrations_ci_emitted.py` |
| `add_factory` | `add_factory/{__init__.py, templates/}` | ≤ 220 | ≥ 6 (6 `dedent`, 28 triple-quote anchors) | `test_add_factory_emitted.py` |
| `add_load_profile` | `add_load_profile/{__init__.py, templates/}` | ≤ 280 | ≥ 8 (8 `dedent`, 39 triple-quote anchors) | `test_add_load_profile_emitted.py` |
| `add_sbom_guardian` | `add_sbom_guardian/{__init__.py, templates/}` | ≤ 220 | ≥ 2 (2 `dedent`, 17 triple-quote anchors) | `test_add_sbom_guardian_emitted.py` |
| `add_schema_enforcer` | `add_schema_enforcer/{__init__.py, templates/}` | ≤ 240 | ≥ 3 (3 `dedent`, 49 triple-quote anchors) | `test_add_schema_enforcer_emitted.py` |
| `add_schema_evolution_guard` | `add_schema_evolution_guard/{__init__.py, templates/}` | ≤ 270 | ≥ 4 (4 `dedent`, 23 triple-quote anchors, 2 `_GLUE`) | `test_add_schema_evolution_guard_emitted.py` |

- **Out of scope:** behavior changes, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope, touching any sibling WP's tools, touching `add_e2e_test_suite`.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Same `ToolInput` → same `ToolResult` shape; same files emitted (byte-equivalent after stripping comments/whitespace from emitted code). Proven by GATE 1.
- [ ] **Import paths stable.** `from adapt.extend.testing_tools.add_<tool> import add_<tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep -E 'textwrap\.dedent|^\s*"""' add_<tool>/__init__.py | wc -l` returning 0 for emitted-code blocks.
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused `_GLUE`/`_TEMPLATE` constants left dangling.
- [ ] **Docstrings honest.** A tool that does not enforce something MUST say so in `warnings`. Specifically: a fuzzer that does not assert invariants MUST say so; a contract-test tool that does not verify provider compatibility MUST say so; a schema enforcer that only logs (does not block) MUST say so; an SBOM guardian that only diffs (does not fail CI) MUST say so.
- [ ] **No new dependencies.** No `pyproject.toml` change in the kit. (Test deps — `hypothesis`, `pact-python`, `factory-boy`, `locust`, etc. — are emitted into the generated project's `requirements-dev.txt`, not into the kit.)
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool.

## 5. Test emission (per P1 #15) — and the meta-question
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy that format verbatim** (location: `{project}/tests/test_<tool>_emitted.py`).

For each of the 9 tools in §1, the migrated `__init__.py` MUST:
- Render an emitted test from `templates/test_<tool>_emitted.py.tmpl`.
- Place it at `{project_dir}/tests/test_<tool>_emitted.py`.
- Make it green under the emitted project's `pytest tests/` after compose.
- Cover at least one positive (added test-infra fires: e.g. fuzzer generates and runs ≥1 case, contract test executes against a provider stub, factory builds an instance with all required fields, migration runner applies up+down, schema enforcer rejects a malformed payload, SBOM guardian diffs a known-bad pin, load profile invokes ≥1 scenario, seeder inserts ≥1 row) and one negative (boundary or off-path: empty input, schema-valid edge, idempotent re-run) assertion.

**Important meta-distinction for THIS WP only:** the *tool* under test is itself a test-infra tool. The emitted test asserts that the emitted test infra fires — NOT that every fuzz case finds a bug, NOT that every contract pact validates against an external provider. See §11 for the open question this raises.

Failure to emit a test = WP rejected; this is non-negotiable per P1 #15.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/extend/testing_tools/add_{api_fuzzer,contract_tests,data_seeder,database_migrations_ci,factory,load_profile,sbom_guardian,schema_enforcer,schema_evolution_guard}
$PY -m ruff format --check adapt/extend/testing_tools/add_{api_fuzzer,contract_tests,data_seeder,database_migrations_ci,factory,load_profile,sbom_guardian,schema_enforcer,schema_evolution_guard}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/extend/testing_tools/test_add_{api_fuzzer,contract_tests,data_seeder,database_migrations_ci,factory,load_profile,sbom_guardian,schema_enforcer,schema_evolution_guard}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'add_api_fuzzer|add_contract_tests|add_data_seeder|add_database_migrations_ci|add_factory|add_load_profile|add_sbom_guardian|add_schema_enforcer|add_schema_evolution_guard'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (37/37)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-11 owns (write surface):** the 9 directories under `adapt/extend/testing_tools/add_<tool>/` listed in §1, plus the 9 legacy flat `.py` file deletions listed in §1.

**WP-11 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-10 Realtime | the 5 tools listed in §1 of `docs/wp/WP-10-realtime.md` |
| WP-12 API design | the 7 tools listed in §1 of `docs/wp/WP-12-api-design.md` |
| WP-01/02/03 | all 27 `adapt/extend/infrastructure/add_*` tools listed in those manifests |
| WP-Z2 / WP-C / WP-E / WP-F (sibling) | infra 04-06, crud+auth 07-09, evolve/verify/hex 13-15, engine 16-17 |
| (sibling, category-internal) | `adapt/extend/testing_tools/add_e2e_test_suite.py` (NOT in this WP) |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Shared | `adapt/extend/testing_tools/__init__.py`, all other `adapt/extend/<cat>/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation; LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'`; `glue` = `grep -cE '_GLUE|_TEMPLATE|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `add_api_fuzzer` | 735 | ≤ 260 (-65%) | 4 | 24 | 0 | 3.0 h | `sonnet` |
| `add_contract_tests` | 685 | ≤ 250 (-64%) | 10 | 43 | 0 | 3.0 h | `sonnet` |
| `add_data_seeder` | 814 | ≤ 270 (-67%) | 5 | 30 | 0 | 3.0 h | `sonnet` |
| `add_database_migrations_ci` | 709 | ≤ 260 (-63%) | 4 | 24 | 0 | 3.0 h | `sonnet` |
| `add_factory` | 526 | ≤ 220 (-58%) | 6 | 28 | 0 | 2.5 h | `sonnet` |
| `add_load_profile` | 939 | ≤ 280 (-70%) | 8 | 39 | 0 | 3.5 h | `sonnet` |
| `add_sbom_guardian` | 541 | ≤ 220 (-59%) | 2 | 17 | 0 | 2.5 h | `sonnet` |
| `add_schema_enforcer` | 627 | ≤ 240 (-62%) | 3 | 49 | 0 | 3.0 h | `sonnet` |
| `add_schema_evolution_guard` | 842 | ≤ 270 (-68%) | 4 | 23 | 2 | 3.0 h | `sonnet` |
| **TOTAL** | **6418** | **~2270 (-65%)** | **46** | **277** | **2** | **~26.5 h** | `sonnet` |

**Model recommendation: `sonnet`.** This batch is mechanical (extract triple-quoted blobs → `.tmpl`, route discovery/patch through `_base`); pattern is set by F1 golden tool. The semantic meta-question in §11 is a tech-lead decision **before** execution; once decided, the executor's job remains structural. Promotion to `opus` only if §11 resolves toward a semantic redesign or the agent hits a STOP-and-report rule in §9.

## 9. Failure modes (≥6 anticipated traps)

1. **F-01. Embedded f-string interpolation lost in template move.**
   - *Symptom:* emitted code refers to `${project_name}` literally instead of substituted value; `pytest tests/` in emitted project fails at import.
   - *Cause:* triple-quoted block in source used Python f-string interpolation; template renderer in `_base` uses different placeholder syntax.
   - *STOP-and-report rule:* before any extraction, dump the source's interpolation style for the tool; if it does not match F1 golden's template syntax, **stop and report**.

2. **F-02. `MCP_TOOL` metadata lost in module split.**
   - *Symptom:* `engine.audit.contract_check` drops from 37/37 → 36/37 for the migrated tool.
   - *Cause:* `MCP_TOOL = {...}` constant lived at module top in the flat `.py` and was not copied into the new `__init__.py`.
   - *STOP-and-report rule:* after every per-tool migration, run `python -c "from adapt.extend.testing_tools import add_<tool>; assert add_<tool>.MCP_TOOL"` — fail = stop and report.

3. **F-03. Idempotency regression — second run rewrites files.**
   - *Symptom:* `pytest` for `test_add_<tool>.py` fails on the second-run idempotency case; `ToolResult.status` returns `success` instead of `no_op`.
   - *Cause:* `discover()` was inlined per tool with custom skip-set; replacing with `adapt/_base/discover.py` lost a skip entry (e.g. `tests/conftest.py`, `tests/factories/`).
   - *STOP-and-report rule:* if `adapt/_base/discover.py` does not expose the tool's required skip-set, **stop and report** — do NOT re-inline discovery.

4. **F-04. Hidden behavior leak via `__init__.py` side-effects.**
   - *Symptom:* boot smoke fails — `import adapt.extend.testing_tools.add_<tool>` raises.
   - *Cause:* the flat `.py` ran top-level code (eager Hypothesis registration, global factory registry mutation, Alembic env-load).
   - *STOP-and-report rule:* never paper over with try/except; **stop and report**.

5. **F-05. Template syntax drift — Jinja vs str.format.**
   - *Symptom:* templates render with literal `{var}` instead of values.
   - *Cause:* author used `str.format` placeholders in a `_base` Jinja renderer (or vice-versa).
   - *STOP-and-report rule:* before migration, confirm the renderer in `adapt/_base/render.py` and use **only** that syntax.

6. **F-06. Emitted-test missing or trivially-true (per P1 #15).**
   - *Symptom:* `tests/test_<tool>_emitted.py` exists in emitted project but has zero `assert` statements, or asserts only `True`. **Higher risk on this WP** because the tool already emits test code — author may conflate "tool emitted a test file" with "emitted test asserts behavior".
   - *Cause:* template author copied the golden skeleton without adapting the behavior assertions; or assumed the tool's own emitted test infra is itself the §5 emitted test.
   - *STOP-and-report rule:* every emitted test MUST cover one positive (test-infra fires) and one negative (boundary) case; if the tool's behavior cannot be asserted on the emitted surface without invoking the tool's own emitted test infra as a sub-runner, see §11 open question and **stop and report**.

7. **F-07. Reflexive emitted-test loop.**
   - *Symptom:* the emitted test for `add_api_fuzzer` tries to assert that the fuzzer's emitted test passes — but the fuzzer's emitted test is generated, non-deterministic, or requires a long run.
   - *Cause:* author interpreted §5 as "assert the emitted test infra passes" rather than "assert the emitted test infra is correctly wired".
   - *STOP-and-report rule:* the §5 emitted test asserts **wiring** (file exists at expected path, importable, expected fixtures/markers present), not **execution success of the emitted test infra**. If the §11 open question resolves differently, restart this WP.

8. **F-08. Hypothesis / Locust / factory-boy assertion non-determinism.**
   - *Symptom:* emitted `test_add_api_fuzzer_emitted.py` or `test_add_load_profile_emitted.py` passes locally but flakes in CI; depends on RNG seed, network, or wall-clock.
   - *Cause:* test invokes Hypothesis with `@given` without `@settings(deadline=None, max_examples=1)`, or invokes locust with a real socket.
   - *STOP-and-report rule:* if a deterministic, in-process assertion is not possible, **stop and report** — do NOT add `time.sleep`, RNG-fixed seeds, or `@flaky`.

9. **F-09. Schema-enforcer / SBOM-guardian overclaim.**
   - *Symptom:* `add_schema_enforcer` ships warnings claiming hard-block on schema drift, but the emitted code only logs; `add_sbom_guardian` claims CI failure on vuln but only diffs.
   - *Cause:* honesty rule violation carried over from source.
   - *STOP-and-report rule:* if migrated `warnings` overstate enforcement, **stop and report** — fix the warnings to honest in this WP (not the behavior; that is out of scope).

10. **F-10. Hard-cap LOC breach (`__init__.py` > 500).**
    - *Symptom:* size invariant fails for `add_load_profile` (939 LOC), `add_schema_evolution_guard` (842), or `add_data_seeder` (814) — the three heaviest tools.
    - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
    - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC of logic without inlining `_base/`, **stop and report**.

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-00.** §11 open question resolved by tech-lead before any code is touched.
- [ ] **D-01.** All 9 tool directories created under `adapt/extend/testing_tools/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 9 legacy flat `.py` files removed (`git diff --name-only` shows 9 deletions). `add_e2e_test_suite.py` is NOT touched.
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c 'textwrap.dedent' add_<tool>/__init__.py` → 0 for all 9).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not).
- [ ] **D-06.** All 9 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive + ≥1 negative assertion, deterministic, asserting **wiring** (per §11 resolution).
- [ ] **D-07.** §6 gate 1 (ruff) green for all 9 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 9 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke `tests/test_boot.py | grep`) returns a PASS line per tool name.
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 37/37.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface (no sibling WP surface touched; `add_e2e_test_suite` untouched).
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`).
- [ ] **D-14.** Reflexive emitted-test loop avoided (F-07 cleared): emitted tests assert wiring, not sub-runner success.
- [ ] **D-15.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

---

## 11. Open question for tech-lead (resolve BEFORE execution)

**Question.** WP-11 migrates the tools that emit test infrastructure into the
generated project. The golden pattern (`add_cursor_pagination`) was set on a
tool that emits **behavior code** (cursor-pagination logic) and a single
emitted test that asserts that behavior fires. For WP-11's tools, the *tool's*
output is itself test infrastructure (fuzzers, contract pacts, factories,
schema enforcers, SBOM diffs, load profiles, seeders). This raises a reflexive
semantic question:

> **What does "emit a test that asserts the behavior added by the tool" mean
> when the tool IS test infrastructure?**

Three candidate interpretations, none pre-decided:

1. **Wiring assertion (cheapest, most deterministic).** The §5 emitted test
   asserts only that the tool's emitted test files exist at the expected path,
   are importable, declare the expected fixtures/markers, and that any
   generated `conftest.py` / `factories/` / `pact/` / `locustfile.py` /
   `alembic.ini` is structurally valid. Does NOT invoke the tool's own emitted
   test infra as a sub-runner.

2. **Sub-runner assertion (more semantic, costlier, riskier).** The §5 emitted
   test invokes the tool's own emitted test infra as a sub-process (e.g. runs
   `pytest tests/fuzz/` for `add_api_fuzzer`, `pytest tests/contracts/` for
   `add_contract_tests`) and asserts exit code 0. Captures actual behavior but
   adds non-determinism (F-08) and CI time.

3. **Hybrid.** Wiring assertion is mandatory; sub-runner assertion is added
   only for tools whose emitted infra is itself deterministic and fast
   (`add_factory`, `add_data_seeder`, `add_schema_enforcer`). Fuzzers and load
   profiles ship wiring-only.

**Why this needs tech-lead resolution, not agent decision.** Two prior PRs were
rejected for partition decisions made by an agent. The §11 question changes the
*semantic* of P1 #15 for one WP only, which is a contract-level call. The agent
executing WP-11 should NOT pre-decide; the manifest documents the three
candidates so tech-lead can pick one before execution.

**Default if not resolved.** Treat this WP as **blocked on D-00**. Do NOT
proceed with implementation until the answer is recorded as an amendment to
this manifest. The structural transformation (§3) is unaffected by the
resolution — only the emitted-test template content changes.

---

## Appendix A — Composition notes for this batch (read-only context)

The 9 tools in this WP frequently compose together in a typical FastAPI
production test stack: `add_factory` + `add_data_seeder` seed the database for
`add_contract_tests` and `add_api_fuzzer`; `add_schema_enforcer` and
`add_schema_evolution_guard` co-validate request/response shapes;
`add_database_migrations_ci` runs as a pre-test step;
`add_load_profile` and `add_sbom_guardian` ship as out-of-band CI jobs. None of
these compositions add behavior in *this* WP — the migration is structural —
but the agent SHOULD be aware:

- After WP-11 merges, downstream composition tests (`tests/test_boot_chains.py`)
  exercise these tools as a group. A regression in any one tool surfaces in the
  chain test.
- The `__init__.py` orchestration MUST be import-cheap (no Hypothesis
  registration, no factory-boy registry mutation at module scope).
- If `add_e2e_test_suite` (sibling-owned, NOT in this WP) composes with any of
  these 9 tools, the agent SHOULD verify the composition still resolves after
  the migration — but MUST NOT touch `add_e2e_test_suite` itself.

## Appendix B — Why theme-grouping (not size-balanced batches)

WP-11 carries 9 tools that share a "test infrastructure emitted into the
generated project" mental model. An agent reading the manifest gets the same
conceptual frame for every tool in the batch, which reduces cross-tool
reasoning cost. Size-balanced batches would have mixed test infra with
realtime or API-design paradigms, forcing context switches. The trade-off
(9 tools, 6418 LOC total) is accepted for cohesion gains.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
