## Tool: `performance_baseline`

### Overview parameters
- Tool name: `fastapi_performance_baseline`
- Category: VERIFY
- Complexity: High
- Dependencies: existing FastAPI project, pytest-benchmark, Locust or k6 (optional)
- Signature: `performance_baseline(project_dir: str, baseline_file: str = ".perf.baseline.json", tolerance_pct: float = 10.0, metrics: list[str] | None = None, fail_on_regression: bool = True) -> dict`
- Parameters:
  - `project_dir`: project root
  - `baseline_file`: where per-endpoint p50/p95/p99 are stored
  - `tolerance_pct`: allowed drift before flagging regression (default 10%)
  - `metrics`: subset of `["p50","p95","p99","rps","memory"]`; default all
  - `fail_on_regression`: fail the gate when any metric exceeds tolerance

### Purpose
Capture latency (p50/p95/p99), throughput (rps), and memory baselines per endpoint by running a short controlled load inside the test suite, then compare against a committed baseline on every CI run. Answers "did my refactor slow the API down?" before production ever sees the code. Uses pytest-benchmark for micro-routes and a short Locust/k6 scenario for composite workloads. Emits a regression report with the delta per metric and the probable cause hint (e.g., "p95 latency +18% on /users/{id} — likely new DB query").

### Performance SLOs
- Tool execution time < 60s for 20 endpoints (excluding warmup)
- Files modified ≤ 3 (pyproject.toml, CI workflow, .gitignore)
- Files created ≥ 8 (baseline config, bench harness, CI workflow, report template, tests, Locustfile, Makefile targets, perf markers module)
- Baseline diff < 500 ms
- Report generation < 300 ms
- Zero production overhead

### Key technical decisions
1. **Bench method:** `pytest-benchmark` for per-route micro-bench, Locust for composite
2. **Warmup:** 50 requests discarded before measurement to stabilize JIT/caches
3. **Sample size:** minimum 1000 requests per endpoint for stable p95/p99
4. **Baseline:** JSON with per-endpoint metrics + hardware fingerprint (CPU, RAM, arch)
5. **Regression:** `(current - baseline) / baseline > tolerance_pct`
6. **Hardware drift:** if fingerprint differs, run calibration task to normalize
7. **Endpoint discovery:** auto-detect from `app.routes`, exclude health/metrics
8. **Update:** `--update-baseline` flag, requires justification in commit message
9. **CI integration:** runs on PR + main, posts Markdown table, blocks on regression
10. **Report:** JSON + Markdown + flame graph (optional) via py-spy

### Key invariants
1. Warmup requests are NEVER counted in the metrics.
2. Hardware fingerprint ALWAYS recorded to detect machine drift.
3. Baseline NEVER updates silently — requires explicit flag.
4. Regressions ALWAYS fail when `fail_on_regression=True`.
5. Sample size is ALWAYS >= 1000 per endpoint for p99 stability.
6. Excluded endpoints (health, metrics) NEVER counted.
7. Report is DETERMINISTIC given the same baseline and same measurements.

### User story themes
- 9.1 Basic baseline (US-01..05): capture, compare, pass/fail, tolerance
- 9.2 Regression detection (US-06..10): p95 +15%, memory +20%, rps -12%, multi-metric
- 9.3 Hardware drift (US-11..15): fingerprint change, calibration, normalization
- 9.4 CI integration (US-16..20): PR comment, artifact, block on regression, flame graph
- 9.5 Edge cases (US-21..25): new endpoint, removed endpoint, idempotency, noisy environment

### Test plan categories
- 10.1 Measurement (T-01..06): p50/p95/p99 calc, warmup discarded, sample size
- 10.2 Regression (T-07..12): within tolerance, over tolerance, multi-metric, per-endpoint
- 10.3 Baseline lifecycle (T-13..18): first run, update with flag, reject silent update
- 10.4 CI (T-19..24): exit code, Markdown, annotations
- 10.5 Edge cases (T-25..30): hardware drift, noisy, tool idempotency

### Edge cases (15)
1. First run with no baseline → creates baseline, passes
2. Baseline hardware differs → warning + calibration suggestion
3. New endpoint added → no baseline, skipped (not regression)
4. Endpoint removed → dropped from baseline on update
5. Noisy CI machine → detection via variance threshold (cv > 0.3)
6. Sample < 1000 → test fails with clear message
7. Tolerance 0% → every flake fails (use with care)
8. p99 dominated by single outlier → trimmed mean option
9. Memory leak detected → RSS growing over iterations → flagged
10. Cold cache skews p95 → warmup threshold enforced
11. Endpoint hangs → timeout + mark as regression
12. Tool re-run idempotent
13. Baseline expiry (e.g., 90 days) → stale warning
14. GPU/ARM machine → fingerprint distinguishes
15. Network/disk noise → stddev reported alongside percentiles

### Anti-patterns
- DO NOT measure without warmup (JIT warmup skews p50)
- DO NOT use small sample (< 1000) for p99
- DO NOT compare across machines without calibration
- DO NOT silently accept 5% regressions (they compound)
- DO NOT run perf in production (profiling overhead)
