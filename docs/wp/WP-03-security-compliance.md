# Work Package Contract — `WP-03-security-compliance`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-03-specific content fills each section.
> Theme: **surface hardening, leak prevention, compliance, abuse detection** —
> 9 cohesive tools from `adapt/extend/infrastructure/`.
>
> **Model elevation:** WP-03 runs on `opus`, not `sonnet`, because security
> primitives have the highest behavior-change blast radius in the WAVE 1 batch.
> See §11 for the byte-equivalence diff-gate mandated for this WP.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-03-security-compliance` |
| **Title** | Migrate 9 security/compliance tools to per-tool directory + externalized templates |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (PR #24, merged) · `WP-F1-base-and-golden` (in flight — `adapt/_base/` + golden `add_cursor_pagination/`) |
| **Blocks** | none (sibling WPs are file-disjoint) |
| **Branch** | `wp/03-security-compliance` (off the post-dependency main, i.e. main with WP-F0 + WP-F1 merged) |
| **Isolation** | dedicated git worktree |
| **Model** | `opus` — security/compliance primitives carry the highest behavior-change blast radius; honesty-rule checks are subtle; byte-equivalence diff gate applies (§11) |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_canary_tokens/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_chaos_testing/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_compliance_engine/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_cors_config/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_csrf_protection/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_dlp_shield/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_input_sanitization/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_request_fingerprint/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_secret_rotation/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_canary_tokens.py        [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_chaos_testing.py        [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_compliance_engine.py    [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_cors_config.py          [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_csrf_protection.py      [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_dlp_shield.py           [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_input_sanitization.py   [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_request_fingerprint.py  [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_secret_rotation.py      [DELETE]
  ```
- **Golden reference (read-only, copy the pattern):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` (post WP-F1)
- **Shared base/contract to import (read-only):** `skills/SKILL-001-fastapi-production/adapt/_base/` + `skills/SKILL-001-fastapi-production/adapt/contracts/`
- **Spec to follow:** `docs/tool-contract.md`, `docs/architecture.md`
- **Staging pool (read-only reference, not a write surface):** `core/venous/_staging/` (renamed via WP-F0; see PR #24)

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-01 (Resiliency/Defense) tools** — the 9 tools listed in §1 of `docs/wp/WP-01-resiliency-defense.md`. Read that manifest for the canonical list.
- **WP-02 (Observability/Diagnostics) tools** — the 9 tools listed in §1 of `docs/wp/WP-02-observability-diagnostics.md`. Read that manifest for the canonical list.
- **WP-04/05/06 (sibling Z2) tools** — the remaining 26 infrastructure tools owned by `wp/async-storage-payments`.
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here. (Note: `core/venous/security/` and `core/venous/compliance/` host the registered primitives some of these tools wire into — read but never write.)
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope.
- `adapt/extend/infrastructure/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report**.
- `hugr_auth/` — license/auth gate is a separate service; touching it is an instant reject.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 9 security/compliance tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl`, route their `discover/patch` through `adapt/_base/`, AND pass the §11 byte-equivalence diff gate per tool.
- **Before:** Each tool is a single `add_<tool>.py` carrying embedded code-as-strings (security middleware, CSP/CORS configs, DLP regex tables, compliance audit hooks, canary token wiring). `add_compliance_engine.py` is the heaviest in the WAVE-1 batch at 1150 LOC. Per-tool LOC measurements (raw, end of §8) range 406–1150.
- **After:**
  - Each tool becomes `add_<tool>/__init__.py` + `templates/*.py.tmpl`.
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*.py.tmpl`. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.extend.infrastructure.add_<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.
  - **Honesty-rule audit per tool:** any `warnings` string MUST honestly describe what the migrated code enforces. Carry-over of overclaiming from the source is an instant reject (security overclaiming = audit failure).
  - **§11 byte-equivalence diff gate** must pass for each tool.

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `add_canary_tokens` | `add_canary_tokens/{__init__.py, templates/}` | ≤ 280 | ≥ 6 (6 `dedent`, 26 triple-quote anchors) | `test_add_canary_tokens_emitted.py` |
| `add_chaos_testing` | `add_chaos_testing/{__init__.py, templates/}` | ≤ 260 | ≥ 4 (4 `dedent`, 26 triple-quote anchors) | `test_add_chaos_testing_emitted.py` |
| `add_compliance_engine` | `add_compliance_engine/{__init__.py, templates/}` | ≤ 290 | ≥ 14 (7 `dedent` + 14 `_GLUE` consts) | `test_add_compliance_engine_emitted.py` |
| `add_cors_config` | `add_cors_config/{__init__.py, templates/}` | ≤ 180 | ≥ 3 (3 `dedent`, 21 triple-quote anchors) | `test_add_cors_config_emitted.py` |
| `add_csrf_protection` | `add_csrf_protection/{__init__.py, templates/}` | ≤ 260 | ≥ 4 (4 `dedent`, 26 triple-quote anchors) | `test_add_csrf_protection_emitted.py` |
| `add_dlp_shield` | `add_dlp_shield/{__init__.py, templates/}` | ≤ 260 | ≥ 4 (4 `dedent`, 20 triple-quote anchors) | `test_add_dlp_shield_emitted.py` |
| `add_input_sanitization` | `add_input_sanitization/{__init__.py, templates/}` | ≤ 240 | ≥ 4 (4 `dedent`, 26 triple-quote anchors) | `test_add_input_sanitization_emitted.py` |
| `add_request_fingerprint` | `add_request_fingerprint/{__init__.py, templates/}` | ≤ 240 | ≥ 4 (4 `dedent`, 24 triple-quote anchors) | `test_add_request_fingerprint_emitted.py` |
| `add_secret_rotation` | `add_secret_rotation/{__init__.py, templates/}` | ≤ 280 | ≥ 6 (3 `dedent` + 6 `_GLUE` consts) | `test_add_secret_rotation_emitted.py` |

- **Out of scope:** behavior changes, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope. **Specifically:** the agent MUST NOT "improve" the security posture of any emitted code (e.g. tighten a CSP, restrict a CORS allowlist, expand a DLP regex). Those are separate WPs.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Same `ToolInput` → same `ToolResult` shape; same files emitted, byte-equivalent per §11 diff gate. Proven by GATE 1 + §11 diff.
- [ ] **Import paths stable.** `from adapt.extend.infrastructure.add_<tool> import add_<tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep`.
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused `_GLUE`/`_TEMPLATE` constants left dangling.
- [ ] **Docstrings honest.** Security/compliance-specific: a tool that does NOT enforce a guarantee MUST lead its `warnings` with `⚠ … IS NOT ENFORCED`. Examples: `add_cors_config` warning if origin allowlist is permissive; `add_dlp_shield` warning if regex catalog is sample-only; `add_compliance_engine` warning that policies are advisory unless wired to a blocking middleware.
- [ ] **No new dependencies.** No `pyproject.toml` change. Emitted deps go in generated `requirements.txt`.
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool.
- [ ] **§11 byte-equivalence diff gate passes per tool.**

## 5. Test emission (per P1 #15)
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy that format verbatim** (location: `{project}/tests/test_<tool>_emitted.py`).

For each of the 9 tools in §1, the migrated `__init__.py` MUST:
- Render an emitted test from `templates/test_<tool>_emitted.py.tmpl`.
- Place it at `{project_dir}/tests/test_<tool>_emitted.py`.
- Make it green under the emitted project's `pytest tests/` after compose.
- Cover at least one positive (security control fires: e.g. CORS blocks disallowed origin, CSRF rejects missing token, DLP redacts PII pattern, canary token records hit, sanitizer strips a malicious payload) and one negative (allowed traffic passes through unchanged) assertion. Same skeleton as F1 golden.
- **Honesty rule:** if the tool's behavior is advisory-only (e.g. `add_compliance_engine` policy evaluation without blocking middleware), the emitted test MUST assert the advisory signal (log line / metric / response header), NOT a fictitious block.

Failure to emit a test, OR an emitted test that asserts a guarantee the tool does not deliver, = WP rejected. Non-negotiable per P1 #15 + honesty rules.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/extend/infrastructure/add_{canary_tokens,chaos_testing,compliance_engine,cors_config,csrf_protection,dlp_shield,input_sanitization,request_fingerprint,secret_rotation}
$PY -m ruff format --check adapt/extend/infrastructure/add_{canary_tokens,chaos_testing,compliance_engine,cors_config,csrf_protection,dlp_shield,input_sanitization,request_fingerprint,secret_rotation}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/extend/infrastructure/test_add_{canary_tokens,chaos_testing,compliance_engine,cors_config,csrf_protection,dlp_shield,input_sanitization,request_fingerprint,secret_rotation}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'add_canary_tokens|add_chaos_testing|add_compliance_engine|add_cors_config|add_csrf_protection|add_dlp_shield|add_input_sanitization|add_request_fingerprint|add_secret_rotation'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (37/37)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7. Additionally, §11 byte-equivalence diff must be PASS per tool.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-03 owns (write surface):** the 9 directories under `adapt/extend/infrastructure/add_<tool>/` listed in §1, plus the 9 legacy `.py` file deletions listed in §1.

**WP-03 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-01 Resiliency | the 9 tools listed in §1 of `docs/wp/WP-01-resiliency-defense.md` |
| WP-02 Observability | the 9 tools listed in §1 of `docs/wp/WP-02-observability-diagnostics.md` |
| WP-04/05/06 Z2 | all 26 remaining `adapt/extend/infrastructure/add_*` tools NOT named in §1 of this manifest |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Shared | `adapt/extend/infrastructure/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI, `hugr_auth/` |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation; LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'`; `glue` = `grep -c '_GLUE\|_TEMPLATE\|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `add_canary_tokens` | 759 | ≤ 280 (-63%) | 6 | 26 | 0 | 3.5 h | `opus` |
| `add_chaos_testing` | 643 | ≤ 260 (-60%) | 4 | 26 | 0 | 3.0 h | `opus` |
| `add_compliance_engine` | 1150 | ≤ 290 (-75%) | 7 | 30 | 14 | 5.0 h | `opus` |
| `add_cors_config` | 406 | ≤ 180 (-56%) | 3 | 21 | 0 | 2.0 h | `opus` |
| `add_csrf_protection` | 613 | ≤ 260 (-58%) | 4 | 26 | 0 | 3.0 h | `opus` |
| `add_dlp_shield` | 612 | ≤ 260 (-58%) | 4 | 20 | 0 | 3.0 h | `opus` |
| `add_input_sanitization` | 572 | ≤ 240 (-58%) | 4 | 26 | 0 | 2.5 h | `opus` |
| `add_request_fingerprint` | 576 | ≤ 240 (-58%) | 4 | 24 | 0 | 2.5 h | `opus` |
| `add_secret_rotation` | 738 | ≤ 280 (-62%) | 3 | 16 | 6 | 3.5 h | `opus` |
| **TOTAL** | **6069** | **~2290 (-62%)** | **39** | **215** | **20** | **~28 h** | `opus` |

**Model recommendation: `opus`.** Security primitives have a different risk profile from the other WAVE-1 batches: an honesty-rule violation in a `warnings` string can ship as a security overclaim and erode user trust; a silent byte-level drift in a CSP or CORS allowlist can downgrade an emitted app's posture. `opus` reasoning is required for the per-tool diff review (§11) and for the honesty-rule audit (§4).

## 9. Failure modes (≥6 anticipated traps)

1. **F-01. Embedded f-string interpolation lost in template move.**
   - *Symptom:* emitted code refers to `${project_name}` literally instead of substituted value.
   - *Cause:* triple-quoted block used Python f-strings; renderer uses a different placeholder syntax.
   - *STOP-and-report rule:* before extraction, dump source's interpolation style; mismatch with F1 golden = stop and report.

2. **F-02. `MCP_TOOL` metadata lost in module split.**
   - *Symptom:* `engine.audit.contract_check` drops from 37/37 → 36/37.
   - *Cause:* `MCP_TOOL = {...}` constant not copied into new `__init__.py`.
   - *STOP-and-report rule:* per-tool sanity import check; fail = stop and report.

3. **F-03. Idempotency regression — second run rewrites files.**
   - *Symptom:* `test_add_<tool>.py` fails on the second-run idempotency case.
   - *Cause:* `discover()` skip-set lost when routing through `adapt/_base/discover.py`.
   - *STOP-and-report rule:* missing skip-set entry = stop and report; do NOT re-inline discovery.

4. **F-04. Honesty-rule violation — overclaiming security guarantees.**
   - *Symptom:* migrated `warnings` claim "CSP enforced" or "DLP redacts all PII" when emitted code only sets a sample policy.
   - *Cause:* author copy-pasted optimistic `warnings` from source without re-reading the emitted templates.
   - *STOP-and-report rule:* per tool, read every emitted template, then read the `warnings`. Any unenforced claim = **stop and report, do NOT ship**. Fix the `warnings` to honest in this WP (behavior change is out of scope per §3).

5. **F-05. Regex catalog drift in `add_dlp_shield` / `add_input_sanitization`.**
   - *Symptom:* a regex pattern's character class changes during template extraction (e.g. `[\w\-]` → `[\w-]`), causing the emitted-project test to flag false negatives.
   - *Cause:* triple-quoted regex tables include escape sequences that the template engine re-escapes.
   - *STOP-and-report rule:* raw-string preservation is mandatory. If the renderer cannot pass through raw strings unchanged, **stop and report** — joint amendment with WP-F1.

6. **F-06. Emitted-test missing or trivially-true (per P1 #15).**
   - *Symptom:* emitted test asserts only `True`, OR asserts a fictitious block (e.g. asserts CORS rejects an origin when the migrated tool emits a permissive policy).
   - *Cause:* skeleton copied without honesty-adapted assertions.
   - *STOP-and-report rule:* every emitted test MUST cover ≥1 positive (control fires per actual emitted config) + ≥1 negative (allowed traffic passes). Mismatch with emitted policy = stop and report.

7. **F-07. `add_compliance_engine` 14 `_GLUE` constants form a graph, not a list.**
   - *Symptom:* extracting one `_GLUE` to a template breaks another that depended on it.
   - *Cause:* the compliance engine assembles emitted code from interdependent fragments (policy DSL + evaluator + middleware glue).
   - *STOP-and-report rule:* before extraction, draw the dependency graph between the 14 `_GLUE` constants. If extraction would require inlining them back, **stop and report** — a `_base` fragment-composition helper may be needed (joint amendment with WP-F1).

8. **F-08. `add_secret_rotation` writes to environment / startup hooks.**
   - *Symptom:* boot smoke succeeds locally but fails in CI because a secret rotation hook fires at import time.
   - *Cause:* the flat `.py` had a top-level side-effect (eager key derivation, registry registration).
   - *STOP-and-report rule:* zero top-level side-effects in `__init__.py`. If migration cannot avoid one, **stop and report**.

9. **F-09. Hidden behavior leak via `__init__.py` side-effects.**
   - *Symptom:* boot smoke fails — import raises.
   - *Cause:* the flat `.py` ran top-level code that the new layout no longer triggers.
   - *STOP-and-report rule:* never paper over with try/except; **stop and report**.

10. **F-10. Hard-cap LOC breach (`__init__.py` > 500).**
    - *Symptom:* size invariant fails for `add_compliance_engine` (1150 LOC source, 14 `_GLUE` consts).
    - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
    - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC of logic without inlining `_base/`, **stop and report**.

11. **F-11. §11 byte-equivalence diff gate fails for non-cosmetic reason.**
    - *Symptom:* diff shows a logic change (re-ordered regex, dropped header, altered allowlist), not whitespace/comment drift.
    - *Cause:* extraction lost or re-ordered emitted content.
    - *STOP-and-report rule:* never normalize the diff away. **Stop and report** with the diff verbatim.

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** All 9 tool directories created under `adapt/extend/infrastructure/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 9 legacy flat `.py` files removed (`git diff --name-only` shows 9 deletions).
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c 'textwrap.dedent' add_<tool>/__init__.py` → 0 for all 9).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not).
- [ ] **D-06.** All 9 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive (control fires per actual emitted config) + ≥1 negative assertion. Honesty-adapted per F-06.
- [ ] **D-07.** §6 gate 1 (ruff) green for all 9 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 9 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke `tests/test_boot.py | grep`) returns a PASS line per tool name.
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 37/37.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface (no forbidden surface touched).
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`).
- [ ] **D-14.** §11 byte-equivalence diff gate PASS for all 9 tools, diff output pasted in PR.
- [ ] **D-15.** Honesty-rule audit per tool: every `warnings` string re-read against actually emitted templates; overclaims fixed to honest.
- [ ] **D-16.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

## 11. Risk callout (WP-03-specific — security primitives blast radius)

**Why this section exists:** WP-01 and WP-02 are mechanical refactors against a well-understood pattern. WP-03 sits on top of code that ships security guarantees. A subtle drift in any of these 9 tools can ship as:

- A weakened CORS allowlist that lets a cross-origin attack succeed.
- A CSRF token validator that no longer checks the cookie/header pair.
- A DLP regex that misses a class of PII it previously redacted.
- A canary token that no longer records hits.
- A compliance audit log that drops events under load.
- An input sanitizer that re-encodes a payload into a still-malicious form.
- A rotated secret that is never re-read by the running process.
- A request fingerprint that collides for distinct clients (abuse-detection false negative).

**Mitigation: per-tool byte-equivalence diff gate.** Before declaring any tool migrated, the agent MUST:

```bash
# For each of the 9 tools:
# 1. Compose the tool against a fixed test project on main (pre-migration) → capture emitted files.
PY=.venv/bin/python
git checkout main -- skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_<tool>.py
$PY -m engine.compose --tool add_<tool> --project /tmp/pre/<tool>
# 2. Compose the migrated tool against the same fixed test project.
git checkout HEAD -- skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_<tool>
$PY -m engine.compose --tool add_<tool> --project /tmp/post/<tool>
# 3. Diff. Allowed drift: comment/whitespace only. Anything else = STOP and report.
diff -ruN /tmp/pre/<tool> /tmp/post/<tool> | grep -vE '^[+-]\s*(#|$)' | tee /tmp/diff_<tool>.txt
test ! -s /tmp/diff_<tool>.txt   # PASS = empty after comment/whitespace strip
```

Paste each tool's diff-gate result in §7. If the diff-gate is non-empty for non-cosmetic reasons, **stop and report — do NOT ship**.

**Model elevation rationale:** `opus` reasoning is required to read the diff and judge "cosmetic" vs "behavioral" drift, especially for the regex-heavy tools (`add_dlp_shield`, `add_input_sanitization`) and the multi-fragment `add_compliance_engine`. Running this gate on `sonnet` risks false-negative diff judgements.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
