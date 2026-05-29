# Work Package Contract — `WP-06-payments-notif-ml`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-06-specific content fills each section.
> Theme: **revenue-critical payments, notification fan-out, ML serving** —
> 8 cohesive tools from `adapt/extend/infrastructure/`.
>
> **Model elevation:** WP-06 runs on `opus`, not `sonnet`, because Stripe +
> ML serving primitives carry the highest behavior-change blast radius in
> the WAVE 1 batch. See §11 for the byte-equivalence diff-gate mandated
> per tool (Stripe-critical) and the ML-serving safety rules.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-06-payments-notif-ml` |
| **Title** | Migrate 8 payments / notifications / ML-serving tools to per-tool directory + externalized templates |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (PR #24, merged) · `WP-F1-base-and-golden` (PR #28, merged — `adapt/_base/` + golden `add_cursor_pagination/`) |
| **Blocks** | none (sibling WPs are file-disjoint) |
| **Branch** | `wp/06-payments-notif-ml` (off main; main carries WP-F0 + WP-F1) |
| **Isolation** | dedicated git worktree |
| **Model** | `opus` — Stripe + ML serving primitives carry the highest behavior-change blast radius; webhook-signature handling and weight-loading safety are subtle; byte-equivalence diff gate applies (§11) |

> **Phase 4 split note (2026-05-29).** WP-06 estimates ~38 h / 9 066 LOC across 8 tools — too heavy for a single agent session per the SOTA v2.1 STOP-and-report doctrine. Execute as **3 sub-WPs**, each shipping as its own PR with full §10 paste-proof:
> - **WP-06a stripe (3 tools)** — Stripe-touching primitives only. Highest webhook-signature blast radius; isolated to keep the §11 diff reviewable.
> - **WP-06b ml-serving (3 tools)** — ML weight-loading safety (`add_ml_model_registry`, `add_ml_serving`, `add_ml_drift_detector` or equivalents). Held to the §11 mitigation 2 (lazy SDK imports) hard.
> - **WP-06c notifications (2 tools)** — remaining notification primitives.
> Each sub-WP picks a slice of the §1 owned files below + carries the full §11 byte-equivalence diff for its 2-3 tools. The §4 invariants and §6 mandatory gates apply per sub-WP. Sub-WP ids: `WP-06a`, `WP-06b`, `WP-06c`. Branches: `wp/06a-stripe`, `wp/06b-ml-serving`, `wp/06c-notifications`. Re-use the existing manifest; only the file-list in §1 narrows.

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_notifications/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_push_notifications_native/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_stripe_checkout/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_stripe_refund_flow/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_stripe_subscription/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_ml_gpu_inference/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_ml_model_registry/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_ml_model_server/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_notifications.py              [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_push_notifications_native.py  [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_stripe_checkout.py            [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_stripe_refund_flow.py         [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_stripe_subscription.py        [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_ml_gpu_inference.py           [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_ml_model_registry.py          [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_ml_model_server.py            [DELETE]
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
- **WP-05 (Storage/Deployment) tools** — the 9 tools listed in §1 of `docs/wp/WP-05-storage-deployment.md`.
- **WP-07..17 (sibling Wave-1 tools)** — `crud_data`, `auth_access` (×2), `realtime`, `testing_tools`, `api_design`, `evolve`, `verify`, `hexagon-ports`, `engine-split`. Out of scope.
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here. (`core/venous/billing/`, `core/venous/events/`, `core/venous/llm/` host the registered primitives some of these tools wire into — read but never write.)
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope.
- `adapt/extend/infrastructure/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report**.
- `hugr_auth/` — license/auth gate is a separate service; touching it is an instant reject.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 8 payments / notifications / ML-serving tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl`, route their `discover/patch` through `adapt/_base/`, AND pass the §11 byte-equivalence diff gate per Stripe tool plus the §11 ML-serving safety checks per ML tool.
- **Before:** Each tool is a single `add_<tool>.py` carrying embedded code-as-strings: Stripe checkout/refund/subscription wiring (webhook signature verification, idempotency, retry semantics), push-notification platform glue (APNs/FCM), notification fan-out with channel routing, and ML serving boilerplate (model registry, weight loading, GPU inference paths). `add_stripe_checkout.py` is the heaviest at 1416 LOC; the three ML tools share a multi-fragment glue graph. Per-tool LOC measurements (raw, end of §8) range 773–1416.
- **After:**
  - Each tool becomes `add_<tool>/__init__.py` + `templates/*.py.tmpl`.
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*.py.tmpl`. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.extend.infrastructure.add_<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.
  - **Honesty-rule audit per tool:** any `warnings` string MUST honestly describe what the migrated code enforces. Carry-over of overclaiming from the source is an instant reject (payments overclaiming = financial-grade audit failure; ML overclaiming = silent correctness failure).
  - **§11 byte-equivalence diff gate** must pass for each of the 3 Stripe tools. **§11 ML-serving safety checks** must pass for each of the 3 ML tools.

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `add_notifications` | `add_notifications/{__init__.py, templates/}` | ≤ 290 | ≥ 9 (9 `dedent`, 38 triple-quote anchors) | `test_add_notifications_emitted.py` |
| `add_push_notifications_native` | `add_push_notifications_native/{__init__.py, templates/}` | ≤ 290 | ≥ 10 (10 `dedent`, 36 triple-quote anchors) | `test_add_push_notifications_native_emitted.py` |
| `add_stripe_checkout` | `add_stripe_checkout/{__init__.py, templates/}` | ≤ 290 | ≥ 6 (6 `dedent` + 12 `_GLUE` consts) | `test_add_stripe_checkout_emitted.py` |
| `add_stripe_refund_flow` | `add_stripe_refund_flow/{__init__.py, templates/}` | ≤ 290 | ≥ 7 (7 `dedent` + 12 `_GLUE` consts) | `test_add_stripe_refund_flow_emitted.py` |
| `add_stripe_subscription` | `add_stripe_subscription/{__init__.py, templates/}` | ≤ 290 | ≥ 6 (6 `dedent` + 12 `_GLUE` consts) | `test_add_stripe_subscription_emitted.py` |
| `add_ml_gpu_inference` | `add_ml_gpu_inference/{__init__.py, templates/}` | ≤ 280 | ≥ 5 (5 `dedent`, 31 triple-quote anchors) | `test_add_ml_gpu_inference_emitted.py` |
| `add_ml_model_registry` | `add_ml_model_registry/{__init__.py, templates/}` | ≤ 290 | ≥ 6 (6 `dedent` + 12 `_GLUE` consts) | `test_add_ml_model_registry_emitted.py` |
| `add_ml_model_server` | `add_ml_model_server/{__init__.py, templates/}` | ≤ 290 | ≥ 6 (6 `dedent`, 28 triple-quote anchors) | `test_add_ml_model_server_emitted.py` |

- **Out of scope:** behavior changes, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope. **Specifically:** the agent MUST NOT "improve" Stripe code (e.g. tighten webhook tolerance window, switch from synchronous to async webhook handling, change idempotency key derivation), MUST NOT "improve" ML weight-loading paths (e.g. add safetensors-only enforcement, change device-placement defaults), MUST NOT "improve" notification fan-out (e.g. add retry budget, change ordering guarantees). Those are separate WPs.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Same `ToolInput` → same `ToolResult` shape; same files emitted, byte-equivalent per §11 diff gate. Proven by GATE 1 + §11 diff.
- [ ] **Import paths stable.** `from adapt.extend.infrastructure.add_<tool> import add_<tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep`.
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused `_GLUE`/`_TEMPLATE` constants left dangling.
- [ ] **Docstrings honest.** Payments/ML-specific: a Stripe tool that does NOT verify webhook signatures MUST lead its `warnings` with `⚠ WEBHOOK SIGNATURE VERIFICATION IS NOT ENFORCED`; a Stripe tool that retries on 5xx without idempotency keys MUST say so; an ML model server that loads pickled weights (vs safetensors) MUST disclose the deserialization-RCE risk; an ML model server that does not enforce a GPU memory cap MUST say so; a notification tool that fan-outs best-effort (no per-channel retry budget) MUST disclose drop semantics; a push-notification tool that does not refresh tokens on `Unregistered` MUST disclose silent-drop semantics.
- [ ] **No new dependencies.** No `pyproject.toml` change. Provider deps (stripe SDK, apns2/fcm, torch/vllm/triton) are emitted into the generated project's `requirements.txt`, not into the kit.
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool.
- [ ] **§11 byte-equivalence diff gate passes for all 3 Stripe tools.**
- [ ] **§11 ML-serving safety checks pass for all 3 ML tools.**

## 5. Test emission (per P1 #15)
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy that format verbatim** (location: `{project}/tests/test_<tool>_emitted.py`).

For each of the 8 tools in §1, the migrated `__init__.py` MUST:
- Render an emitted test from `templates/test_<tool>_emitted.py.tmpl`.
- Place it at `{project_dir}/tests/test_<tool>_emitted.py`.
- Make it green under the emitted project's `pytest tests/` after compose.
- Cover at least one positive (added behavior fires) and one negative (boundary or off-path) assertion. Same skeleton as F1 golden.
- **Payments-specific assertions:** Stripe emitted tests MUST assert (a) a valid webhook signature is accepted, (b) an invalid/missing signature is rejected with the correct status code, (c) the idempotency key short-circuits a duplicate replay. The negative test MUST exercise (b) or (c).
- **ML-specific assertions:** ML emitted tests MUST assert (a) a valid model id loads + predicts on a fixed input, (b) an unknown model id returns the correct error, (c) [for `add_ml_gpu_inference`/`add_ml_model_server`] that GPU absence does not crash boot (CPU fallback or honest failure).
- **Notification-specific assertions:** `add_notifications` MUST assert at least one channel adapter is exercised and (negative) at least one missing-channel returns the correct error; `add_push_notifications_native` MUST assert a device-token registration round-trip and (negative) a stale/`Unregistered` token is handled without crashing.
- **Honesty rule:** if the tool's behavior is advisory-only (e.g. fan-out is best-effort), the emitted test MUST assert the advisory signal (log line / metric / queued payload), NOT a fictitious guaranteed delivery.

Failure to emit a test, OR an emitted test that asserts a guarantee the tool does not deliver, = WP rejected. Non-negotiable per P1 #15 + honesty rules.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/extend/infrastructure/add_{notifications,push_notifications_native,stripe_checkout,stripe_refund_flow,stripe_subscription,ml_gpu_inference,ml_model_registry,ml_model_server}
$PY -m ruff format --check adapt/extend/infrastructure/add_{notifications,push_notifications_native,stripe_checkout,stripe_refund_flow,stripe_subscription,ml_gpu_inference,ml_model_registry,ml_model_server}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/extend/infrastructure/test_add_{notifications,push_notifications_native,stripe_checkout,stripe_refund_flow,stripe_subscription,ml_gpu_inference,ml_model_registry,ml_model_server}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'add_notifications|add_push_notifications_native|add_stripe_checkout|add_stripe_refund_flow|add_stripe_subscription|add_ml_gpu_inference|add_ml_model_registry|add_ml_model_server'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (40/40)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7. Additionally, §11 byte-equivalence diff must be PASS per Stripe tool AND §11 ML-serving safety checks must be PASS per ML tool.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-06 owns (write surface):** the 8 directories under `adapt/extend/infrastructure/add_<tool>/` listed in §1, plus the 8 legacy `.py` file deletions listed in §1.

**WP-06 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-01 Resiliency | the 9 tools listed in §1 of `docs/wp/WP-01-resiliency-defense.md` |
| WP-02 Observability | the 9 tools listed in §1 of `docs/wp/WP-02-observability-diagnostics.md` |
| WP-03 Security | the 9 tools listed in §1 of `docs/wp/WP-03-security-compliance.md` |
| WP-04 Async/Workflow | the 9 tools listed in §1 of `docs/wp/WP-04-async-workflow.md` |
| WP-05 Storage/Deployment | the 9 tools listed in §1 of `docs/wp/WP-05-storage-deployment.md` |
| WP-07..17 | all infrastructure/crud_data/auth_access/realtime/testing_tools/api_design/evolve/verify tools NOT named in §1 of this manifest |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Shared | `adapt/extend/infrastructure/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI, `hugr_auth/` |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation; LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'`; `glue` = `grep -cE '_GLUE|_TEMPLATE|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `add_notifications` | 1003 | ≤ 290 (-71%) | 9 | 38 | 0 | 4.0 h | `opus` |
| `add_push_notifications_native` | 1046 | ≤ 290 (-72%) | 10 | 36 | 0 | 4.5 h | `opus` |
| `add_stripe_checkout` | 1416 | ≤ 290 (-80%) | 6 | 44 | 12 | 6.0 h | `opus` |
| `add_stripe_refund_flow` | 1139 | ≤ 290 (-75%) | 7 | 40 | 12 | 5.0 h | `opus` |
| `add_stripe_subscription` | 1283 | ≤ 290 (-77%) | 6 | 40 | 12 | 5.5 h | `opus` |
| `add_ml_gpu_inference` | 773 | ≤ 280 (-64%) | 5 | 31 | 0 | 3.5 h | `opus` |
| `add_ml_model_registry` | 1222 | ≤ 290 (-76%) | 6 | 29 | 12 | 5.0 h | `opus` |
| `add_ml_model_server` | 1184 | ≤ 290 (-76%) | 6 | 28 | 0 | 5.0 h | `opus` |
| **TOTAL** | **9066** | **~2310 (-75%)** | **55** | **286** | **48** | **~38 h** | `opus` |

**Model recommendation: `opus`.** Payments + ML serving have a different risk profile from the other WAVE-1 batches:
- A subtle drift in a Stripe webhook handler can drop signature verification, silently double-charge customers via lost idempotency, or invert a refund decision; financial-grade reviewers will reject any byte-level drift that is not provably cosmetic.
- An ML model server that loads weights with `torch.load(weights_only=False)` (pickle) instead of safetensors silently ships an RCE; an ML model registry that mis-routes by name can serve the wrong model to all traffic.
- A notification fan-out that drops the `Retry-After` header or mis-routes a channel adapter can ship as an availability incident.

`opus` reasoning is required for the per-tool diff review (§11) and for the honesty-rule audit (§4). Running this gate on `sonnet` risks false-negative diff judgements and is rejected.

## 9. Failure modes (≥6 anticipated traps)

1. **F-01. Embedded f-string interpolation lost in template move.**
   - *Symptom:* emitted code refers to `${project_name}` literally instead of substituted value.
   - *Cause:* triple-quoted block used Python f-strings; renderer uses a different placeholder syntax.
   - *STOP-and-report rule:* before extraction, dump source's interpolation style; mismatch with F1 golden = stop and report.

2. **F-02. `MCP_TOOL` metadata lost in module split.**
   - *Symptom:* `engine.audit.contract_check` drops from 40/40 → 36/37.
   - *Cause:* `MCP_TOOL = {...}` constant not copied into new `__init__.py`.
   - *STOP-and-report rule:* per-tool sanity import check; fail = stop and report.

3. **F-03. Idempotency regression — second run rewrites files.**
   - *Symptom:* `test_add_<tool>.py` fails on the second-run idempotency case.
   - *Cause:* `discover()` skip-set lost when routing through `adapt/_base/discover.py`.
   - *STOP-and-report rule:* missing skip-set entry = stop and report; do NOT re-inline discovery.

4. **F-04. Stripe webhook signature drift.**
   - *Symptom:* emitted webhook handler skips signature verification, or uses a different tolerance window, or short-circuits on header-presence-only.
   - *Cause:* triple-quoted block in source contained the signature-verification call site; template extraction split the import from the call, or dropped the `stripe.Webhook.construct_event(...)` line during a multi-fragment extract.
   - *STOP-and-report rule:* per Stripe tool, the §11 byte-equivalence diff MUST be empty after comment/whitespace strip on the webhook-handler emitted file. Any drift on lines containing `construct_event`, `signing_secret`, `idempotency_key`, or `tolerance=` = **stop and report, do NOT ship**.

5. **F-05. Stripe idempotency-key derivation drift.**
   - *Symptom:* duplicate webhook replays create duplicate charges/refunds/subscriptions; emitted test catches it only if it exercises replay.
   - *Cause:* migration extracted idempotency-key derivation into a template fragment but lost the salt / event-id seeding.
   - *STOP-and-report rule:* §11 diff PLUS emitted test MUST cover an explicit replay-of-same-event assertion. Mismatch = stop and report.

6. **F-06. Honesty-rule violation — overclaiming payments / ML guarantees.**
   - *Symptom:* migrated `warnings` claim "PCI-compliant" / "exactly-once webhook processing" / "GPU memory bounded" / "model weights cryptographically verified" when emitted code wires none of those.
   - *Cause:* author copy-pasted optimistic `warnings` from source without re-reading the emitted templates.
   - *STOP-and-report rule:* per tool, read every emitted template, then read the `warnings`. Any unenforced claim = **stop and report, do NOT ship**. Fix the `warnings` to honest in this WP (behavior change is out of scope per §3).

7. **F-07. ML weight-loading deserialization-RCE silent regression.**
   - *Symptom:* `add_ml_model_server` / `add_ml_model_registry` ship code with `torch.load(path)` (default `weights_only=False`, accepts arbitrary pickle), which is RCE-equivalent on attacker-controlled weights.
   - *Cause:* source carried the unsafe default; carry-over without honesty-rule warning ships the foot-gun.
   - *STOP-and-report rule:* if the emitted ML code uses unsafe deserialization (raw pickle, `torch.load` without `weights_only=True`, `joblib.load` from untrusted paths), the `warnings` MUST lead with `⚠ MODEL LOADING IS RCE-EQUIVALENT WITH UNTRUSTED WEIGHTS — pin a trusted registry`. Missing warning = **stop and report**, do NOT ship.

8. **F-08. Stripe / ML `_GLUE` constants form a graph, not a list.**
   - *Symptom:* extracting one `_GLUE` to a template breaks another (e.g. Stripe `_GLUE_CHECKOUT_SESSION` depends on `_GLUE_CUSTOMER_LOOKUP`; ML `_GLUE_REGISTRY_CLIENT` depends on `_GLUE_VERSION_RESOLVER`).
   - *Cause:* the source assembles emitted code from interdependent fragments (Stripe: customer lookup → session → confirmation → webhook; ML: registry client → version resolver → loader → server).
   - *STOP-and-report rule:* before extraction, draw the dependency graph between each tool's `_GLUE` constants. If extraction would require inlining them back, **stop and report** — a `_base` fragment-composition helper may be needed (joint amendment with WP-F1).

9. **F-09. Hidden behavior leak via `__init__.py` side-effects.**
   - *Symptom:* boot smoke fails — `import adapt.extend.infrastructure.add_<tool>` raises (e.g. Stripe SDK config at module load, GPU CUDA init at import, APNs/FCM credential read at boot).
   - *Cause:* the flat `.py` ran top-level code that the new `__init__.py` no longer triggers.
   - *STOP-and-report rule:* zero top-level side-effects in `__init__.py`. If migration cannot avoid one (e.g. CUDA device probe), **stop and report**.

10. **F-10. Hard-cap LOC breach (`__init__.py` > 500).**
    - *Symptom:* size invariant fails for `add_stripe_checkout` (1416 LOC source), `add_stripe_subscription` (1283 LOC source), or `add_ml_model_registry` (1222 LOC source).
    - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
    - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC of logic without inlining `_base/`, **stop and report**.

11. **F-11. §11 byte-equivalence diff gate fails for non-cosmetic reason.**
    - *Symptom:* diff shows a logic change (re-ordered Stripe API params, dropped header, altered idempotency-key derivation, altered ML weight-loading path), not whitespace/comment drift.
    - *Cause:* extraction lost or re-ordered emitted content.
    - *STOP-and-report rule:* never normalize the diff away. **Stop and report** with the diff verbatim.

12. **F-12. Notification fan-out ordering / channel mis-route.**
    - *Symptom:* `add_notifications` emits a channel adapter list re-ordered (e.g. SMS-first instead of in-app-first), or `add_push_notifications_native` routes APNs payloads to FCM (or vice-versa) after migration.
    - *Cause:* `_GLUE_CHANNEL_REGISTRY` was extracted to a template but the iteration order was not preserved (`set` vs `list`).
    - *STOP-and-report rule:* notification channel order MUST be deterministic and match source byte-for-byte after compose. Any drift = stop and report.

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** All 8 tool directories created under `adapt/extend/infrastructure/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 8 legacy flat `.py` files removed (`git diff --name-only` shows 8 deletions).
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c 'textwrap.dedent' add_<tool>/__init__.py` → 0 for all 8).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not).
- [ ] **D-06.** All 8 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive (Stripe/ML/notification control fires per actual emitted config) + ≥1 negative assertion. Honesty-adapted per F-06.
- [ ] **D-07.** §6 gate 1 (ruff) green for all 8 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 8 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke `tests/test_boot.py | grep`) returns a PASS line per tool name.
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 40/40.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface (no forbidden surface touched).
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`).
- [ ] **D-14.** §11 byte-equivalence diff gate PASS for all 3 Stripe tools, diff output pasted in PR.
- [ ] **D-15.** §11 ML-serving safety checks PASS for all 3 ML tools (weight-loading safety, GPU-absence boot, model-id mis-route).
- [ ] **D-16.** Honesty-rule audit per tool: every `warnings` string re-read against actually emitted templates; overclaims fixed to honest. Stripe tools MUST disclose webhook-signature + idempotency-key semantics honestly; ML tools MUST disclose weight-loading deserialization risk.
- [ ] **D-17.** Notification channel-order determinism verified (F-12 cleared).
- [ ] **D-18.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

## 11. Risk callout (WP-06-specific — payments + ML serving blast radius)

**Why this section exists:** WP-01, WP-02, WP-04, and WP-05 are mechanical refactors against a well-understood pattern. WP-03 elevated to `opus` because security primitives ship security guarantees. WP-06 elevates to `opus` for two structurally distinct reasons:

- **Payments (3 Stripe tools)** ship code that touches money. A byte-level drift on a webhook handler can drop signature verification, double-charge via lost idempotency, or invert a refund decision. Stripe API consumers expect financial-grade audit trails.
- **ML serving (3 ML tools)** ships code that loads weights — `torch.load` defaults to pickle deserialization, which is RCE-equivalent on attacker-controlled weights. A migrated ML tool that drops the safetensors path or the registry trust-pin silently downgrades the project's security posture without changing behavior on the happy path.
- **Notification fan-out (2 tools)** ships best-effort delivery semantics that are easily overclaimed. A subtle drift in channel order or per-channel retry budget can ship as a silent availability incident.

**Mitigation 1 — per-tool byte-equivalence diff gate (Stripe + ML registry).** Before declaring any of the 3 Stripe tools OR `add_ml_model_registry` migrated, the agent MUST:

```bash
# For each Stripe tool AND add_ml_model_registry:
PY=.venv/bin/python
# 1. Compose the tool against a fixed test project on main (pre-migration).
git checkout main -- skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_<tool>.py
$PY -c "from tests.common.fixture_factory import create_fixture_project; create_fixture_project("/tmp/pre/<tool>")"  # baseline scaffold; tool not yet applied
# 2. Compose the migrated tool against the same fixed test project.
git checkout HEAD -- skills/SKILL-001-fastapi-production/adapt/extend/infrastructure/add_<tool>
$PY -c "from tests.common.fixture_factory import create_fixture_project; from adapt.contracts import ToolInput; from adapt.extend.${BUCKET}.add_<tool> import add_<tool> as _t; p = create_fixture_project("/tmp/post/<tool>"); _t(ToolInput(project_dir=str(p)))"  # apply the migrated tool
# 3. Diff. Allowed drift: comment/whitespace only. Anything else = STOP and report.
diff -ruN /tmp/pre/<tool> /tmp/post/<tool> | grep -vE '^[+-]\s*(#|$)' | tee /tmp/diff_<tool>.txt
test ! -s /tmp/diff_<tool>.txt   # PASS = empty after comment/whitespace strip
```

Paste each tool's diff-gate result in §7. If the diff-gate is non-empty for non-cosmetic reasons — especially on lines containing `construct_event`, `signing_secret`, `idempotency_key`, `tolerance=`, `torch.load`, `weights_only`, `safetensors`, or `model_registry`-route — **stop and report — do NOT ship**.

**Mitigation 2 — ML-serving safety checks (3 ML tools).** Before declaring any of `add_ml_gpu_inference`, `add_ml_model_registry`, `add_ml_model_server` migrated, the agent MUST verify:

- **S1. Weight-loading safety.** Inspect every emitted-template line that loads model weights. If the source uses `torch.load(...)` without `weights_only=True` OR uses `joblib.load`/`pickle.load` on a registry-resolved path, the migrated `warnings` MUST lead with `⚠ MODEL LOADING IS RCE-EQUIVALENT WITH UNTRUSTED WEIGHTS — pin a trusted registry`. Missing warning OR silent switch to a "safer" loader = **stop and report**.
- **S2. GPU-absence boot.** Emitted code MUST boot on a CPU-only host (`add_ml_gpu_inference` / `add_ml_model_server`). Either a CPU fallback exists, or boot fails with an honest message. A silent CUDA-init crash at import = **stop and report**.
- **S3. Model-id mis-route guard.** `add_ml_model_registry` MUST resolve a model id deterministically; the emitted test MUST exercise an unknown id and assert the correct error code (404 / `ModelNotFound`), NOT a silent fallback to a default model.

**Mitigation 3 — notification channel-order determinism (2 notification tools).** Before declaring `add_notifications` / `add_push_notifications_native` migrated:

- **N1. Channel-order byte-equivalence.** §11 byte-equivalence diff scope extends to the emitted channel registry / route table. Any drift in channel iteration order = **stop and report**.
- **N2. Stale-token honesty.** `add_push_notifications_native` MUST disclose APNs/FCM `Unregistered` / `BadDeviceToken` handling honestly in `warnings`. If the emitted code does NOT refresh tokens, the warning MUST say so.

**Model elevation rationale:** `opus` reasoning is required to read the diff and judge "cosmetic" vs "behavioral" drift, especially across (a) the three Stripe tools whose 12 `_GLUE` constants each form a tight graph (F-08), (b) the ML weight-loading paths whose unsafe defaults are easy to carry over silently (F-07), and (c) the notification channel registries whose iteration order is easy to break (F-12). Running this gate on `sonnet` risks false-negative diff judgements with financial / security blast radius and is rejected.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
