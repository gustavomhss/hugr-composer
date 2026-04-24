# cross_model_fnf/ — Fresh-N-Foreign: 10 specs × 3 models

## Claim

PRODUCT §1: "kit is model-agnostic — same quality result across frontier LLMs."

## Method

1. **Corpus.** Same 10 blind specs as `single_shot_benchmark/specs/`.
2. **Models.** Three frontier LLMs in parallel, same prompt bundle, same tools:
   - Claude Opus 4.7 (`anthropic:claude-opus-4-7-20260101` pinned at run time)
   - GPT-5.1-pro (`openai:gpt-5.1-pro-20260401` pinned at run time)
   - Gemini 2.5 Ultra (`google:gemini-2.5-ultra-20260215` pinned at run time)
3. **Runner.** `_harness/run.py` orchestrates 30 runs (10 specs × 3 models). Each run uses the SAME prompt bundle as `single_shot_benchmark/_harness/prompt.md`.
4. **Grading.** Same `grade.py` as single_shot_benchmark — 4 checks per run.
5. **Variance.** `_harness/variance.py` computes:
   - per-spec: max(model_score) - min(model_score) across the 3 models
   - across-specs: `stddev(overall_score_per_model) / mean(overall_score_per_model)` (CV%)
6. **Target:** CV ≤10% → kit carries the weight. CV >10% → the user's model choice drives the result, and "model-agnostic" is weaker than claimed.

## Files

```
cross_model_fnf/
├── README.md
├── _harness/
│   ├── run.py              (orchestrates 30 runs)
│   ├── variance.py         (post-run analysis)
│   └── prompt.md           (symlink → ../single_shot_benchmark/_harness/prompt.md)
├── transcripts/            (30 subdirs: <spec>_<model>/...)
├── results.json            (populated; empty at Wave H)
├── variance_report.json    (populated; empty at Wave H)
└── run_manifest.json       (one block per model column; empty at Wave H)
```

## Why same prompt, not model-specific tuning

Model-specific prompt tuning would mask the kit's contribution: if each model gets its own hand-tuned scaffolding prompt, what we measure is prompt-tuning skill, not kit quality. Same prompt = same conditions = honest comparison.

## Cost

Three providers × 10 specs × ~30k tokens/spec ≈ $75-$150 per full pass.

## Wave H status

Harness authored (`run.py` skeleton + `variance.py` formula). Execution deferred to the 48h pre-tag window per LAUNCH.md §2.0. Results empty.
