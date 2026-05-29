# Work Package Contract — `WP-05-storage-deployment`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-05-specific content fills each section.
> Theme: **persistent storage, container ops, deployment artifacts, report
> rendering, transactional email** — 9 cohesive tools from `adapt/extend/infrastructure/`.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-05-storage-deployment` |
| **Title** | Migrate 9 storage/deployment tools to per-tool directory + externalized templates |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (PR #24, merged) · `WP-F1-base-and-golden` (in flight — `adapt/_base/` + golden `add_cursor_pagination/`) |
| **Blocks** | none (sibling WPs are file-disjoint) |
| **Branch** | `wp/05-storage-deployment` (off the post-dependency main, i.e. main with WP-F0 + WP-F1 merged) |
| **Isolation** | dedicated git worktree |
| **Model** | `sonnet` — mechanical refactor; heavy mixed-language (YAML / Dockerfile / HTML) template payloads — see F-09 |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_cache_layer/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_docker_production/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_kubernetes_manifests/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_s3_storage/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_excel_export/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_pdf_reports/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_sqladmin/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_email_templates/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_transactional_email/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_cache_layer.py            [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_docker_production.py      [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_kubernetes_manifests.py   [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_s3_storage.py             [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_excel_export.py           [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_pdf_reports.py            [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_sqladmin.py               [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_email_templates.py        [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_transactional_email.py    [DELETE]
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
- **WP-04 (Async/Workflow) tools** — the 9 tools listed in §1 of `docs/wp/WP-04-async-workflow.md`.
- **WP-06 (Payments/Notifications/ML) tools** — the 8 tools listed in §1 of `docs/wp/WP-06-payments-notif-ml.md`.
- **WP-07..17 (sibling Wave-1 tools)** — `crud_data`, `auth_access` (×2), `realtime`, `testing_tools`, `api_design`, `evolve`, `verify`, `hexagon-ports`, `engine-split`. Out of scope.
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here. (`core/venous/cache/`, `core/venous/data/` host the registered primitives some of these tools wire into — read but never write.)
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope.
- `adapt/extend/infrastructure/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report**.
- `deploy/` — kit deployment artefacts (separate from emitted-project Dockerfile/k8s manifests); read-only here.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 9 storage/deployment tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl` (plus mixed-language `templates/*.yaml.tmpl`, `templates/Dockerfile.tmpl`, `templates/*.html.tmpl` as needed), and route their `discover/patch` through `adapt/_base/`.
- **Before:** Each tool is a single `add_<tool>.py` carrying embedded code-as-strings: Dockerfile lines, k8s YAML manifests, S3 wiring, Excel/PDF rendering boilerplate, admin scaffolds, HTML email templates. `add_email_templates.py` is the heaviest in the WAVE-1 storage batch at 1975 LOC and 36 `_GLUE`/template consts. Per-tool LOC measurements (raw, end of §8) range 474–1975.
- **After:**
  - Each tool becomes `add_<tool>/__init__.py` + `templates/*.py.tmpl` (plus mixed-language templates per F-09 callout).
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*` files. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.extend.infrastructure.add_<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `add_cache_layer` | `add_cache_layer/{__init__.py, templates/}` | ≤ 280 | ≥ 7 (7 `dedent` + 2 `_GLUE` consts) | `test_add_cache_layer_emitted.py` |
| `add_docker_production` | `add_docker_production/{__init__.py, templates/}` | ≤ 240 | ≥ 4 (4 `dedent`, includes `Dockerfile.tmpl` + `.dockerignore.tmpl` — see F-09) | `test_add_docker_production_emitted.py` |
| `add_kubernetes_manifests` | `add_kubernetes_manifests/{__init__.py, templates/}` | ≤ 260 | ≥ 8 (8 `dedent`, multiple `*.yaml.tmpl` — see F-09) | `test_add_kubernetes_manifests_emitted.py` |
| `add_s3_storage` | `add_s3_storage/{__init__.py, templates/}` | ≤ 290 | ≥ 5 (5 `dedent` + 10 `_GLUE` consts) | `test_add_s3_storage_emitted.py` |
| `add_excel_export` | `add_excel_export/{__init__.py, templates/}` | ≤ 270 | ≥ 4 (4 `dedent` + 8 `_GLUE` consts) | `test_add_excel_export_emitted.py` |
| `add_pdf_reports` | `add_pdf_reports/{__init__.py, templates/}` | ≤ 280 | ≥ 7 (7 `dedent` + 19 `_GLUE` consts) | `test_add_pdf_reports_emitted.py` |
| `add_sqladmin` | `add_sqladmin/{__init__.py, templates/}` | ≤ 280 | ≥ 5 (5 `dedent` + 8 `_GLUE` consts) | `test_add_sqladmin_emitted.py` |
| `add_email_templates` | `add_email_templates/{__init__.py, templates/}` | ≤ 290 | ≥ 14 (14 `dedent` + 36 `_GLUE` consts — heaviest in batch — see F-10) | `test_add_email_templates_emitted.py` |
| `add_transactional_email` | `add_transactional_email/{__init__.py, templates/}` | ≤ 290 | ≥ 9 (9 `dedent`, 34 triple-quote anchors) | `test_add_transactional_email_emitted.py` |

- **Out of scope:** behavior changes, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope. **Specifically:** the agent MUST NOT "improve" k8s manifests (e.g. tighten resource limits, add `securityContext`, switch to a non-root image) or Dockerfiles (e.g. swap base image, add multi-stage build). Those are separate WPs.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Same `ToolInput` → same `ToolResult` shape; same files emitted (byte-equivalent after stripping comments/whitespace from emitted code). Proven by GATE 1.
- [ ] **Import paths stable.** `from adapt.extend.infrastructure.add_<tool> import add_<tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep -E 'textwrap\.dedent|^\s*"""' add_<tool>/__init__.py | wc -l` returning 0 for emitted-code blocks. Mixed-language templates (`Dockerfile.tmpl`, `*.yaml.tmpl`, `*.html.tmpl`) count as externalized.
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused `_GLUE`/`_TEMPLATE` constants left dangling.
- [ ] **Docstrings honest.** Storage/deployment-specific: a Dockerfile that runs as root MUST say so in `warnings`; a k8s manifest WITHOUT `securityContext`/`resources` MUST say so; `add_s3_storage` MUST disclose whether it enforces server-side encryption or merely sets a hint; `add_transactional_email` MUST disclose whether it talks to a real provider or only stages payloads.
- [ ] **No new dependencies.** No `pyproject.toml` change. Provider deps (boto3, openpyxl, reportlab/weasyprint, sqladmin, Jinja2, postmark/sendgrid/SES SDKs) are emitted into the generated project's `requirements.txt`, not into the kit.
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool.

## 5. Test emission (per P1 #15)
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy that format verbatim** (location: `{project}/tests/test_<tool>_emitted.py`).

For each of the 9 tools in §1, the migrated `__init__.py` MUST:
- Render an emitted test from `templates/test_<tool>_emitted.py.tmpl`.
- Place it at `{project_dir}/tests/test_<tool>_emitted.py`.
- Make it green under the emitted project's `pytest tests/` after compose.
- Cover at least one positive (added behavior fires: e.g. cache GET returns staged value, Dockerfile lints (`hadolint` if available, otherwise structural assertion), k8s YAML parses + Service references the right Deployment, S3 PUT round-trips a byte buffer through a mocked client, Excel export writes a valid `.xlsx`, PDF report renders a non-empty PDF, sqladmin login route returns 200 with auth + 401 without, email template renders with substituted variables, transactional email enqueues a payload to the staged provider) and one negative (boundary or off-path: e.g. cache miss returns None, Dockerfile rejects an empty COPY src, S3 GET on missing key raises 404, sqladmin no-auth returns 401, transactional email rejects missing recipient) assertion. Same skeleton as F1 golden.
- **Honesty rule:** if a tool stages-only (e.g. `add_transactional_email` against a fake transport), the emitted test MUST assert the staged payload, NOT a real network round-trip.

Failure to emit a test = WP rejected; this is non-negotiable per P1 #15.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/extend/infrastructure/add_{cache_layer,docker_production,kubernetes_manifests,s3_storage,excel_export,pdf_reports,sqladmin,email_templates,transactional_email}
$PY -m ruff format --check adapt/extend/infrastructure/add_{cache_layer,docker_production,kubernetes_manifests,s3_storage,excel_export,pdf_reports,sqladmin,email_templates,transactional_email}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/extend/infrastructure/test_add_{cache_layer,docker_production,kubernetes_manifests,s3_storage,excel_export,pdf_reports,sqladmin,email_templates,transactional_email}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'add_cache_layer|add_docker_production|add_kubernetes_manifests|add_s3_storage|add_excel_export|add_pdf_reports|add_sqladmin|add_email_templates|add_transactional_email'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (40/40)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-05 owns (write surface):** the 9 directories under `adapt/extend/infrastructure/add_<tool>/` listed in §1, plus the 9 legacy `.py` file deletions listed in §1.

**WP-05 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-01 Resiliency | the 9 tools listed in §1 of `docs/wp/WP-01-resiliency-defense.md` |
| WP-02 Observability | the 9 tools listed in §1 of `docs/wp/WP-02-observability-diagnostics.md` |
| WP-03 Security | the 9 tools listed in §1 of `docs/wp/WP-03-security-compliance.md` |
| WP-04 Async/Workflow | the 9 tools listed in §1 of `docs/wp/WP-04-async-workflow.md` |
| WP-06 Payments/Notif/ML | the 8 tools listed in §1 of `docs/wp/WP-06-payments-notif-ml.md` |
| WP-07..17 | all infrastructure/crud_data/auth_access/realtime/testing_tools/api_design/evolve/verify tools NOT named in §1 of this manifest |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Shared | `adapt/extend/infrastructure/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI, `deploy/` |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation; LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'`; `glue` = `grep -cE '_GLUE|_TEMPLATE|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `add_cache_layer` | 888 | ≤ 280 (-68%) | 7 | 42 | 2 | 3.5 h | `sonnet` |
| `add_docker_production` | 474 | ≤ 240 (-49%) | 4 | 24 | 0 | 2.0 h | `sonnet` |
| `add_kubernetes_manifests` | 503 | ≤ 260 (-48%) | 8 | 36 | 0 | 2.5 h | `sonnet` |
| `add_s3_storage` | 890 | ≤ 290 (-67%) | 5 | 36 | 10 | 3.5 h | `sonnet` |
| `add_excel_export` | 679 | ≤ 270 (-60%) | 4 | 24 | 8 | 3.0 h | `sonnet` |
| `add_pdf_reports` | 759 | ≤ 280 (-63%) | 7 | 32 | 19 | 3.5 h | `sonnet` |
| `add_sqladmin` | 811 | ≤ 280 (-65%) | 5 | 34 | 8 | 3.5 h | `sonnet` |
| `add_email_templates` | 1975 | ≤ 290 (-85%) | 14 | 58 | 36 | 6.0 h | `sonnet` |
| `add_transactional_email` | 933 | ≤ 290 (-69%) | 9 | 34 | 0 | 4.0 h | `sonnet` |
| **TOTAL** | **7912** | **~2480 (-69%)** | **63** | **320** | **83** | **~32 h** | `sonnet` |

**Model recommendation: `sonnet`.** This batch is mechanical (extract triple-quoted blobs → `.tmpl` or mixed-language template files, route discovery/patch through `_base`). It carries the highest `_GLUE`-constant count of the three Z2 WPs (83 across the batch), concentrated in `add_email_templates`, `add_pdf_reports`, and `add_s3_storage`. The transformation pattern is identical to the F1 golden tool; the only WP-05-specific risk is mixed-language template extraction (F-09). Promotion to `opus` only if the agent hits a STOP-and-report rule in §9 — particularly F-09 (YAML/Dockerfile/HTML brace collisions) or F-10 (`add_email_templates` 36-glue graph).

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
   - *Cause:* `discover()` was inlined per tool with custom skip-set; replacing with `adapt/_base/discover.py` lost a skip entry.
   - *STOP-and-report rule:* if `adapt/_base/discover.py` does not expose the tool's required skip-set, **stop and report** — do NOT re-inline discovery.

4. **F-04. Hidden behavior leak via `__init__.py` side-effects.**
   - *Symptom:* boot smoke fails — `import adapt.extend.infrastructure.add_<tool>` raises (e.g. boto3 client init at module load, Redis ping at import, sqladmin app construction eager).
   - *Cause:* the flat `.py` ran top-level code that the new `__init__.py` no longer triggers.
   - *STOP-and-report rule:* never paper over with try/except; **stop and report**.

5. **F-05. Template syntax drift — Jinja vs str.format.**
   - *Symptom:* templates render with literal `{var}` instead of values.
   - *Cause:* author used `str.format` placeholders in a `_base` Jinja renderer (or vice-versa).
   - *STOP-and-report rule:* before migration, confirm the renderer in `adapt/_base/render.py` and use **only** that syntax.

6. **F-06. Honesty-rule violation — overclaiming storage / deployment guarantees.**
   - *Symptom:* migrated `warnings` claim "k8s manifests production-ready" / "S3 SSE enforced" / "transactional email guaranteed delivery" when emitted code omits resource limits / merely sets a hint header / fires-and-forgets to a fake transport.
   - *Cause:* author copy-pasted optimistic `warnings` from source without re-reading the emitted templates.
   - *STOP-and-report rule:* per tool, read every emitted template, then read the `warnings`. Any unenforced claim = **stop and report, do NOT ship**. Fix the `warnings` to honest in this WP (behavior change is out of scope per §3).

7. **F-07. `add_email_templates` HTML body brace collisions.**
   - *Symptom:* template extraction breaks because HTML email bodies use Jinja-style `{{ var }}` literals INSIDE Python-source triple-quoted strings that the kit's renderer also interprets.
   - *Cause:* the source embeds rendered-by-the-emitted-app Jinja inside rendered-by-the-kit Jinja → double-render collision.
   - *STOP-and-report rule:* if a kit-side template needs to ship LITERAL `{{` / `}}` to the emitted project, **stop and report** — a `{% raw %}` passthrough or escape policy MUST be defined in `adapt/_base/render.py` (joint amendment with WP-F1).

8. **F-08. `_GLUE`/`_TEMPLATE` constants pruned but still imported.**
   - *Symptom:* `ruff check` flags `F821` (undefined name) or import fails at boot.
   - *Cause:* externalization removed the constant but a sibling helper still references it.
   - *STOP-and-report rule:* run `python -m ruff check add_<tool>/` after every tool; non-empty output = stop and report (do NOT auto-fix without re-reading).

9. **F-09. Mixed-language template files (`Dockerfile`, `*.yaml`, `*.html`).**
   - *Symptom:* `add_docker_production` Dockerfile lines collide with template engine syntax (e.g. `${VAR}` ENV references), or `add_kubernetes_manifests` YAML indentation breaks after substitution, or `add_email_templates` HTML brace literals double-render (see F-07).
   - *Cause:* the renderer expects `.py.tmpl` and does not have a passthrough mode for shell `${VAR}` / YAML structural sensitivity / HTML literal braces.
   - *STOP-and-report rule:* mixed-language templates MUST be named with their target extension (`Dockerfile.tmpl`, `deployment.yaml.tmpl`, `welcome_email.html.tmpl`). If the renderer in `adapt/_base/render.py` cannot pass through shell-style `${VAR}` unchanged or preserve YAML indentation byte-for-byte, **stop and report** — joint amendment with WP-F1 (raw-passthrough mode).

10. **F-10. `add_email_templates` 36 `_GLUE` constants form a graph, not a list.**
    - *Symptom:* extracting one `_GLUE` to a template breaks another that depended on it (shared header/footer fragments, theme-color constants referenced across multiple email bodies).
    - *Cause:* the email-templates tool assembles emitted email bodies from interdependent fragments (layout + header + body + footer + style block).
    - *STOP-and-report rule:* before extraction, draw the dependency graph between the 36 `_GLUE` constants. If extraction would require inlining them back, **stop and report** — a `_base` fragment-composition helper may be needed (joint amendment with WP-F1).

11. **F-11. Hard-cap LOC breach (`__init__.py` > 500).**
    - *Symptom:* size invariant fails for `add_email_templates` (1975 LOC source) or `add_transactional_email` (933 LOC source).
    - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
    - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC of logic without inlining `_base/`, **stop and report**.

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** All 9 tool directories created under `adapt/extend/infrastructure/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 9 legacy flat `.py` files removed (`git diff --name-only` shows 9 deletions).
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c 'textwrap.dedent' add_<tool>/__init__.py` → 0 for all 9).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not). Mixed-language template files counted as externalized.
- [ ] **D-06.** All 9 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive + ≥1 negative assertion. Honesty-adapted per F-06.
- [ ] **D-07.** §6 gate 1 (ruff) green for all 9 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 9 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke `tests/test_boot.py | grep`) returns a PASS line per tool name.
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 40/40.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface (no forbidden surface touched).
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`).
- [ ] **D-14.** `add_docker_production` / `add_kubernetes_manifests` / `add_email_templates` mixed-language templates successfully extracted (F-07 + F-09 cleared) OR explicit stop-and-report posted.
- [ ] **D-15.** `add_email_templates` 36-`_GLUE` graph decomposition decision recorded (F-10 cleared).
- [ ] **D-16.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

---

## Appendix A — Composition notes for this batch (read-only context)

The 9 tools in WP-05 form the **storage + deployment + outbound-comms surface** of a typical emitted project:
- `add_cache_layer` provides Redis-backed read-through caching.
- `add_docker_production` + `add_kubernetes_manifests` provide the container + orchestration artefacts.
- `add_s3_storage` provides object-storage for user uploads and report archives.
- `add_excel_export` + `add_pdf_reports` provide report rendering on top of the data layer.
- `add_sqladmin` provides a generated admin UI that depends on the project's SQLAlchemy models.
- `add_email_templates` + `add_transactional_email` provide outbound email — the template tool ships layouts; the transactional tool ships the queue + provider adapter.

After WP-05 merges, downstream composition tests exercise these tools as a group. A regression in any one tool surfaces in the chain test, not just the per-tool test. The `__init__.py` orchestration MUST be import-cheap (no top-level boto3 client construction, no eager Redis ping, no eager sqladmin app build) so that `tests/test_boot.py` boot-time per tool stays under its current budget.

## Appendix B — Why theme-grouping (not size-balanced batches)

WP-05 carries 9 tools that share a **persistence + ops + outbound-comms mental model**: storage (cache + S3), container ops (Docker + k8s), report rendering (Excel + PDF + admin), and email (templates + transactional). An agent reading the manifest gets the same conceptual frame for every tool in the batch, which reduces cross-tool reasoning cost. Size-balanced batches would have mixed storage with payments or async, forcing the executor to switch contexts between every tool. The trade-off (uneven LOC across WP-04/05/06) is accepted for cohesion gains. See sibling WPs for the Async and Payments-Notif-ML themed partitions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
