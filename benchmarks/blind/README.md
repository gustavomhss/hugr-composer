# Blind Benchmark — HuGR SkillKit

> **Third-party-credible measurement** of whether the kit improves an
> LLM agent's ability to produce a working backend from a plain-English
> spec, AND fine-tuning-grade harvest of every signal needed to train
> a SOTA backend agent on this data.
>
> **Read `PROTOCOL.md` first.** It is pre-registered (2026-04-20) and
> governs the design choices here. Changes require a protocol version
> bump and invalidate prior runs.

## Layout

```
benchmarks/blind/
├── PROTOCOL.md               # pre-registered hypothesis, schema, guarantees
├── README.md                 # this file
├── specs/
│   └── <tier>/<NN>_<slug>/
│       ├── brief.md          # agent-visible product brief
│       ├── metadata.json     # tier, difficulty axes, predicted scores,
│       │                     # required primitives, boot_command, …
│       └── judge/
│           ├── conftest.py
│           ├── test_A_functional__*.py     # Layer A — smoke
│           ├── test_B_property__*.py       # Layer B — hypothesis
│           ├── test_C_concurrency__*.py    # Layer C — asyncio stress
│           ├── test_D_chaos__*.py          # Layer D — failure injection
│           ├── test_E_static__*.py         # Layer E — AST scan only
│           └── static_scan.yaml            # extra rules for Layer E
├── _stub_fixtures/
│   └── <spec_slug>/
│       ├── naked/emitted/    # deliberately-flawed reference
│       └── kit/emitted/      # SOTA reference
└── results/
    └── <run_id>/
        ├── MANIFEST.json
        ├── aggregate.json
        ├── pairs.jsonl        # DPO preference pairs
        ├── anti_pairs.jsonl   # cases where naked beat kit (investigate)
        ├── sft.jsonl          # supervised records from high-scoring runs
        └── <spec_slug>/<condition>/<attempt>/
            ├── meta.json
            ├── brief.md
            ├── trajectory.jsonl
            ├── tool_calls.jsonl
            ├── judge/{boot_log.txt,test_results.jsonl,pytest_report.json}
            ├── emitted/                    # final artefact
            └── metrics.json                # aggregate reward signal
```

## Running

### Stub (plumbing validation — no LLM needed)

```bash
PYTHONPATH=. .venv/bin/python -m engine.bench.blind.runner --stub
```

Uses `_stub_fixtures/` to copy a deliberately-flawed "naked" emission
and a SOTA "kit" emission into workdirs, then runs the full judge
pipeline. Expected:

- naked: boot success, final_score in [15, 35]
- kit:   boot success, final_score ≥ 90
- margin (kit − naked) ≥ 25 → H1 trivially supported on stub

### Live (Claude CLI subagent)

Requires locally-authenticated `claude` CLI.

```bash
# Single spec, one seed, both conditions
PYTHONPATH=. .venv/bin/python -m engine.bench.blind.runner \
    --spec hard/01_financial_ledger --seeds 7919

# Full run (3 specs × 2 conditions × 3 seeds = 18 runs, ~30-90 min)
PYTHONPATH=. .venv/bin/python -m engine.bench.blind.runner
```

Conditions:
- **naked** — `claude -p "<brief>" --model <M>` with NO `--mcp-config`
- **kit**   — same, plus `--mcp-config examples/claude_code.mcp.json`

Model + temperature fixed in `adapter.ClaudeCliConfig` defaults; override
via `--model`.

## Interpreting results

Every run produces `aggregate.json` under `results/<run_id>/`. Key fields:

```json
"hypothesis_test": {
  "H1_hard_tier_gap_mean": 37.5,
  "H1_threshold": 25.0,
  "H1_supported": true,
  "H2_impossible_tier_ceiling_gap": 42.0,
  "H2_threshold": 30.0,
  "H2_supported": true
}
```

These two booleans are the ONLY claim we make. Aggregate statistics are
descriptive; pre-registered hypothesis is the load-bearing output.

## Fine-tuning pipeline consumption

After a run, `pairs.jsonl` + `sft.jsonl` + (in v1.1) `process_rewards.jsonl`
are ready for:

- **DPO / IPO / KTO** — `pairs.jsonl` is `{chosen, rejected, margin}` per spec
- **SFT** — `sft.jsonl` is HuggingFace-compatible messages
- **PRM training** — `process_rewards.jsonl` is turn-level deltas (landing
  in v1.1 once snapshot-per-turn is wired)

All data is additive across run_ids; no historical result is ever
overwritten.

## Spec authoring

New specs must pass `load_spec()` validation:

- `brief.md` under the spec directory
- `metadata.json` with all required keys (see `spec.py::Spec`)
- `judge/` with at least one `test_*.py`, naming convention
  `test_<A|B|C|D|E>_<bucket>__<descriptor>`
- Predicted naked score must fall within the tier's declared band:

| Tier         | Naked band | Kit band |
|--------------|-----------:|---------:|
| calibration  |   75 – 95  |  80 – 95 |
| hard         |   10 – 40  |  55 – 85 |
| impossible   |    0 – 15  |  30 – 60 |

Predictions outside the band cause validation to fail — the spec either
belongs in a different tier or was mis-estimated.

## Current state (v0.2.0 → v0.3.0 in-flight)

- **1 seed spec** written: `hard/01_financial_ledger`
- **Stub adapter + fixtures** validated (plumbing end-to-end)
- **Live Claude CLI adapter** implemented but not yet exercised at scale
- **2 more hard specs** + **2-3 impossible** specs queued for v0.3.0
