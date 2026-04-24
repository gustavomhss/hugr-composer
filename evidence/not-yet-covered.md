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

**PRODUCT §6.3 claim.** Emit-time idempotency IS covered: the orchestrator-twice probe (`evidence/deterministic/generator_idempotence.json`) proves byte-identical re-emission across `minimal`, `api`, and `full` profiles when `PYTHONHASHSEED=0` is pinned.

What this does NOT prove:

- **Longitudinal soak:** "apply tool → hand-edit → apply tool → hand-edit → apply tool" over N cycles, across many projects and edit styles, without divergence.
- **Hash-randomization-independent reproduction:** `generators/middleware/request_logging.py` uses `repr({'authorization', 'cookie', 'x-api-key'})` directly on a set; without `PYTHONHASHSEED=0` the iteration order is non-deterministic. Fix: sort the set before repr-ing in the generator source.
- **Timestamp-independent reproduction:** `core/venous/.../_origin.json` records `copied_at` host timestamp under the orchestrator's project-emit shape. Excluded from the diff today; pin to commit SHA or build-time env var to remove.

**Milestone to close:** v1.1+ — soak-edit harness + remove the two known generator non-determinisms (request_logging set, copied_at timestamp).

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

## §6 — Property test §3.9 — RUFF_CRITICAL_CLEAN 7/8

**LAUNCH.md §1.2 hard pre-tag gate**: `tests/property_tests.py` exits 0.

**Observed reality (`evidence/deterministic/test_suites/property_tests.log`)**: 7 of 8 properties pass. RUFF_CRITICAL_CLEAN fails on ~119 of 123 emitted templates due to F401 unused imports + F541 empty f-strings in the EMITTED OUTPUT (not the tools themselves; not the kit code).

This is a tag-gate blocker per LAUNCH.md §1.2 unless either:

- The emitted-template style is fixed (Wave-2 cleanup per ROADMAP.md §6.1).
- Gustavo ratifies an explicit carve-out in CONTRACT.md §E for v1.0.0.

**Milestone to close:** before tag — choose fix-or-ratify; both paths are explicit.

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
