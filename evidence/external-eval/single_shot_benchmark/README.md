# single_shot_benchmark/ — 10 unseen specs × 1 shot

## Claim

PRODUCT §4: "Maestro produces running, tested, production-grade backend single-session on ≥70% of fresh specs."

## Method

1. **Corpus.** 10 specs under `specs/` that were NOT part of the benchmark corpus used for `plan_level` / `code_level` training. Each spec is a ~200-word prompt + 3-5 acceptance criteria + 1-2 non-requirements, following the same shape as `benchmarks/specs/` but authored post-freeze specifically for this artefact.
2. **Runner.** `_harness/run.py` drives one Maestro session per spec with the canonical system prompt + HuGR MCP tools available. Single-shot means NO intermediate human guidance; only the initial spec goes in.
3. **Grading.** `_harness/grade.py` checks for each spec:
   - Emitted project boots (`.venv/bin/uvicorn app.main:app` returns 200 on `/healthz`).
   - Emitted `test_*.py` all pass (`.venv/bin/pytest`).
   - `bandit -r app/` returns 0 HIGH + 0 MEDIUM.
   - All acceptance criteria listed in the spec are covered by at least one emitted test.
4. **Scoring.** Pass = all 4 checks green. Grade = `pass_count / 10 × 100`.

## Files

```
single_shot_benchmark/
├── README.md              (this file)
├── specs/
│   ├── 01-*.md ... 10-*.md   (blind specs)
│   └── README.md              (authoring rules + corpus hash)
├── _harness/
│   ├── run.py                 (Maestro session driver)
│   ├── grade.py               (4-check grader)
│   └── prompt.md              (system prompt used for the run)
├── transcripts/              (one dir per spec, populated by run.py)
├── results.json              (populated by grade.py; empty at Wave H)
└── run_manifest.json         (populated by the runner; empty at Wave H)
```

## Why the specs are blind

Codex v6 B5 correctly flagged that if the same specs drove rubric training AND final scoring, the result is self-graded. Blind specs are authored here specifically to sit OUTSIDE the training corpus; the corpus hash recorded in `run_manifest.json` confirms no leakage.

## Wave H status

Harness authored; specs authored in `specs/` placeholder form pending Gustavo's pre-tag sign-off on spec content (authoring blind specs is a 2-3h task). Results empty. Run scheduled inside the 48h pre-tag window per LAUNCH.md §2.0.

## Wave-H concrete authoring deliverable

At commit time the following ARE in-repo:

- This README.
- `_harness/prompt.md` — the system prompt (authored).
- `_harness/grade.py` — the 4-check grader (authored + unit-smoked).
- `_harness/run.py` — the runner skeleton (authored; API key env-var wiring; result writer).
- `specs/README.md` — the spec authoring rules + 10 spec stubs.

Full spec bodies land with Gustavo's pre-tag sign-off (the 10 specs ARE the canonical benchmark at v1.0.0; authoring them needs founder tone).
