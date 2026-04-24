# counterfactual/ — baseline run without HuGR access

## Claim

PRODUCT §1 implicit: "cheaper + faster than hand-coded from scratch (with the same model)."

## Method

1. **Corpus.** Same 10 blind specs.
2. **Model.** Same model as `single_shot_benchmark/` (default: Claude Opus 4.7).
3. **Baseline prompt** (`_harness/baseline_prompt.md`): instructs Maestro to produce the same output shape WITHOUT access to the HuGR MCP server. The model must hand-author every route, test, and middleware from scratch.
4. **Runner.** `_harness/run.py` drives 10 runs (10 specs × 1 model × no-HuGR) in parallel with the WITH-HuGR runs; results compared spec-by-spec.
5. **Grading.** Same 4-check `grade.py` as single_shot_benchmark.
6. **Deltas:**
   - `tokens_delta`: WITH-HuGR input+output tokens / WITHOUT-HuGR input+output tokens
   - `wallclock_delta`: WITH / WITHOUT (median over 10 specs)
   - `loc_delta`: emitted LoC WITH / WITHOUT
   - `grade_delta`: WITH 4-check pass rate / WITHOUT 4-check pass rate

## Why this is HONEST and LIMITED

Codex v6 correctly flagged that "cheaper than hand-coded" is TWO claims:

1. **Same-model relative claim** (what this artefact measures): given the same LLM, does having HuGR make the output cheaper / better? Falsifiable; either the delta lands or it doesn't.
2. **Real-team absolute claim** (what this artefact does NOT measure): is HuGR cheaper than a real human engineer writing FastAPI? That needs population-scale telemetry from Phase B+ cohort and is tracked in `not-yet-covered.md` §3.

Honest framing: at v1.0.0 we evidence the RELATIVE form. The absolute form is v1.2+ with real-team telemetry.

## Files

```
counterfactual/
├── README.md
├── _harness/
│   ├── baseline_prompt.md      (no-HuGR system prompt)
│   ├── run.py                  (10 baseline runs + delta analysis)
│   └── compare.py              (produces results.json)
├── transcripts/                (10 subdirs, one per spec)
├── results.json                (populated; empty at Wave H)
└── run_manifest.json           (populated; empty at Wave H)
```

## Cost

10 specs × 1 model × ~40k tokens/spec (baseline produces MORE code per spec because no primitive reuse) ≈ $35-$70 per pass.

## Wave H status

Harness authored (baseline prompt + runner skeleton). Execution deferred to the 48h pre-tag window per LAUNCH.md §2.0. Results empty.
