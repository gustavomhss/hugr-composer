## Tool: `connection_pool_monitor`

### Overview parameters
- Tool name: `fastapi_connection_pool_monitor`
- Category: OPERATE
- Complexity: High
- Dependencies: existing FastAPI project, SQLAlchemy async, Redis (optional), Prometheus client
- Signature: `connection_pool_monitor(project_dir: str, pool_size: int = 20, max_overflow: int = 10, timeout_s: float = 30.0, alert_threshold_pct: float = 80.0, metrics_port: int = 9100) -> dict`
- Parameters:
  - `project_dir`: project root
  - `pool_size`: steady-state connections per worker
  - `max_overflow`: extra connections allowed under burst
  - `timeout_s`: acquire timeout before a request fails
  - `alert_threshold_pct`: pool utilization percentage that triggers a warning metric
  - `metrics_port`: Prometheus endpoint port

### Purpose
Instrument SQLAlchemy (and optionally Redis) connection pools with detailed metrics: active/idle counts, wait times, acquire failures, peak usage, recycling events. Exposes Prometheus metrics so operators can alert on pool exhaustion **before** requests start failing. Also provides a `/pool/health` endpoint returning structured JSON for load balancers, and a CLI mode for printing a live snapshot. Critical for high-load APIs where silent pool exhaustion causes cascading 504s.

### Performance SLOs
- Instrumentation overhead < 50 µs per acquire
- Files modified ≤ 3 (config.py, main.py, pyproject.toml)
- Files created ≥ 8 (monitor module, metrics module, health route, alert rules, dashboard, tests, docs, Makefile targets)
- Metric scrape time < 50 ms
- Event loop overhead negligible
- Zero impact on normal acquire path

### Key technical decisions
1. **SQLAlchemy events:** `pool.checkout`, `pool.checkin`, `pool.connect`, `pool.invalidate`
2. **Prometheus metrics:**
   - `db_pool_active_connections{pool="default"}` gauge
   - `db_pool_wait_seconds_bucket{}` histogram
   - `db_pool_acquire_total{result="success|timeout|error"}` counter
   - `db_pool_overflow_total{}` counter
3. **Pool health endpoint:** `/pool/health` returns utilization, wait p95, recycle count
4. **Alert thresholds:** 80% utilization = warning, 95% = critical, timeout increase = page
5. **Recycling:** tracks `pool_pre_ping` and `pool_recycle` events
6. **Redis pool (optional):** same metrics via `redis-py` connection hooks
7. **Dashboard:** Grafana JSON with 6 panels (utilization, wait, acquire rate, errors, overflow, recycles)
8. **CLI snapshot:** `python -m pool_monitor status` prints table
9. **Context propagation:** acquire time linked to request via OpenTelemetry trace
10. **Config overrides:** env vars `DB_POOL_SIZE`, `DB_POOL_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`

### Key invariants
1. Instrumentation NEVER blocks the acquire path.
2. Metrics are ALWAYS exported even if pool is idle.
3. Every acquire result (success/timeout/error) is ALWAYS counted.
4. Alert thresholds are ALWAYS configurable via env.
5. Pool utilization is ALWAYS computed from live pool state, not cached.
6. `/pool/health` returns within 50 ms regardless of load.
7. OpenTelemetry context propagation is OPTIONAL but off-by-default to avoid dep.

### User story themes
- 9.1 Basic metrics (US-01..05): active count, idle count, acquire success, timeout, overflow
- 9.2 Alerts (US-06..10): 80% warning, 95% critical, timeout surge, reset
- 9.3 Health endpoint (US-11..15): JSON shape, p95 latency, recycle count, LB probe
- 9.4 Dashboard (US-16..20): Grafana panels, CLI snapshot, scrape interval
- 9.5 Edge cases (US-21..25): pool exhausted, DB down, recycling, tool idempotency

### Test plan categories
- 10.1 Instrumentation (T-01..06): checkout, checkin, invalidate, connect, overflow
- 10.2 Metrics (T-07..12): counter, gauge, histogram, labels, scrape
- 10.3 Health endpoint (T-13..18): JSON shape, thresholds, fast response
- 10.4 Alerts (T-19..24): threshold triggered, reset, multi-pool
- 10.5 Edge cases (T-25..30): exhaustion, DB down, tool idempotency

### Edge cases (15)
1. Pool empty, no requests → zero utilization, no alerts
2. Pool exhausted → acquire timeout metric increments
3. Pool grows to overflow → overflow metric increments
4. Connection invalidated (DB restart) → invalidate counter increments
5. `pool_pre_ping` detects dead connection → recycle counter
6. Metrics scraped while pool is in transition → atomic snapshot
7. Redis pool not present → gracefully skipped, no error
8. Multi-pool (primary + replica) → labelled separately
9. High churn (1000 req/s) → overhead remains < 50 µs
10. App restart → counters reset, gauge snapshots current state
11. `/pool/health` called under load → responds < 50 ms
12. Tool re-run idempotent
13. Env var override → honored over defaults
14. Instrumentation disabled → zero overhead
15. OpenTelemetry trace ID attached → visible in span attributes

### Anti-patterns
- DO NOT block the acquire path with logging
- DO NOT sample metrics (lose rare events)
- DO NOT hardcode pool config (use env)
- DO NOT forget to count errors (success-only masks failures)
- DO NOT expose metrics without auth in public deployments
