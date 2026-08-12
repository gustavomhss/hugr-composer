---
spec_id: "TOOL-086"
tool_name: "add_prometheus_metrics"
primitive: "resiliency/TracingBuffer"
primitive_path: "core.venous.resiliency.TracingBuffer"
generator: "generators/observability/prometheus.py"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-PROM-01"
  - "INV-PROM-02"
  - "INV-PROM-03"
  - "INV-PROM-04"
  - "INV-PROM-05"
  - "INV-PROM-06"
  - "INV-PROM-07"
  - "INV-PROM-08"
  - "INV-PROM-09"
  - "INV-PROM-10"
  - "INV-PROM-11"
  - "INV-PROM-12"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
  - "CC-21"
  - "CC-22"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
tags:
  - "performance"
  - "data"
  - "api"
  - "testing"
  - "crud"
---
# TOOL-086 — `add_prometheus_metrics`

**Layer:** extend / infrastructure / observability
**Entry point:** `adapt.extend.infrastructure.add_prometheus_metrics.add_prometheus_metrics`
**MCP name:** `fastapi_add_prometheus_metrics`
**Source:** `adapt/extend/infrastructure/add_prometheus_metrics.py` (530 LOC)
**Tests:** `adapt/extend/infrastructure/test_add_prometheus_metrics.py` (22 tests)

---

## 1. Overview

`add_prometheus_metrics` installs a complete **RED metrics layer** (Rate, Errors, Duration) into
an existing FastAPI project. It writes the `app/metrics/` package — `collectors.py`,
`middleware.py`, and `__init__.py` — plus a `GET /metrics` endpoint, patches
`app/core/config.py` with `PROMETHEUS_ENABLED` / `PROMETHEUS_PREFIX` settings, and patches
`app/main.py` to register the middleware and router at startup.

All `prometheus_client` SDK calls are **lazy** (imported inside function bodies), so the
application boots without the package installed. The tool is fully **idempotent**: a second
invocation detects `"RequestMetrics" in app/metrics/collectors.py` and returns
`status="no_op"` without touching any file.

---

## 2. Purpose

| Problem | Solution |
|---------|---------|
| No visibility into request rate or error rate | `RequestMetrics` Counter with method/path/status labels |
| No latency histograms | `Histogram` with standard OTEL-compatible buckets |
| Hard dependency on prometheus_client at import time | All SDK calls behind `_ensure_initialized()` lazy pattern |
| Metrics endpoint not registered | `GET /metrics` route returning `text/plain; version=0.0.4` |
| Config values hardcoded | `PROMETHEUS_ENABLED` / `PROMETHEUS_PREFIX` injected into Settings |

---

## 3. Performance SLOs

| SLO | Target |
|-----|--------|
| Tool execution time | < 200 ms on warm filesystem |
| `execution_time_ms` field | Always present and > 0 |
| Generated `collectors.py` | 0 top-level prometheus_client imports |
| Histogram latency buckets | 11 buckets per Prometheus best practice |
| `record_request()` overhead | < 1 µs per call when already initialized |

---

## 4. Code Examples

### Before

```python
# app/main.py — no metrics instrumentation
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "ok"}
```

```python
# app/core/config.py — no Prometheus fields
class Settings(BaseSettings):
    APP_NAME: str = "myapp"
    REDIS_URL: str = "redis://localhost:6379/0"
```

### After

```python
# app/metrics/collectors.py — RequestMetrics with lazy prometheus_client
class RequestMetrics:
    def __init__(self, prefix: str = "http") -> None:
        self._prefix = prefix
        self._counter: Any = None
        self._histogram: Any = None
        self._errors: Any = None

    def _ensure_initialized(self) -> None:
        if self._counter is not None:
            return
        import prometheus_client as prom  # noqa: PLC0415 — lazy
        p = self._prefix
        buckets = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
        self._counter = prom.Counter(
            f"{p}_requests_total",
            "Total HTTP requests",
            ["method", "path", "status"],
        )
        self._histogram = prom.Histogram(
            f"{p}_request_duration_seconds",
            "HTTP request latency",
            ["method", "path"],
            buckets=buckets,
        )
        self._errors = prom.Counter(
            f"{p}_request_errors_total",
            "Total HTTP errors (4xx + 5xx)",
            ["method", "path", "status"],
        )

    def record_request(
        self, method: str, path: str, status: int, duration: float,
    ) -> None:
        try:
            self._ensure_initialized()
            labels = [method, path, str(status)]
            self._counter.labels(*labels).inc()
            self._histogram.labels(method, path).observe(duration)
            if status >= 400:
                self._errors.labels(*labels).inc()
        except Exception:
            logger.warning("Failed to record Prometheus metric", exc_info=True)
```

```python
# app/metrics/middleware.py — PrometheusMiddleware skips /metrics itself
class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)
        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start
        metrics = get_metrics()
        if metrics is not None:
            metrics.record_request(
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration=duration,
            )
        return response
```

```python
# app/api/routes/metrics.py — GET /metrics returns Prometheus exposition format
@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    try:
        import prometheus_client  # noqa: PLC0415 — lazy
        data = prometheus_client.generate_latest()
        ct = getattr(prometheus_client, "CONTENT_TYPE_LATEST", _CONTENT_TYPE)
        return Response(content=data, media_type=ct)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="prometheus_client not installed. Run: pip install prometheus-client",
        )
```

```python
# app/core/config.py — patched with PROMETHEUS_* fields
class Settings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    # Prometheus metrics — added by add_prometheus_metrics tool
    PROMETHEUS_ENABLED: bool = True
    PROMETHEUS_PREFIX: str = "http"
```

```python
# app/main.py — patched to register middleware and router
from fastapi import FastAPI
from app.metrics.middleware import PrometheusMiddleware  # noqa: F401 — metrics layer
from app.metrics.collectors import init_metrics as _init_metrics
from app.api.routes.metrics import router as _metrics_router
import os as _prom_os

app = FastAPI()

# Prometheus middleware + /metrics endpoint — added by add_prometheus_metrics tool
if _prom_os.getenv("PROMETHEUS_ENABLED", "true").lower() != "false":
    _prom_prefix = _prom_os.getenv("PROMETHEUS_PREFIX", "http")
    _init_metrics(prefix=_prom_prefix)
    app.add_middleware(PrometheusMiddleware)
app.include_router(_metrics_router)
```

---

## 5. Quality Standards

| Standard | Requirement |
|----------|-------------|
| Function size | No function > 50 LOC (AST-verified in T-07) |
| Type hints | 100% on all public functions |
| Docstrings | Every public function and class has a docstring |
| Lazy imports | `prometheus_client` NEVER at module top-level |
| Syntax validity | All generated `.py` files pass `ast.parse()` |
| Config indent | All injected Settings fields use 4-space indent |
| Idempotency | Second run returns `status="no_op"`, zero file changes |
| Self-instrumentation | `/metrics` path skipped by `PrometheusMiddleware.dispatch()` |
| Error recovery | `record_request()` catches all exceptions to never fail a request |

---

## 6. Completeness Criteria

| ID | Criterion | Verified by |
|----|-----------|-------------|
| CC-01 | Tool returns `status="success"` on a fresh fixture project | T-01 |
| CC-02 | Second run returns `status="no_op"` with zero files created/modified | T-02 |
| CC-03 | `dry_run=True` returns success but writes nothing to disk | T-03 |
| CC-04 | `files_created` contains >= 3 entries, all of which exist on disk | T-04 |
| CC-05 | `files_modified` contains >= 1 entry, all of which exist on disk | T-05 |
| CC-06 | All `.py` files in the project parse without `SyntaxError` | T-06 |
| CC-07 | No generated function in `app/metrics/` exceeds 50 LOC | T-07 |
| CC-08 | `PROMETHEUS_ENABLED` and `PROMETHEUS_PREFIX` appear in `config.py` with 4-space indent | T-08 |
| CC-09 | `app/api/routes/metrics.py` exists with a `router` and `/metrics` reference | T-09 |
| CC-10 | `app/metrics/collectors.py` contains `RequestMetrics` and `requests_total` | T-10 |
| CC-11 | `collectors.py` contains `request_duration_seconds` Histogram with `buckets` | T-11 |
| CC-12 | `collectors.py` contains `errors_total` Counter | T-12 |
| CC-13 | `prometheus_client` is NOT imported at module top-level in any generated file | T-13 |
| CC-14 | `app/metrics/middleware.py` exists and contains `PrometheusMiddleware` | T-14 |
| CC-15 | `app/main.py` is patched to contain `PrometheusMiddleware` or `init_metrics` | T-15 |
| CC-16 | `app/metrics/__init__.py` re-exports `RequestMetrics` and `PrometheusMiddleware` | T-16 |
| CC-17 | `result.execution_time_ms` is a positive integer | T-17 |
| CC-18 | `result.next_steps` is non-empty and mentions `prometheus` or `pip` | T-18 |
| CC-19 | After two runs all `.py` files remain parseable | T-19 |
| CC-20 | `result.notes` describe RED metrics | T-20 |
| CC-21 | `collectors.py` defines histogram `buckets` tuple | T-21 |
| CC-22 | `collectors.py` contains `get_metrics()` accessor function | T-22 |

---

## 7. Definition of Done

- [ ] `add_prometheus_metrics(ToolInput(project_dir=...))` returns `status="success"`
- [ ] `app/metrics/__init__.py`, `collectors.py`, `middleware.py` all created
- [ ] `app/api/routes/metrics.py` created (when `app/api/routes/` exists)
- [ ] `app/core/config.py` patched with `PROMETHEUS_ENABLED` and `PROMETHEUS_PREFIX`
- [ ] `app/main.py` patched with middleware registration and router include
- [ ] `requirements.txt` updated with `prometheus-client>=0.20.0`
- [ ] Second run returns `no_op` without touching any file
- [ ] `dry_run=True` writes nothing to disk
- [ ] All 22 tests pass: `pytest adapt/extend/infrastructure/test_add_prometheus_metrics.py -v`

---

## 8. Invariants

| ID | Invariant |
|----|-----------|
| INV-PROM-01 | `prometheus_client` is NEVER imported at module top-level in any generated file |
| INV-PROM-02 | `_ensure_initialized()` is the sole creation point for all Counter/Histogram objects |
| INV-PROM-03 | `PrometheusMiddleware.dispatch()` ALWAYS skips the `/metrics` path itself |
| INV-PROM-04 | `record_request()` wraps all SDK calls in `try/except` — a metrics failure NEVER fails a request |
| INV-PROM-05 | `PROMETHEUS_ENABLED` defaults to `True`; opt-out via env var, not opt-in |
| INV-PROM-06 | Histogram buckets are exactly `(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)` |
| INV-PROM-07 | `/metrics` endpoint returns HTTP 503 (not 500) when `prometheus_client` not installed |
| INV-PROM-08 | `PROMETHEUS_PREFIX` controls all metric name prefixes; default is `"http"` |
| INV-PROM-09 | Idempotency fingerprint is `"RequestMetrics" in app/metrics/collectors.py` |
| INV-PROM-10 | Config anchor is `REDIS_URL: str = "redis://localhost:6379/0"` (not `ACCESS_TOKEN_EXPIRE_MINUTES`) |
| INV-PROM-11 | `execution_time_ms` is recorded on every return path including errors and no_op |
| INV-PROM-12 | All generated `.py` files pass `ast.parse()` before `status="success"` is returned |

---

## 9. User Stories

### Installation Stories (US-01 – US-05)

**US-01** — As a backend engineer, I want to run `fastapi_add_prometheus_metrics` once and have
all RED metric infrastructure in place, so I don't manually write boilerplate collectors.

**US-02** — As an SRE, I want the tool to be idempotent, so I can include it in CI pipelines
without worrying about duplicate metric registrations or file overwrites.

**US-03** — As a developer, I want `dry_run=True` to show me what would change without touching
any files, so I can preview the installation before committing.

**US-04** — As a DevOps engineer, I want `PROMETHEUS_ENABLED` to default to `True` and be
overridable via environment variable, so staging can disable scraping without code changes.

**US-05** — As a platform engineer, I want `requirements.txt` updated automatically with
`prometheus-client>=0.20.0`, so the dependency is tracked in source control.

### Observability Stories (US-06 – US-10)

**US-06** — As a Grafana administrator, I want `{prefix}_requests_total` Counter with
`method/path/status` labels, so I can build dashboards for request rate by endpoint.

**US-07** — As an SRE, I want `{prefix}_request_duration_seconds` Histogram with 11 standard
latency buckets, so I can compute P50/P95/P99 percentiles in Prometheus queries.

**US-08** — As an on-call engineer, I want `{prefix}_request_errors_total` Counter incremented
for every 4xx and 5xx response, so I can alert on error rate spikes.

**US-09** — As a DevOps engineer, I want `GET /metrics` to return Prometheus text exposition
format with content type `text/plain; version=0.0.4`, so Prometheus can scrape it directly.

**US-10** — As a developer, I want the middleware to skip the `/metrics` path to avoid
self-instrumentation that would inflate request counts.

### Safety Stories (US-11 – US-15)

**US-11** — As a developer, I want `prometheus_client` imports to be lazy, so the app boots
without the SDK installed and I can add it incrementally.

**US-12** — As a developer, I want metrics recording errors to be silently logged rather than
propagated, so a Prometheus counter bug never takes down production traffic.

**US-13** — As a developer, I want `GET /metrics` to return HTTP 503 (not 500 or panic) when
`prometheus_client` is not installed, so the error is clearly actionable.

**US-14** — As a developer, I want all generated Python files to pass `ast.parse()` validation
before the tool reports success, so I never receive a project with syntax errors.

**US-15** — As a developer, I want the metric prefix to be configurable via
`PROMETHEUS_PREFIX` env var, so I can namespace metrics per service.

### Configuration Stories (US-16 – US-20)

**US-16** — As a developer, I want `PROMETHEUS_ENABLED` and `PROMETHEUS_PREFIX` injected into
`class Settings` in `config.py`, so settings are consistent with the rest of the application.

**US-17** — As a developer, I want injected config fields to have 4-space indent matching the
rest of the `Settings` class body.

**US-18** — As a developer, I want the config injection to anchor on
`REDIS_URL: str = "redis://localhost:6379/0"` so it appears logically grouped with other
infrastructure settings.

**US-19** — As a developer, I want the tool to check `PROMETHEUS_ENABLED` already in config
before patching, so a second run never duplicates fields.

**US-20** — As a developer, I want the tool to fall back to `@computed_field` / `@model_validator`
/ `@property` decorators or `settings = Settings()` as secondary config anchors.

### Integration Stories (US-21 – US-25)

**US-21** — As a developer, I want `app/metrics/__init__.py` to re-export `RequestMetrics`,
`get_metrics`, and `PrometheusMiddleware`, so imports from the package are clean and stable.

**US-22** — As a developer, I want `app/main.py` to be patched with the middleware registration
guarded by `PROMETHEUS_ENABLED` env check, so toggling metrics requires only an env var change.

**US-23** — As a developer, I want `init_metrics(prefix=...)` called at startup with the
configured prefix, so all metrics share the correct namespace from the first request.

**US-24** — As a developer, I want `app/api/routes/metrics.py` to define `router = APIRouter(tags=["metrics"])`,
so the route is consistently discoverable by FastAPI's router inspection tools.

**US-25** — As a developer, I want `next_steps` to include the `pip install` command, Grafana
dashboard ID, and `.env` configuration hints, so the full setup path is documented.

---

## 10. Test Plan

| Test ID | Test Name | CC Covered | What it verifies |
|---------|-----------|------------|-----------------|
| T-01 | `test_success_status` | CC-01 | `status == "success"` on fresh fixture project |
| T-02 | `test_idempotent` | CC-02 | Second run: `status == "no_op"`, no files created/modified |
| T-03 | `test_dry_run` | CC-03 | `dry_run=True` returns success, zero disk changes, `before == after` snapshot |
| T-04 | `test_files_created_count` | CC-04 | `len(files_created) >= 3`, all paths exist on disk |
| T-05 | `test_files_modified_count` | CC-05 | `len(files_modified) >= 1`, all paths exist on disk |
| T-06 | `test_all_py_parse` | CC-06 | Every `.py` in project parses after tool |
| T-07 | `test_no_function_over_50_loc` | CC-07 | AST walk of `app/metrics/`: no function > 50 LOC |
| T-08 | `test_config_fields_patched` | CC-08 | `PROMETHEUS_ENABLED` and `PROMETHEUS_PREFIX` in `config.py`; 4-space indent |
| T-09 | `test_routes_registered` | CC-09 | `app/api/routes/metrics.py` exists with `router` and `/metrics` |
| T-10 | `test_collectors_file_has_request_metrics` | CC-10 | `RequestMetrics` and `requests_total` in `collectors.py` |
| T-11 | `test_collectors_has_duration_histogram` | CC-11 | `request_duration_seconds` and `buckets` in `collectors.py` |
| T-12 | `test_collectors_has_errors_counter` | CC-12 | `errors_total` in `collectors.py` |
| T-13 | `test_prometheus_client_is_lazy` | CC-13 | AST walk of `app/metrics/`: no top-level `import prometheus_client` |
| T-14 | `test_middleware_file_created` | CC-14 | `middleware.py` exists with `PrometheusMiddleware` |
| T-15 | `test_main_py_patched_with_middleware` | CC-15 | `main.py` contains `PrometheusMiddleware` or `init_metrics` |
| T-16 | `test_metrics_init_has_exports` | CC-16 | `__init__.py` contains `RequestMetrics` and `PrometheusMiddleware` |
| T-17 | `test_execution_time_recorded` | CC-17 | `result.execution_time_ms > 0` |
| T-18 | `test_next_steps_present` | CC-18 | `result.next_steps` non-empty, contains `prometheus` or `pip` |
| T-19 | `test_idempotent_project_still_parses` | CC-19 | Two runs; all `.py` still parseable |
| T-20 | `test_notes_mention_red_metrics` | CC-20 | `result.notes` mentions `request` / `red` / `metrics` |
| T-21 | `test_latency_buckets_in_collectors` | CC-21 | `buckets` keyword present in `collectors.py` |
| T-22 | `test_get_metrics_function_present` | CC-22 | `get_metrics` function in `collectors.py` |

**Run command:**
```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_prometheus_metrics.py -v
```

---

## 11. Interaction Matrix

| Tool | Interaction | Notes |
|------|-------------|-------|
| `fastapi_generate_project` | Prerequisite | Provides `app/core/config.py` with REDIS_URL anchor and `app/main.py` |
| `add_opentelemetry` (TOOL-085) | Complementary | OTEL and Prometheus can coexist; both patch `main.py` idempotently |
| `add_structured_logging` (TOOL-087) | Complementary | Structlog and Prometheus are independent; can be installed in any order |
| `add_arq_worker` (TOOL-053) | Complementary | Worker metrics should be a separate `RequestMetrics` instance with different prefix |
| Prometheus server | Consumer | Scrapes `GET /metrics` on configured interval |
| Grafana | Consumer | Dashboard ID 12708 maps directly to the RED metric names generated |

---

## 12. Rollback Procedure

The tool does not provide an automated rollback command. Manual steps:

1. **Remove generated package:**
   ```bash
   rm -rf app/metrics/ app/api/routes/metrics.py
   ```

2. **Revert `app/core/config.py`** — remove the `PROMETHEUS_ENABLED` / `PROMETHEUS_PREFIX` block.

3. **Revert `app/main.py`** — remove the `from app.metrics...` import lines and the
   `if _prom_os.getenv(...)` registration block appended at the end.

4. **Revert `requirements.txt`** — remove `prometheus-client>=0.20.0`.

5. Verify with `pytest` to confirm no test regressions.

---

## 13. Edge Cases

| Scenario | Behaviour |
|----------|-----------|
| `prometheus_client` not installed at runtime | `_ensure_initialized()` raises `ImportError`; caught by `record_request()` which logs a warning; `GET /metrics` returns HTTP 503 |
| `app/api/routes/` does not exist | Step 2 is skipped entirely; no `metrics.py` created, no error raised |
| `app/main.py` does not exist | Step 4 is skipped entirely; `files_modified` will not include `main.py` |
| `REDIS_URL` anchor absent from `config.py` | `_patch_config()` falls back to `@computed_field` / `@model_validator` / `@property` decorators, then `settings = Settings()`, then raw append |
| `PROMETHEUS_ENABLED` already in `config.py` | `_patch_config()` detects it and returns without patching |
| `PrometheusMiddleware` already in `main.py` | `_patch_main()` detects it and returns without patching |
| Metric registered twice (duplicate registration) | `prometheus_client` raises `ValueError` on second `Counter()`/`Histogram()` creation; caught by `try/except` in `record_request()` |
| Very high-cardinality paths (e.g. `/users/123/orders/456`) | No normalisation is applied; high-cardinality paths create many label combinations — caller must normalise paths before recording |

---

## 14. Security Considerations

| Concern | Mitigation |
|---------|------------|
| `/metrics` endpoint publicly accessible | The endpoint has `include_in_schema=False`; callers should add IP-allow-list middleware or auth in production |
| Label injection via path values | Labels accept arbitrary path strings — path normalisation (stripping IDs) should be applied before `record_request()` in production |
| Denial of service via metric cardinality | High-cardinality label sets (e.g. per-user paths) can exhaust memory; route normalisation is required |
| Dependency `prometheus-client` not pinned | `requirements.txt` adds `>=0.20.0`; a `.lock` file should constrain the upper bound |

---

## 15. Observability

The Prometheus layer is itself the observability output. The generated metrics include:

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `{prefix}_requests_total` | Counter | `method`, `path`, `status` | Total HTTP requests |
| `{prefix}_request_duration_seconds` | Histogram | `method`, `path` | Request latency in seconds |
| `{prefix}_request_errors_total` | Counter | `method`, `path`, `status` | Total 4xx + 5xx responses |

All metric names use the configured `PROMETHEUS_PREFIX` (default `"http"`).

Tool execution itself records `execution_time_ms` in the `ToolResult`. Failures during
`record_request()` are logged at WARNING level via `logging.getLogger(__name__)`.

---

## 16. Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-04-15 | Initial spec — 22 CCs, 12 invariants, 25 user stories |
