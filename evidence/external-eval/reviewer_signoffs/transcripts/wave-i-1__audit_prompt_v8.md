# Codex Audit v8 — Wave I-1 closures (re-audit on post-fix HEAD)

You are running a RE-AUDIT against the same `/evidence/` package you audited in Wave-I-1 v7 (verdict file at `evidence/external-eval/reviewer_signoffs/transcripts/wave-i-1__codex_v7__verdict.md`). Your earlier verdict was conditional NO with 4 BLOCKERs + 7+ HIGHs. Wave I-1 attempted to close every single finding.

Your job NOW: confirm whether the Wave I-1 closures actually addressed your earlier findings (or are theatrical), AND find any NEW defects introduced by the closure work.

## Repo + HEAD context

- **Repo:** `humangr-labs/HuGR_Skills` at `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills`
- **Audit HEAD:** `d84e94b` (4 commits past your v7 audit point)
- **Closure log (your authoritative starting reference):**
  `evidence/external-eval/reviewer_signoffs/wave-i-1__closure_log.md` —
  this file maps each of your v7 findings → the Wave-I-1 commit that
  claims to close it. SPOT-CHECK each row by `git show <commit>` and
  by running the relevant probe; do NOT accept the closure log at
  face value.

## What changed since v7

```
e30571b  Wave I-1 closure: atomic regen — every _meta.commit = 6d2dfb3
6d2dfb3  metrics_summary.py: pickup new probes
059de74  reproduce.sh contract fix + EVIDENCE.md framing + not-yet-covered 6→12
26d14c5  3 probes hardened (framework_free runtime, emitted_glue_loc, grade.py AST)
         + cross_model_fnf + counterfactual run.py + 10 spec stubs + 4 suite logs
c0363e1  per_example_pytest_matrix + generator_idempotence
26e1cfe  5 per-surface attestations (per_tool/primitive/adapter/module/benchmark)
06263c7  I1.J — persist Codex v7 + Opus v7 transcripts (this audit closure)
90218ec  I1.K — fix 2 generator non-determinisms at SOURCE
b0080a9  I1.L — RUFF_CRITICAL_CLEAN 7/8 → 8/8
d84e94b  I1.L closure artefacts
```

## The adversarial questions (re-audit form)

### Q1 — Closure verification (was each v7 BLOCKER actually closed?)

For each row in `wave-i-1__closure_log.md` under "Codex v7 findings",
verify the closure by:

1. Reading the commit cited (`git show <sha>`).
2. Running the relevant probe (`./evidence/reproduce.sh --verify-fast`,
   or directly `.venv/bin/python evidence/_harness/<probe>.py`).
3. Spot-reading the output file.

For each finding, mark one of:

- ✅ CLOSED — the change actually addresses the defect.
- ⚠️ PARTIAL — the change addresses some but not all of the defect.
- ❌ THEATRE — the label changed but substance didn't.
- 🆕 REGRESSION — the change introduced a new defect.

Be specific. Cite file:line for any THEATRE / REGRESSION call.

### Q2 — New defects introduced by Wave I-1

Wave I-1 added ~3000 LOC of new code (probes + harnesses + reproduce.sh
+ EVIDENCE rewrite + 5 generator-source edits). Find any NEW defects:

- Probe bugs? (e.g., per_tool_pattern_audit.py exempts entire categories
  from required patterns — is that exemption honest?)
- reproduce.sh regressions? (does --verify FAIL if it should? does
  --deterministic now correctly enforce byte-identity?)
- Generator-edit regressions? (e.g., did removing `import time` break
  any consumer? did `# noqa: F401` propagate to all needed lines?)
- Honesty regressions? (did EVIDENCE.md or not-yet-covered.md OVERSTATE
  any closure?)

### Q3 — Sign-off verdict

Given Q1 + Q2, answer:

> "Would you sign off on `/evidence/` at HEAD `d84e94b` as sufficient
> proof for the v1.0.0 tag cut today?"

- **Yes / No / Yes-conditional**
- If conditional: top 3 conditions
- If No: hard blockers

Note: full external-eval (paid LLM single_shot/cross_model/counterfactual)
is still deferred to Wave I-4. The §5.1 reviewer-independence question
is what THIS audit closes — your v8 verdict is one of the 2-of-3
required.

## Rules of engagement

- Cite specific files + line numbers
- Do NOT accept the closure log on faith — spot-check
- If you flag a v7 finding as still open, say WHY by line
- ≤2500 words; structured Q1/Q2/Q3
- Severity-tag any new findings: BLOCKER / HIGH / MEDIUM / LOW / NIT
- Try to write to `/tmp/codex-audit-wave-i-1-v8-verdict.md` — sandbox is
  read-only so write may fail; emit the verdict to stdout regardless
  (it will be captured from the codex CLI transcript).
