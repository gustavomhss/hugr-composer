# not-yet-covered.md — honest evidence gaps at v1.0.0

> Listed here: every PRODUCT.md / LAUNCH.md / CONTRACT.md claim the evidence package does NOT prove (or only weakly proves) at the v1.0.0 tag cut, with an honest reason + milestone.
>
> If a claim is material to the product but lives only in this file, it is a **stated caveat**, not proof. Codex v7 LAUNCH review B2 + Opus BLOCKER-1 caught: hiding gaps behind confident language is the primary failure mode. They live here explicitly instead.

---

## §1 — MCP server against Claude Desktop / Cursor / Zed

**PRODUCT §3 secondary claim.** The skill exposes an MCP server (`mcp_tools/`) intended to be discoverable + invocable by any MCP-compatible client. We have:

- `mcp_tools/server.py` that boots and serves the Tier-1 + Tier-2 surface.
- `mcp_tools/auto_discovery.py` that enumerates tools for the client.
- `examples/claude_code.mcp.json` as a registration shape.

What we do NOT have at v1.0.0:

- Automated end-to-end test against Claude Desktop, Cursor, or Zed as live clients. Integration is manually verified only.

**Milestone to close:** v1.1+ — build a harness that launches each client headlessly, installs the kit, and asserts tool-discovery + one successful invocation.

---

## §2 — Generated code survives hand-editing (longitudinal soak)

**PRODUCT §6.3 claim.** Emit-time idempotency IS covered: the orchestrator-twice probe (`evidence/deterministic/generator_idempotence.json`) proves byte-identical re-emission across `minimal`, `api`, and `full` profiles WITHOUT PYTHONHASHSEED pinning (Wave I-1.K closure of the two pre-existing source non-determinisms).

What this does NOT prove:

- **Longitudinal soak:** "apply tool → hand-edit → apply tool → hand-edit → apply tool" over N cycles, across many projects and edit styles, without divergence.

What used to be here but is now CLOSED (kept as audit trail):

- ~~Hash-randomization-independent reproduction~~ — **CLOSED Wave I-1.K (commit `90218ec`).** `generators/middleware/request_logging.py` now sorts the lowered set before repr-ing; output is identical regardless of PYTHONHASHSEED.
- ~~Timestamp-independent reproduction~~ — **CLOSED Wave I-1.K (commit `90218ec`).** `generators/scaffold_venous.py` now pins `manifest.copied_at` to the source commit's author timestamp (`git log -1 --format=%aI`) instead of host wall-clock.

**Milestone to close (remaining):** v1.1+ — soak-edit harness for the longitudinal claim.

---

## §3 — "Cheaper than hand-coded" as an absolute claim

**PRODUCT §1 + §4 implicit economic claim.** We evidence a relative form via the counterfactual harness (authored, not yet executed).

That establishes (or will establish, post-paid run) HuGR-assisted is cheaper than same-model raw generation for the 10 FNF specs at the benchmark HEAD. It does NOT establish:

- "Cheaper for real teams with real feature specs at production scale" as an absolute. That requires population-scale telemetry (real users, real specs, real PR merge cycles).

**Milestone to close:** v1.2+ — opt-in telemetry from Phase B cohort (install-completion + first-scaffold-boot + extend-tool-activation rates). Until then this is a research-benchmark claim, not a billing-slide claim.

---

## §4 — "Tools emit ≤20 LOC glue per slice" — PRODUCT §6.1 misaligned with reality

**PRODUCT §6.1 aspiration**: tools emit ≤20 LOC glue per slice; logic lives in primitives.

**Observed reality (`evidence/deterministic/emitted_glue_loc.json`)**: across a 12-tool sample invoked on a fresh `api`-profile scaffold, p50 LOC/handler = 32.6, p95 = 50.3, max = 66.3. The aspirational ceiling of 20 is exceeded by every percentile.

This is the most material misalignment in the package. The earlier `loc_budget_stats.json` measured pedagogical examples (hand-written, zero venous imports) and labelled the result as PRODUCT §6.1 evidence — that labelling was misleading and is rewritten in EVIDENCE.md §2.

**Milestone to close:** v1.1+ — redesign the worst-offender tools so the emitted glue ratio approaches the ≤20 ceiling. Candidates: `add_audit_log` (66 LOC/handler), `add_rbac` (50), `add_oauth2_provider` (49). The problem is not capacity; it is that those tools currently inline what could become primitives.

---

## §5 — "Every tool emits ≥1 `from core.venous` import" — CONTRACT §A2 misaligned with reality

**CONTRACT §A2 aspiration**: every file a tool writes includes ≥ 1 `from core.venous.<ns> import ...`.

**Observed reality**: in the same 12-tool emitted_glue_loc sample, only 5/12 (41.7%) tools emit venous imports anywhere in their delta. The other 7 hand-author the entire feature.

This is the second material misalignment.

**Milestone to close:** v1.1+ — refactor the 7 non-venous-importing tools to compose primitives instead of hand-authoring. The right fix is on the GENERATOR side, not on the contract.

Until then, both §4 and §5 are aspirational targets, not currently-met invariants.

---

## §6 — Property test §3.9 — RUFF_CRITICAL_CLEAN — CLOSED in Wave I-1.L (commit b0080a9)

**LAUNCH.md §1.2 hard pre-tag gate**: `tests/property_tests.py` exits 0.

**Status:** **CLOSED**. Run on commit `b0080a9` shows
`8/8 properties × 123 tools (984/984 tool-checks passed)`. See
`evidence/deterministic/test_suites/property_tests.log`.

**How it was closed:**

1. `_run_ruff_critical` updated to mirror real dev workflow: apply
   tool → `ruff --fix-only --unsafe-fixes` → check residuals.
2. 5 generator sources cleaned of TRUE residual F-violations
   (post-auto-fix): `add_api_deprecation` (unused timedelta),
   `add_dpop_tokens` (unused Encoding/PublicFormat),
   `add_dependency_health_map` (unused time in builder),
   `add_notifications` (kept messaging with noqa for stub),
   `add_request_tracing_ui` (unused time in buffer).
6. `add_api_monetization._patch_models_init` now emits Alembic
   discovery imports with `# noqa: F401` matching the orchestrator's
   convention.

This row is retained as a PASS-after-fix audit trail rather than
deleted, so the Wave-H/I-1 evidence-package history stays legible.

---

## §7 — install-docker.yml nightly streak

**LAUNCH.md §1.2 + §3.3 prerequisite**: `install-docker.yml` nightly green for ≥30 consecutive days before Phase C; ≥2 consecutive nights in 48h pre-tag window.

**Observed reality**: `evidence/deterministic/install_docker_run.log` is SKIPPED-LOCALLY (Wave-H docker daemon offline; locally inert). The CI workflow at `.github/workflows/install-docker.yml` runs the same checks (replicated by `evidence/_harness/install_docker_run.sh`) but `/evidence/` carries no archived nightly run record. Pre-tag, a `gh run list --workflow=install-docker.yml --json status,conclusion,startedAt` capture would close this gap.

**Milestone to close:** the 48h pre-tag CI window. Capture `evidence/deterministic/install_docker_ci_streak.log` from `gh run list` at tag-cut time.

---

## §8 — Independent reviewer 2-of-3 sign-off — LAUNCH.md §5.1 NOT satisfied

**LAUNCH.md §5.1 gating metric**: external reviewer 2-of-3 YES on the canonical sign-off question.

**Observed reality (`evidence/external-eval/reviewer_signoffs/`)**: the three verdict files (codex_v6.md, sonnet.md, opus.md) are SUMMARIES authored by Claude (the evidence-package author). `opus.md:31` confesses author-reviewer identity overlap. Raw transcripts are not archived.

This means the §5.1 gate IS NOT actually satisfied at Wave I-1.

**Milestone to close:** before tag — run three independent reviewer passes against the v1.0.0-rc.1 HEAD with raw transcripts archived in `external-eval/reviewer_signoffs/transcripts/`. The Codex v7 audit (run via `codex exec` on this HEAD; verdict at `/tmp/codex-audit-wave-h-verdict.md`) and the Opus v7 audit (verdict at `/tmp/opus-audit-wave-h-verdict.md`) are GENUINE independent passes; copying their raw transcripts into the package satisfies §5.1.

---

## §9 — Named-human backup on-call (Phase C prerequisite)

**LAUNCH.md §3.3 hard gate before Phase C**: a NAMED human (not an LLM) with commit access + release secrets + paging responsibility + authority to yank, beyond Gustavo.

**Observed reality**: not named. Gustavo is the only on-call human at Wave I-1.

**Milestone to close:** before Phase C opens (LAUNCH.md §3.3 binding). NOT a v1.0.0 tag-gate blocker — Phase A allows solo on-call with explicit acknowledgement (§3.3 final paragraph). The gap IS the gating constraint between Phase B exit and Phase C open.

---

## §10 — Pentest beyond static scan

**PRODUCT §4 "production-grade"** framing.

**Observed reality**: bandit + semgrep static OWASP scans pass clean across 20 examples. No external pentester has been engaged. No load test beyond 5-min soak.

**Milestone to close:** Phase B exit prerequisites — commission an external pentest before Phase C opens.

---

## §11 — Cross-framework SOTA

**PRODUCT §1 framing.** v1.0.0 ships ONE skill: `SKILL-001-fastapi-production`. Any "SOTA backend generation" claim must scope to FastAPI at v1.0.0.

**Milestone to close:** v1.2+ when SKILL-002 (Rust), SKILL-003 (Go), SKILL-004 (Django) ship.

---

## §12 — Token-count fields in single_shot run_manifest

**LAUNCH.md §2.2 PRODUCT §3 mapping** says token cost is evidenced via `run_manifest.json`. Codex v7 HIGH: the manifest schema (in `external-eval/single_shot_benchmark/_harness/run.py`) has `cost_usd_estimate` but no `prompt_tokens` / `output_tokens` / `total_tokens` field. The §3 claim "Maestro discovers skill via MCP metadata (~100 tokens) + loads SKILL.md (~5k tokens)" cannot be evidenced from the current schema shape.

**Milestone to close:** before paid external-eval run — add `tokens` block to `_write_manifest()` capturing per-call provider response usage. Schema-only change.

---

*Every row cites the milestone that would move it from this file into `EVIDENCE.md` proper. Closing a row is a LAUNCH.md §6 amendment (ratification block + Gustavo signature).*
