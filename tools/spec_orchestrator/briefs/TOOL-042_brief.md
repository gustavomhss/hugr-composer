## Tool: `sla_reporter`

### Overview parameters
- Tool name: `fastapi_sla_reporter`
- Category: OPERATE
- Complexity: High
- Dependencies: existing FastAPI project, Prometheus, optional Grafana
- Signature: `sla_reporter(project_dir: str, sla_config_file: str = "sla.yaml", report_period: str = "month", p99_budget_ms: int = 500, availability_target_pct: float = 99.9, output_format: str = "pdf") -> dict`
- Parameters:
  - `project_dir`: project root
  - `sla_config_file`: YAML defining per-endpoint SLOs (availability, p99, error budget)
  - `report_period`: `day`, `week`, `month`, `quarter`
  - `p99_budget_ms`: default p99 latency budget
  - `availability_target_pct`: default uptime target (99.9 = "three nines")
  - `output_format`: `pdf`, `markdown`, `html`, `json`

### Purpose
Produce auditable SLA reports from Prometheus metrics: computes uptime, p50/p95/p99 latency, and error-budget burn per endpoint against targets defined in `sla.yaml`. Generates a branded PDF/Markdown/HTML report with traffic-light status per SLO, breakdowns by endpoint, and a narrative summary of notable incidents. Essential for customer contracts, internal reviews, and error-budget policies. Supports multiple report periods (daily for engineering, monthly for management, quarterly for executives). Integrates with incident postmortems by linking error-budget spikes to specific outages.

### Performance SLOs
- Report generation < 10s for 30 days of data
- Files modified ≤ 2 (pyproject.toml, CI workflow)
- Files created ≥ 8 (reporter module, sla.yaml template, PDF renderer, HTML template, tests, CLI, docs, Makefile)
- Prometheus query < 2s
- PDF rendering < 5s
- Zero production impact

### Key technical decisions
1. **SLA YAML format:**
   ```yaml
   endpoints:
     - path: /api/orders
       availability_pct: 99.95
       p99_ms: 300
       error_budget_window: 30d
   ```
2. **Metric source:** Prometheus via `prometheus-api-client` Python lib
3. **Availability calc:** `1 - (5xx_count / total_count)` over the period
4. **Error budget:** `(1 - availability_target) * total_count` = allowed errors; burn rate = used / allowed
5. **Multi-window burn:** 1h, 6h, 24h burn rates (Google SRE approach)
6. **PDF rendering:** WeasyPrint or ReportLab, branded with logo
7. **HTML template:** Jinja2 with charts via Plotly embedded as SVG
8. **Narrative section:** auto-generated incident summary from alert history
9. **Incident linkage:** query Alertmanager or Sentry for events in period
10. **CI integration:** runs monthly, uploads to S3, sends email to stakeholders

### Key invariants
1. Availability calc is ALWAYS based on total requests, never averaged.
2. Error budget burn is ALWAYS time-windowed (not cumulative).
3. Reports are ALWAYS signed with a generation timestamp + git SHA.
4. Targets are ALWAYS loaded from YAML, never hardcoded.
5. Report format is DETERMINISTIC (same metrics → same output).
6. Incidents NEVER invented — only linked from real alert history.
7. Metric queries are ALWAYS bounded by period to avoid slow queries.

### User story themes
- 9.1 Basic report (US-01..05): daily, weekly, monthly, quarterly, empty data
- 9.2 SLA YAML (US-06..10): parse, multi-endpoint, default, override, validation error
- 9.3 Calculations (US-11..15): availability, p99, error budget, burn rate, multi-window
- 9.4 Rendering (US-16..20): PDF, HTML, Markdown, JSON, CLI
- 9.5 Edge cases (US-21..25): no data, metric gap, tool idempotency, Prometheus down

### Test plan categories
- 10.1 Loading (T-01..06): YAML parse, defaults, per-endpoint, validation
- 10.2 Calculations (T-07..12): availability, percentiles, burn rate, multi-window
- 10.3 Rendering (T-13..18): PDF, HTML, Markdown, JSON, CLI
- 10.4 Incident linkage (T-19..24): alert query, timeline, narrative
- 10.5 Edge cases (T-25..30): no data, Prometheus down, tool idempotency

### Edge cases (15)
1. No data in period → report shows "No traffic" for endpoint
2. Metric gap (Prometheus restart) → extrapolation warning in report
3. Endpoint removed mid-period → partial availability calculated
4. Endpoint added mid-period → partial period counted
5. Target missed by 1 error → "At Risk" status (yellow)
6. Budget fully consumed → "Exhausted" status (red)
7. Budget under 10% used → "Healthy" status (green)
8. Multi-window burn conflicts (1h red, 24h green) → report shows both
9. Incident period excluded via maintenance window → respected
10. PDF rendering font missing → fallback font
11. Report > 50 pages → chunked rendering
12. Tool re-run idempotent (same period → same report)
13. Prometheus query timeout → partial report + warning
14. Timezone handling → UTC default, configurable
15. Holiday / blackout period → excluded from SLA calc if configured

### Anti-patterns
- DO NOT average percentiles (mathematically wrong)
- DO NOT ignore maintenance windows
- DO NOT hardcode targets (always YAML-driven)
- DO NOT invent incidents (only link from real alerts)
- DO NOT generate reports without period boundaries
