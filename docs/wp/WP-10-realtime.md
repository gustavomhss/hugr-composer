# Work Package Contract — `WP-10-realtime`

> **Binding contract, not a suggestion.** An agent executing this WP MUST satisfy
> every section below. The WP is *done* only when every acceptance gate is green
> and every Definition-of-Done box is checked, with proof pasted. Anything less
> is "in progress", never "done".
>
> Authored against `docs/wp/WP-CONTRACT-TEMPLATE.md`. Section order and headers
> are verbatim from the template; WP-10-specific content fills each section.
> Theme: **streaming, async client push, websocket lifecycle** — 5 cohesive tools
> from `adapt/extend/realtime/`.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-10-realtime` |
| **Title** | Migrate 5 realtime tools to per-tool directory + externalized templates |
| **Wave** | `1` |
| **Depends on** | `WP-F0-staging-rename` (merged) · `WP-F1-base-and-golden` (in flight — `adapt/_base/` + golden `add_cursor_pagination/`) |
| **Blocks** | none (sibling WPs are file-disjoint) |
| **Branch** | `wp/10-realtime` (off the post-dependency main, i.e. main with WP-F0 + WP-F1 merged) |
| **Isolation** | dedicated git worktree |
| **Model** | `sonnet` — mechanical refactor; pattern set by F1 golden tool. `add_webhook_sender` (1981 LOC, 13 dedent, 75 triple) and `add_websocket_chat` (1717 LOC, 8 dedent, 53 triple) are heavy but structurally identical to WP-02's heaviest tools. |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.

- **Owned files (exclusive write surface):**
  ```
  skills/SKILL-001-fastapi-production/adapt/extend/realtime/add_sse/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/realtime/add_webhook_receiver/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/realtime/add_webhook_sender/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/realtime/add_websocket_chat/
    __init__.py
    templates/*.py.tmpl
  skills/SKILL-001-fastapi-production/adapt/extend/realtime/add_websocket_presence/
    __init__.py
    templates/*.py.tmpl
  # Delete after migration (one-line removal each):
  skills/SKILL-001-fastapi-production/adapt/extend/realtime/add_sse.py                  [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/realtime/add_webhook_receiver.py     [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/realtime/add_webhook_sender.py       [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/realtime/add_websocket_chat.py       [DELETE]
  skills/SKILL-001-fastapi-production/adapt/extend/realtime/add_websocket_presence.py   [DELETE]
  ```
- **Golden reference (read-only, copy the pattern):** `skills/SKILL-001-fastapi-production/adapt/extend/crud_data/add_cursor_pagination/` (post WP-F1)
- **Shared base/contract to import (read-only):** `skills/SKILL-001-fastapi-production/adapt/_base/` + `skills/SKILL-001-fastapi-production/adapt/contracts/`
- **Spec to follow:** `docs/tool-contract.md`, `docs/architecture.md`, `docs/adr/0001-architecture.md`
- **Staging pool (read-only reference, not a write surface):** `core/venous/_staging/` (renamed via WP-F0)

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits:
- **WP-11 (Testing tools) targets** — the 9 tools listed in §1 of `docs/wp/WP-11-testing-tools.md`. Read that manifest for the canonical list.
- **WP-12 (API design) targets** — the 7 tools listed in §1 of `docs/wp/WP-12-api-design.md`.
- **WP-01/02/03 (infrastructure) tools** — all 27 tools owned by those manifests.
- **WP-Z2 / WP-C / WP-E / WP-F sibling targets** — infrastructure 04-06, crud+auth 07-09, evolve/verify/hex 13-15, engine 16-17.
- `adapt/_base/` — owned by WP-F1; read-only here.
- `core/venous/` — primitives layer; read-only here.
- `engine/`, `generators/`, `tests/`, `pyproject.toml`, CI config — out of scope.
- `adapt/extend/realtime/__init__.py` — shared registry surface; if a re-export needs to change, **stop and report** (registry update is a separate WP).
- All other `adapt/extend/<cat>/__init__.py` files — read-only.

If the task seems to require touching a forbidden file, **stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** Migrate 5 realtime tools from flat single-file modules with inline emitted code into the per-tool directory layout with externalized `templates/*.py.tmpl`, and route their `discover/patch` through `adapt/_base/`.
- **Before:** Each tool is a single `add_<tool>.py` carrying embedded code-as-strings (triple-quoted blocks, `textwrap.dedent`, occasional `_GLUE`-style constants) plus per-tool ad-hoc discovery/patching. These tools ship a lot of async-loop and connection-lifecycle boilerplate: SSE generators, websocket accept/disconnect hooks, presence heartbeats, webhook HMAC signing, replay protection. Per-tool LOC measurements (raw, end of §8) range 172–1981.
- **After:**
  - Each tool becomes `add_<tool>/__init__.py` + `templates/*.py.tmpl`.
  - `__init__.py` is orchestration only: `discover()` → `plan()` → `write()` → `patch()` → `verify()`, importing from `adapt/_base/`.
  - All emitted code lives in `templates/*.py.tmpl`. **No** triple-quoted Python-source blocks remain in `__init__.py`. `textwrap.dedent` calls drop to **zero** in `__init__.py`.
  - `__init__.py` ≤ 300 LOC of logic (hard cap 500 per §4). Templates exempt.
  - Public dotted path `adapt.extend.realtime.add_<tool>` resolves identically; `MCP_TOOL` metadata preserved verbatim.

| Tool | Target dir layout | Expected post-LOC (`__init__.py`) | Templates to externalize | Emitted-test name |
|---|---|---:|---:|---|
| `add_sse` | `add_sse/{__init__.py, templates/}` | ≤ 280 | ≥ 9 (9 `dedent`, 51 triple-quote anchors) | `test_add_sse_emitted.py` |
| `add_webhook_receiver` | `add_webhook_receiver/{__init__.py, templates/}` | ≤ 130 | ≥ 3 (3 triple-quote blocks + 2 `_GLUE`) | `test_add_webhook_receiver_emitted.py` |
| `add_webhook_sender` | `add_webhook_sender/{__init__.py, templates/}` | ≤ 290 | ≥ 13 (13 `dedent`, 75 triple-quote anchors, 2 `_GLUE`) | `test_add_webhook_sender_emitted.py` |
| `add_websocket_chat` | `add_websocket_chat/{__init__.py, templates/}` | ≤ 290 | ≥ 8 (8 `dedent`, 53 triple-quote anchors, 4 `_GLUE`) | `test_add_websocket_chat_emitted.py` |
| `add_websocket_presence` | `add_websocket_presence/{__init__.py, templates/}` | ≤ 270 | ≥ 6 (6 `dedent`, 41 triple-quote anchors) | `test_add_websocket_presence_emitted.py` |

- **Out of scope:** behavior changes, contract changes, registry edits, dependency additions, formatter overhauls, renaming tools, modifying tests outside this WP's emitted-test scope, touching any sibling WP's tools.

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change.** Same `ToolInput` → same `ToolResult` shape; same files emitted (byte-equivalent after stripping comments/whitespace from emitted code). Proven by GATE 1.
- [ ] **Import paths stable.** `from adapt.extend.realtime.add_<tool> import add_<tool>` resolves identically; `MCP_TOOL` metadata preserved.
- [ ] **Templates externalized.** Zero triple-quoted Python-source bodies, zero `textwrap.dedent` calls in any `__init__.py`. Verified by `grep -E 'textwrap\.dedent|^\s*"""' add_<tool>/__init__.py | wc -l` returning 0 for emitted-code blocks.
- [ ] **File size.** Each `__init__.py` ≤ 300 LOC of logic (hard cap 500); templates exempt.
- [ ] **No dead code.** No orphan helpers, no commented-out blocks, no unused `_GLUE`/`_TEMPLATE` constants left dangling.
- [ ] **Docstrings honest.** Tools that do not enforce something MUST say so in `warnings`. Specifically: a websocket "presence" tool that does not guarantee delivery MUST say so; a webhook sender that does not guarantee at-least-once MUST say so; an SSE tool that does not back-pressure slow consumers MUST say so.
- [ ] **No new dependencies.** No `pyproject.toml` change; no new top-level imports beyond what `adapt/_base/` already provides.
- [ ] **Idempotent.** Second run returns `no_op` without touching files. Verified per tool.

## 5. Test emission (per P1 #15)
P1 backlog item **#15** mandates: every tool emits a test in the generated project that asserts the behavior added by the tool. WP-F1's golden tool (`add_cursor_pagination`) sets the emitted-test format — **copy that format verbatim** (location: `{project}/tests/test_<tool>_emitted.py`).

For each of the 5 tools in §1, the migrated `__init__.py` MUST:
- Render an emitted test from `templates/test_<tool>_emitted.py.tmpl`.
- Place it at `{project_dir}/tests/test_<tool>_emitted.py`.
- Make it green under the emitted project's `pytest tests/` after compose.
- Cover at least one positive (added behavior fires: e.g. SSE chunk observed by `TestClient`, websocket frame echoed, webhook HMAC verifies, presence heartbeat increments) and one negative (boundary or off-path: bad signature rejected, disconnect cleans up state, replay token refused) assertion. Same skeleton as F1 golden.

Failure to emit a test = WP rejected; this is non-negotiable per P1 #15.

## 6. Validation gates (deterministic — copy/paste, must be GREEN)
Run from `skills/SKILL-001-fastapi-production` with the shared interpreter; paste each result in §7.

```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# Mandatory gate 1 — ruff (lint + format)
$PY -m ruff check adapt/extend/realtime/add_{sse,webhook_receiver,webhook_sender,websocket_chat,websocket_presence}
$PY -m ruff format --check adapt/extend/realtime/add_{sse,webhook_receiver,webhook_sender,websocket_chat,websocket_presence}
# Mandatory gate 2 — pytest per tool (owned)
$PY -m pytest adapt/extend/realtime/test_add_{sse,webhook_receiver,webhook_sender,websocket_chat,websocket_presence}*.py -q -p no:cacheprovider -n auto
# Mandatory gate 3 — boot smoke for each tool name
$PY tests/test_boot.py | grep -E 'add_sse|add_webhook_receiver|add_webhook_sender|add_websocket_chat|add_websocket_presence'
# Mandatory gate 4 — boot chains (run ALONE — contention-sensitive)
$PY tests/test_boot_chains.py
# Mandatory gate 5 — contract audit (37/37)
$PY -m engine.audit.contract_check
```

All five gates must be GREEN. Paste verbatim tails in §7.

## 7. File-disjoint guarantee (your WP's surface + EXPLICIT forbidden list)

**WP-10 owns (write surface):** the 5 directories under `adapt/extend/realtime/add_<tool>/` listed in §1, plus the 5 legacy flat `.py` file deletions listed in §1.

**WP-10 must NOT touch (forbidden):**

| Owner | Forbidden tools / paths |
|---|---|
| WP-11 Testing tools | the 9 tools listed in §1 of `docs/wp/WP-11-testing-tools.md` |
| WP-12 API design | the 7 tools listed in §1 of `docs/wp/WP-12-api-design.md` |
| WP-01/02/03 | all 27 `adapt/extend/infrastructure/add_*` tools listed in those manifests |
| WP-Z2 (sibling) | infrastructure 04-06 tools |
| WP-C (sibling) | crud_data + auth_access 07-09 tools |
| WP-E (sibling) | evolve/verify/hex 13-15 tools |
| WP-F (sibling) | engine-split 16-17 |
| WP-F1 | `adapt/_base/`, golden `crud_data/add_cursor_pagination/` |
| Shared | `adapt/extend/realtime/__init__.py`, all other `adapt/extend/<cat>/__init__.py`, `adapt/contracts/`, `core/venous/`, `engine/`, `generators/`, `tests/` outside emitted scope, `pyproject.toml`, CI |

`git diff --name-only main..HEAD` MUST list only paths inside the §1 write surface.

## 8. Estimated effort (per-tool)

Measurements taken on `main` at branch creation; LOC = `wc -l`; `dedent` = `grep -c 'textwrap.dedent'`; `triple` = `grep -c '"""'`; `glue` = `grep -cE '_GLUE|_TEMPLATE|_SOURCE'`.

| Tool | Current LOC | Expected post-migration `__init__.py` LOC | `dedent` | `triple` | `_GLUE` | Wall-clock | Model |
|---|---:|---:|---:|---:|---:|---:|---|
| `add_sse` | 1124 | ≤ 280 (-75%) | 9 | 51 | 0 | 4.0 h | `sonnet` |
| `add_webhook_receiver` | 172 | ≤ 130 (-24%) | 0 | 6 | 2 | 1.0 h | `sonnet` |
| `add_webhook_sender` | 1981 | ≤ 290 (-85%) | 13 | 75 | 2 | 5.0 h | `sonnet` |
| `add_websocket_chat` | 1717 | ≤ 290 (-83%) | 8 | 53 | 4 | 4.5 h | `sonnet` |
| `add_websocket_presence` | 849 | ≤ 270 (-68%) | 6 | 41 | 0 | 3.0 h | `sonnet` |
| **TOTAL** | **5843** | **~1260 (-78%)** | **36** | **226** | **8** | **~17.5 h** | `sonnet` |

**Model recommendation: `sonnet`.** This batch is mechanical (extract triple-quoted blobs → `.tmpl`, route discovery/patch through `_base`); pattern is set by F1 golden tool; no behavior-change reasoning required. The heavy tools (`add_webhook_sender`, `add_websocket_chat`, `add_sse`) are larger than WP-02's heaviest but structurally identical. Promotion to `opus` only if the agent hits a STOP-and-report rule in §9 — particularly F-07 (async-loop side effects at import time) or F-08 (websocket-test determinism).

## 9. Failure modes (≥6 anticipated traps)

1. **F-01. Embedded f-string interpolation lost in template move.**
   - *Symptom:* emitted code refers to `${project_name}` literally instead of substituted value; `pytest tests/` in emitted project fails at import.
   - *Cause:* triple-quoted block in source used Python f-string interpolation (`f"""…{var}…"""`); template renderer in `_base` uses different placeholder syntax (e.g. `{{ var }}`).
   - *STOP-and-report rule:* before any extraction, dump the source's interpolation style for the tool; if it does not match F1 golden's template syntax, **stop and report** — joint amendment with WP-F1 needed.

2. **F-02. `MCP_TOOL` metadata lost in module split.**
   - *Symptom:* `engine.audit.contract_check` drops from 37/37 → 36/37 for the migrated tool.
   - *Cause:* `MCP_TOOL = {...}` constant lived at module top in the flat `.py` and was not copied into the new `__init__.py`.
   - *STOP-and-report rule:* after every per-tool migration, run `python -c "from adapt.extend.realtime import add_<tool>; assert add_<tool>.MCP_TOOL"` — fail = stop and report.

3. **F-03. Idempotency regression — second run rewrites files.**
   - *Symptom:* `pytest` for `test_add_<tool>.py` fails on the second-run idempotency case; `ToolResult.status` returns `success` instead of `no_op`.
   - *Cause:* `discover()` was inlined per tool with custom skip-set; replacing with `adapt/_base/discover.py` lost a skip entry.
   - *STOP-and-report rule:* if `adapt/_base/discover.py` does not expose the tool's required skip-set, **stop and report** — do NOT re-inline discovery.

4. **F-04. Hidden behavior leak via `__init__.py` side-effects.**
   - *Symptom:* boot smoke fails — `import adapt.extend.realtime.add_<tool>` raises.
   - *Cause:* the flat `.py` ran top-level code (e.g. eager template render, global registry mutation, asyncio loop probe).
   - *STOP-and-report rule:* never paper over with try/except; **stop and report** — top-level side-effects are an upstream bug.

5. **F-05. Template syntax drift — Jinja vs str.format.**
   - *Symptom:* templates render with literal `{var}` instead of values; emitted file is syntactically valid Python but semantically broken.
   - *Cause:* author used `str.format` placeholders in a `_base` Jinja renderer (or vice-versa).
   - *STOP-and-report rule:* before migration, confirm the renderer in `adapt/_base/render.py` and use **only** that syntax. Mixed syntax = stop and report.

6. **F-06. Emitted-test missing or trivially-true (per P1 #15).**
   - *Symptom:* `tests/test_<tool>_emitted.py` exists in emitted project but has zero `assert` statements, or asserts only `True`.
   - *Cause:* template author copied the golden skeleton without adapting the behavior assertions.
   - *STOP-and-report rule:* every emitted test MUST cover one positive and one negative case (§5); if the tool's behavior cannot be asserted (e.g. async-only side-effect, no observable surface), **stop and report** — do not ship a no-op test.

7. **F-07. Async-loop side effects at import time.**
   - *Symptom:* `add_sse` or `add_webhook_sender` imports start a background task or open a socket on import; boot-smoke gate hangs or fails.
   - *Cause:* the flat `.py` instantiated an `asyncio.Queue`, `httpx.AsyncClient`, or `asyncio.create_task` at module scope.
   - *STOP-and-report rule:* if the flat `.py` has any top-level `asyncio.*` call or network handle, the migration MUST move it inside a function. If that requires a behavior change to the emitted code (rather than the kit `__init__.py`), **stop and report**.

8. **F-08. Websocket / SSE emitted-test non-determinism.**
   - *Symptom:* emitted `test_add_websocket_chat_emitted.py` or `test_add_sse_emitted.py` passes locally but flakes in CI; depends on event-loop timing.
   - *Cause:* test awaits a frame with no timeout, or uses `time.sleep` for ordering, or depends on multi-task scheduling.
   - *STOP-and-report rule:* if a deterministic, in-process assertion (e.g. `TestClient` + `websocket_connect()` context, finite `recv_text()` with explicit timeout, single-task sequence) is not possible, **stop and report** — do NOT add `time.sleep` or `@flaky`.

9. **F-09. Webhook HMAC / replay-token assertion overclaim.**
   - *Symptom:* `add_webhook_sender` ships warnings claiming exactly-once delivery or strong replay protection, but the emitted code only signs the payload.
   - *Cause:* honesty rule violation carried over from source.
   - *STOP-and-report rule:* if migrated `warnings` overstate enforcement, **stop and report** — fix the warnings to honest in this WP (not the behavior; that is out of scope).

10. **F-10. Hard-cap LOC breach (`__init__.py` > 500).**
    - *Symptom:* size invariant fails for `add_webhook_sender` (1981 LOC) or `add_websocket_chat` (1717 LOC) — the two heaviest tools.
    - *Cause:* author left orchestration helpers in `__init__.py` that belong in `adapt/_base/`.
    - *STOP-and-report rule:* if `__init__.py` cannot be brought below 300 LOC of logic without inlining `_base/`, **stop and report** — a `_base` extension may be needed (joint amendment with WP-F1).

## 10. DoD checklist (every box, or it's not done)

- [ ] **D-01.** All 5 tool directories created under `adapt/extend/realtime/`, each with `__init__.py` + `templates/`.
- [ ] **D-02.** All 5 legacy flat `.py` files removed (`git diff --name-only` shows 5 deletions).
- [ ] **D-03.** Each `__init__.py` ≤ 300 LOC (verified by `wc -l`).
- [ ] **D-04.** Zero `textwrap.dedent` calls in any new `__init__.py` (verified by `grep -c 'textwrap.dedent' add_<tool>/__init__.py` → 0 for all 5).
- [ ] **D-05.** Zero embedded Python-source triple-quoted bodies in any new `__init__.py` (module/function docstrings are fine; emitted code is not).
- [ ] **D-06.** All 5 emitted tests rendered into `{project_dir}/tests/test_<tool>_emitted.py` with ≥1 positive + ≥1 negative assertion, deterministic.
- [ ] **D-07.** §6 gate 1 (ruff) green for all 5 tools.
- [ ] **D-08.** §6 gate 2 (pytest per tool) green for all 5 tools.
- [ ] **D-09.** §6 gate 3 (boot smoke `tests/test_boot.py | grep`) returns a PASS line per tool name; no import-time async side effects (F-07 cleared).
- [ ] **D-10.** §6 gate 4 (`tests/test_boot_chains.py`) green, run ALONE.
- [ ] **D-11.** §6 gate 5 (`engine.audit.contract_check`) 37/37.
- [ ] **D-12.** `git diff --name-only main..HEAD` lists only paths inside §1 write surface (no sibling WP surface touched).
- [ ] **D-13.** Idempotency check passes per tool (second run = `no_op`).
- [ ] **D-14.** Websocket / SSE emitted tests confirmed deterministic (no `time.sleep`, no `@flaky`); F-08 cleared.
- [ ] **D-15.** Self-review: agent re-read its own diff as an adversarial reviewer and pasted findings in PR body.

---

## Appendix A — Composition notes for this batch (read-only context)

The 5 tools in this WP frequently compose together in a typical FastAPI realtime
stack: SSE for one-way push, websocket-chat / websocket-presence for bidirectional
session traffic, webhook sender for outbound async events, webhook receiver for
inbound third-party callbacks. None of these compositions add behavior in *this*
WP — the migration is structural — but the agent SHOULD be aware:

- After WP-10 merges, downstream composition tests (`tests/test_boot_chains.py`)
  exercise these tools as a group. A regression in any one tool surfaces in the
  chain test, not just the per-tool test.
- The `__init__.py` orchestration MUST be import-cheap (no top-level work,
  especially no `asyncio.*` calls) so that `tests/test_boot.py` boot-time per
  tool stays under its current budget. See F-07.
- Webhook sender + receiver, when composed, MUST agree on HMAC scheme. The
  migration does not touch the scheme — but if the agent notices a divergence
  between sender's signing template and receiver's verification template,
  **report it** (do not fix it — that is another WP).

## Appendix B — Why theme-grouping (not size-balanced batches)

WP-10 carries 5 tools that share a streaming / async-push mental model. An agent
reading the manifest gets the same conceptual frame for every tool in the batch,
which reduces cross-tool reasoning cost. Size-balanced batches would have mixed
streaming with testing infra or API-design paradigms, forcing context switches
between every tool. The trade-off (5 tools vs WP-01's 9, but with two ~1700-1981
LOC heavies) is accepted for cohesion gains.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
