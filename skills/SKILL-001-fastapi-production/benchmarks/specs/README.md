# Benchmark specs

Plain-English product briefs used by the agent benchmark harness
(CONTRACT §B3). Each spec file contains **four mandatory sections**:

- `## Title` — one line.
- `## Requirements` — bulleted list of what the service must do.
- `## Acceptance criteria` — bulleted list of observable behaviors that
  make the spec "done".
- `## Non-requirements` — bulleted list of explicitly out-of-scope items.

### Rules authored into every spec

1. **No tool hints.** The spec NEVER names a primitive or tool
   (`CircuitBreaker`, `add_rbac`, …). The agent must discover.
2. **No framework hints.** Specs describe behavior, not FastAPI /
   SQLAlchemy / Celery conventions.
3. **Acceptance criteria are machine- or inspection-checkable.** "Fast"
   is not acceptable; "p95 < 200ms at 100 rps" is.

Tiered directories:

- `baseline/` (5) — single-concern services, low ambiguity.
- `mid/` (10) — realistic SaaS cross-sections.
- `adversarial/` (5) — edge cases, contradictions, gaps, hidden scaling.

Scoring rubric: see `engine/bench/rubric.py`.
