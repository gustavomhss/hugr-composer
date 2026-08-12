---
spec_id: "TOOL-085"
tool_name: "add_opentelemetry"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-OTEL-01"
  - "INV-OTEL-02"
  - "INV-OTEL-03"
  - "INV-OTEL-04"
  - "INV-OTEL-05"
  - "INV-OTEL-06"
  - "INV-OTEL-07"
  - "INV-OTEL-08"
  - "INV-OTEL-09"
  - "INV-OTEL-10"
  - "INV-OTEL-11"
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
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-13"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
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
tags:
  - "performance"
  - "data"
  - "realtime"
  - "compliance"
  - "api"
---
# TOOL-085: add_opentelemetry

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_opentelemetry` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium-High |
| Dependencies | FastAPI, starlette, pydantic-settings; all opentelemetry SDK packages optional (lazy-imported) |
| Signature | `add_opentelemetry(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_opentelemetry", "description": "Add OpenTelemetry traces, metrics, and logs with lazy SDK imports, OTELMiddleware for request tracing, metric counters, and structlog integration.", "tags": ["extend", "infrastructure"], "entry": "add_opentelemetry"}` |
| Files created (typical) | 4 — `app/telemetry/__init__.py`, `app/telemetry/setup.py`, `app/telemetry/middleware.py`, `app/telemetry/metrics.py` |
| Files modified (typical) | 2 — `app/core/config.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_opentelemetry` tool installs a complete OpenTelemetry observability stack — distributed traces, RED metrics, and structured logs — into a FastAPI project. Teams skip instrumentation until incidents happen, then discover they have no trace IDs correlating HTTP requests to database calls to external API latencies. OpenTelemetry is the vendor-neutral answer: emit once, ship to Jaeger, Tempo, Honeycomb, Datadog, or any OTLP-compatible backend by changing one env var. The impediment is complexity: the OTel Python SDK has more than a dozen sub-packages, incompatible major versions between `opentelemetry-api` and `opentelemetry-sdk`, and a bootstrap pattern that must run exactly once before any request is handled. This tool reduces all of that to a single tool call.

It generates: (a) `app/telemetry/setup.py` with `init_telemetry()` — boots `TracerProvider` (OTLP gRPC exporter + `BatchSpanProcessor`), `MeterProvider` (OTLP metric exporter + `PeriodicExportingMetricReader`), and `LoggerProvider` (OTLP log exporter + `BatchLogRecordProcessor`); (b) `app/telemetry/middleware.py` with `OTELMiddleware` — an ASGI `BaseHTTPMiddleware` that creates a span per request with `http.method`, `http.url`, `http.route`, `http.status_code`, `http.response_time_ms` attributes, guarded by `if not settings.OTEL_ENABLED: return await call_next(request)` so the overhead is exactly zero when disabled; (c) `app/telemetry/metrics.py` with `get_meter()`, `record_request()`, `record_error()` — counter and histogram instruments created lazily on first call; (d) five settings fields — `OTEL_ENABLED` (bool, default `False`), `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_TRACES_SAMPLER`, `OTEL_TRACES_SAMPLER_ARG`; and (e) `opentelemetry-sdk>=1.23.0` and `opentelemetry-exporter-otlp>=1.23.0` appended to `requirements.txt`.

Key design decisions: **ALL** opentelemetry imports are lazy (inside function bodies) — the app boots without any OTel package installed and `OTEL_ENABLED=false` is the safe default; `OTELMiddleware.dispatch()` is a two-line pass-through when disabled (`if not settings.OTEL_ENABLED: return await call_next(request)`) so instrumented and uninstrumented deployments share the same code path; `_init_tracer_provider`, `_init_meter_provider`, `_init_logger_provider` are separate private functions each ≤ 20 LOC so they stay auditable and independently replaceable; metric instruments (`_request_counter`, `_error_counter`, `_duration_histogram`) are created lazily by `_ensure_instruments()` on first `record_request()` call — no global state at module import time; the tool is **idempotent** — detects `init_telemetry` in `app/telemetry/__init__.py`.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget (T-18) |
| Files created | ≥ 4 | Telemetry package (T-04) |
| Files modified | ≥ 2 | Config + requirements (T-05) |
| Max function LOC in generated code | ≤ 50 | Auditable (T-07) |
| Overhead when `OTEL_ENABLED=false` | 0 ms | Pure pass-through in middleware |
| Span creation latency | < 1 ms | SDK in-process; OTLP export is async/batched |
| `init_telemetry()` startup time | < 500 ms | Provider bootstraps are synchronous but fast |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── core/config.py       # No OTEL_* settings
│   └── main.py              # No telemetry init
└── requirements.txt         # no opentelemetry packages
```

No distributed tracing. No metrics. Logs have no trace correlation.

### 4.2 Telemetry setup: AFTER

```python
# app/telemetry/setup.py
def init_telemetry() -> None:
    """Bootstrap TracerProvider, MeterProvider, LoggerProvider.
    No-op when OTEL_ENABLED=False — no SDK imports."""
    from app.core.config import settings
    if not settings.OTEL_ENABLED:
        return
    _init_tracer_provider(settings)
    _init_meter_provider(settings)
    _init_logger_provider(settings)

def _init_tracer_provider(settings) -> None:
    from opentelemetry import trace            # lazy
    from opentelemetry.sdk.trace import TracerProvider  # lazy
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # lazy
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # lazy
    ...

def get_tracer(name: str = "app"):
    """Return tracer or no-op when SDK unavailable."""
```

### 4.3 OTELMiddleware: AFTER

```python
# app/telemetry/middleware.py
class OTELMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        from app.core.config import settings
        if not settings.OTEL_ENABLED:
            return await call_next(request)   # zero overhead
        return await self._traced_dispatch(request, call_next)

    async def _traced_dispatch(self, request, call_next) -> Response:
        """Wrap request in OTEL span with HTTP attributes."""
```

### 4.4 Config patch: AFTER

```python
# app/core/config.py
    # --- OpenTelemetry — added by add_opentelemetry tool ---
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    OTEL_SERVICE_NAME: str = "fastapi-app"
    OTEL_TRACES_SAMPLER: str = "parentbased_traceidratio"
    OTEL_TRACES_SAMPLER_ARG: float = 1.0
```

### 4.5 Requirements patch: AFTER

```
opentelemetry-sdk>=1.23.0
opentelemetry-exporter-otlp>=1.23.0
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `"init_telemetry" in app/telemetry/__init__.py` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any write |
| QS-3 | **Every generated `.py` AST-parses** | `ast.parse` loop on all created `.py` |
| QS-4 | **No generated function exceeds 50 LOC** | All helpers short |
| QS-5 | **ALL opentelemetry imports are lazy** | Every `from opentelemetry.*` import inside function body; never at module level |
| QS-6 | **`OTEL_ENABLED=False` is zero-overhead** | `if not settings.OTEL_ENABLED: return await call_next(request)` in middleware |
| QS-7 | **`OTEL_ENABLED` defaults to `False`** | `OTEL_ENABLED: bool = False` in generated settings block |
| QS-8 | **`OTEL_EXPORTER_OTLP_ENDPOINT` read from settings** | Never hard-coded in setup.py |
| QS-9 | **Metric instruments created lazily via `_ensure_instruments()`** | `if _meter is not None: return` guard |
| QS-10 | **`OTEL_*` fields inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` |
| QS-11 | **`opentelemetry-sdk` and `opentelemetry-exporter-otlp` added to requirements** | `_patch_requirements` appends if absent |
| QS-12 | **`execution_time_ms` set on every return path** | `_elapsed_ms(start)` on all branches |
| QS-13 | **`next_steps` include `pip install` for OTEL packages** | Hard-coded in success branch |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` | Both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes | FS snapshot identical | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 4 new files | `len(files_created) >= 4`; all exist | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(files_modified) >= 2`; all exist | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses | `ast.parse` over all `.py` | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC | AST walk; `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `OTEL_ENABLED` exists inside `class Settings` | String scan + 4-space indent | T-08 (`test_config_fields_patched`) |
| CC-09 | `OTEL_ENABLED` defaults to `False` | `"OTEL_ENABLED: bool = False" in config` | T-09 (`test_otel_disabled_by_default`) |
| CC-10 | `opentelemetry-sdk` in `requirements.txt` | `"opentelemetry-sdk" in req_content` | T-10 (`test_requirements_patched`) |
| CC-11 | `app/telemetry/__init__.py` contains `init_telemetry` | File exists + `"init_telemetry" in content` | T-11 (`test_telemetry_init_created`) |
| CC-12 | `app/telemetry/setup.py` has `init_telemetry`, `_init_tracer_provider`, `get_tracer` | File exists + substring checks | T-12 (`test_setup_created`) |
| CC-13 | All opentelemetry imports are inside function bodies (not module-level) | No `from opentelemetry` at indent=0 in any generated file | T-13 (`test_otel_imports_lazy`) |
| CC-14 | `OTELMiddleware` in `app/telemetry/middleware.py` | File exists + `"OTELMiddleware" in content` | T-14 (`test_middleware_created`) |
| CC-15 | Middleware has zero-overhead pass-through when disabled | `"if not settings.OTEL_ENABLED" in middleware` | T-15 (`test_middleware_passthrough`) |
| CC-16 | `app/telemetry/metrics.py` has `get_meter`, `record_request`, `record_error` | File exists + substring checks | T-16 (`test_metrics_created`) |
| CC-17 | Metric instruments created lazily via `_ensure_instruments()` | `"_ensure_instruments" in metrics.py` | T-17 (`test_instruments_lazy`) |
| CC-18 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | T-18 (`test_execution_time_recorded`) |
| CC-19 | `next_steps` include OTEL packages and `OTEL_ENABLED=true` guidance | `"opentelemetry" in next_steps` + `"otel_enabled" in next_steps.lower()` | T-19 (`test_next_steps_mention_otel`) |
| CC-20 | Running the tool twice leaves project AST-parseable | `ast.parse` after two runs | T-20 (`test_idempotent_project_still_parses`) |

---

## 7. Definition of Done (DoD)

- [ ] All 20 Completeness Criteria verified by `test_add_opentelemetry.py`
- [ ] `ast.parse` run on every created `.py` before returning success
- [ ] Fingerprint `"init_telemetry" in app/telemetry/__init__.py` → `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty lists
- [ ] ALL `from opentelemetry.*` imports inside function bodies — none at module level
- [ ] `OTEL_ENABLED` defaults to `False` — opt-in, not opt-out
- [ ] Middleware pass-through when `OTEL_ENABLED=false` is a single `if` check with no SDK imports
- [ ] Metric instruments created lazily on first `record_request()` call
- [ ] Config fields anchored inside `class Settings`
- [ ] `opentelemetry-sdk>=1.23.0` and `opentelemetry-exporter-otlp>=1.23.0` in requirements
- [ ] `execution_time_ms` set on every return path
- [ ] Tool exits within 5 s
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}`

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-OTEL-01 | Tool ALWAYS idempotent on second invocation | `"init_telemetry" in telemetry_init` → `no_op` | T-02, T-20 |
| INV-OTEL-02 | `dry_run=True` NEVER writes to disk | Early return before any write | T-03 |
| INV-OTEL-03 | Every generated `.py` MUST parse as valid Python | Final `ast.parse` loop | T-06, T-20 |
| INV-OTEL-04 | ALL opentelemetry imports MUST be lazy | No `from opentelemetry` at module scope in any generated file | T-13 |
| INV-OTEL-05 | `OTEL_ENABLED` MUST default to `False` | `OTEL_ENABLED: bool = False` in config patch | T-09 |
| INV-OTEL-06 | Middleware MUST be zero-cost when `OTEL_ENABLED=False` | `if not settings.OTEL_ENABLED: return await call_next(request)` first line of `dispatch` | T-15 |
| INV-OTEL-07 | OTLP endpoint MUST be read from settings | `settings.OTEL_EXPORTER_OTLP_ENDPOINT` in setup.py — never hard-coded | T-12 |
| INV-OTEL-08 | Config fields MUST live inside `class Settings` body | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` | T-08 |
| INV-OTEL-09 | OTEL SDK packages MUST be in `requirements.txt` | `_patch_requirements` appends both packages if absent | T-10 |
| INV-OTEL-10 | `ToolResult.execution_time_ms` MUST be positive | `_elapsed_ms(start)` on all branches | T-18 |
| INV-OTEL-11 | `next_steps` MUST reference OTEL packages and `OTEL_ENABLED=true` | Hard-coded in success branch | T-19 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install OTEL into a clean project**
- **As a** backend engineer wanting distributed tracing
- **When:** `add_opentelemetry(ToolInput(project_dir=...))`
- **Then:** `status="success"`, ≥ 4 files created, ≥ 2 modified (T-01, T-04, T-05)

**US-02: Re-run on already-installed project**
- **Given:** `app/telemetry/__init__.py` contains `init_telemetry`
- **When:** Tool invoked again
- **Then:** `status="no_op"`, empty lists (T-02, T-20)

**US-03: Dry-run preview**
- **When:** `add_opentelemetry(ToolInput(dry_run=True))`
- **Then:** Success + notes; filesystem unchanged (T-03)

**US-04: App boots without OTEL SDK installed**
- **Given:** `opentelemetry-sdk` not installed
- **When:** App starts with `OTEL_ENABLED=false`
- **Then:** No `ImportError`; zero SDK code executed (INV-OTEL-04, INV-OTEL-06)

**US-05: OTEL is opt-in by default**
- **Given:** App just installed OTEL layer
- **When:** App starts without setting `OTEL_ENABLED`
- **Then:** `settings.OTEL_ENABLED == False`; telemetry is silent (INV-OTEL-05)

### 9.2 Telemetry setup (US-06 .. US-10)

**US-06: Bootstrap all three providers**
- **Given:** `OTEL_ENABLED=true`, OTEL packages installed, `OTEL_EXPORTER_OTLP_ENDPOINT` set
- **When:** `init_telemetry()` called at app startup
- **Then:** TracerProvider, MeterProvider, LoggerProvider all initialised; spans flow to OTLP backend (T-12)

**US-07: `init_telemetry` is no-op when disabled**
- **Given:** `OTEL_ENABLED=false`
- **When:** `init_telemetry()` called
- **Then:** Returns immediately; no SDK package imported (INV-OTEL-05, T-12)

**US-08: Tracer usable without checking enabled flag**
- **As a** developer adding custom spans
- **Given:** `get_tracer("my_module")`
- **When:** `with tracer.start_as_current_span("my_op"):` executed
- **Then:** Span created when OTEL enabled; no-op tracer used when SDK unavailable (T-12)

**US-09: OTLP endpoint read from settings**
- **Given:** `OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317`
- **When:** `_init_tracer_provider(settings)` runs
- **Then:** `OTLPSpanExporter(endpoint="http://tempo:4317")` instantiated (INV-OTEL-07)

**US-10: Three private provider init functions stay short**
- **As a** code reviewer
- **Given:** `setup.py` with three `_init_*` helpers
- **When:** AST-walk for function length
- **Then:** Each `_init_*` function ≤ 50 LOC (QS-4, T-07)

### 9.3 OTELMiddleware (US-11 .. US-15)

**US-11: Middleware traces every request when enabled**
- **Given:** `OTEL_ENABLED=true`; request `GET /users`
- **When:** Request passes through `OTELMiddleware`
- **Then:** Span created with `http.method=GET`, `http.route=/users`, `http.status_code=200` (T-14)

**US-12: Middleware zero-overhead when disabled**
- **Given:** `OTEL_ENABLED=false`
- **When:** Request passes through `OTELMiddleware`
- **Then:** `dispatch()` returns `call_next(request)` on first line; no OTel SDK imported (INV-OTEL-06, T-15)

**US-13: Response time attribute set on span**
- **Given:** Request takes 50 ms
- **When:** Span closed
- **Then:** `http.response_time_ms >= 50` in span attributes (T-14)

**US-14: Span contains URL, method, and status**
- **Given:** `POST /items` returns 201
- **When:** Span attributes read
- **Then:** `http.method="POST"`, `http.route="/items"`, `http.status_code=201` (T-14)

**US-15: `_traced_dispatch` extracted for readability**
- **As a** code reviewer
- **When:** `middleware.py` reviewed
- **Then:** `_traced_dispatch` is a separate method; `dispatch` stays ≤ 10 LOC (T-07)

### 9.4 Metrics (US-16 .. US-20)

**US-16: `record_request` creates instruments lazily**
- **Given:** No prior `record_request` calls
- **When:** `record_request("GET", "/users", 200, 42.5)` called
- **Then:** `_ensure_instruments()` creates counter, histogram; instruments cached (INV-OTEL-04, T-17)

**US-17: `record_request` increments counter and histogram**
- **Given:** Instruments initialised
- **When:** `record_request("GET", "/users", 200, 42.5)`
- **Then:** `http_requests_total` counter incremented; `http_request_duration` histogram records 42.5 ms (T-16)

**US-18: `record_error` increments error counter for 5xx**
- **When:** `record_error("POST", "/items", 500)`
- **Then:** `http_server_error_count` incremented; WARNING logged (T-16)

**US-19: `get_meter` returns None when SDK unavailable**
- **Given:** `opentelemetry` not installed
- **When:** `get_meter("app")` called
- **Then:** `ImportError` caught; returns `None`; caller must guard `if meter is not None` (T-16)

**US-20: Metrics use standard OTEL semantic convention names**
- **When:** Instrument names read from `metrics.py`
- **Then:** `http.server.request_count`, `http.server.request_duration`, `http.server.error_count` (T-16)

### 9.5 Config and operator experience (US-21 .. US-25)

**US-21: Enable OTEL via env var**
- **Given:** `OTEL_ENABLED=true` in `.env`
- **When:** App starts
- **Then:** `init_telemetry()` bootstraps all providers (INV-OTEL-08)

**US-22: OTEL packages added to requirements**
- **When:** Tool runs on project without OTEL packages
- **Then:** `opentelemetry-sdk>=1.23.0` and `opentelemetry-exporter-otlp>=1.23.0` in `requirements.txt` (INV-OTEL-09, T-10)

**US-23: `next_steps` guide operator to enable and install**
- **When:** `result.next_steps` inspected
- **Then:** Contains `"OTEL_ENABLED=true"` guidance and `"pip install opentelemetry-sdk"` (INV-OTEL-11, T-19)

**US-24: Execution time recorded**
- **Then:** `result.execution_time_ms > 0` (INV-OTEL-10, T-18)

**US-25: Second run leaves project parseable**
- **Given:** Tool ran twice
- **When:** All `.py` AST-parsed
- **Then:** No `SyntaxError` (T-20)

---

## 10. Test Plan

All 20 tests live in `adapt/extend/infrastructure/test_add_opentelemetry.py`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `otel_t01` | `add_opentelemetry(ToolInput(project_dir))` | `result.status == "success"` (CC-01) |
| T-02 | `test_idempotent` | Fixture `otel_t02`; run once | Run again | `r2.status == "no_op"` (CC-02) |
| T-03 | `test_dry_run` | Fixture `otel_t03` | `dry_run=True` | Success; FS unchanged (CC-03) |
| T-04 | `test_files_created_count` | Fixture `otel_t04` | Run tool | `len(files_created) >= 4`; all exist (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `otel_t05` | Run tool | `len(files_modified) >= 2`; all exist (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `otel_t06`; run | AST-parse all `.py` | No `SyntaxError` (CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `otel_t07`; run | AST walk `app/` | `max_loc <= 50` (CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `otel_t08`; run | Read `config.py` | `OTEL_ENABLED` with 4-space indent (CC-08) |
| T-09 | `test_otel_disabled_by_default` | Fixture `otel_t09`; run | Read `config.py` | `"OTEL_ENABLED: bool = False"` present (INV-OTEL-05, CC-09) |
| T-10 | `test_requirements_patched` | Fixture `otel_t10`; run | Read `requirements.txt` | Both `opentelemetry-sdk` and `opentelemetry-exporter-otlp` present (CC-10) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_telemetry_init_created` | Fixture `otel_t11`; run | Read `app/telemetry/__init__.py` | Contains `"init_telemetry"` (CC-11) |
| T-12 | `test_setup_created` | Fixture `otel_t12`; run | Read `app/telemetry/setup.py` | Contains `init_telemetry`, `_init_tracer_provider`, `get_tracer` (CC-12) |
| T-13 | `test_otel_imports_lazy` | Fixture `otel_t13`; run | Read all generated `.py` files | No `from opentelemetry` at indent=0 (module scope) (INV-OTEL-04, CC-13) |
| T-14 | `test_middleware_created` | Fixture `otel_t14`; run | Read `app/telemetry/middleware.py` | Contains `OTELMiddleware` and `http.method` attribute (CC-14) |
| T-15 | `test_middleware_passthrough` | Fixture `otel_t15`; run | Read `app/telemetry/middleware.py` | Contains `"if not settings.OTEL_ENABLED"` (INV-OTEL-06, CC-15) |
| T-16 | `test_metrics_created` | Fixture `otel_t16`; run | Read `app/telemetry/metrics.py` | Contains `get_meter`, `record_request`, `record_error` (CC-16) |
| T-17 | `test_instruments_lazy` | Fixture `otel_t17`; run | Read `app/telemetry/metrics.py` | Contains `"_ensure_instruments"` (CC-17) |

### 10.4 Category D — Meta (T-18 .. T-20)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-18 | `test_execution_time_recorded` | Fixture `otel_t18` | `result.execution_time_ms` | `> 0` (CC-18) |
| T-19 | `test_next_steps_mention_otel` | Fixture `otel_t19` | Lowercase-join `result.next_steps` | Contains `"opentelemetry"` and `"otel_enabled"` (CC-19) |
| T-20 | `test_idempotent_project_still_parses` | Fixture `otel_t20`; run twice | AST-parse all `.py` | No `SyntaxError` (CC-20) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_opentelemetry.py -v
```

Target: 20/20 passed, 0 failed.

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_prometheus_metrics` (TOOL-086) | No | ✅ Compatible | OTEL metrics + Prometheus RED can coexist; OTEL exports to OTLP, Prometheus scrapes `/metrics` |
| `add_structured_logging` (TOOL-087) | No | ✅ Compatible | structlog `correlation_id` and OTEL `trace_id` should both appear in log entries |
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | Worker tasks can create child spans under the parent HTTP span |
| `add_health_deep` (TOOL-061) | No | ✅ Compatible | Health check endpoint should be excluded from tracing via `OTEL_EXCLUDED_URLS` |
| `add_webhook_sender` (TOOL-015) | No | ✅ Compatible | Propagate `traceparent` header in outbound webhook requests |
| `add_multi_tenancy` (TOOL-008) | No | ✅ Compatible | Add `tenant_id` span attribute in middleware for tenant-scoped trace filtering |

---

## 12. Rollback Procedure

### 12.1 Code rollback

```bash
git checkout HEAD -- app/core/config.py requirements.txt
rm -rf app/telemetry/
```

Also remove `init_telemetry()` call and `OTELMiddleware` addition from `app/main.py` if manually added.

### 12.2 No database rollback required

OTEL layer has no ORM model or migration.

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Missing `app/` directory | `validate_project_dir` fails → `status="error"` |
| EC-02 | `app/telemetry/__init__.py` already contains `init_telemetry` | Early return `status="no_op"` |
| EC-03 | `dry_run=True` | Success + notes; no FS changes |
| EC-04 | OTEL SDK not installed; `OTEL_ENABLED=true` | `ImportError` raised inside `_init_tracer_provider`; app should catch and log |
| EC-05 | `OTEL_ENABLED=false` (default) | `init_telemetry()` returns immediately; zero SDK imports |
| EC-06 | `OTEL_ENABLED` already in config | `_patch_config` early-returns |
| EC-07 | `opentelemetry-sdk` already in requirements | `_patch_requirements` skips that line |
| EC-08 | `opentelemetry-exporter-otlp` already in requirements | `_patch_requirements` skips that line |
| EC-09 | `app/core/config.py` lacks anchor field | Falls back to `settings = Settings()` or EOF append |
| EC-10 | Tool runs twice | Second run returns `no_op`; project parses (T-20) |
| EC-11 | OTLP endpoint unreachable | `BatchSpanProcessor` buffers spans; drops on overflow; no API impact |
| EC-12 | `get_meter()` SDK unavailable | Returns `None`; `_ensure_instruments()` no-ops |

---

## 14. Security Considerations

| # | Concern | Mitigation |
|---|---------|------------|
| SEC-01 | Trace data exfiltration | `OTEL_EXPORTER_OTLP_ENDPOINT` should point to an internal collector, not a public endpoint |
| SEC-02 | PII in span attributes | `http.url` attribute may contain query params; sanitise before adding to spans or use `OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT` |
| SEC-03 | Overhead when OTEL enabled | Use `OTEL_TRACES_SAMPLER_ARG < 1.0` (e.g., `0.1`) in high-traffic production to limit overhead |
| SEC-04 | Version pinning | Both `opentelemetry-sdk` and `opentelemetry-exporter-otlp` pinned at `>=1.23.0`; keep both in sync |

---

## 15. Observability

| Signal | Location | Notes |
|--------|----------|-------|
| `OpenTelemetry initialised for service '{name}'` | `init_telemetry()` | INFO level |
| `OTEL disabled — skipping telemetry bootstrap` | `init_telemetry()` | DEBUG level |
| `5xx error recorded: {method} {path} → {status}` | `record_error()` | WARNING level |

---

## 16. Changelog

| Version | Date | Change |
|---------|------|--------|
| v1 | 2026-04-15 | Initial spec — lazy OTEL imports, zero-overhead disabled path, 3 providers, 20 CCs |
