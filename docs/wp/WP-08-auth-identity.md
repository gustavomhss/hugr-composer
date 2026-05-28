# Work Package Contract — `WP-08-auth-identity`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-08-specific content fills each section.
> Theme: **caller-side credential primitives — what the client presents** —
> 8 cohesive tools from `adapt/extend/auth_access/`. Identity tools establish
> *who* a request claims to be; policy tools (WP-09) decide *what* that identity
> may do. The split keeps the credential surface (this WP) disjoint from the
> authorization surface (WP-09).
>
> **Model elevation:** WP-08 runs on `opus`, not `sonnet`, because identity
> primitives carry the highest credential-leak blast radius in WAVE 1. A subtle
> drift in token verification (DPoP nonce binding, passkey assertion check,
> OAuth2 PKCE code verifier validation, request-signing canonicalization, MFA
> step-up window, API key constant-time compare) can ship as an authentication
> bypass. See §11 for the WP-specific risk callout and the byte-equivalence
> diff gate carried over from WP-03 §11.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-08-auth-identity` |
| **Title** | Migrate 8 auth identity / credential tools to per-tool directory + externalized templates |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (PR #24, merged) · `WP-F1-base-and-golden` (golden `add_cursor_pagination/` already on main via PR #28) |
| **Blocks** | none (sibling WPs are file-disjoint) |
| **Branch** | `wp/08-auth-identity` (off the post-dependency main) |
| **Isolation** | dedicated git worktree |
| **Model** | `opus` — credential primitives carry highest token-verification blast radius; honesty-rule checks (e.g. "passkey enforces user-verification" vs "passkey records the assertion") are subtle; byte-equivalence diff gate applies (§11) |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_api_key_auth/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_dpop_tokens/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_mfa/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_oauth2_provider/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_passkey_auth/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_request_signing/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_sms_otp/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_social_login/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_api_key_auth.py      [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_dpop_tokens.py       [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_mfa.py               [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_oauth2_provider.py   [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_passkey_auth.py      [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_request_signing.py   [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_sms_otp.py           [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_social_login.py      [DELETE]
  ```
- **Golden reference (read-only, copy the pattern):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` (already on main via PR #28; canonical F1 golden)
- **Shared base/contract to import (read-only):** `skills/SKILL-001-fastapi-production/adapt/_base/` + `skills/SKILL-001-fastapi-production/adapt/contracts/`
- **Spec to follow:** `docs/tool-contract.md`, `docs/architecture.md`
- **Staging pool (read-only reference, not a write surface):** `core/venous/_staging/` (renamed via WP-F0; see PR #24)
- **Auth primitives (read-only context):** `core/venous/auth/` — registered identity primitives some of these tools wire into.

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-01/02/03 (infrastructure WAVE 1) tools** — all 27 tools owned by the three sibling infrastructure manifests.
- **WP-04/05/06 (sibling Z2) tools** — the 26 remaining `adapt/extend/infrastructure/add_*` tools.
- **WP-07 (CRUD data) tools** — `add_audit_log`, `add_bulk_operations`, `add_data_export`, `add_data_import`, `add_data_versioning`, `add_event_sourcing`, `add_file_upload`, `add_search`, `add_soft_delete` (plus the read-only `add_cursor_pagination` golden).
- **WP-09 (Auth policy) tools** — `add_bola_guard`, `add_cedar_policies`, `add_feature_flags`, `add_feature_toggles_api`, `add_multi_tenancy`, `add_opa_integration`, `add_rbac`. These are the *authorization* surface — disjoint from this WP's *credential* surface.
- **WP-D/E/F sibling agents** — tools under `realtime/`, `testing_tools/`, `api_design/`, evolve/verify/hex/engine-split surfaces.
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here.
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope.
- `adapt/extend/auth_access/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report**.
- `hugr_auth/` — HuGR license/auth gate is a separate service; touching it is an instant reject. (Note: `hugr_auth/` is the HuGR product's own MCP-level auth; this WP migrates *emitted-app* credential tools, never the kit's own gate.)

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 8 auth identity / credential tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl`, route their `discover/patch` through `adapt/_base/`, AND pass the §11 byte-equivalence diff gate per tool (carried over from WP-03 §11 because credential primitives share the same blast-radius profile as security primitives).
- **Before:** Each tool is a single `add_<tool>.py` carrying embedded code-as-strings (API-key middleware + storage, DPoP nonce + proof verification, MFA TOTP setup + verification, OAuth2 authorization-code + PKCE flow, passkey WebAuthn registration + assertion, request-signing canonicalization + HMAC, SMS OTP send + verify, social-login providers + state CSRF). Per-tool LOC measurements (raw, end of §8) range 161–1378.
- **After:**
  - Each tool becomes `add_<tool>/__init__.py` + `templates/*.py.tmpl`.
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*.py.tmpl`. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.extend.auth_access.add_<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.
  - **Honesty-rule audit per tool:** any `warnings` string MUST honestly describe what the migrated code enforces. Carry-over of overclaiming from the source is an instant reject (credential overclaiming = security failure that ships as silent bypass).
  - **§11 byte-equivalence diff gate** must pass for each tool.

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `add_api_key_auth` | `add_api_key_auth/{__init__.py, templates/}` | ≤ 290 | ≥ 9 (9 `dedent`, 47 triple-quote anchors) | `test_add_api_key_auth_emitted.py` |
| `add_dpop_tokens` | `add_dpop_tokens/{__init__.py, templates/}` | ≤ 280 | ≥ 6 (3 `dedent` + 6 `_GLUE` consts) | `test_add_dpop_tokens_emitted.py` |
| `add_mfa` | `add_mfa/{__init__.py, templates/}` | ≤ 200 | ≥ 2 (9 triple-quote anchors → ~4 code blocks, 2 `_GLUE`) | `test_add_mfa_emitted.py` |
| `add_oauth2_provider` | `add_oauth2_provider/{__init__.py, templates/}` | ≤ 140 | ≥ 2 (5 triple-quote anchors → ~2 code blocks, 2 `_GLUE`) | `test_add_oauth2_provider_emitted.py` |
| `add_passkey_auth` | `add_passkey_auth/{__init__.py, templates/}` | ≤ 290 | ≥ 5 (5 `dedent`, 33 triple-quote anchors) | `test_add_passkey_auth_emitted.py` |
| `add_request_signing` | `add_request_signing/{__init__.py, templates/}` | ≤ 270 | ≥ 4 (4 `dedent`, 21 triple-quote anchors) | `test_add_request_signing_emitted.py` |
| `add_sms_otp` | `add_sms_otp/{__init__.py, templates/}` | ≤ 280 | ≥ 5 (5 `dedent`, 33 triple-quote anchors) | `test_add_sms_otp_emitted.py` |
| `add_social_login` | `add_social_login/{__init__.py, templates/}` | ≤ 290 | ≥ 7 (7 `dedent`, 41 triple-quote anchors) | `test_add_social_login_emitted.py` |

- **Out of scope:** behavior changes, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope. **Specifically:** the agent MUST NOT "improve" the credential posture of any emitted code (e.g. tighten the API-key entropy threshold, swap HS256 for RS256, force PKCE on a public client that currently allows implicit grant). Those are separate WPs.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Same `ToolInput` → same `ToolResult` shape; same files emitted, byte-equivalent per §11 diff gate. Proven by GATE 1 + §11 diff.
- [ ] **Import paths stable.** `from adapt.extend.auth_access.add_<tool> import add_<tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep`.
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused `_GLUE`/`_TEMPLATE` constants left dangling.
- [ ] **Docstrings honest.** Credential-specific: a tool that does NOT enforce a guarantee MUST lead its `warnings` with `⚠ … IS NOT ENFORCED`. Examples: `add_api_key_auth` warning if comparison is not constant-time; `add_dpop_tokens` warning if nonce replay window is best-effort; `add_passkey_auth` warning if user-verification flag is not asserted; `add_oauth2_provider` warning if PKCE is optional; `add_social_login` warning if state-CSRF is generated but not validated server-side; `add_request_signing` warning if canonicalization is naive (header-order sensitive); `add_sms_otp` warning if rate-limit is per-IP-not-per-phone; `add_mfa` warning if step-up window is unbounded.
- [ ] **No new dependencies.** No `pyproject.toml` change. Emitted deps go in generated `requirements.txt`.
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool.
- [ ] **§11 byte-equivalence diff gate passes per tool.**

## 5. Test emission (per P1 #15)
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy that format verbatim** (location: `{project}/tests/test_<tool>_emitted.py`). WP-07 is the canonical propagation precedent for the WAVE 1 P1 #15 rollout; WP-08 follows it.

For each of the 8 tools in §1, the migrated `__init__.py` MUST:
- Render an emitted test from `templates/test_<tool>_emitted.py.tmpl`.
- Place it at `{project_dir}/tests/test_<tool>_emitted.py`.
- Make it green under the emitted project's `pytest tests/` after compose.
- Cover at least one positive (credential primitive fires: e.g. `add_api_key_auth` rejects an invalid key in constant-time path, `add_dpop_tokens` rejects a re-used nonce, `add_mfa` accepts a valid TOTP and rejects an off-by-window code, `add_oauth2_provider` validates a PKCE verifier, `add_passkey_auth` rejects an assertion with the wrong RP-ID, `add_request_signing` rejects a tampered body, `add_sms_otp` rejects an expired OTP, `add_social_login` rejects a missing/forged state parameter) and one negative (allowed traffic / valid credential passes through unchanged) assertion. Same skeleton as F1 golden.
- **Honesty rule:** if the tool's behavior is advisory-only (e.g. `add_mfa` records step-up without forcing it on every authenticated route), the emitted test MUST assert the advisory signal (log line / metric / record), NOT a fictitious enforcement. **Credential overclaiming is an instant reject.**

Failure to emit a test, OR an emitted test that asserts a guarantee the tool does not deliver, = WP rejected. Non-negotiable per P1 #15 + honesty rules.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7. These are the 5 mandatory WAVE 1 gates established by WP-01 §6.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/extend/auth_access/add_{api_key_auth,dpop_tokens,mfa,oauth2_provider,passkey_auth,request_signing,sms_otp,social_login}
$PY -m ruff format --check adapt/extend/auth_access/add_{api_key_auth,dpop_tokens,mfa,oauth2_provider,passkey_auth,request_signing,sms_otp,social_login}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/extend/auth_access/test_add_{api_key_auth,dpop_tokens,mfa,oauth2_provider,passkey_auth,request_signing,sms_otp,social_login}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'add_api_key_auth|add_dpop_tokens|add_mfa|add_oauth2_provider|add_passkey_auth|add_request_signing|add_sms_otp|add_social_login'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (37/37)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7. Additionally, §11 byte-equivalence diff must be PASS per tool.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-08 owns (write surface):** the 8 directories under `adapt/extend/auth_access/add_<tool>/` listed in §1, plus the 8 legacy flat `.py` file deletions listed in §1.

**WP-08 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-01 Resiliency | the 9 tools in `docs/wp/WP-01-resiliency-defense.md` §1 |
| WP-02 Observability | the 9 tools in `docs/wp/WP-02-observability-diagnostics.md` §1 |
| WP-03 Security | the 9 tools in `docs/wp/WP-03-security-compliance.md` §1 |
| WP-04/05/06 Z2 | all 26 remaining `adapt/extend/infrastructure/add_*` tools |
| WP-07 CRUD data | `add_audit_log`, `add_bulk_operations`, `add_cursor_pagination` (golden), `add_data_export`, `add_data_import`, `add_data_versioning`, `add_event_sourcing`, `add_file_upload`, `add_search`, `add_soft_delete` |
| WP-09 Auth policy | `add_bola_guard`, `add_cedar_policies`, `add_feature_flags`, `add_feature_toggles_api`, `add_multi_tenancy`, `add_opa_integration`, `add_rbac` |
| WP-D/E/F | `adapt/extend/realtime/`, `adapt/extend/testing_tools/`, `adapt/extend/api_design/`, evolve/verify/hex/engine-split tools |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Shared | `adapt/extend/auth_access/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI, `hugr_auth/` |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation; LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'`; `glue` = `grep -c '_GLUE\|_TEMPLATE\|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `add_api_key_auth` | 1378 | ≤ 290 (-79%) | 9 | 47 | 0 | 5.5 h | `opus` |
| `add_dpop_tokens` | 815 | ≤ 280 (-66%) | 3 | 18 | 6 | 4.0 h | `opus` |
| `add_mfa` | 277 | ≤ 200 (-28%) | 0 | 9 | 2 | 2.0 h | `opus` |
| `add_oauth2_provider` | 161 | ≤ 140 (-13%) | 0 | 5 | 2 | 1.5 h | `opus` |
| `add_passkey_auth` | 1020 | ≤ 290 (-72%) | 5 | 33 | 0 | 5.0 h | `opus` |
| `add_request_signing` | 718 | ≤ 270 (-62%) | 4 | 21 | 0 | 3.5 h | `opus` |
| `add_sms_otp` | 773 | ≤ 280 (-64%) | 5 | 33 | 0 | 3.5 h | `opus` |
| `add_social_login` | 1176 | ≤ 290 (-75%) | 7 | 41 | 0 | 5.0 h | `opus` |
| **TOTAL** | **6318** | **~2040 (-68%)** | **33** | **207** | **10** | **~30 h** | `opus` |

**Model recommendation: `opus`.** Three forces drive elevation. (1) Credential blast radius: a silent drift in DPoP nonce binding, passkey RP-ID check, OAuth2 PKCE verifier validation, or API-key constant-time compare ships as an auth bypass that the kit's per-tool tests will not catch (they assert structure, not adversarial-grade flow). (2) Honesty-rule audit on `warnings` strings is subtle for credential primitives — many of them are advisory-by-design (e.g. step-up MFA, request signing on a subset of routes); the `warnings` MUST honestly say so. (3) §11 byte-equivalence diff reading needs `opus`-grade judgement to distinguish cosmetic drift from semantic drift in middleware ordering, header canonicalization, and token-verification branches.

## 9. Failure modes (≥6 anticipated traps)

1. **F-01. Embedded f-string interpolation lost in template move.**
   - *Symptom:* emitted code refers to `${project_name}` literally; `pytest tests/` in emitted project fails at import.
   - *Cause:* triple-quoted block used Python f-strings; renderer uses a different placeholder syntax.
   - *STOP-and-report rule:* before extraction, dump source's interpolation style; mismatch with F1 golden = stop and report.

2. **F-02. `MCP_TOOL` metadata lost in module split.**
   - *Symptom:* `engine.audit.contract_check` drops from 37/37 → 36/37.
   - *Cause:* `MCP_TOOL = {...}` not copied into the new `__init__.py`.
   - *STOP-and-report rule:* per-tool sanity import check; fail = stop and report.

3. **F-03. Idempotency regression — second run rewrites files.**
   - *Symptom:* second-run case fails; `ToolResult.status` returns `success` instead of `no_op`.
   - *Cause:* `discover()` skip-set lost when routing through `adapt/_base/discover.py`. auth tools historically skip `user`, `superuser`, `oauth`, `mfa`, `passkey`, `tenant`.
   - *STOP-and-report rule:* missing skip-set entry = stop and report; do NOT re-inline discovery.

4. **F-04. Honesty-rule violation — overclaiming credential guarantees.**
   - *Symptom:* migrated `warnings` claim "API keys are constant-time compared" when the emitted code uses `==`; or "PKCE enforced" when the emitted OAuth2 provider treats `code_challenge` as optional.
   - *Cause:* author copy-pasted optimistic `warnings` from source without re-reading emitted templates.
   - *STOP-and-report rule:* per tool, read every emitted template, then read the `warnings`. Any unenforced credential claim = **stop and report, do NOT ship**. Fix the `warnings` to honest in this WP (behavior change is out of scope per §3).

5. **F-05. DPoP nonce / replay-window drift in `add_dpop_tokens`.**
   - *Symptom:* migrated emitted code accepts a re-used nonce because the cache TTL was lost in `_GLUE` extraction, or accepts a `jti` outside the freshness window because the clock-skew tolerance moved from constant to literal.
   - *Cause:* 6 `_GLUE` consts include the nonce cache key + TTL + skew tolerance + RP issuer; extracting them as separate templates can drop a value.
   - *STOP-and-report rule:* before extraction, snapshot the 6 `_GLUE` values; post-extraction grep the emitted output for each value. Missing = stop and report.

6. **F-06. Emitted-test missing or trivially-true (per P1 #15).**
   - *Symptom:* emitted test asserts `True`, OR asserts a guarantee the tool does not deliver (e.g. `add_oauth2_provider` asserts PKCE rejection when the emitted code accepts both PKCE and plain).
   - *Cause:* skeleton copied without honesty-adapted assertions.
   - *STOP-and-report rule:* every emitted test MUST cover ≥1 positive + ≥1 negative against the actual emitted behavior. Mismatch = stop and report.

7. **F-07. `add_passkey_auth` WebAuthn challenge state lost in template move.**
   - *Symptom:* registration ceremony succeeds but assertion fails because the challenge was stored in a per-request dict that disappeared during template extraction.
   - *Cause:* the flat `.py` colocated challenge storage with the emitted route; splitting them dropped the import.
   - *STOP-and-report rule:* the emitted test MUST run a full register-then-assert round trip; failure = stop and report.

8. **F-08. `add_request_signing` canonicalization byte drift.**
   - *Symptom:* signature verification fails because header order, query-string encoding, or trailing-newline handling changed during template extraction.
   - *Cause:* canonicalization is byte-sensitive; even whitespace normalization in a template breaks it.
   - *STOP-and-report rule:* §11 byte-equivalence diff MUST be empty for the canonicalization function block; any drift = stop and report.

9. **F-09. `add_social_login` state-CSRF parameter generated but never validated.**
   - *Symptom:* emitted callback accepts any `state` value; CSRF protection is theatre.
   - *Cause:* the source already has this bug (advisory-only `state`); migration must NOT silently "improve" it (§3 out of scope) but the `warnings` MUST say `⚠ STATE PARAMETER IS NOT VALIDATED` per the honesty rule.
   - *STOP-and-report rule:* if the source's emitted callback does not validate `state`, the migrated `warnings` MUST say so; the emitted test asserts only what is enforced (NOT a fictitious CSRF block).

10. **F-10. Hard-cap LOC breach (`__init__.py` > 500).**
    - *Symptom:* size invariant fails for `add_api_key_auth` (1378 LOC source, 9 `dedent` blocks) or `add_social_login` (1176 LOC, 7 `dedent`).
    - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
    - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC without inlining `_base/`, **stop and report**.

11. **F-11. §11 byte-equivalence diff gate fails for non-cosmetic reason.**
    - *Symptom:* diff shows a logic change (re-ordered middleware, dropped header verification, altered scope check), not whitespace/comment drift.
    - *Cause:* extraction lost or re-ordered emitted content.
    - *STOP-and-report rule:* never normalize the diff away. **Stop and report** with the diff verbatim.

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** All 8 tool directories created under `adapt/extend/auth_access/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 8 legacy flat `.py` files removed (`git diff --name-only` shows 8 deletions).
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c` → 0 for all 8).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not).
- [ ] **D-06.** All 8 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive + ≥1 negative assertion. Honesty-adapted per F-06.
- [ ] **D-07.** §6 gate 1 (ruff) green for all 8 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 8 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke) returns a PASS line per tool name.
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 37/37.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface.
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`).
- [ ] **D-14.** §11 byte-equivalence diff gate PASS for all 8 tools, diff output pasted in PR.
- [ ] **D-15.** Honesty-rule audit per tool: every `warnings` string re-read against actually emitted templates; credential overclaims fixed to honest.
- [ ] **D-16.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

## 11. Risk callout (WP-08-specific — credential blast radius + §11 byte-equivalence diff gate)

**Why this section exists:** WP-07 ships data integrity; WP-08 ships authentication. Both are the highest-blast-radius batches in WAVE 1. A subtle drift in any of these 8 tools can ship as:

- An API-key compare that drops constant-time (timing oracle → brute-force).
- A DPoP nonce cache TTL that re-opens replay (proof reuse).
- An MFA step-up window that never closes (one TOTP accepted forever).
- An OAuth2 PKCE check that treats `plain` and `S256` as equivalent (auth-code interception bypass).
- A passkey assertion verifier that drops RP-ID / user-verification check (cross-origin assertion accepted).
- A request-signing canonicalization that re-orders headers (signature still verifies a tampered body).
- An SMS OTP rate-limit keyed per-IP instead of per-phone (SIM-bound brute-force).
- A social-login state parameter that is generated but never validated server-side (CSRF on the OAuth handshake).

### Mitigation: per-tool byte-equivalence diff gate (carried over from WP-03 §11)

Before declaring any tool migrated, the agent MUST:

```bash
# For each of the 8 tools:
# 1. Compose the tool against a fixed test project on main (pre-migration) → capture emitted files.
PY=.venv/bin/python
git checkout main -- skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_<tool>.py
$PY -m engine.compose --tool add_<tool> --project /tmp/pre/<tool>
# 2. Compose the migrated tool against the same fixed test project.
git checkout HEAD -- skills/SKILL-001-fastapi-production/adapt/extend/auth_access/add_<tool>
$PY -m engine.compose --tool add_<tool> --project /tmp/post/<tool>
# 3. Diff. Allowed drift: comment/whitespace only. Anything else = STOP and report.
diff -ruN /tmp/pre/<tool> /tmp/post/<tool> | grep -vE '^[+-]\s*(#|$)' | tee /tmp/diff_<tool>.txt
test ! -s /tmp/diff_<tool>.txt   # PASS = empty after comment/whitespace strip
```

Paste each tool's diff-gate result in §7. If the diff-gate is non-empty for non-cosmetic reasons, **stop and report — do NOT ship**.

### Honesty-rule audit (credential overclaims = instant reject)

For each tool, after migration, the agent MUST:

1. Read every emitted template.
2. Read the `warnings` string in the migrated `__init__.py`.
3. Cross-check: does every claim in `warnings` map to an enforced behavior in the templates? Examples of carry-over overclaims to catch:
   - `add_api_key_auth` `warnings` claiming "constant-time compare" when the emitted code uses `==`.
   - `add_dpop_tokens` claiming "replay-protected" when the nonce cache is in-process only (no cross-instance store).
   - `add_passkey_auth` claiming "user-verification enforced" when the assertion verifier accepts `uv=0`.
   - `add_oauth2_provider` claiming "PKCE required" when `code_challenge` is optional.
   - `add_social_login` claiming "CSRF-protected" when `state` is generated but never validated.

Any unenforced claim = fix the `warnings` to honest in this WP. Behavior changes are out of scope per §3.

### Model elevation rationale

`opus` reasoning is required to (a) read the §11 diff and judge cosmetic vs behavioral drift, especially for the canonicalization-heavy tools (`add_request_signing`, `add_dpop_tokens`) and (b) audit honesty on credential `warnings`. Running this gate on `sonnet` risks false-negative diff judgements and silent credential overclaims.

### Trade-offs declared

- **T-01.** Theme partition (identity / credential primitives) over alphabetical — keeps the "what does the client present" mental model intact across the 8 tools; the authorization side (what the request may do) is the disjoint sibling WP-09.
- **T-02.** All `opus`, not `sonnet` — auth + data integrity are the two highest-blast-radius domains in WAVE 1; this WP is the auth-identity half.
- **T-03.** P1 backlog items NOT folded into THIS WP (P1 #14 is WP-07's; P1 #16 is WP-09's). WP-08 is the "clean" auth WP — pure mechanical migration plus §11 byte-equivalence + honesty audit. This keeps WP-08's blast radius scoped tighter than its two siblings.
- **T-04.** Identity/policy split (8 + 7 here vs one big 15-tool WP) — the two halves have different review cadences (identity = byte-equivalence diff on token-verification flows; policy = secure-default audit on authz code paths). Splitting halves the cognitive load per agent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
