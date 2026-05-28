# MODULES V2 AUDIT — Payments, Observability, Deployment
**Date:** 2026-04-12
**Scope:** 9 files across 3 modules — full read comparison against `generators/`
**Question:** Unique/valuable logic or duplicate of generators?

---

## TL;DR (Decisions at a Glance)

| File | Decision | Reason |
|------|----------|--------|
| `scaffold_payments.py` | **PRESERVAR** | Entire domain is ABSENT from generators. Full PCI-aware Stripe scaffold. |
| `verify_payments.py` | **PRESERVAR** | 8 payment-specific rules (PAY-01..08) not in any generator or verifier. |
| `generate_alerts.py` | **PRESERVAR** | Multi-burn-rate SLO math + Grafana JSON generator. generators/alerting.py is a stub. |
| `scaffold_otel.py` | **PRESERVAR** | 3 exporter variants, SQLAlchemy/HTTPX switches, Prometheus middleware generator. generators/otel.py is ~60 LOC thin wrapper. |
| `verify_traces.py` | **PRESERVAR** | 10 AST-based OBS rules (OBS-01..10). Nothing equivalent exists in generators. |
| `generate_k8s.py` | **PRESERVAR (merge)** | Has `_validate_config()` with 5 DEPLOY rules, preStop timing math, HPA memory target. generators/k8s.py lacks all three. |
| `generate_ci.py` | **PRESERVAR (merge)** | `analyze_github_workflow()` + Trivy-scan-before-push gate + concurrency + unpinned actions checks (CI-01..06). generators/github_actions.py has none. |
| `generate_docker.py` | **PRESERVAR (merge)** | `analyze_dockerfile()` with 7 DOCKER rules + two-function API (Dockerfile + .dockerignore). generators/ has no Dockerfile generator at all. |
| `generate_k6.py` | **PRESERVAR** | Configurable ramping + 3 test-type presets (smoke/stress/main). generators/k6_loadtest.py is hardcoded 4-stage script with no per-endpoint thresholds. |

**Net verdict:** Zero files are discardable. All contain logic not present in `generators/`. The payments domain is a complete gap in the generators layer.

---

## 1. `modules/payments/tools/scaffold_payments.py` (680 LOC)

### A. What it does
Generates a complete `payments/` Python package inside a target directory. Produces 7–8 files:
`__init__.py`, `config.py`, `schemas.py`, `checkout.py`, `webhooks.py`, `handlers.py`, `refunds.py`, and optionally `subscriptions.py`.

### B. Unique logic
Several domain-specific decisions are hard-coded that require knowledge to get right:

- **PCI SAQ A scoping:** The docstring on `_checkout_py()` explicitly documents that using Stripe Checkout keeps you in SAQ A (22 questions) vs SAQ D (329 questions). This is non-obvious practitioner knowledge baked into the generator.
- **`ZERO_DECIMAL_CURRENCIES` set** in `_config_py()`: 16 ISO currency codes (JPY, KRW, BIF, etc.) that require amount in base units, not cents. This is a live Stripe API gotcha that causes silent overcharges if wrong.
- **Idempotency key strategy:** `checkout:{order_id}`, `sub:{customer_id}:{price_id}`, `refund:{order_id}:{amount}:{hour_bucket}` — deterministic, collision-resistant keys with hourly bucketing for refunds (to allow retry within an hour but not across hours).
- **Webhook handler contract:** `_webhooks_py()` enforces the `return {"received": True}` after exception catch so Stripe does not retry on application bugs.
- **Subscription state machine in handlers:** `handle_subscription_updated()` maps `active/past_due/canceled/unpaid/paused` to `grant/restrict/revoke/pause`. This is the exact Stripe lifecycle model.
- **Conditional scaffolding:** `with_subscriptions=False` drops 3 files and 2 event handlers, keeping smaller scope for non-SaaS projects.

### C. Equivalent in `generators/`?
**None.** There is no payments directory, no Stripe file, and no payment-adjacent generator anywhere in `generators/`. This is a complete gap.

### D. Spec coverage
No existing spec covers payments. This is a confirmed skill gap. The closest related spec is TOOL-015 (add_webhook_sender) and TOOL-016 (add_webhook_receiver), but those are generic webhooks, not payment lifecycle.

### E. Recommendation
**PRESERVAR.** No equivalent exists. The PCI/idempotency/lifecycle logic is practitioner knowledge that belongs in the skill. Additionally, this is a strong candidate for a future spec (e.g., `TOOL-052-add_stripe_payments`) that would reference this module.

---

## 2. `modules/payments/tools/verify_payments.py` (496 LOC)

### A. What it does
AST + regex static analyzer that scans a FastAPI project for 8 payment integration anti-patterns. Entry point: `verify_payment_config(project_path)` → `list[Finding]`.

### B. Unique logic — 8 Payment-Specific Rules

| Rule | Severity | What it catches |
|------|----------|-----------------|
| PAY-01 | CRITICAL | Webhook endpoint without `construct_event()` signature verification |
| PAY-02 | HIGH | Stripe `.create()` calls without `idempotency_key` |
| PAY-03 | CRITICAL | Raw card fields (`card_number`, `cvv`, `pan`, `card_exp`) in server code — PCI violation |
| PAY-04 | HIGH | Stripe API calls without `stripe.error` exception handling |
| PAY-05 | CRITICAL/HIGH | Hardcoded Stripe keys via regex for `sk_live_`, `sk_test_`, `pk_live_`, `whsec_` patterns |
| PAY-06 | HIGH | Order fulfillment triggered on success redirect URL (not on webhook) |
| PAY-07 | MEDIUM | Payment creation with no refund capability |
| PAY-08 | HIGH | Webhook handlers without deduplication (`upsert`, `event_id`, `processed_events`) |

Notably PAY-03 uses a 9-pattern regex (`card_number`, `card_num`, `ccn`, `cvv`, `cvc`, `expiry_month`, `expiry_year`, `card_exp`, `pan\b`) with a word-boundary guard on `pan` to avoid false positives on "expand", "panel", etc. This is a deliberate heuristic.

PAY-05 has a two-pass strategy: regex for literal key strings, then assignment pattern for `stripe.api_key = "sk_..."` with a lookahead to ignore `os.getenv()` wrappers.

### C. Equivalent in `generators/`?
**None.** No generator has any payment verification. `generators/observability/` has no payment checks. No static analysis tool in the skill covers financial integrations.

### D. Spec coverage
No spec covers payment verification. This could be a future TOOL-053 (`verify_payment_config`). The closest is TOOL-051 (`fastapi_doctor`) which is a general health check, but PAY-01..08 are specific enough to warrant their own tool.

### E. Recommendation
**PRESERVAR.** 8 unique payment rules with real-world PCI/financial correctness implications. PAY-03 (raw card data) and PAY-01 (webhook signature) are CRITICAL severity catches that could prevent significant security incidents. Fully unique to this module.

---

## 3. `modules/observability/tools/generate_alerts.py` (723 LOC)

### A. What it does
Generates two files: `prometheus_rules.yaml` (recording rules + multi-burn-rate alert rules) and `grafana_dashboard.json` (importable Grafana model). Entry point: `generate_alerting_rules(service_name, slo_availability, slo_latency_p99_ms, output_dir)`.

### B. Unique logic

**Multi-burn-rate SLO math** (Google SRE Workbook, Chapter 5):
- Error budget computed as `1.0 - slo_availability`
- Three alert tiers with different burn rate multipliers: fast (14.4x → page, budget exhausted in ~50h), medium (6x → page, ~5 days), slow (1x → ticket)
- Window pairs: fast uses `1h + 5m`, medium uses `6h + 30m`, slow uses `6h + 1h`
- Short-window formula comment: `short_window = long_window / 12` — this is the Google SRE Workbook rule

Recording rules pre-compute: `error_ratio:5m`, `error_ratio:30m`, `error_ratio:1h`, `error_ratio:6h`, `burn_rate:1h`, `burn_rate:6h`, `latency_p99:5m`, `request_rate:5m`, `error_budget_remaining:30d`

**Grafana dashboard generator** produces a fully structured JSON model (not a placeholder) with:
- Traffic & Errors row: request rate by endpoint timeseries, error rate % with SLO-derived thresholds (green/yellow/red bands computed from `error_budget * 100`)
- Latency row: p50/p95/p99 timeseries with SLO threshold line, heatmap panel
- Saturation & SLO row: active requests timeseries, error budget gauge (red < 20%, yellow < 50%, green ≥ 50%), burn rate comparison panel with 14.4x threshold line

### C. Equivalent in `generators/observability/alerting.py`?
Read the first 80 lines. The generator has 5 simple static alerts (HighErrorRate > 5%, HighLatency p95 > 1s, etc.) with hardcoded thresholds and no SLO parameterization. No burn rates. No Grafana JSON generation. The generator's Grafana dashboard is a placeholder with 4 basic panels, not computed from SLO targets.

**The module is strictly superior:** parameterized SLO math, multi-burn-rate pattern, fully rendered Grafana JSON vs static 5-alert YAML.

### D. Spec coverage
Partially maps to TOOL-042 (`sla_reporter`) and TOOL-034 (`performance_baseline`). The burn-rate alert generation is the foundation of SLA reporting. TOOL-041 (`error_rate_analyzer`) would benefit from the recording rules generated here.

### E. Recommendation
**PRESERVAR.** The multi-burn-rate math and parameterized Grafana generation are the SOTA approach. The generator is a stub. This module's logic should be the authoritative implementation.

---

## 4. `modules/observability/tools/scaffold_otel.py` (629 LOC)

### A. What it does
Generates a complete `observability/` Python package with 4 files: `telemetry.py` (TracerProvider, BatchSpanProcessor, exporter), `metrics.py` (Prometheus RED middleware + metrics endpoint), `logging_config.py` (structlog + OTel trace_id/span_id injection), `__init__.py`. Entry point: `generate_otel_setup(output_dir, service_name, exporter, with_prometheus, with_sqlalchemy, with_httpx)`.

### B. Unique logic

**3 exporter variants** (branched template at generation time):
- `otlp` → `OTLPSpanExporter` (gRPC) from `opentelemetry.exporter.otlp.proto.grpc`
- `otlp-http` → `OTLPSpanExporter` (HTTP/protobuf) from `opentelemetry.exporter.otlp.proto.http`
- `console` → `ConsoleSpanExporter` for development

**Conditional instrumentation helpers** via `with_sqlalchemy` and `with_httpx` flags — generates `instrument_sqlalchemy(engine)` and `instrument_httpx()` functions only when needed.

**`_logging_config_py()`** generates `_add_otel_context()` structlog processor that uses `format(ctx.trace_id, "032x")` and `format(ctx.span_id, "016x")` — W3C-standard hex formatting that matches exactly what Jaeger/Tempo/Datadog display. This detail matters for cross-system correlation.

**`PrometheusMiddleware._get_route_template()`** resolves route templates (`/users/{id}`) instead of actual paths (`/users/12345`) using `route.matches(request.scope)` — prevents label cardinality explosion. `EXCLUDED_PATHS` frozenset prevents K8s probe traffic from polluting business SLIs.

**Requirements list** returned in result dict is built conditionally per exporter type and flags — downstream tooling can inject the exact pip packages needed.

### C. Equivalent in `generators/observability/otel.py`?
The generator is a thin wrapper (~60 LOC) that generates a single `telemetry.py` with a try/except import guard and no exporter variants. It has no metrics module, no structlog setup, no trace_id injection, no Prometheus middleware, no conditional SQLAlchemy/HTTPX instrumentation.

The module generates 4 files vs the generator's 1 file. The module's `telemetry.py` alone is ~50% longer and more complete.

### D. Spec coverage
No direct spec in the 51 new specs, but foundational for TOOL-040 (`connection_pool_monitor`) and TOOL-041 (`error_rate_analyzer`) which both require OTel to be configured.

### E. Recommendation
**PRESERVAR.** The module is the SOTA implementation. The generator is a legacy stub. The cardinality-safe middleware and W3C trace_id formatting are the specific details that make this production-grade.

---

## 5. `modules/observability/tools/verify_traces.py` (625 LOC)

### A. What it does
AST + regex static analyzer for observability anti-patterns. Entry point: `verify_observability(project_path)` → `list[Finding]`. Scans all `.py` files (excluding venv/test/cache dirs) for 10 rules.

### B. Unique logic — 10 OBS Rules

| Rule | Severity | Detection method |
|------|----------|-----------------|
| OBS-01 | CRITICAL | No `TracerProvider` + `set_tracer_provider` in project-wide scan |
| OBS-02 | HIGH | FastAPI app without `FastAPIInstrumentor.instrument_app()` |
| OBS-03 | MEDIUM | `create_engine`/`AsyncSession` present but no `SQLAlchemyInstrumentor` |
| OBS-04 | MEDIUM | OTel configured but no `start_as_current_span` in non-test production code |
| OBS-05 | HIGH | `prometheus_client` imported but no `/metrics` route, or neither present |
| OBS-06 | LOW | `print()` calls in production code via AST walk (capped at 5 findings + overflow) |
| OBS-07 | MEDIUM | Logging present but no `trace_id`/`span_id`/`get_current_span` in any source |
| OBS-08 | MEDIUM | Both Prometheus and `/healthz` present but no `EXCLUDED_PATHS` or exclusion pattern |
| OBS-09 | MEDIUM | Custom spans exist but no `set_status`/`StatusCode.ERROR`/`record_exception` |
| OBS-10 | LOW | `logging.info(f"...")` f-string pattern in logger calls (unstructured logging) |

**`_is_non_production()`** filters out `tests/`, `examples/`, `benchmarks/`, `scripts/` to avoid false positives. OBS-06 caps at 5 findings to prevent noise flooding.

OBS-08 has a subtle heuristic: checks `healthz` appears in content after `"exclude"` split to detect indirect exclusion patterns.

### C. Equivalent in `generators/`?
**None.** No verifier exists in the generators layer for observability. This is entirely unique.

### D. Spec coverage
No direct spec, but foundational for TOOL-040 (`connection_pool_monitor`) and TOOL-041 (`error_rate_analyzer`). Could feed into TOOL-051 (`fastapi_doctor`) as a sub-check domain.

### E. Recommendation
**PRESERVAR.** 10 unique, production-vetted rules. The AST-based `print()` detection and route cardinality check (OBS-08) are particularly valuable. Zero equivalence in generators.

---

## 6. `modules/deployment/tools/generate_k8s.py` (480 LOC)

### A. What it does
Generates K8s manifests: `deployment.yaml`, `service.yaml`, `hpa.yaml` (optional), `pdb.yaml` (optional). Includes `_validate_config()` that returns `list[Finding]` for configuration anti-patterns.

### B. Unique logic vs `generators/deployment/k8s.py`

**What the module adds that the generator lacks:**

1. **`_validate_config()`** — 5 DEPLOY rules:
   - DEPLOY-001 (HIGH): `replicas < 2` — single replica means zero capacity during pod restart
   - DEPLOY-002 (CRITICAL): `min_available >= replicas` — PDB that blocks ALL voluntary evictions, kubectl drain hangs forever
   - DEPLOY-003 (HIGH): `prestop_sleep >= termination_grace` — K8s will SIGKILL before preStop completes (the math: `termination_grace >= prestop_sleep + graceful_shutdown + buffer`)
   - DEPLOY-004 (MEDIUM): `min_replicas < 2` — HPA at 1 minimum means zero capacity during pod failure
   - DEPLOY-005 (HIGH): `max_replicas <= min_replicas` — HPA effectively disabled

2. **preStop hook** with configurable sleep duration — generator has `terminationGracePeriodSeconds: 30` but no preStop lifecycle hook at all.

3. **HPA memory metric** — the module adds `memory: averageUtilization: 80` alongside CPU. The generator HPA has only CPU.

4. **`revisionHistoryLimit: 5`** on Deployment — generator does not set this (defaults to 10).

5. **Configurable resource parameters** (14 keyword args) vs generator's 4 parameters.

### C. What the generator has that the module lacks
The generator creates `configmap.yaml` and `secret.yaml`. The module does not (references them via `optional: true` envFrom).

### D. Spec coverage
Not directly mapped, but underpins TOOL-027 (`add_load_profile`) for deployment configuration and TOOL-034 (`performance_baseline`) for resource sizing.

### E. Recommendation
**PRESERVAR + merge.** The `_validate_config()` function is the critical unique value — 5 rules preventing real production disasters (especially DEPLOY-002 and DEPLOY-003 which are subtle and dangerous). The generator should absorb the preStop hook and HPA memory metric. The module should absorb ConfigMap/Secret generation from the generator.

---

## 7. `modules/deployment/tools/generate_ci.py` (454 LOC)

### A. What it does
Generates GitHub Actions CI/CD workflow YAML (function: `generate_github_actions`) and also analyzes existing workflows for anti-patterns (function: `analyze_github_workflow`).

### B. Unique logic vs `generators/deployment/github_actions.py`

**`analyze_github_workflow(workflow_content)` — 6 CI Rules:**

| Rule | Severity | Check |
|------|----------|-------|
| CI-01 | HIGH | No Trivy/Snyk/Grype scan in pipeline |
| CI-02 | HIGH | Actions pinned to `@master/@main/@latest` (supply chain attack vector) |
| CI-03 | LOW | Missing `concurrency:` group (race conditions, wasted minutes) |
| CI-04 | CRITICAL | No test step at all |
| CI-05 | HIGH | Docker push present but no scan gate between build and push |
| CI-06 | LOW | No pip or Docker layer cache |

This static analyzer has no equivalent anywhere in the skill.

**Generator differences for `generate_github_actions()`:**
- Module has **Trivy scan step** (`aquasecurity/trivy-action@0.28.0`) between build and push, with SARIF upload to GitHub Security tab. Generator has Trivy in the template.
- Module has **concurrency control** (`cancel-in-progress: true`). Generator does not.
- Module has **optional K8s deploy job** with `kubectl rollout status --timeout=300s`. Generator does not have K8s deploy.
- Module returns a string (no disk write). Generator writes to disk. Different API contract.

### C. Spec coverage
Not directly in the 51 specs. The static analyzer (`analyze_github_workflow`) could be part of TOOL-051 (`fastapi_doctor`) as a CI health sub-check.

### E. Recommendation
**PRESERVAR + merge.** The `analyze_github_workflow()` function is entirely unique and valuable. The K8s deploy job and concurrency control in the generator are additive. The two implementations complement each other — the module's generator is the one to keep (more complete), the generator's postgres service container setup is worth absorbing.

---

## 8. `modules/deployment/tools/generate_docker.py` (445 LOC)

### A. What it does
Two public functions:
- `generate_dockerfile(project_name, python_version, port, workers, use_gunicorn, requirements_file, app_module, graceful_shutdown_timeout)` → Dockerfile string
- `generate_dockerignore(project_name)` → .dockerignore string
- `analyze_dockerfile(dockerfile_content)` → `list[Finding]`

### B. Unique logic vs `generators/`

**`generators/` has no Dockerfile generator at all.** The generators layer only generates GitHub Actions, K8s, k6, and OTel. This module fills a complete gap.

**`analyze_dockerfile()` — 7 DOCKER Rules:**

| Rule | Severity | Check |
|------|----------|-------|
| DOCKER-01 | HIGH | No `USER` directive (runs as root) |
| DOCKER-02 | MEDIUM | No `HEALTHCHECK` instruction |
| DOCKER-03 | MEDIUM | Single-stage build (counts `FROM` lines) |
| DOCKER-04 | LOW | `pip install` without `--no-cache-dir` |
| DOCKER-05 | CRITICAL | `ARG` names matching `*SECRET*`, `*PASSWORD*`, `*KEY*`, `*TOKEN*` |
| DOCKER-06 | HIGH | Unpinned base image (no `:tag` or `@digest`) |
| DOCKER-07 | MEDIUM | `COPY . .` before `COPY requirements.txt` (breaks layer cache) |

DOCKER-05 uses `re.IGNORECASE` regex on `ARG` declarations — catches `ARG API_SECRET_KEY` or `ARG DATABASE_PASSWORD`.

DOCKER-07 tracks line numbers of both `COPY . .` and `COPY requirements.txt` to detect ordering violation.

**`use_gunicorn` flag:** generates either Gunicorn multi-worker CMD (with `--worker-class uvicorn.workers.UvicornWorker`) or pure Uvicorn CMD. The docstring explains: in Kubernetes use 1 worker (K8s manages replicas), on single VM use Gunicorn.

**`generate_dockerignore()`** includes `!requirements*.yaml` exception (preserve helm charts in requirements.yaml while ignoring other yaml files).

### C. Spec coverage
No direct spec. Foundational infrastructure. Could be part of a future `TOOL-052` or absorbed into TOOL-051 (`fastapi_doctor`) as a Dockerfile health check.

### E. Recommendation
**PRESERVAR.** Dockerfile generation is absent from generators. The `analyze_dockerfile()` analyzer is unique. DOCKER-05 (secrets in ARG) and DOCKER-07 (cache layer ordering) are subtle catches that prevent real production issues.

---

## 9. `modules/deployment/tools/generate_k6.py` (299 LOC)

### A. What it does
Generates k6 JavaScript load test scripts. Three public functions:
- `generate_k6_script(base_url, endpoints, max_vus, duration_seconds, ...)` — parameterized full load test
- `generate_smoke_test(base_url, health_path)` — 1 VU, 10s, health endpoint (deploy gate)
- `generate_stress_test(base_url, endpoints, breaking_point_vus)` — 5-stage ramp to find breaking point

### B. Unique logic vs `generators/deployment/k6_loadtest.py`

**Generator:** hardcoded 5-stage script with `login_duration` and `errors` custom metrics, fixed 10/10/50/100/0 VU profile, no parameterization, no per-endpoint thresholds.

**Module adds:**
- `endpoints: list[dict]` API — caller specifies method/path/name/body/expected_status per endpoint
- Per-endpoint threshold rules: `http_req_duration{name:my_endpoint}: ['p(95)<500']`
- Per-endpoint check blocks: status code + duration per response
- `handleSummary()` exporting JSON to `k6-summary.json` for CI integration
- `think_time_seconds` parameter (realistic user simulation)
- Three preset functions: `generate_smoke_test()` (1 VU, strict thresholds, deploy gate), `generate_stress_test()` (relaxed thresholds, finds breaking point)

The preset architecture is the key differentiator: smoke/load/stress are three different test types with different VU profiles and threshold tolerances, all using the same underlying generator.

### C. Spec coverage
**TOOL-027 (`add_load_profile`)** — direct match. This is the tool that TOOL-027 would use. Also relevant to TOOL-034 (`performance_baseline`) for establishing baseline latencies.

### E. Recommendation
**PRESERVAR.** The per-endpoint parameterization and three test-type presets (smoke/load/stress) are the SOTA k6 patterns. The generator is a hardcoded one-size-fits-all script. The module is what TOOL-027 should call.

---

## Key Finding: Payments Gap

The `modules/payments/` directory covers a complete domain (Stripe integration + payment verification) that has **zero representation in `generators/`**. This is not a near-duplicate situation — it is the only place in the entire skill that handles:

- PCI compliance enforcement (SAQ A vs SAQ D scoping)
- Webhook signature verification checks
- Idempotency key analysis
- Raw card data detection
- Subscription lifecycle management
- Refund endpoint scaffolding

If `modules/payments/` were discarded, this knowledge would be entirely lost from the skill. It maps to a clear product need (any FastAPI app taking payments) and should be documented as a gap in the 51 new specs with a suggested `TOOL-052-add_stripe_payments` spec.

---

## Summary Recommendations

### PRESERVAR as-is (no merge needed)
- `scaffold_payments.py` — complete gap in generators
- `verify_payments.py` — complete gap in generators
- `generate_alerts.py` — superior to generators/observability/alerting.py (SLO math + Grafana JSON)
- `scaffold_otel.py` — superior to generators/observability/otel.py (4 files vs 1, 3 exporters)
- `verify_traces.py` — complete gap in generators
- `generate_k6.py` — superior to generators/deployment/k6_loadtest.py (parameterized + presets)

### PRESERVAR + merge with generators (bidirectional)
- `generate_k8s.py` — module has `_validate_config()` + preStop + HPA memory; generator has ConfigMap/Secret
- `generate_ci.py` — module has `analyze_github_workflow()` + K8s deploy job; generator has postgres service container
- `generate_docker.py` — module fills complete gap (no generator equivalent); `analyze_dockerfile()` is unique

### New specs to create (gaps surfaced by this audit)
- `TOOL-052-add_stripe_payments` — scaffold and verify Stripe integration (PAY-01..08)
- Consider: `TOOL-053-verify_dockerfile` — wraps `analyze_dockerfile()` as standalone tool
