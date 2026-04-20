# `benchmark/` — code-level analyzer (MCP tool surface)

This directory contains the **`fastapi_analyze`** MCP tool
(`benchmark/analyzer.py`) that mechanically checks a generated
FastAPI project against structural requirements (routes, auth
middleware, rate limiting, health probes, etc.). It is consumed by
`generators/tools/fix_findings.py` and surfaced to the Maestro via
`mcp_tools.discovery`.

## Why two directories named `benchmark` / `benchmarks`?

They are distinct surfaces:

| Path | Role | Consumer |
| --- | --- | --- |
| `benchmark/analyzer.py` | **Code-level analyzer** — runs against an *emitted* project, returns structured findings. | `fastapi_analyze` MCP tool + `fix_findings.py` |
| `benchmarks/` | **Spec-level benchmark harness** (Phase 3) — scores the kit against 20 plain-English product specs. | `engine.bench.runner` + nightly CI |

Merging them is tracked as a v0.2.0 polish item (renaming either
directory is a surface-breaking change that needs coordinated
rollout across documentation + importers).

## What was archived 2026-04-20 (v0.1.0 release)

Removed from this directory during the close-v0.1.0 sprint:

- `test_e2e_agent.py`    — pre-Phase-3 E2E harness; superseded by
                           `tests/test_e2e_hardcore.py` +
                           `tests/test_e2e_postgres.py`.
- `test_functional.py`   — pre-Phase-3 functional proof of the
                           generated app; superseded by the skill's
                           behavior scenarios + examples/.
- `test_generators.py`   — superseded by the per-tool unit tests
                           under `adapt/**/test_*.py` (3168 passing).
- `test_integration.py`  — superseded by `engine/tests/test_integration.py`.
- `import_audit.py`      — one-shot script from the Phase-1
                           reconnection pass; its findings are now
                           encoded as CONTRACT §B1.3.

And from `benchmarks/`:

- `run_finhealth.py`     — pre-Phase-3 "FinHealth" benchmark; the
                           Phase-3 harness supersedes it end-to-end.
- `HARDCORE_BENCHMARK.md` — design doc for the FinHealth harness.
- `v0_score.json`        — first pass of the Phase-3 score; now
                           stored via git history of `latest_score.json`.
