# evidence/external-eval/ — auditable, NOT byte-reproducible

> Evidence that requires live LLM inference. Per LAUNCH.md §2.0: archived-and-auditable, never replayable bit-for-bit. Reproducing a cell here means re-running against the same model pins and capturing a fresh `run_manifest.json`; the SHAPE of the archive stays stable, the TOKENS don't.

## Content map

| Directory | Artefact | Bound to which PRODUCT claim |
|---|---|---|
| `single_shot_benchmark/` | 10 unseen specs × 1 model × single-shot success rate | PRODUCT §4 ≥70% target |
| `cross_model_fnf/` | 10 specs × 3 models (Claude + GPT + Gemini) → variance report | PRODUCT §1 model-agnostic (≤10% cross-model variance) |
| `counterfactual/` | Same 10 specs, same model, NO HuGR access → baseline LOC / token / time | PRODUCT §1 "cheaper than hand-coded" (vs same-model baseline) |
| `reviewer_signoffs/` | 3 independent adversarial reviewers (Codex v6 + Sonnet + Opus) | LAUNCH.md §5.1 "2-of-3 YES on sign-off question" |

## Execution policy

At Wave-H commit time:

- `_harness/` directory under each artefact contains the harness (runner script + prompt + grader), NOT the results.
- Execution IS deferred to the 48h pre-tag window (ROADMAP §5.7) so results land with model IDs current at tag cut, not an intermediate HEAD.
- `run_manifest.json` per artefact is empty at Wave H and populated by the first paid `reproduce.sh --external-eval` run.
- Cost envelope: ~$200-500 per full pass across all three artefacts.

## Manifest schema (common across artefacts)

```json
{
    "commit": "<git SHA at time of run>",
    "tree": "<git tree SHA>",
    "stable_hash": "<catalog.json stable_hash at time of run>",
    "model": {
        "id": "<provider:model-id>",
        "pinned_at": "<ISO8601>",
        "params": {"temperature": 0, "top_p": 1, "seed": null}
    },
    "prompt_bundle_hash": "<sha256 of concatenated prompt files>",
    "tool_manifest_hash": "<sha256 of tools/* discovered>",
    "run_started": "<ISO8601>",
    "run_completed": "<ISO8601>",
    "cost_usd_estimate": 0.0,
    "results_file": "./results.json",
    "transcripts_dir": "./transcripts/",
    "grader_version": "<harness file SHA or git SHA>",
    "judge_notes": "<free-form human notes from reviewer>"
}
```

## Why external-eval is NOT gating at Wave H

Per LAUNCH.md §5.1, gating metrics must be closed-loop + falsifiable. External-eval results ARE falsifiable (wrong answers are checkable), but they require cost and fresh runs to have meaning — a stale run_manifest from 3 months ago would be a lie-by-timestamp. Gating therefore runs the external-eval IN the 48h pre-tag window, so the numbers on the tag commit are the numbers the public can reproduce.
