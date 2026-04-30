# Blind Benchmark Protocol — HuGR Smith v1

> **Purpose.** Third-party-credible measurement of whether the kit improves
> an LLM agent's ability to produce a working backend from a plain-English
> spec, AND harvest of every signal needed to fine-tune a SOTA backend
> agent on this data.
>
> **Pre-registration date:** 2026-04-20. Any design change after this
> date ships as a new protocol version (v2, v3, ...) — past runs are
> preserved verbatim and never re-scored under a new rubric.

---

## 0. Threat model — what would make this bench cheap

A naïve bench is easy to game:

- **Specs recognizable from training data** → naked Opus ≥ 80%. Signal dies.
- **Self-judging** → conflict of interest; reviewers discount the number.
- **Happy-path only** → agent writes code that passes smoke tests but
  breaks under contention, partial failure, or edge cases.
- **Aggregate-only scores** → no ablation signal; can't tell WHY kit helped.
- **No preference pairs** → data can't drive DPO/RLHF.

This protocol counters each threat explicitly. See §3 (spec authoring),
§4 (judge design), §5 (transcript schema), §6 (preference-pair emission).

---

## 1. Hypothesis (pre-registered)

**H0** — Kit has no effect: `mean(score_kit) − mean(score_naked) ≤ 5 pts`
on the hard tier.

**H1** — Kit helps substantively: `mean(score_kit) − mean(score_naked) ≥ 25 pts`
on the hard tier.

**H2** — Kit expands ceiling: `max(score_kit) − max(score_naked) ≥ 30 pts`
on the impossible tier.

Secondary: kit reduces variance (`stdev(score_kit) < stdev(score_naked)`),
tokens-per-pass (`tokens_kit / pass_kit < tokens_naked / pass_naked`), and
time-to-first-pass.

Any change to these numbers invalidates the pre-registration — must be
declared openly in the commit message and a new protocol version cut.

---

## 2. Conditions (two-arm, identical base agent)

| Arm | Base | MCP tools available | Prompt |
|---|---|---|---|
| **naked** | Claude Opus/Sonnet via CLI subagent | none (no `--mcp-config`) | base brief |
| **kit**   | Same model / temperature | SKILL-001 MCP (201 tools) | base brief + kit-tools announcement paragraph |

> **Prompt-parity exception (v1.1, 2026-04-20).** The first live run on
> `hard/01` surfaced that an MCP surface being AVAILABLE is not the same
> as being USED — Claude ignored the kit entirely and scored identically
> to naked (38.46 vs 38.46, zero margin). The kit arm's prompt therefore
> includes an explicit paragraph listing the MCP tool families
> (`fastapi_meta_search_primitive`, `fastapi_meta_search_composition`,
> `fastapi_add_*`, `fastapi_generate_project`) so the agent knows they
> exist. The BRIEF text is byte-identical across arms — the announcement
> is a prompt-scaffolding delta, not a task-information delta. A
> reviewer can confirm via the `brief_sha256` field, which matches
> across conditions.

Constants held across arms:
- Model + temperature + max-tokens
- System prompt (thin harness wrapper, no task hints)
- Wall-clock timeout per spec
- Emission workdir layout
- Base image / Python version

**Randomization.** Condition order randomized per-seed to avoid cache-warmth
bias. Seeds: `[7919, 15485863, 2038074743]` (three distinct primes).

---

## 3. Spec authoring rules

A spec passes authoring review iff ALL hold:

1. **Post-training-cutoff brief.** Author guarantees the specific wording
   + acceptance bullets were not in any public corpus before 2026-01-01.
   Specs can reference well-known primitives (HMAC, JWT) but must combine
   them in a way not pre-solved in a public tutorial.

2. **Sealed judge.** Test files NEVER shown to the agent. Agent sees only
   `brief.md`. Judge acceptance criteria are written BEFORE authoring the
   reference solution, not after.

3. **Naked-baseline prediction.** Author estimates naked-Opus pass rate
   **before** the first live run. Post-hoc adjustments are tracked.

4. **Difficulty-axis labels.** Each spec declares which axes it stresses
   (concurrency, exactly-once, causal order, multi-invariant conflict,
   failure-injection, property-based, large-n scaling).

5. **Required primitives.** Author lists which `core/venous/*` primitives
   a SOTA solution imports — used for ablation attribution in §7, not
   scoring.

6. **Reproducibility.** Boot command declared (`uvicorn <mod>:app`), health
   probe declared, teardown deterministic. Judge runs in ≤ 3 minutes.

### Tiers

| Tier | Predicted naked | Predicted kit | Role |
|---|---|---|---|
| calibration (2 specs) | 75-95% | 80-95% | harness sanity |
| hard        (10 specs) | 10-40% | 55-85% | discrimination |
| impossible  (3 specs)  | 0-15%  | 30-60% | ceiling expansion |

---

## 4. Judge architecture

The judge is **sealed** (not shown to the agent), **mechanical** (no LLM
in the judging loop), and **multi-layer** to prevent happy-path gaming.

**Layer A — Functional tests.** `pytest` against the emitted app
(via FastAPI TestClient or uvicorn + `httpx`). Every bullet of `brief.md
## Acceptance criteria` maps to ≥ 1 test.

**Layer B — Property-based.** `hypothesis` generates inputs (random
transfer graphs, malformed webhooks, out-of-order deliveries). Minimal
failing case recorded per test.

**Layer C — Concurrency stress.** `asyncio.gather` with N ≥ 100 parallel
requests; assert invariants (conservation, exactly-once, session
consistency) after the storm.

**Layer D — Failure injection.** Deterministic chaos: kill the app
subprocess at pre-registered cut-points; kill simulated dependencies
(DB, broker). Assert recovery.

**Layer E — Code-level static.** AST scan of emitted code:
- disallow `float` where money is handled (Spec 01 etc.)
- detect missing idempotency stores
- detect in-memory session state in a multi-node-claim spec

Each layer emits `test_results.jsonl` with one line per assertion:

```json
{"layer": "C", "test_id": "conservation_under_1000_parallel",
 "outcome": "fail", "elapsed_ms": 842, "bucket": "concurrency",
 "hypothesis_minimal": {...}, "stderr_snippet": "..."}
```

**Score** = `100 × passed / (passed + failed + error)` across all layers.
Per-layer + per-bucket subscores also emitted for ablation.

---

## 5. Trajectory schema (fine-tuning-grade)

Every run produces a canonical directory:

```
results/<run_id>/<spec_id>/<condition>/<attempt>/
├── meta.json                   # model, temp, seeds, git SHAs, MCP hash, timestamps
├── brief.md                    # copy of the agent-visible brief (redundant but self-contained)
├── trajectory.jsonl            # agent transcript; one JSON object per turn
├── tool_calls.jsonl            # flat per-tool-call log (extracted from trajectory for convenience)
├── file_snapshots/
│   ├── 00_initial.tar.zst      # empty workdir
│   ├── 01_after_turn_001.tar.zst
│   ├── ...
│   └── final.tar.zst           # last emission
├── emitted/                    # plain dir of final artifact (== final.tar.zst)
├── judge/
│   ├── boot_log.txt            # uvicorn subprocess stdout/stderr
│   ├── test_results.jsonl      # per-test outcome with all metadata
│   ├── chaos_log.jsonl         # chaos events + responses
│   └── static_scan.json        # Layer E findings
└── metrics.json                # aggregate reward signal per §6
```

### `trajectory.jsonl` line format (one turn per line)

```json
{
  "turn": 0,
  "timestamp": "2026-04-20T17:03:11Z",
  "role": "system" | "user" | "assistant" | "tool",
  "model": "claude-opus-4-7",
  "content": [  // Anthropic content-block shape, preserved
    {"type": "text", "text": "..."},
    {"type": "tool_use", "id": "...", "name": "...", "input": {...}},
    {"type": "tool_result", "tool_use_id": "...", "content": "..."}
  ],
  "usage": {"input_tokens": 1234, "output_tokens": 567, "cache_read": 0, "cache_creation": 0},
  "latency_ms": 3421,
  "workdir_snapshot_after": "file_snapshots/01_after_turn_001.tar.zst",
  "score_after": 0.25,           // judge re-run after this turn (optional; only at checkpoints)
  "score_delta": +0.05
}
```

This format is compatible with:
- **Anthropic agent traces** (direct subset)
- **HuggingFace SFT** (`messages` field after flattening)
- **DPO pairs** (see §6)
- **Process-reward-model training** (turn-level `score_delta`)

### Workdir snapshots

`tar.zst` at every tool-use turn that writes to disk. Enables:
- Step-level rewards (diff + judge → did this step help?)
- Counterfactual rollback (what if the agent had stopped at turn 5?)
- Deterministic replay

Compression ratio on typical FastAPI project: ~ 20×. ~5 MB raw → ~250 KB.

---

## 6. Metrics emitted (`metrics.json`)

Aggregate over one run:

```json
{
  "identity": {
    "run_id": "...",
    "spec_id": "hard/01_financial_ledger",
    "condition": "kit",
    "attempt": 1,
    "model": "claude-opus-4-7",
    "temperature": 0.7,
    "seed": 7919,
    "kit_commit": "d26ad99",
    "mcp_config_hash": "...",
    "harness_version": "1.0.0"
  },
  "outcome": {
    "final_score": 73.4,
    "boot_status": "success",
    "emit_status": "success",
    "tests_passed": 11,
    "tests_total": 15,
    "per_layer": {"A": 100, "B": 75, "C": 60, "D": 50, "E": 100},
    "per_bucket": {
      "concurrency": 40, "exactly_once": 100, "type_safety": 100,
      "failure_recovery": 50, "multi_invariant": 67
    }
  },
  "efficiency": {
    "wall_clock_s": 412,
    "input_tokens": 24567, "output_tokens": 12483,
    "cache_read_tokens": 8124, "cache_creation_tokens": 4231,
    "tool_calls_total": 31, "tool_calls_distinct": 12,
    "files_emitted": 18, "lines_emitted": 1432,
    "time_to_first_test_pass_s": 178, "time_to_best_score_s": 394
  },
  "kit_attribution": {
    "mcp_tools_called": {"fastapi_add_rbac": 1, "fastapi_meta_search_primitive": 3, ...},
    "primitives_imported": ["Repository","UnitOfWork","AuditEvent",...],
    "primitives_required_by_spec": ["UnitOfWork","OptimisticConcurrency","TransactionalOutbox","AuditEvent"],
    "coverage_of_required": 0.75,
    "unexpected_imports": ["RateLimiter"]
  },
  "failure_signals": {
    "used_float_for_money": false,
    "missing_idempotency_store": false,
    "in_memory_session_store": true,    // a failure mode, caught by static scan
    "race_condition_detected": true,
    "naive_error_handling": false
  },
  "process_rewards": [
    {"turn": 3, "delta": +10, "reason": "first successful DB model"},
    {"turn": 7, "delta": -5,  "reason": "introduced race in transfer handler"},
    {"turn": 12, "delta": +15, "reason": "fixed race via UnitOfWork primitive"}
  ]
}
```

Every field is machine-harvestable. `metrics.json` across all runs merges
into a single training-ready table.

---

## 7. Fine-tuning-ready artifact emission

Post-run, the harness emits:

### a) `pairs.jsonl` — DPO preference pairs

For every (spec, attempt) where both conditions ran:

```json
{
  "spec_id": "hard/01_financial_ledger",
  "prompt": "<brief.md contents>",
  "chosen": {"trajectory": "<path>", "score": 73.4, "condition": "kit"},
  "rejected": {"trajectory": "<path>", "score": 28.1, "condition": "naked"},
  "margin": 45.3,
  "chosen_metrics": {...},
  "rejected_metrics": {...}
}
```

Pairs where `margin < 10 pts` are excluded (noise). Pairs where `naked >
kit` are NOT flipped — recorded in a separate `anti_pairs.jsonl` and
investigated (may indicate a kit bug to fix).

### b) `sft.jsonl` — flat supervised-fine-tuning records

Only from runs that achieved `score ≥ 90`:

```json
{
  "messages": [...],           // trajectory flattened
  "metadata": {"spec_id": "...", "score": 95.2, "condition": "kit"}
}
```

Curation policy: successful kit trajectories are the primary SFT source.
Naked successes also included (captures cases where raw Opus suffices).
Failed runs NOT included in `sft.jsonl` but preserved raw for RLHF.

### c) `process_rewards.jsonl` — turn-level signal for PRM training

One record per turn, across ALL runs (even failures):

```json
{
  "spec_id": "...", "run_id": "...", "turn": 7,
  "state_before": "<hash of workdir>",
  "action": {"type": "tool_use", "name": "Write", "input": {...}},
  "state_after": "<hash>",
  "score_before": 25.0, "score_after": 20.0,
  "reward": -5.0,
  "reward_category": "regression"
}
```

### d) `rubric_traces.jsonl` — per-assertion explanations

Every judge test emits a structured record explaining WHY it passed or
failed. Usable for training a rubric-generation model.

---

## 8. Contamination guards

- **Temporal hash.** Each spec's `brief.md` is hashed (sha256); hash
  committed with spec. Hash appears in every trajectory — verifies that
  the same brief was used.
- **Proxy detection.** If an agent's trajectory contains verbatim spec
  text from a different spec (cross-leakage), that run is flagged.
- **No-internet mode.** Agent runs in a sandboxed workdir with no
  network access (except MCP tools, which are explicit + logged).
- **Spec-author recusal.** Whoever writes a spec cannot audit runs of
  that spec.

---

## 9. Publishing + reproducibility

After each run set, the harness writes:

```
benchmarks/blind/results/<run_id>/
  aggregate.json                # tier-level + overall + by-condition
  pairs.jsonl                   # as §7a
  sft.jsonl                     # as §7b
  process_rewards.jsonl         # as §7c
  rubric_traces.jsonl           # as §7d
  MANIFEST.json                 # full set of run IDs + SHAs
```

All results are additive — past runs never overwritten. `latest.json` is
a symlink/pointer to the most recent `<run_id>`.

A third party can reproduce by:
1. Clone repo at committed SHA.
2. `./scripts/blind_run.sh <spec> <condition> <seed>`
3. Compare emitted `metrics.json` with the published one.

---

## 10. Known limitations

- **Single model family.** Starts with Claude. Extending to GPT / Gemini
  requires adapter wiring (planned v2).
- **English-only specs.** i18n deferred.
- **No UI eval.** Backend-only.
- **Self-authored specs.** Until external parties contribute adversarial
  specs, there remains an authoring-bias risk. Mitigated by: (a) sealed
  judges, (b) pre-registered naked-baseline predictions, (c) full
  transcript transparency.

---

Signed: Gustavo Schneiter — pre-registration 2026-04-20.
Changes after this date require a protocol version bump.
