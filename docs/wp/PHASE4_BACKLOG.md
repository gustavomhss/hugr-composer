# WAVE 1 Phase 4 Backlog — what did NOT ship in the 2026-05-29 cascade

Authored **2026-05-29** after the WAVE 1 cascade closed.

## What shipped in WAVE 1 (5 PRs merged to main)

| PR | WP | What landed |
|---|---|---|
| #47 | WP-17 engine-build-compose-split | `engine/audit/_build_compose.py` (2 584 LOC) → `compose_data/` package (1 facade + 4 helpers + 13 entry fragments); byte-equivalent build output (stable_hash unchanged) |
| #48 | WP-04 async-workflow | 9 tools migrated to per-tool dir form (`add_<tool>/__init__.py` + `templates/*.py.tmpl`) |
| #49 | WP-05 storage-deployment | 9 tools migrated, dir form |
| #50 | WP-01 resiliency-defense | 9 tools migrated, dir form |
| #51 | WP-12 api-design | 7 tools migrated + **`mcp_tools/discovery.py` fix** so dir-form tools are actually picked up |

Cumulative: **34 + 7 = 41 adapt tools migrated**; engine surface split; discovery loop generalised; CI gate intact (default ≤ 30 / full ≥ 170, currently 18 / 200).

## What did NOT ship and why

### #52 — WP-02 observability-diagnostics (CLOSED, broken)
**Status:** PR was opened, CI failed massively (37 pytest failures), agent (`sonnet`) had declared DoD green but the emitted templates **did not satisfy the pre-existing `test_<tool>.py` suite** for any of the 9 migrated tools.

**Sanity check on `main` (with flat `.py`):** `test_add_anomaly_detector.py` passes 25/25. On the closed PR branch (dir form): 6/25 failed; same for `add_health_deep`, `add_prometheus_metrics`, `add_request_tracing_ui`, `add_runtime_sentinel`, `add_structured_logging`, `add_dependency_health_map`, `add_opentelemetry`, `add_api_replay_debugger`.

**Root cause:** sonnet wrote templates that emit code missing required symbols (`init_detector`, `AlertDispatcher`, `checks/database.py`, `configure_structlog`, `Redactor`, `bind_context`, `get_correlation_id`, `RequestMetrics`, `init_metrics`, `PrometheusMiddleware`, …). DoD §6 boot smoke passed because boot doesn't import these symbols, but `test_<tool>.py` does.

**Phase 4 mandate:** re-dispatch on **opus** with stricter DoD adding `pytest adapt/extend/<bucket>/test_*.py ALL PASS` as a gate (boot smoke is necessary but not sufficient).

### 10 WPs — STOP-and-report (manifest defects)
All 10 returned without any code change, citing manifest contradictions that the standing brief forbids them from working around. The defects are **shared across most WAVE 1 manifests** (they came from the same template) and must be fixed before any of these can be re-dispatched.

**Affected:** WP-03 security-compliance, WP-06 payments-notif-ml, WP-07 crud-data, WP-08 auth-identity, WP-09 auth-policy, WP-11 testing-tools, WP-13 evolve, WP-14 verify, WP-15 hexagon-ports, WP-16 engine-contract-check-split.

### Manifest defects to fix before Phase 4

#### D1 — `engine.compose` does not exist (§11 byte-equivalence diff gate)
Every manifest's §11 mandates:
```bash
$PY -m engine.compose --tool add_<tool> --project /tmp/post/<tool>
```
There is no `engine/compose.py` module and no CLI entry that takes `--tool` + `--project`. Existing modules:
- `engine.discovery.compose` — BM25 retrieval over "Compose with:" recipe sections (not an emitter)
- `mcp_tools.compose` — primitive-set composition into `app/compositions/<slug>.py`
- `engine.audit._build_compose` — splitter that the WP-17 just refactored

**Phase 4 fix:** rewrite §11 to use the proven fixture pattern that every existing per-tool test already uses:
```python
from tests.common.fixture_factory import create_fixture_project
project = create_fixture_project()
result = add_<tool>(ToolInput(project_dir=str(project)))
# then `diff -ruN /tmp/pre /tmp/post` on the project dir
```
This is byte-equivalent in spirit and actually executable. Back-port to every manifest that cites `engine.compose`.

#### D2 — `37/37` contract floor is stale (`§6 gate 5` / `§10 D-11`)
The manifests were authored against the contract suite at PR #28 (37 rules). Wave 0 F2 (#39) added B0.9, B2.7, B2.8 → **40/40 is the current floor**.

**Phase 4 fix:** bump the literal `37/37` → `40/40` (or replace with "≥ baseline, no regression" if we want future-proofing).

#### D3 — WP-09 `auth-policy` is obsolete
PR #35 (`fix/p1-16-bola-secure-default`) shipped P1 #16 in **`generators/orchestrator.py`** (not in `add_bola_guard` as WP-09 §3 mandates). The §3 centerpiece is now a duplicate of work already in main, and `§2` forbids editing `generators/orchestrator.py`.

**Phase 4 fix:** decide between (a) drop the P1 #16 fold from WP-09, repurpose it as a pure 7-tool dir-form migration with byte-equivalent diff, or (b) repurpose `add_bola_guard` as a retrofit path for projects scaffolded before v0.5 with a *distinct* contract from the orchestrator's secure-default.

#### D4 — WP-15 has internal `§0` model contradiction
Table says `Model = sonnet`; the justification line below says "sonnet is insufficient for the §11 compat-shim tradeoff" and requires opus.

**Phase 4 fix:** set `Model = opus` in the table to remove the ambiguity.

#### D5 — WP-16 §6 gate 4 hard-codes the pre-F2 RULES list
`§6 gate 4` literally asserts `len(RULES) == 37` and lists 37 IDs. Post-F2 reality is 40 with `B0.9`, `B2.7`, `B2.8` added.

**Phase 4 fix:** update `§6 gate 4` to current 40-rule list + `len(RULES) == 40`, and add the 3 new rules to `§3` decomposition table (`B0.9` → `phase0_identity.py`, `B2.7` → `phase2_tier1.py`, `B2.8` → `phase2_catalog.py`).

#### D6 — WP-11 `§11` open question never resolved
Manifest explicitly says `D-00` is blocked until tech-lead resolves `§11` (what "emit a test that asserts the behavior added by the tool" means when the tool *is* test infrastructure). Three candidates listed; **none pre-decided**. Standing rule forbids the agent from picking.

**Phase 4 fix:** tech-lead picks one of (wiring-assertion / sub-runner-assertion / hybrid) and writes it into `§11` as an amendment.

#### D7 — WP-06, WP-07, WP-08 scope estimates exceed single-session budget
- WP-06: ~38 h / 9 066 LOC across 8 tools — §11 diff gate per tool + ML safety + honesty audit
- WP-07: ~37 h / 7 011 LOC across 9 tools — multi-tool dependency-graph
- WP-08: ~36 h / 7 950 LOC across 8 tools — 2 of which are already venous (`add_oauth2_provider`, `add_mfa`)

**Phase 4 fix:** split each into 3 sub-WPs (a/b/c per natural fault line), each one a one-session unit.

#### D8 — WP-08 architectural ambiguity
`add_oauth2_provider` and `add_mfa` are **already venous-hexagon** (use `ensure_primitives` + `core/venous/_adapters/fastapi/`). The WP-08 manifest demands they migrate to the `adapt/_base/` + `templates/*.py.tmpl` shape — but that would either:
- (a) drop their venous wiring (regression vs `docs/architecture.md` §"Key invariants"), or
- (b) keep venous wiring + skip templates dir (violates §1 + §3).

**Phase 4 fix:** declare them out-of-scope for WP-08 (they are already in the architecture's target state).

## Recovered partial work (do NOT lose)

Two pieces of work were recovered from agents that hit `[Tool result missing due to internal error]` returns:

### `/tmp/recovered_wp15/_ports/` — WP-15 hexagon-ports
Architecture audit + port catalog produced by the WP-15 agent before the internal error swallowed its return. **21 files**, 108 K:
- `CATALOG.json` (752 LOC) — full per-primitive port-binding audit across the 124 registered primitives, 11 namespaces (`api`, `auth`, `billing`, `cache`, `compliance`, `data`, `flags`, `llm`, `obs`, `resiliency`, `security`)
- `CATALOG.md` (152 LOC) — agent-readable summary
- `README.md` (150 LOC)
- `__init__.py`, `api/`, `auth/`, `billing/`, `cache/`, `compliance/`, `data/`, `flags/`, `llm/`, `obs/`, `policy/`, `resiliency/`, `security/`, `events/`, `extras/`

**Phase 4 use:** this is the §11 compat-shim plan's primary input. Restore into a fresh `wp/15-hexagon-ports` branch as the first commit, then have opus re-derive `§11 compat-shim plan summary` against it. Do NOT just commit `_ports/` to main blind — WP-15 §10 D-09 requires `engine.audit.contract_check` to stay green after the import-graph rewrite, which needs the shim plan first.

### `/tmp/wp02_full/infrastructure/` — WP-02 + WP-01 worktree snapshot
The entire `adapt/extend/infrastructure/` directory from the closed PR #52 branch, **8.1 MB**, including:
- 6 broken WP-02 dir-form tools (anomaly_detector, api_replay_debugger, dependency_health_map, health_deep, opentelemetry, request_tracing_ui)
- 3 broken WP-02 dir-form tools that were already reverted to flat `.py` during the close (prometheus_metrics, runtime_sentinel, structured_logging — saved as `add_<tool>/` dirs)
- The WP-01 9 tools (which DID merge in #50) snapshot

**Phase 4 use:** reference only — opus re-dispatch should produce fresh templates. The broken templates are useful as "what NOT to emit" examples in the brief (e.g., "do not import `prometheus_client` at module top-level; do not omit `configure_structlog` from `setup.py.tmpl`").

## Phase 4 plan

Each step is a separate PR. Sequence preserves dependency order:

1. **`docs/wave1-manifest-refresh`** — fix D1–D8 inside the 10 stale manifests in one PR (single touch surface = `docs/wp/`). No code change.
2. **`wp/15-hexagon-ports`** — opus, single-session, scope = restore `/tmp/recovered_wp15/_ports/` + author `§11 compat-shim plan` per refreshed manifest. Blocks WP-08 sub-WPs.
3. **`wp/16-engine-contract-check-split`** — opus, single-session, against refreshed manifest with 40-rule list.
4. **WP-02 redux (3 sub-PRs)** — opus, one bucket per PR (observability-core / observability-stats / observability-traces). Each PR runs `pytest adapt/extend/infrastructure/test_*.py` as a hard gate.
5. **WP-03 + WP-06 + WP-07 + WP-08 splits** — opus, ~9 sub-WPs total across the 4 heavy WPs, ratified per the D7+D8 splits above.
6. **WP-11 + WP-13 + WP-14** — opus, single-session each, once §11 / D-00 is resolved (WP-11) and the manifest is refreshed.

Estimated Phase 4 footprint: **~12-18 PRs**, ~4-6 cascades each ≈ same shape as today's 5-PR cascade. Sequential merge with the proven pattern (cancel main CI → trigger PR alone → watch → merge → rebase next).

## Lessons banked from WAVE 1 cascade (2026-05-29)

1. **Sonnet failed silently on #52.** DoD §6 listed boot smoke + emitted-test-template + lint, but NOT `pytest existing tests`. Boot smoke is necessary but not sufficient — sonnet's templates booted but failed all behavioural assertions. Phase 4 DoD must include `pytest adapt/extend/<bucket>/test_*.py` as a hard gate.
2. **Discovery loop had a silent regression class.** `mcp_tools/discovery.py` skipped all `__init__.py` files, so every dir-form tool was invisible to MCP discovery even though the catalog counted them. Fixed in #51 by special-casing `add_<tool>/__init__.py` to import the *package* (not the `.__init__` submodule, which creates a duplicate module object holding the same `MCP_TOOL` name and breaks `register_adapt_tool`).
3. **Rebase + delete-remote-branch ordering matters.** `gh pr merge` returned "branch was already merged" but the GH state hadn't propagated; deleting the remote branch before the merge state settled re-closed PR #48 prematurely. Always `gh pr view <n> --json state` AFTER merge and AFTER a 5-8 s sleep before `gh api -X DELETE`.
4. **CI flakes are real.** PR #51 failed `integration (sqlite e2e)` + `boot chains` once (postgres role missing, redis 6379 down, full-100-tools timeout > 90 s), then passed on idempotent re-trigger. Re-trigger before treating as a real regression — but only if the failure pattern matches known flakes (DB connectivity, CPU contention, timeouts).
5. **Worktree slip risk on parent agent.** When PR #52's `git rebase --continue` ran with `git add -A`, it accidentally committed leftover `core/venous/_ports/` work from the WP-15 missing-result agent. Recovered to `/tmp/recovered_wp15/`; the lesson is to `git status` before `git add -A` in a rebase-continue context to catch untracked-leftovers.
