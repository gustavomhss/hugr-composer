# Work Package Contract — `WP-02-observability-diagnostics`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-02-specific content fills each section.
> Theme: **telemetry, traces, metrics, health probes, runtime introspection** —
> 9 cohesive tools from `adapt/extend/infrastructure/`.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-02-observability-diagnostics` |
| **Title** | Migrate 9 observability/diagnostics tools to per-tool directory + externalized templates |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (PR #24, merged) · `WP-F1-base-and-golden` (in flight — `adapt/_base/` + golden `add_cursor_pagination/`) |
| **Blocks** | none (sibling WPs are file-disjoint) |
| **Branch** | `wp/02-observability-diagnostics` (off the post-dependency main, i.e. main with WP-F0 + WP-F1 merged) |
| **Isolation** | dedicated git worktree |
| **Model** | `sonnet` — mechanical refactor with moderate template heft; pattern set by F1 golden tool |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_anomaly_detector/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_api_replay_debugger/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_dependency_health_map/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_health_deep/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_opentelemetry/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_prometheus_metrics/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_request_tracing_ui/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_runtime_sentinel/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_structured_logging/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_anomaly_detector.py       [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_api_replay_debugger.py    [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_dependency_health_map.py  [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_health_deep.py            [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_opentelemetry.py          [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_prometheus_metrics.py     [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_request_tracing_ui.py     [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_runtime_sentinel.py       [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_structured_logging.py     [DELETE]
  ```
- **Golden reference (read-only, copy the pattern):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` (post WP-F1)
- **Shared base/contract to import (read-only):** `skills/SKILL-001-fastapi-production/adapt/_base/` + `skills/SKILL-001-fastapi-production/adapt/contracts/`
- **Spec to follow:** `docs/tool-contract.md`, `docs/architecture.md`
- **Staging pool (read-only reference, not a write surface):** `core/venous/_staging/` (renamed via WP-F0; see PR #24)

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-01 (Resiliency/Defense) tools** — the 9 tools listed in §1 of `docs/wp/WP-01-resiliency-defense.md`. Read that manifest for the canonical list.
- **WP-03 (Security/Compliance) tools** — the 9 tools listed in §1 of `docs/wp/WP-03-security-compliance.md`. Read that manifest for the canonical list.
- **WP-04/05/06 (sibling Z2) tools** — the remaining 26 infrastructure tools owned by `wp/async-storage-payments`.
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here.
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope.
- `adapt/extend/infrastructure/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report**.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 9 observability/diagnostics tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl`, and route their `discover/patch` through `adapt/_base/`.
- **Before:** Each tool is a single `add_<tool>.py` carrying embedded code-as-strings (triple-quoted blocks + `textwrap.dedent` blobs — these tools ship a lot of telemetry boilerplate: OTel exporters, Prometheus collectors, health probe wiring, log formatters). Per-tool LOC measurements (raw, end of §8) range 486–854.
- **After:**
  - Each tool becomes `add_<tool>/__init__.py` + `templates/*.py.tmpl`.
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*.py.tmpl`. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.extend.infrastructure.add_<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `add_anomaly_detector` | `add_anomaly_detector/{__init__.py, templates/}` | ≤ 260 | ≥ 6 (6 `dedent`, 32 triple-quote anchors) | `test_add_anomaly_detector_emitted.py` |
| `add_api_replay_debugger` | `add_api_replay_debugger/{__init__.py, templates/}` | ≤ 280 | ≥ 7 (7 `dedent`, 36 triple-quote anchors) | `test_add_api_replay_debugger_emitted.py` |
| `add_dependency_health_map` | `add_dependency_health_map/{__init__.py, templates/}` | ≤ 240 | ≥ 4 (4 `dedent`, 31 triple-quote anchors) | `test_add_dependency_health_map_emitted.py` |
| `add_health_deep` | `add_health_deep/{__init__.py, templates/}` | ≤ 290 | ≥ 10 (10 `dedent`, 48 triple-quote anchors) | `test_add_health_deep_emitted.py` |
| `add_opentelemetry` | `add_opentelemetry/{__init__.py, templates/}` | ≤ 260 | ≥ 8 (4 `dedent` + 8 `_GLUE`/template consts) | `test_add_opentelemetry_emitted.py` |
| `add_prometheus_metrics` | `add_prometheus_metrics/{__init__.py, templates/}` | ≤ 220 | ≥ 5 (5 `dedent`, 28 triple-quote anchors) | `test_add_prometheus_metrics_emitted.py` |
| `add_request_tracing_ui` | `add_request_tracing_ui/{__init__.py, templates/}` | ≤ 280 | ≥ 6 (6 `dedent`, includes a JS/HTML UI blob — see F-09) | `test_add_request_tracing_ui_emitted.py` |
| `add_runtime_sentinel` | `add_runtime_sentinel/{__init__.py, templates/}` | ≤ 260 | ≥ 2 (2 `dedent`, 17 triple-quote anchors) | `test_add_runtime_sentinel_emitted.py` |
| `add_structured_logging` | `add_structured_logging/{__init__.py, templates/}` | ≤ 200 | ≥ 5 (5 `dedent`, 28 triple-quote anchors) | `test_add_structured_logging_emitted.py` |

- **Out of scope:** behavior changes, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Same `ToolInput` → same `ToolResult` shape; same files emitted (byte-equivalent after stripping comments/whitespace from emitted code). Proven by GATE 1.
- [ ] **Import paths stable.** `from adapt.extend.infrastructure.add_<tool> import add_<tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep -E 'textwrap\.dedent|^\s*"""' add_<tool>/__init__.py | wc -l` returning 0 for emitted-code blocks.
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused `_GLUE`/`_TEMPLATE` constants left dangling.
- [ ] **Docstrings honest.** A tool that does not enforce something MUST say so in `warnings`. Specifically: a deep health probe that does not actually probe a downstream MUST say so; a structured logger that does not actually mask PII MUST say so.
- [ ] **No new dependencies.** No `pyproject.toml` change. (OTel/Prometheus dependencies are emitted into the generated project's `requirements.txt`, not into the kit.)
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool.

## 5. Test emission (per P1 #15)
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy that format verbatim** (location: `{project}/tests/test_<tool>_emitted.py`).

For each of the 9 tools in §1, the migrated `__init__.py` MUST:
- Render an emitted test from `templates/test_<tool>_emitted.py.tmpl`.
- Place it at `{project_dir}/tests/test_<tool>_emitted.py`.
- Make it green under the emitted project's `pytest tests/` after compose.
- Cover at least one positive (telemetry signal observed: e.g. metric increments, log line emitted, trace span created, `/health` endpoint returns expected JSON) and one negative (boundary or off-path) assertion. Same skeleton as F1 golden.

Failure to emit a test = WP rejected; non-negotiable per P1 #15.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/extend/infrastructure/add_{anomaly_detector,api_replay_debugger,dependency_health_map,health_deep,opentelemetry,prometheus_metrics,request_tracing_ui,runtime_sentinel,structured_logging}
$PY -m ruff format --check adapt/extend/infrastructure/add_{anomaly_detector,api_replay_debugger,dependency_health_map,health_deep,opentelemetry,prometheus_metrics,request_tracing_ui,runtime_sentinel,structured_logging}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/extend/infrastructure/test_add_{anomaly_detector,api_replay_debugger,dependency_health_map,health_deep,opentelemetry,prometheus_metrics,request_tracing_ui,runtime_sentinel,structured_logging}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'add_anomaly_detector|add_api_replay_debugger|add_dependency_health_map|add_health_deep|add_opentelemetry|add_prometheus_metrics|add_request_tracing_ui|add_runtime_sentinel|add_structured_logging'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (37/37)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-02 owns (write surface):** the 9 directories under `adapt/extend/infrastructure/add_<tool>/` listed in §1, plus the 9 legacy `.py` file deletions listed in §1.

**WP-02 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-01 Resiliency | the 9 tools listed in §1 of `docs/wp/WP-01-resiliency-defense.md` |
| WP-03 Security | the 9 tools listed in §1 of `docs/wp/WP-03-security-compliance.md` |
| WP-04/05/06 Z2 | all 26 remaining `adapt/extend/infrastructure/add_*` tools NOT named in §1 of this manifest |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Shared | `adapt/extend/infrastructure/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation; LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'`; `glue` = `grep -c '_GLUE\|_TEMPLATE\|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `add_anomaly_detector` | 669 | ≤ 260 (-61%) | 6 | 32 | 0 | 3.0 h | `sonnet` |
| `add_api_replay_debugger` | 854 | ≤ 280 (-67%) | 7 | 36 | 0 | 3.5 h | `sonnet` |
| `add_dependency_health_map` | 601 | ≤ 240 (-60%) | 4 | 31 | 0 | 2.5 h | `sonnet` |
| `add_health_deep` | 854 | ≤ 290 (-66%) | 10 | 48 | 0 | 3.5 h | `sonnet` |
| `add_opentelemetry` | 624 | ≤ 260 (-58%) | 4 | 20 | 8 | 3.0 h | `sonnet` |
| `add_prometheus_metrics` | 529 | ≤ 220 (-58%) | 5 | 28 | 0 | 2.5 h | `sonnet` |
| `add_request_tracing_ui` | 717 | ≤ 280 (-61%) | 6 | 32 | 2 | 3.5 h | `sonnet` |
| `add_runtime_sentinel` | 631 | ≤ 260 (-59%) | 2 | 17 | 0 | 2.5 h | `sonnet` |
| `add_structured_logging` | 486 | ≤ 200 (-59%) | 5 | 28 | 0 | 2.0 h | `sonnet` |
| **TOTAL** | **5965** | **~2290 (-62%)** | **49** | **272** | **10** | **~26 h** | `sonnet` |

**Model recommendation: `sonnet`.** This batch is mechanical (extract triple-quoted blobs → `.tmpl`, route discovery/patch through `_base`). It is heavier than WP-01 (more `dedent` calls, more templates per tool) but the transformation pattern is the same. Promotion to `opus` only if the agent hits a STOP-and-report rule in §9 — particularly F-09 (mixed-language UI blob in `add_request_tracing_ui`).

## 9. Failure modes (≥6 anticipated traps)

1. **F-01. Embedded f-string interpolation lost in template move.**
   - *Symptom:* emitted code refers to `${project_name}` literally instead of substituted value; `pytest tests/` in emitted project fails at import.
   - *Cause:* triple-quoted block in source used Python f-string interpolation; template renderer in `_base` uses different placeholder syntax.
   - *STOP-and-report rule:* before any extraction, dump the source's interpolation style for the tool; if it does not match F1 golden's template syntax, **stop and report**.

2. **F-02. `MCP_TOOL` metadata lost in module split.**
   - *Symptom:* `engine.audit.contract_check` drops from 37/37 → 36/37 for the migrated tool.
   - *Cause:* `MCP_TOOL = {...}` constant lived at module top in the flat `.py` and was not copied into the new `__init__.py`.
   - *STOP-and-report rule:* after every per-tool migration, run `python -c "from adapt.extend.infrastructure import add_<tool>; assert add_<tool>.MCP_TOOL"` — fail = stop and report.

3. **F-03. Idempotency regression — second run rewrites files.**
   - *Symptom:* `pytest` for `test_add_<tool>.py` fails on the second-run idempotency case; `ToolResult.status` returns `success` instead of `no_op`.
   - *Cause:* `discover()` was inlined per tool with custom skip-set; replacing with `adapt/_base/discover.py` lost a skip entry.
   - *STOP-and-report rule:* if `adapt/_base/discover.py` does not expose the tool's required skip-set, **stop and report** — do NOT re-inline discovery.

4. **F-04. Hidden behavior leak via `__init__.py` side-effects.**
   - *Symptom:* boot smoke fails — `import adapt.extend.infrastructure.add_<tool>` raises.
   - *Cause:* the flat `.py` ran top-level code (eager template render, global registry mutation, OTel provider init).
   - *STOP-and-report rule:* never paper over with try/except; **stop and report**.

5. **F-05. Template syntax drift — Jinja vs str.format.**
   - *Symptom:* templates render with literal `{var}` instead of values.
   - *Cause:* author used `str.format` placeholders in a `_base` Jinja renderer (or vice-versa).
   - *STOP-and-report rule:* before migration, confirm the renderer in `adapt/_base/render.py` and use **only** that syntax.

6. **F-06. Emitted-test missing or trivially-true (per P1 #15).**
   - *Symptom:* `tests/test_<tool>_emitted.py` exists in emitted project but has zero `assert` statements or asserts only `True`.
   - *Cause:* template author copied the golden skeleton without adapting the behavior assertions.
   - *STOP-and-report rule:* every emitted test MUST cover one positive (telemetry signal observed) and one negative case; if the tool's behavior cannot be asserted on the emitted surface, **stop and report**.

7. **F-07. OTel/Prometheus probe assertion flakes.**
   - *Symptom:* emitted `test_add_opentelemetry_emitted.py` or `test_add_prometheus_metrics_emitted.py` is non-deterministic — passes locally, fails in CI.
   - *Cause:* probe relies on a global registry or a real network socket; metric scrape happens before increment.
   - *STOP-and-report rule:* if a deterministic, in-process assertion is not possible, **stop and report** — do NOT add `time.sleep` or `@flaky` markers.

8. **F-08. Health-deep probe asserts what it does not actually probe.**
   - *Symptom:* `add_health_deep` ships warnings claiming downstream DB/cache probes are enforced, but the emitted code only checks process liveness.
   - *Cause:* honesty rule violation carried over from source; the flat `.py` already overclaimed.
   - *STOP-and-report rule:* if migrated `warnings` overstate enforcement, **stop and report** — fix the warnings to honest in this WP (not the behavior; that is out of scope).

9. **F-09. `add_request_tracing_ui` ships a mixed-language HTML/JS UI blob.**
   - *Symptom:* template extraction breaks because the blob contains `{` / `}` literals that collide with the template engine's syntax.
   - *Cause:* the source file embeds a UI in a triple-quoted string with literal braces.
   - *STOP-and-report rule:* if the UI blob cannot be cleanly extracted to `templates/_ui.html.tmpl` (or `.js.tmpl`) without escaping every `{` and `}`, **stop and report** — a `_base` raw-passthrough mode may be needed (joint amendment with WP-F1).

10. **F-10. Hard-cap LOC breach (`__init__.py` > 500).**
    - *Symptom:* size invariant fails for `add_api_replay_debugger` or `add_health_deep` (the two heaviest tools at 854 LOC each).
    - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
    - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC of logic without inlining `_base/`, **stop and report**.

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** All 9 tool directories created under `adapt/extend/infrastructure/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 9 legacy flat `.py` files removed (`git diff --name-only` shows 9 deletions).
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c 'textwrap.dedent' add_<tool>/__init__.py` → 0 for all 9).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not).
- [ ] **D-06.** All 9 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive (telemetry observed) + ≥1 negative assertion.
- [ ] **D-07.** §6 gate 1 (ruff) green for all 9 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 9 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke `tests/test_boot.py | grep`) returns a PASS line per tool name.
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 37/37.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface (no forbidden surface touched).
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`).
- [ ] **D-14.** `add_request_tracing_ui` UI blob successfully extracted to `templates/_ui.*.tmpl` (F-09 cleared) OR explicit stop-and-report posted.
- [ ] **D-15.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
