## Tool: `error_rate_analyzer`

### Overview parameters
- Tool name: `fastapi_error_rate_analyzer`
- Category: OPERATE
- Complexity: High
- Dependencies: existing FastAPI project, structlog, Prometheus, optional Loki
- Signature: `error_rate_analyzer(project_dir: str, lookback_hours: int = 24, group_by: list[str] | None = None, threshold_5xx_pct: float = 1.0, threshold_4xx_pct: float = 5.0, sink: str = "prometheus") -> dict`
- Parameters:
  - `project_dir`: project root
  - `lookback_hours`: retention window for in-memory aggregation
  - `group_by`: dimensions to aggregate by, e.g., `["route","status","user_id"]`
  - `threshold_5xx_pct`: alert if 5xx rate exceeds this percentage
  - `threshold_4xx_pct`: alert if 4xx rate exceeds this percentage
  - `sink`: `prometheus`, `loki`, or `console`

### Purpose
Aggregate and categorize errors across all routes to answer "which endpoints are breaking and for whom?". Groups 4xx/5xx by route + status code + optional user dimension, exposes live rates via Prometheus, and writes structured log events to Loki. Computes sliding windows (1m, 5m, 1h) so operators can spot spikes immediately. Generates trend reports (e.g., "error rate for /orders up 300% over last hour") and classifies errors into "expected" (4xx validation) vs "unexpected" (5xx), routing alerts accordingly. Avoids the "we lost an endpoint and found out from customers" failure.

### Performance SLOs
- Middleware overhead < 100 µs per request
- Files modified ≤ 3 (main.py, config.py, pyproject.toml)
- Files created ≥ 8 (middleware, aggregator, metrics, alert rules, dashboard, tests, docs, Makefile)
- Metric export < 50 ms
- Memory bounded (max 10 MB for 24h window at 1k rps)
- Zero blocking on the request path

### Key technical decisions
1. **Middleware:** captures every response, increments counter, records latency
2. **Counters:** `http_errors_total{route, status_class, user_tier}` labels
3. **Sliding windows:** 1m, 5m, 1h rates via Prometheus rate() queries
4. **Structured logs:** `error.route`, `error.status`, `error.exception_type`, `error.user_id` via structlog
5. **Trace correlation:** links each error to its request ID and trace ID
6. **Classification:** 4xx client error vs 5xx server error, with optional custom classifier
7. **Cardinality cap:** route patterns used (not full paths) to avoid unbounded labels
8. **Alert rules:** Prometheus rules YAML included; threshold pct + window
9. **Trend detection:** compares current window to baseline (7-day avg)
10. **CLI mode:** `python -m error_analyzer top --by=route --since=1h`

### Key invariants
1. Middleware NEVER throws on its own errors (safe fallback).
2. Labels are ALWAYS bounded (route patterns, not full paths).
3. 4xx and 5xx are ALWAYS counted separately.
4. Alerts ALWAYS fire through the sink, never silently dropped.
5. Cardinality is ALWAYS < 1000 unique label combinations.
6. Trace IDs are ALWAYS propagated to log entries.
7. Classification is DETERMINISTIC given the same status code + exception.

### User story themes
- 9.1 Basic counting (US-01..05): 4xx, 5xx, route labelled, status code, user tier
- 9.2 Sliding windows (US-06..10): 1m, 5m, 1h, threshold breach, reset
- 9.3 Classification (US-11..15): expected (4xx), unexpected (5xx), custom, exception type
- 9.4 Alerts (US-16..20): Prometheus rule, Loki push, console, trend detected
- 9.5 Edge cases (US-21..25): cardinality bounded, middleware resilient, tool idempotency

### Test plan categories
- 10.1 Middleware (T-01..06): 200, 404, 500, exception, latency, trace ID
- 10.2 Aggregation (T-07..12): counter, labels, cardinality cap, 1m/5m/1h
- 10.3 Classification (T-13..18): 4xx, 5xx, exception, custom, route pattern
- 10.4 Alerts (T-19..24): threshold breach, Prometheus rule, Loki push, trend
- 10.5 Edge cases (T-25..30): middleware exception, idempotency

### Edge cases (15)
1. Route not in registry → labelled as `unknown_route` (capped)
2. 0 requests in window → 0 rate, no alert
3. 100% 5xx rate → alert fires, log entry per request
4. Middleware itself raises → request still completes, error logged
5. Request without user context → `user_tier=anonymous`
6. High cardinality user IDs → grouped by tier only, not ID
7. Trace ID missing → placeholder `no-trace`
8. Structured log sink down → falls back to stdout
9. Prometheus scrape fails → metrics buffered in memory
10. Tool re-run idempotent
11. Alert window rolling boundary → no duplicate alerts
12. Custom classifier raises → falls back to default classification
13. Response streaming → error captured only on abort
14. WebSocket upgrade → skipped (not HTTP error)
15. 1000 rps load → middleware overhead still < 100 µs

### Anti-patterns
- DO NOT label by full path (cardinality explosion)
- DO NOT use exception type alone (misses 4xx)
- DO NOT throw from middleware (kills requests)
- DO NOT mix 4xx and 5xx in one alert (different remedies)
- DO NOT forget cardinality cap (Prometheus OOM)
