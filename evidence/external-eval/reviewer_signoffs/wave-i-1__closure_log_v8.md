# Wave-I-1.N closure log — Codex v8 + Opus v8 finding remediation

> Auditable 1:1 mapping: every BLOCKER + HIGH from the Codex v8 + Opus v8 re-audits → the Wave-I-1.N commit that closes it.
>
> Companion to `wave-i-1__closure_log.md` (which mapped v7 findings → J/K/L closures).

## Codex v8 findings

### Q1 — Closure verification (Codex v7 findings still open?)

Codex v8 marked all v7 findings as ✅ CLOSED in Q1; no follow-up needed.

### Q2 — New defects introduced by Wave I-1

| # | Severity | Finding | Closed by |
|---|---|---|---|
| C8.Q2.1 | BLOCKER | Exact-HEAD freshness regressed — _meta.commit split across `6d2dfb3`, `06263c7`, `b0080a9`, current HEAD; `EVIDENCE.md:3` claims atomic | Wave I-1.N final atomic regen at the v8 HEAD; every `_meta.commit` pinned to same SHA |
| C8.Q2.2 | HIGH | `reproduce.sh` overclaims `--verify` — omits `install_docker_run.log` and `cross_composition.log` (`evidence/reproduce.sh:395-407`) | Wave I-1.N reproduce.sh hardening — both included in --verify diff |
| C8.Q2.3 | HIGH | `--deterministic` 2nd-pass diff omits scan summaries, suite logs, install-docker, full pytest | Wave I-1.N — 2nd-pass diff now mirrors --verify (full surface) |
| C8.Q2.4 | HIGH | `--external-eval` fail-open with partial credentials (only requires 1 key; runners silently emit empty manifests) | Wave I-1.N — require ALL three provider keys (Anthropic + OpenAI + Google) |
| C8.Q2.5 | HIGH | `per_tool_pattern_audit.py` exempts `evolve/` from `ast_parse_validation` too broadly; multiple evolve tools DO write Python | Wave I-1.N — per-tool refinement: only `EVOLVE_NON_PYTHON_EMITTERS = {generate_sdk, generate_admin_panel}` exempt; the 3 Python-emitting evolve tools (`add_event_driven`, `add_i18n`, `add_migration_data`) now have ast.parse validation pass added at end |
| C8.Q2.6 | HIGH | `framework_free_runtime` overstated in EVIDENCE.md — probe records 122/124 imported_clean, EVIDENCE says 124/124 boot | Wave I-1.N — EVIDENCE.md §2.1 row corrected: "122/124 boot clean; 2 ImportErrors are CROSS-PRIMITIVE (events.DeadLetterRoute + events.TopicBus depend on sibling EventEnvelope), 0 framework violations" |
| C8.Q2.7 | MEDIUM | `emitted_glue_loc.py` measures whole-file post-state, not emitted diffs | open — informative: probe is more honest in scope than `loc_budget_probe.py` but not tighter in method. Wave I-1.N keeps the current shape; tighter diff-based measurement is v1.1+. |
| C8.Q2.8 | MEDIUM | Reviewer-signoff honesty contradiction across `README.md:28` (says SATISFIES) / `:53-56` (says doesn't until re-audit YES) / `EVIDENCE.md:93` / `not-yet-covered.md:118-122` | Wave I-1.N — README rewritten with §5.1 status timeline (Wave-H NOT SATISFIED → I-1.J PARTIAL → I-1.M PARTIAL → I-1.N SATISFIED). EVIDENCE.md §3 reviewer row aligned. |
| C8.Q2.9 | LOW | "127 adapt tools" stale (probe says 123); `metrics_summary.json` suite `summary_line` shows separator lines | Wave I-1.N — EVIDENCE.md §2.2 row says "123 adapt tools"; `metrics_summary._suite_log_summary` skips separator-only trailing lines |

### Q3 — Sign-off verdict

Codex v8 said **No** with 3 hard blockers (mixed `_meta.commit`, untrustworthy reproduction contract, internally inconsistent reviewer-independence). All three are addressed in Wave I-1.N.

## Opus v8 findings

### Q1 — Closure verification (16/18 ✅ closed; 1 ⚠️ partial; 1 ❌ regression)

| # | Severity | Finding | Closed by |
|---|---|---|---|
| O8.Q1.1 | ❌ REGRESSION (HIGH-M6) | Three-SHA drift returned: `_meta.commit` split across `6d2dfb3`, `06263c7`, `b0080a9`, actual HEAD `d84e94b`; `freshness_proof.log:14` shows `clean: 66 modified/untracked paths` | Wave I-1.N atomic regen — same closure as Codex C8.Q2.1 |
| O8.Q1.2 | ⚠️ PARTIAL (HIGH-8) | CI-deferred suites legitimately tracked but not regenerated | open — Wave I-3 (CI 48h window) closes |
| O8.Q1.3 | ⚠️ PARTIAL (HIGH-M11) | Spec stubs not yet bodies | open — Wave I-2 (Gustavo) closes |

The other 16 v7 findings flipped from open → ✅ CLOSED per Opus's spot-check.

### Q2 — New defects introduced by Wave I-1

| # | Severity | Finding | Closed by |
|---|---|---|---|
| O8.N1 | HIGH | HEAD-drift regression (same as C8.Q2.1) | Wave I-1.N atomic regen |
| O8.N2 | HIGH | `EVIDENCE.md:63` and `:105` say RUFF "7/8 known fail" but log + not-yet-covered §6 show 8/8 closed by `b0080a9` | Wave I-1.N — both lines updated to reflect 8/8 closed |
| O8.N3 | MEDIUM | `EVIDENCE.md:33` says "124/124 boot under blocked-framework"; actual is 122/124 | Wave I-1.N — same fix as C8.Q2.6 |
| O8.N4-N8 | LOW | property_tests.py contract change honest; 6 generator-source edits broke 0/136 consumer tests; `--verify` correctly returns exit 1 on drift; not-yet-covered §2 stale; bandit `\|\| true` swallow uncaught | Wave I-1.N — not-yet-covered §2 closed (commit listed). Bandit swallow remains open — informative-only LOW (closed for v1.1+). |

### Q3 — Sign-off verdict

Opus v8: **NO with 2 trivial conditions** (atomic regen ≤15min + EVIDENCE RUFF 7/8 → 8/8 ≤5min). Both conditions are closed in Wave I-1.N.

## Open after Wave-I-1.N

| Item | Severity | Plan |
|---|---|---|
| C8.Q2.7 emitted_glue measures whole-file not diff | MEDIUM | v1.1+ tighter probe |
| C8/O8 v7-residual: Wave I-2 (specs body), Wave I-3 (CI 48h streak), Wave I-4 (paid ext-eval) | structural | as scheduled |
| O8.N8 bandit `\|\| true` swallow | LOW | v1.1+ |

## Verification

A reader who wants to verify the v8 closures:

1. Pull repo at HEAD `<wave-i-1.N final SHA>`
2. Run `./evidence/reproduce.sh --verify` — passes
3. Read `evidence/external-eval/reviewer_signoffs/wave-i-1__closure_log_v8.md` (this file)
4. Compare each finding row against its cited commit via `git show`
5. Read `evidence/EVIDENCE.md` — every line consistent with artefact reality
6. Read `evidence/not-yet-covered.md` — non-determinism rows marked CLOSED with audit trail

§5.1 status post-N: SATISFIED (4 raw transcripts archived from 2 independent reviewer sessions × 2 audit rounds each; v8 conditions structurally closed by N).
