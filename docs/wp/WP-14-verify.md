# Work Package Contract — `WP-14-verify`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-14-specific content fills each section.
> Theme: **project-wide audit / verification** — 6 read-only tools from
> `adapt/verify/` that emit audit infrastructure (scripts, configs, CI
> workflows) into the user's project. **Semantically distinct from
> `adapt/extend/`:** verify tools do NOT add product behavior — they add
> checks. The test-emission semantic differs (§5 flags this) and the §11
> read-only-vs-extend posture differs (§11 flags this).
>
> **Model recommendation:** WP-14 runs on `sonnet`. Verify tools are
> mechanical: each emits a `scripts/<check>.py` orchestrator + config + CI
> workflow, and the patterns are uniform across the 6 tools. No
> irreversible-state risk (no migrations, no service moves), no security
> overclaim risk equivalent to WP-03 (each tool advertises itself as a check,
> not a guarantee). Promotion to `opus` only if the agent hits a
> STOP-and-report rule in §9.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-14-verify` |
| **Title** | Migrate 6 verify tools (audit-only, project-wide checks) to per-tool directory + externalized templates |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (PR #24, merged) · `WP-F1-base-and-golden` (PR #28, merged — `adapt/_base/` + golden `add_cursor_pagination/`) |
| **Blocks** | none (sibling WAVE-1 WPs are file-disjoint) |
| **Branch** | `wp/14-verify` (off the post-dependency main, i.e. main with WP-F0 + WP-F1 merged) |
| **Isolation** | dedicated git worktree |
| **Model** | `sonnet` — verify tools are read-only project audits; pattern set by F1 golden; no behavior-change reasoning required. Promote to `opus` only on a §9 STOP-and-report rule. |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/verify/api_spec_compliance/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/verify/dependency_audit/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/verify/detect_n_plus_one/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/verify/performance_baseline/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/verify/schema_coverage/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/verify/security_scan/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/verify/api_spec_compliance.py    [DELETE]
  skills/SKILL-001-fastapi-production/adapt/verify/dependency_audit.py       [DELETE]
  skills/SKILL-001-fastapi-production/adapt/verify/detect_n_plus_one.py      [DELETE]
  skills/SKILL-001-fastapi-production/adapt/verify/performance_baseline.py   [DELETE]
  skills/SKILL-001-fastapi-production/adapt/verify/schema_coverage.py        [DELETE]
  skills/SKILL-001-fastapi-production/adapt/verify/security_scan.py          [DELETE]
  ```
- **Golden reference (read-only, copy the pattern):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` (post WP-F1, PR #28).
  > **Adaptation note (read carefully):** the golden is an `adapt/extend/` tool — it patches existing routes/models and emits a project-side test asserting *added behavior*. WP-14's verify tools do NOT add product behavior; they emit audit infrastructure (`scripts/<check>.py`, configs, CI workflows). The orchestration phase order (`discover → plan → write → patch → verify`) is identical, but **`patch()` for verify tools is minimal-to-none** (most verify tools only `write()` new files) and **emitted tests assert that the audit infrastructure runs and reports**, not that product behavior fires. See §5 for the precise emitted-test semantic.
- **Shared base/contract to import (read-only):** `skills/SKILL-001-fastapi-production/adapt/_base/` + `skills/SKILL-001-fastapi-production/adapt/contracts/`
- **Spec to follow:** `docs/tool-contract.md`, `docs/architecture.md`

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-13 (Evolve) tools** — the 8 tools listed in §1 of `docs/wp/WP-13-evolve.md`.
- **WP-15 (Hexagon Ports)** — `core/venous/_ports/` (proposed) + any audit/catalog of the 124 registered primitives is owned by WP-15.
- **Sibling WAVE-1 batches** — WP-Z2 (infra 04-06), WP-C (crud+auth 07-09), WP-D (rt/test/api 10-12), WP-F (engine-split 16-17). Read each sibling's §1 for canonical ownership.
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here.
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope.
- `adapt/verify/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report**.
- `hugr_auth/` — license/auth gate is a separate service; touching it is an instant reject.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 6 verify tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl`, route their `discover/write` through `adapt/_base/`.
- **Before:** Each tool is a single `<tool>.py` carrying embedded code-as-strings (pytest-bench harness, openapi diff orchestrator, sqlalchemy event listener for N+1 detection, bandit/pip-audit wrappers, JSON schema coverage walker). Per-tool LOC measurements (raw, end of §8) range 431–583.
- **After:**
  - Each tool becomes `<tool>/__init__.py` + `templates/*.py.tmpl`.
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*.py.tmpl`. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.verify.<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.
  - **Honesty-rule audit per tool** (verify-tool-specific):
    - `api_spec_compliance` — must NOT claim "blocks BREAKING changes" if the emitted CI workflow only annotates a PR comment without a required-check gate.
    - `dependency_audit` — must NOT claim "blocks on CRITICAL CVEs" if the emitted workflow runs with `continue-on-error: true`.
    - `detect_n_plus_one` — must NOT claim "catches all N+1" if the emitted listener is sampling-based or scoped to a subset of routes.
    - `performance_baseline` — must NOT claim "regression detected" without a calibrated threshold; advisory-only baselines must say so.
    - `schema_coverage` — must NOT claim "100% coverage" if the walker ignores `Optional`/union branches.
    - `security_scan` — must NOT claim "OWASP top 10 covered" if bandit's ruleset is the default minimal subset.

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `api_spec_compliance` | `api_spec_compliance/{__init__.py, templates/}` | ≤ 220 | ≥ 5 (3 `dedent`, 28 triple-quote anchors) | `test_api_spec_compliance_emitted.py` |
| `dependency_audit` | `dependency_audit/{__init__.py, templates/}` | ≤ 230 | ≥ 5 (5 `dedent`, 26 triple-quote anchors) | `test_dependency_audit_emitted.py` |
| `detect_n_plus_one` | `detect_n_plus_one/{__init__.py, templates/}` | ≤ 250 | ≥ 6 (7 `dedent`, 34 triple-quote anchors) | `test_detect_n_plus_one_emitted.py` |
| `performance_baseline` | `performance_baseline/{__init__.py, templates/}` | ≤ 240 | ≥ 6 (5 `dedent`, 34 triple-quote anchors) | `test_performance_baseline_emitted.py` |
| `schema_coverage` | `schema_coverage/{__init__.py, templates/}` | ≤ 210 | ≥ 5 (3 `dedent`, 28 triple-quote anchors) | `test_schema_coverage_emitted.py` |
| `security_scan` | `security_scan/{__init__.py, templates/}` | ≤ 250 | ≥ 6 (6 `dedent`, 32 triple-quote anchors) | `test_security_scan_emitted.py` |

- **Out of scope:** behavior changes, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope. **Specifically:** the agent MUST NOT "tighten" any emitted check (e.g. add `continue-on-error: false`, expand bandit ruleset, replace sampling with full instrumentation). Those are separate WPs. The honesty-rule audit (§4) handles overclaims by adjusting `warnings` text only — never by changing behavior.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Same `ToolInput` → same `ToolResult` shape; same files emitted, byte-equivalent (verify-tools have a softer §11 posture — see §11). Proven by GATE 1.
- [ ] **Import paths stable.** `from adapt.verify.<tool> import <tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep`.
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused module-level constants left dangling after extraction.
- [ ] **Docstrings honest.** Verify-tool-specific: any `warnings` string MUST distinguish "the audit runs and reports" from "the audit blocks PRs / catches all instances / covers OWASP top 10". The 6 tools' known overclaim risks are listed in §3. Default to advisory-only language unless the emitted code delivers a hard gate.
- [ ] **No new dependencies.** No `pyproject.toml` change. Emitted deps (pip-audit, bandit, locust/k6, deptry) go in the generated project's `requirements-dev.txt`.
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool (most verify tools already detect their own `scripts/<check>.py` and `no_op` early).
- [ ] **Read-only on user product code.** The migrated tool MUST NOT modify the user's `app/`, `models/`, `schemas/`, `routes/` directories — only emit into `scripts/`, `tests/`, `.github/workflows/`, and a config file at the project root. Any verify tool that `patch()`es product code is OUT OF SCOPE for WP-14 and = stop and report.

## 5. Test emission (per P1 #15) — **semantic note: this WP differs from `adapt/extend/`**
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy the file location and skeleton verbatim** (location: `{project}/tests/test_<tool>_emitted.py`).

**Critical semantic difference vs. `adapt/extend/` tools (e.g. WP-01, WP-13):**

`adapt/extend/` tools add product behavior; their emitted tests assert that behavior fires (e.g. `test_cursor_pagination_emitted.py` asserts a 400 on invalid cursor). The emitted test is *evidence the tool changed the product*.

`adapt/verify/` tools add **audit checks**, not product behavior. The audit infrastructure (the `scripts/<check>.py`, the config, the CI workflow) IS what the tool delivers. Therefore the emitted test in `{project}/tests/test_<tool>_emitted.py` MUST assert:
1. **Positive (audit runs):** `scripts/<check>.py` exists, is importable, and `main()` returns a structured result (JSON report, exit code, etc.) on a synthetic minimal input. The check actually executes its scan/diff/parse step against a small fixture.
2. **Negative (audit reports honestly):** on a known-bad fixture (e.g. for `detect_n_plus_one`: a route that issues two queries per item; for `schema_coverage`: a route missing `response_model`; for `dependency_audit`: a pinned vulnerable package in a fixture lockfile), the check produces a non-empty finding. On a known-clean fixture, the check produces an empty / zero-finding result. **Never assert "the check would block CI"** unless the emitted workflow actually gates with `continue-on-error: false` and an exit-code-aware step.

**Honesty rule for verify-tool emitted tests:** if the emitted check is advisory-only (no PR-blocking, no required-status), the emitted test MUST NOT assert a fictitious block. The negative-case assertion is "the check reports the finding", NOT "the check fails CI".

Failure to emit a test, OR an emitted test that asserts a guarantee the tool does not deliver, = WP rejected. Non-negotiable per P1 #15 + honesty rules. The verify-tool semantic distinction is itself a regression class: an emitted test asserting "CI blocks" when CI does not is exactly the overclaim the honesty rule is meant to catch.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/verify/{api_spec_compliance,dependency_audit,detect_n_plus_one,performance_baseline,schema_coverage,security_scan}
$PY -m ruff format --check adapt/verify/{api_spec_compliance,dependency_audit,detect_n_plus_one,performance_baseline,schema_coverage,security_scan}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/verify/test_{api_spec_compliance,dependency_audit,detect_n_plus_one,performance_baseline,schema_coverage,security_scan}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'api_spec_compliance|dependency_audit|detect_n_plus_one|performance_baseline|schema_coverage|security_scan'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (37/37)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-14 owns (write surface):** the 6 directories under `adapt/verify/<tool>/` listed in §1, plus the 6 legacy flat `.py` file deletions listed in §1.

**WP-14 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-13 Evolve | the 8 tools listed in §1 of `docs/wp/WP-13-evolve.md` |
| WP-15 Hexagon Ports | `core/venous/_ports/` (proposed), the 124 registered primitives' protocol stubs, the port-catalog audit |
| WP-Z2 (04-06) | all infrastructure tools in `adapt/extend/infrastructure/` outside WP-01/02/03 |
| WP-C (07-09) | crud + auth-access tools owned by `wp/crud-auth` |
| WP-D (10-12) | realtime + testing-tools + api-design tools owned by `wp/rt-test-api` |
| WP-F (16-17) | engine-split tools owned by `wp/engine-split` |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Shared | `adapt/verify/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI, `hugr_auth/` |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation (HEAD `bd634a5`); LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'` (each emitted block opens+closes, so divide by 2 for approximate block count); `glue` = `grep -c '_GLUE\|_TEMPLATE\|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `api_spec_compliance` | 460 | ≤ 220 (-52%) | 3 | 28 | 0 | 2.0 h | `sonnet` |
| `dependency_audit` | 485 | ≤ 230 (-53%) | 5 | 26 | 0 | 2.0 h | `sonnet` |
| `detect_n_plus_one` | 573 | ≤ 250 (-56%) | 7 | 34 | 0 | 2.5 h | `sonnet` |
| `performance_baseline` | 551 | ≤ 240 (-56%) | 5 | 34 | 0 | 2.5 h | `sonnet` |
| `schema_coverage` | 431 | ≤ 210 (-51%) | 3 | 28 | 0 | 2.0 h | `sonnet` |
| `security_scan` | 583 | ≤ 250 (-57%) | 6 | 32 | 0 | 2.5 h | `sonnet` |
| **TOTAL** | **3083** | **~1400 (-55%)** | **29** | **182** | **0** | **~13.5 h** | `sonnet` |

**Model recommendation: `sonnet`.** Verify tools are mechanical: extract triple-quoted blocks → `.tmpl`, route discovery through `_base`, preserve `MCP_TOOL`. The pattern is set by the F1 golden and the verify-side adaptation in §5 (test-emission semantic) is captured explicitly so the agent doesn't need to derive it. No irreversible-state risk (no migrations, no service moves), no behavior-change reasoning required. The honesty-rule audit (§4) on `warnings` is text-level review; a `sonnet`-level agent can run it against the per-tool overclaim list in §3. Promotion to `opus` only if the agent hits a STOP-and-report rule in §9.

## 9. Failure modes (≥6 anticipated traps)

1. **F-01. Embedded f-string interpolation lost in template move.**
   - *Symptom:* emitted `scripts/<check>.py` refers to `${project_name}` literally instead of substituted value; orchestrator fails at import.
   - *Cause:* triple-quoted block used Python f-strings; `adapt/_base/render.py` uses `string.Template` (`$name` / `${name}`).
   - *STOP-and-report rule:* before extraction, dump source's interpolation style. `_base.render` is strict-substitute — a missing key raises `KeyError`. Mismatch = stop and report.

2. **F-02. `MCP_TOOL` metadata lost in module split.**
   - *Symptom:* `engine.audit.contract_check` drops from 37/37 → 36/37.
   - *Cause:* `MCP_TOOL = {...}` constant not copied into new `__init__.py`.
   - *STOP-and-report rule:* per-tool sanity import check: `python -c "from adapt.verify import <tool>; assert <tool>.MCP_TOOL"` — fail = stop and report.

3. **F-03. Idempotency regression — second run rewrites the audit script.**
   - *Symptom:* `test_<tool>.py` fails on the second-run idempotency case; `scripts/<check>.py` is rewritten in place, silently overwriting a user customization.
   - *Cause:* `discover()` short-circuit lost in template-move; the existing-script check was an inline `Path.exists()` that didn't survive the move.
   - *STOP-and-report rule:* per tool, confirm second-run returns `no_op` AND that the file's mtime is unchanged. Mtime drift on no-op = stop and report.

4. **F-04. Honesty-rule violation — verify-tool overclaim.**
   - *Symptom:* migrated `warnings` claim "blocks BREAKING API changes" or "catches all N+1 queries" or "100% schema coverage" when the emitted artefact does NOT deliver that gate.
   - *Cause:* author copy-pasted optimistic `warnings` from source without re-reading the emitted CI workflow / sampling config / coverage walker. The 6 tools' known overclaim risks are listed in §3.
   - *STOP-and-report rule:* per tool, read the emitted CI workflow (or detection config) and the `warnings` side-by-side. Any "blocks", "catches all", "100%", "complete", "OWASP top 10 covered" claim that the artefact does not deliver = stop and report. Fix `warnings` to honest in this WP (behavior change is out of scope per §3).

5. **F-05. Read-only invariant breached — verify tool patches product code.**
   - *Symptom:* `git status` after compose shows changes to `{project}/app/`, `{project}/models/`, or `{project}/routes/`.
   - *Cause:* the flat `.py` had an exotic helper (e.g. inserting an `@instrument` decorator at module top) that bled into product code.
   - *STOP-and-report rule:* WP-14's invariant §4 is hard: verify tools touch ONLY `scripts/`, `tests/`, `.github/workflows/`, and root config files. Any other write target = stop and report.

6. **F-06. Emitted-test asserts a fictitious block (per §5 honesty rule).**
   - *Symptom:* `test_<tool>_emitted.py` asserts "CI fails on a finding" when the emitted workflow has `continue-on-error: true`, OR asserts "all routes covered" when `schema_coverage` walker ignores unions.
   - *Cause:* author copied the `adapt/extend/` golden's test skeleton without applying the §5 verify-tool semantic.
   - *STOP-and-report rule:* per tool, re-read §5 BEFORE writing the emitted-test template. Positive case = "audit runs and reports". Negative case = "audit produces non-empty finding on known-bad fixture". NEVER "audit blocks CI" unless the emitted workflow gates. Mismatch = stop and report.

7. **F-07. Sampling/scoping config drift in `detect_n_plus_one` / `performance_baseline`.**
   - *Symptom:* extracted template has the sample rate or threshold hard-coded to a different value than source (e.g. source samples every request; template samples 10%).
   - *Cause:* source had a constant near the top of the file (e.g. `_SAMPLE_RATE = 1.0`) that was inlined into the triple-quoted block; extraction loses it.
   - *STOP-and-report rule:* §11 byte-equivalence diff gate catches this. Drift = stop and report.

8. **F-08. Hidden behavior leak via `__init__.py` side-effects.**
   - *Symptom:* boot smoke fails — import raises.
   - *Cause:* the flat `.py` ran top-level code that the new layout no longer triggers.
   - *STOP-and-report rule:* never paper over with try/except; **stop and report** — top-level side-effects in verify tools are an upstream bug.

9. **F-09. Hard-cap LOC breach (`__init__.py` > 500).**
    - *Symptom:* size invariant fails for the heaviest tool (`security_scan` 583 LOC source).
    - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
    - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC of logic without inlining `_base/`, **stop and report**.

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** All 6 tool directories created under `adapt/verify/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 6 legacy flat `.py` files removed (`git diff --name-only` shows 6 deletions).
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c 'textwrap.dedent' <tool>/__init__.py` → 0 for all 6).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not).
- [ ] **D-06.** All 6 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive (audit runs against fixture and returns a structured result) + ≥1 negative (audit produces finding on known-bad fixture, zero findings on known-clean fixture). Honesty-adapted per F-06 + §5.
- [ ] **D-07.** §6 gate 1 (ruff) green for all 6 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 6 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke `tests/test_boot.py | grep`) returns a PASS line per tool name.
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 37/37.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface (no forbidden surface touched).
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`, emitted `scripts/<check>.py` mtime unchanged).
- [ ] **D-14.** Read-only invariant verified per tool: post-compose `git status` on a fixture project shows changes ONLY in `scripts/`, `tests/`, `.github/workflows/`, and root config files. Any product-code (`app/`, `models/`, `routes/`, `schemas/`) modification = WP rejected per F-05.
- [ ] **D-15.** Honesty-rule audit per tool: every `warnings` string re-read against actually emitted templates + CI workflow gating posture; the 6 tools' overclaim risks (§3) explicitly re-verified; overclaims fixed to honest text.
- [ ] **D-16.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

## 11. Risk callout (WP-14-specific — read-only audit semantic + overclaim risk)

**Why this section exists and how it differs from WP-13's risk section:**

WP-13 (evolve) carries irreversible-state risk: a migration corrupts a database, an SDK overwrite breaks callers. WP-14 (verify) carries a different, subtler risk class: **audit theater**. Verify tools ship checks. If the check is advisory-only but the `warnings` / `notes` / emitted-test claim it gates CI or catches all instances, the user ships with a false sense of security. That is its own corruption-class bug — slower-moving than WP-13's data loss, but with the same trust-erosion blast radius.

**Why this WP gets a softer §11 byte-equivalence posture than WP-03 / WP-13:**

WP-03 and WP-13 mandate per-tool byte-equivalence because a drift in security middleware or a migration template directly degrades a deployed product. WP-14's emitted artefacts are audit infrastructure — they affect what the CI panel reports, not what the deployed app does. Comment/whitespace drift in `scripts/<check>.py` is harmless. The real risk vector is **gating-posture drift** (a check that was a hard gate becoming advisory, or vice-versa) and **threshold/sampling drift** (a rate that was 100% becoming 10%, masking findings). Therefore:

- The byte-equivalence diff gate is **recommended** but **not blocking** for `scripts/<check>.py` body changes that are pure comment/whitespace.
- The diff gate IS blocking for: CI workflow YAML (`continue-on-error`, `if:` conditions, required-status), threshold/sampling-rate constants (`_SAMPLE_RATE`, `_THRESHOLD_MS`, `_MAX_FINDINGS`), and any allowlist/denylist file (`.audit-ignore`, `.bandit`).

**The 8 audit-theater traps WP-14 must avoid:**

- An `api_spec_compliance` workflow that comments BREAKING changes on the PR but does not block merge — `warnings` MUST NOT say "blocks BREAKING".
- A `dependency_audit` workflow that runs `pip-audit` with `continue-on-error: true` — `warnings` MUST NOT say "blocks on CRITICAL CVEs".
- A `detect_n_plus_one` listener that samples 1% of queries — `warnings` MUST NOT say "catches all N+1".
- A `performance_baseline` baseline with no calibrated threshold — `warnings` MUST say "advisory baseline, regression detection requires manual threshold tuning".
- A `schema_coverage` walker that treats `Optional[X]` as a single branch — `warnings` MUST say "union/optional branches counted as single covered branch".
- A `security_scan` bandit run with default ruleset — `warnings` MUST NOT claim "OWASP top 10 covered".
- An emitted test that asserts "CI fails on finding" when the workflow has `continue-on-error: true` — instant reject per F-06.
- A `no_op` return that nonetheless rewrites the emitted `scripts/<check>.py` (silently clobbering a user customization) — caught by D-13 mtime check.

**Mitigation: gating-posture-aware diff gate.** For each of the 6 tools:

```bash
PY=.venv/bin/python
# 1. Compose on main (pre-migration) into /tmp/pre/<tool>
git checkout main -- skills/SKILL-001-fastapi-production/adapt/verify/<tool>.py
$PY -m engine.compose --tool <tool> --project /tmp/pre/<tool>
# 2. Compose the migrated tool into /tmp/post/<tool>
git checkout HEAD -- skills/SKILL-001-fastapi-production/adapt/verify/<tool>
$PY -m engine.compose --tool <tool> --project /tmp/post/<tool>
# 3. Diff. Allowed drift in scripts/<check>.py body: comment/whitespace only.
#    Diff in .github/workflows/*.yml, threshold constants, allowlist files = STOP.
diff -ruN /tmp/pre/<tool> /tmp/post/<tool> | grep -vE '^[+-]\s*(#|$)' | tee /tmp/diff_<tool>.txt
# Inspect /tmp/diff_<tool>.txt: any change to .yml, _SAMPLE_RATE, _THRESHOLD_*, _MAX_FINDINGS,
# continue-on-error, if:, allowlist/denylist file = STOP and report.
```

Paste each tool's gating-posture diff in §7. Non-cosmetic drift in any of the listed protected regions = **stop and report — do NOT ship**.

**Why `sonnet` is sufficient despite the §11 callout:** the gating-posture protected regions are enumerated; the agent does not need to reason about cosmetic vs. behavioral drift in arbitrary Python — only check that workflow YAML, named threshold constants, and allowlist files are byte-equivalent. `sonnet`-level pattern matching on a known protected-region list is reliable. Promote to `opus` only if a STOP-and-report fires.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
