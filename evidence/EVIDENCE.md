# EVIDENCE.md — v1.0.0 verdict

> **Status:** Wave-H package materialised at HEAD `80cf12c`. Deterministic artefacts captured; external-eval harness wired but not executed (paid runs deferred to pre-tag window, see §3 below).
>
> **Read order:** this doc → `metrics_summary.json` → `not-yet-covered.md` → walk `deterministic/` and `external-eval/` for raw artefacts.

---

## §1 — The two-class verdict (LAUNCH.md §2.0)

| Class | Location | Grade | Basis |
|---|---|---|---|
| **Deterministic** — byte-reproducible on same commit | `evidence/deterministic/` | see §2 | `reproduce.sh --verify` diffs against committed; exit 0 = match |
| **External-eval** — auditable, NOT replayable | `evidence/external-eval/` | see §3 | full run manifests (model IDs, prompts, transcripts, cost) archived; results stochastic |

Any reader who does not trust this file's summary can run `reproduce.sh --verify` on a fresh Docker container. Deterministic claims are either reproduced or they're not.

---

## §2 — Deterministic verdict

Every claim below is covered by an artefact under `deterministic/`. Each artefact carries the command that produced it in its header.

| PRODUCT claim | Artefact | Current reading |
|---|---|---|
| 37 machine-checked invariants green (§1, §6) | `contract_check.log` | **37/37 ALL GREEN** |
| Full test sweep green (§1) | `pytest_full_sweep.log` | **5387 passed / 0 failed / 8 skipped** |
| Catalog `stable_hash` idempotent (§1) | `manifest_idempotence.log` | **00cefc4cc477 matches across 2 rebuilds** |
| Tools emit ≤20 LOC glue (§2, §6.1) | `loc_budget_stats.json` | **p95 = 13.33 LOC/handler across 20 examples (≤20 target)** |
| Primitives framework-free (§2, §6.2) | `framework_free_proof.log` | **124/124 registered primitives, 0 web-framework imports** |
| Emitted code passes bandit (OWASP) | `bandit_scan/` | **20/20 examples clean: 0 High, 0 Medium** |
| Emitted code passes semgrep (OWASP) | `semgrep_scan/` | **20/20 examples clean: 0 ERROR, 0 WARNING, 0 INFO (p/python + p/security-audit + p/owasp-top-ten)** |
| Fresh install path works end-to-end | `install_docker_run.log` | harness authored; CI-canonical (install-docker.yml nightly). Local run skipped — docker daemon offline at Wave-H capture. |
| Every tool has MCP metadata (§6.5) | subset of `contract_check.log` (§B1.5) | covered by 37/37 |
| Semantic registry indexes every primitive (§6.6) | subset of `contract_check.log` (§B1.1) | covered by 37/37 |

**Freshness pin:** `freshness_proof.log` records git commit SHA + working-tree hash at evidence-generation time. If that SHA ≠ the tag commit, this package is stale.

---

## §3 — External-eval verdict

External-eval artefacts require live LLM inference; cost ~$200-500 per full run. At Wave-H the harness is **wired and ready** (`external-eval/_harness/` + per-artefact `README.md`), but paid execution is deferred to the 48h pre-tag window so the evidence lands with fresh model IDs on the tag-cut commit — not on an intermediate HEAD.

| PRODUCT claim | Harness location | Run status at Wave-H |
|---|---|---|
| Single-shot success ≥70% on unseen specs (§4) | `single_shot_benchmark/` | specs + prompt + grader authored; `run_manifest.json` empty |
| Model-agnostic (cross-model variance ≤10%) | `cross_model_fnf/` | 10 specs × 3 models harness authored; manifests empty |
| Cheaper than counterfactual (no-HuGR baseline) | `counterfactual/` | baseline prompt authored; manifests empty |
| External reviewer 2-of-3 sign-off | `reviewer_signoffs/` | **Wave-G triangulation archived** (Codex v6 + Sonnet + Opus verdicts present) |

The reviewer_signoffs row already satisfies its bar; the three others require the pre-tag paid run.

---

## §4 — What this package does NOT prove

See `not-yet-covered.md` for the full list. Summary:

1. MCP server integration against Claude Desktop / Cursor / Zed (manual only; automated IDE-invocation harness is v1.1+).
2. "Generated code survives hand-editing" longitudinal soak (emit-time idempotency covered by `_r_generator_*` rules; edit-then-re-apply soak is v1.1+).
3. "Cheaper than hand-coded" as an absolute claim. `counterfactual/` compares vs same-model no-HuGR baseline; absolute real-team economics is post-launch telemetry (v1.2+).

Hiding these would be exactly the failure mode Codex v6 B2 caught. They are listed explicitly so the evidence package is honest about what it DOESN'T prove, not only what it does.

---

## §5 — Reproduction

```bash
# Fast: just confirm the kit is the kit you think it is.
./evidence/reproduce.sh --verify          # ≤15min, exit 0 = byte-match

# Full: regenerate deterministic from scratch.
./evidence/reproduce.sh --deterministic   # ≤1h, exit 0 = byte-match

# Optional: re-run external-eval (needs LLM API keys, costs money).
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...
./evidence/reproduce.sh --external-eval   # ~2-3h, ~$200-500
```

---

## §6 — Grading standard

- **Deterministic:** binary. Either the diff is empty or it isn't. Any drift = evidence package is stale and the tag is not cuttable until refreshed.
- **External-eval:** archived-and-auditable. LLM inference is stochastic; "SOTA" is measured, not decreed. Per-run `run_manifest.json` records model ID, prompt bundle hash, commit SHA, stable_hash, cost, timestamps, and judge notes. Any reader can inspect the transcripts and disagree with the grading — that's the point.

No metric in this package depends on self-reported opt-in telemetry; that class is in LAUNCH.md §5.2 context-metrics (not gating).

---

*Generated as part of Wave H (2026-04-24). Commit-pinned to `freshness_proof.log`. This file is overwritten by `reproduce.sh --deterministic`; amendments flow through a normal PR like any other repo file.*
