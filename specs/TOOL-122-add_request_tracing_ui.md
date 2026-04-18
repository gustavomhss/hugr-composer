# TOOL-122 — add_request_tracing_ui

## 1. Overview

| Field | Value |
|---|---|
| **Tool ID** | TOOL-122 |
| **MCP name** | `fastapi_add_request_tracing_ui` |
| **Entry point** | `adapt/extend/infrastructure/add_request_tracing_ui.py::add_request_tracing_ui` |
| **Tags** | `observability`, `tracing`, `dashboard`, `ring-buffer`, `timing`, `debug` |
| **Input** | `ToolInput(project_dir, dry_run=False)` |
| **Output** | `ToolResult(status, files_created, files_modified, notes, next_steps, execution_time_ms)` |
| **Idempotency fingerprint** | `"TracingBuffer" in app/tracing_ui/__init__.py` |
| **Prerequisite check** | `app/` directory exists |
| **Files created (min)** | 4 (`__init__.py`, `collector.py`, `middleware.py`, `dashboard.html`, tracing route) |
| **Files modified (min)** | 1 (`app/main.py` or `app/core/config.py`) |
| **Test file** | `adapt/extend/infrastructure/test_add_request_tracing_ui.py` |

---

## 2. Purpose

Debugging slow requests in production without an external tracing system requires an embedded, low-overhead request trace buffer. `add_request_tracing_ui` installs a complete in-process tracing system with a browser-based dashboard:

1. **`app/tracing_ui/__init__.py`** — Ring-buffer core:
   - `TracingBuffer` — fixed-capacity ring buffer (default capacity 1000). Stores trace records as dicts.
   - `get_tracing_buffer()` — singleton factory.
   - `make_request_id()` — generates a UUID-based request identifier.
   - `TracingBuffer.record(trace)` — appends a trace; evicts oldest when full.
   - `TracingBuffer.get_all()` — returns all buffered traces (newest-first).
   - `TracingBuffer.get_by_id(request_id)` — returns a single trace or `None`.
   - `TracingBuffer.get_slow(percentile=99)` — returns requests in the top percentile by duration.

2. **`app/tracing_ui/collector.py`** — Span-level timing:
   - `TimingCollector` — accumulates named spans (sub-operations) for a single request.
   - `span(name)` — context manager; records start/end timestamps.
   - `record_span(name, duration_ms)` — explicit span recording.

3. **`app/tracing_ui/middleware.py`** — ASGI middleware:
   - `TracingMiddleware` — assigns `make_request_id()` to every request; times the full request; calls `TracingBuffer.record()`.

4. **Routes** in `app/api/routes/tracing.py`:
   - `GET /tracing/requests` — returns all buffered traces as JSON.
   - `GET /tracing/requests/{request_id}` — returns a single trace.
   - `GET /tracing/slow` — returns slowest requests above the percentile threshold.
   - `GET /tracing/dashboard` — serves the HTML dashboard.

5. **`app/tracing_ui/templates/dashboard.html`** — Auto-refreshing browser dashboard:
   - Uses `setInterval` to fetch `/tracing/requests` every few seconds.
   - Renders a `<table>` of recent requests with request ID, path, method, status code, and duration.

Config fields (`TRACING_UI_ENABLED`, `TRACING_UI_BUFFER_SIZE`, `TRACING_UI_AUTH_REQUIRED`) are injected with 4-space indent. The tracing router is registered in `app/main.py`. No optional SDK imports (redis, aiobotocore, stripe, celery) appear at module top level.

---

## 3. Performance SLOs

| Metric | Target |
|---|---|
| Tool execution time | < 2 s on a cold fixture project |
| `execution_time_ms` field | > 0 (always recorded) |
| `TracingBuffer.record()` | O(1) amortised (ring buffer) |
| `TracingBuffer.get_slow()` | O(n log n) — sort of buffered traces |
| Default buffer capacity | 1000 entries |
| Files created | ≥ 4 |
| Files modified | ≥ 1 |
| Max function LOC in generated `app/tracing_ui/` | ≤ 50 |

---

## 4. Before / After

### 4.1 Project state — before

```
app/
  core/
    config.py    # No TRACING_UI_* fields
  main.py        # app = FastAPI(...)
```

### 4.2 Project state — after

```
app/
  core/
    config.py                              # TRACING_UI_ENABLED, TRACING_UI_BUFFER_SIZE,
                                           # TRACING_UI_AUTH_REQUIRED injected
  tracing_ui/
    __init__.py                            # TracingBuffer (ring=1000), get_tracing_buffer,
                                           # make_request_id, record, get_all,
                                           # get_by_id, get_slow
    collector.py                           # TimingCollector, span(), record_span()
    middleware.py                          # TracingMiddleware
    templates/
      dashboard.html                       # setInterval auto-refresh + <table>
  api/
    routes/
      tracing.py                           # /requests, /{request_id}, /slow, /dashboard
  main.py                                  # tracing router registered
```

### 4.3 TracingBuffer ring buffer

```python
# app/tracing_ui/__init__.py (generated)
import uuid
from collections import deque
from typing import Any

_buffer: "TracingBuffer | None" = None


class TracingBuffer:
    """Fixed-capacity ring buffer for request traces."""

    def __init__(self, capacity: int = 1000) -> None:
        self._capacity = capacity
        self._traces: deque[dict[str, Any]] = deque(maxlen=capacity)

    def record(self, trace: dict[str, Any]) -> None:
        """Append a trace; oldest is evicted automatically when full."""
        self._traces.appendleft(trace)

    def get_all(self) -> list[dict[str, Any]]:
        """Return all buffered traces (newest first)."""
        return list(self._traces)

    def get_by_id(self, request_id: str) -> dict[str, Any] | None:
        """Return the trace for a specific request ID."""
        for trace in self._traces:
            if trace.get("request_id") == request_id:
                return trace
        return None

    def get_slow(self, percentile: int = 99) -> list[dict[str, Any]]:
        """Return requests in the top percentile by duration_ms."""
        traces = sorted(self._traces, key=lambda t: t.get("duration_ms", 0), reverse=True)
        cutoff = max(1, int(len(traces) * (1 - percentile / 100)))
        return traces[:cutoff]


def get_tracing_buffer() -> TracingBuffer:
    """Return the global TracingBuffer singleton."""
    global _buffer
    if _buffer is None:
        _buffer = TracingBuffer(capacity=1000)
    return _buffer


def make_request_id() -> str:
    """Generate a UUID4-based request identifier."""
    return str(uuid.uuid4())
```

### 4.4 TimingCollector with span context manager

```python
# app/tracing_ui/collector.py (generated)
import contextlib
import time
from typing import Generator


class TimingCollector:
    """Accumulates named spans for a single request."""

    def __init__(self) -> None:
        self._spans: dict[str, float] = {}

    @contextlib.contextmanager
    def span(self, name: str) -> Generator[None, None, None]:
        """Context manager that records the duration of a named span."""
        start = time.monotonic()
        yield
        self.record_span(name, (time.monotonic() - start) * 1000)

    def record_span(self, name: str, duration_ms: float) -> None:
        """Explicitly record a span duration."""
        self._spans[name] = self._spans.get(name, 0.0) + duration_ms
```

### 4.5 dashboard.html — auto-refresh

```html
<!-- app/tracing_ui/templates/dashboard.html (generated) -->
<script>
setInterval(function() {
  fetch("/tracing/requests")
    .then(r => r.json())
    .then(data => {
      const tbody = document.getElementById("trace-body");
      tbody.innerHTML = "";
      data.forEach(trace => {
        const row = `<tr>
          <td>${trace.request_id || ""}</td>
          <td>${trace.path || ""}</td>
          <td>${trace.method || ""}</td>
          <td>${trace.status_code || ""}</td>
          <td>${trace.duration_ms || ""}ms</td>
        </tr>`;
        tbody.innerHTML += row;
      });
    });
}, 3000);
</script>
<table id="trace-table">
  <thead>...</thead>
  <tbody id="trace-body"></tbody>
</table>
```

### 4.6 Config patch

```python
    # --- Request tracing UI — added by add_request_tracing_ui tool ---
    TRACING_UI_ENABLED: bool = True
    TRACING_UI_BUFFER_SIZE: int = 1000
    TRACING_UI_AUTH_REQUIRED: bool = True
```

---

## 5. Quality Standards

| ID | Standard |
|---|---|
| QS-1 | `status == "success"` on first run |
| QS-2 | Second run returns `status == "no_op"` |
| QS-3 | `dry_run=True` returns success without writing any bytes |
| QS-4 | `files_created` contains ≥ 4 entries; all exist on disk |
| QS-5 | `files_modified` contains ≥ 1 entry; exists on disk |
| QS-6 | Every generated `.py` file passes `ast.parse()` |
| QS-7 | No function in `app/tracing_ui/` exceeds 50 LOC |
| QS-8 | `TRACING_UI_ENABLED`, `TRACING_UI_BUFFER_SIZE`, `TRACING_UI_AUTH_REQUIRED` in `config.py` with 4-space indent |
| QS-9 | `TracingBuffer` and `get_tracing_buffer` in `app/tracing_ui/__init__.py` |
| QS-10 | `tracing_ui` or `tracing_router` in `app/main.py` |
| QS-11 | `TimingCollector`, `def span`, `record_span` in `collector.py` |
| QS-12 | `TracingMiddleware` in `middleware.py` |
| QS-13 | `/requests`, `request_id`, `slow`, `dashboard` in `tracing.py` |
| QS-14 | `<script>` and `tracing/requests` and `<table` in `dashboard.html` |
| QS-15 | `get_slow` and `percentile` in `__init__.py` |
| QS-16 | No optional SDK (`redis`, `aiobotocore`, `stripe`, `celery`) at module top level |
| QS-17 | `make_request_id` and `uuid` in `__init__.py` |
| QS-18 | `setInterval` in `dashboard.html` |
| QS-19 | `def record`, `def get_all`, `def get_by_id` in `__init__.py` |
| QS-20 | Buffer size default `1000` appears in `__init__.py` |

---

## 6. Completeness Criteria

| ID | Test function | What it verifies |
|---|---|---|
| CC-01 | `test_success_status` | Tool returns `status='success'` on a fresh project |
| CC-02 | `test_idempotent` | Second run returns `status='no_op'` |
| CC-03 | `test_dry_run` | `dry_run=True` writes no files |
| CC-04 | `test_files_created_count` | At least 4 files created; all exist on disk |
| CC-05 | `test_files_modified_count` | At least 1 file modified; exists on disk |
| CC-06 | `test_all_py_parse` | Every `.py` file AST-parses clean |
| CC-07 | `test_no_function_over_50_loc` | No function in `app/tracing_ui/` exceeds 50 LOC |
| CC-08 | `test_config_fields_patched` | 3 `TRACING_UI_*` fields with 4-space indent |
| CC-09 | `test_tracing_buffer_init` | `TracingBuffer` and `get_tracing_buffer` in `__init__.py` |
| CC-10 | `test_routes_registered` | `tracing_ui` or `tracing_router` in `main.py` |
| CC-11 | `test_timing_collector_created` | `TimingCollector`, `def span`, `record_span` in `collector.py` |
| CC-12 | `test_middleware_created` | `TracingMiddleware` in `middleware.py` |
| CC-13 | `test_tracing_routes_file` | `/requests`, `request_id`, `slow`, `dashboard` in route file |
| CC-14 | `test_dashboard_html_created` | `<script>`, `tracing/requests`, `<table` in `dashboard.html` |
| CC-15 | `test_tracing_buffer_get_slow` | `get_slow` and `percentile` in `__init__.py` |
| CC-16 | `test_no_top_level_optional_sdk_imports` | No `redis`, `aiobotocore`, `stripe`, `celery` at module top level |
| CC-17 | `test_execution_time_recorded` | `execution_time_ms > 0` |
| CC-18 | `test_next_steps_present` | `next_steps` mentions `TRACING_UI_ENABLED` or `tracing` |
| CC-19 | `test_make_request_id_defined` | `make_request_id` and `uuid` in `__init__.py` |
| CC-20 | `test_dashboard_auto_refresh` | `setInterval` in `dashboard.html` |
| CC-21 | `test_tracing_buffer_record_method` | `def record`, `def get_all`, `def get_by_id` all present |
| CC-22 | `test_buffer_size_default` | `1000` present in `__init__.py` |
| CC-23 | `test_notes_mention_ring_buffer_and_dashboard` | Notes mention `ring buffer` or `tracing` AND `dashboard` |
| CC-24 | `test_idempotent_project_still_parses` | All `.py` files parse after two consecutive runs |

---

## 7. Definition of Done

- [ ] All 24 tests in `test_add_request_tracing_ui.py` pass
- [ ] `TracingBuffer` ring buffer with capacity 1000; `record`, `get_all`, `get_by_id`, `get_slow(percentile)` methods
- [ ] `make_request_id()` generates UUID4-based identifiers
- [ ] `TimingCollector` with `span()` context manager and `record_span()`
- [ ] `TracingMiddleware` instruments every request
- [ ] All 4 tracing routes: `/requests`, `/{request_id}`, `/slow`, `/dashboard`
- [ ] `dashboard.html` with `setInterval`, `fetch /tracing/requests`, `<table>`
- [ ] No optional SDK imports at module top level in `tracing_ui/` files
- [ ] 3 `TRACING_UI_*` config fields with 4-space indent

---

## 8. Invariants

| ID | Invariant |
|---|---|
| INV-TUI-001 | `TracingBuffer` default capacity MUST be 1000 |
| INV-TUI-002 | `get_slow()` MUST accept a `percentile` parameter |
| INV-TUI-003 | No optional SDK imports (`redis`, `aiobotocore`, `stripe`, `celery`) at module top level |
| INV-TUI-004 | `make_request_id()` MUST use UUID generation |
| INV-TUI-005 | `dashboard.html` MUST use `setInterval` for auto-refresh |
| INV-TUI-006 | Idempotency fingerprint is `"TracingBuffer" in app/tracing_ui/__init__.py` |
| INV-TUI-007 | All generated `.py` files pass `ast.parse()` before `ToolResult` is returned |

---

## 9. User Stories

| ID | Story |
|---|---|
| US-01 | As a developer, I want a browser-based dashboard so that I can inspect recent request traces without connecting to an external system. |
| US-02 | As an SRE, I want `GET /tracing/slow` so that I can find slow requests at a glance. |
| US-03 | As a developer, I want `TimingCollector.span()` so that I can annotate sub-operations with named timing spans. |
| US-04 | As a platform engineer, I want `TRACING_UI_AUTH_REQUIRED` so that the dashboard is not publicly accessible. |
| US-05 | As an ops engineer, I want auto-refresh every 3 seconds so that the dashboard is always current. |
| US-06 | As a developer, I want `get_by_id(request_id)` so that I can deep-link to a specific trace from logs. |

---

## 10. Design Decisions

| Decision | Rationale |
|---|---|
| Ring buffer with `deque(maxlen=N)` | O(1) insert; automatic eviction; no background GC thread |
| Capacity 1000 as default | Balances memory (< 5 MB) with useful history window |
| `setInterval` in plain JavaScript | Zero external dependencies; works in any browser |
| `uuid.uuid4()` for request IDs | Globally unique; no coordination required |
| `TimingCollector` as a context manager | Pythonic span API; exception-safe timing |
| No optional SDK imports at top level | `tracing_ui` must add zero boot dependencies |
| `TRACING_UI_AUTH_REQUIRED` default True | Dashboard exposes internal request details — protect by default |

---

## 11. Dependencies

| Package | Version | Purpose | Import style |
|---|---|---|---|
| `uuid` | stdlib | `make_request_id()` | Top-level |
| `collections` | stdlib | `deque` for ring buffer | Top-level |
| `contextlib` | stdlib | `span()` context manager | Top-level |
| `starlette` | (FastAPI dep) | `BaseHTTPMiddleware` | Top-level |

---

## 12. Error Handling

| Scenario | Behavior |
|---|---|
| `__init__.py` already contains `TracingBuffer` | Return `status="no_op"` |
| `app/` directory missing | Return `status="error"` |
| Generated `.py` has `SyntaxError` | Return `status="error"`; file NOT committed |
| Buffer full | Oldest trace evicted automatically by `deque(maxlen=N)` |
| `get_by_id()` with unknown ID | Returns `None` |
| `get_slow()` called on empty buffer | Returns `[]` |

---

## 13. Security Considerations

- `TRACING_UI_AUTH_REQUIRED` defaults to `True`. The dashboard MUST be gated behind auth — it shows all request paths, status codes, and durations which can reveal internal API structure.
- Trace records must not include request bodies or response bodies — headers and metadata only.
- `GET /tracing/requests` should be restricted to admin roles in production.
- The dashboard HTML is served by the same FastAPI app — no separate web server required, but the route must be protected.

---

## 14. Testing Guide

```bash
# Run full test suite
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_request_tracing_ui.py -v

# Run standalone
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_request_tracing_ui.py

# Verify no optional SDK at top level
python3 -c "
import ast
from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_request_tracing_ui import add_request_tracing_ui
from tests.common.fixture_factory import create_fixture_project
p = create_fixture_project(name='tui_manual')
add_request_tracing_ui(ToolInput(project_dir=str(p)))
for pyfile in sorted((p / 'app' / 'tracing_ui').rglob('*.py')):
    tree = ast.parse(pyfile.read_text())
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    modules = [getattr(n,'module',None) or [a.name for a in n.names] for n in top]
    print(pyfile.name, modules)
"
```

---

## 15. Files Reference

| File | Role |
|---|---|
| `adapt/extend/infrastructure/add_request_tracing_ui.py` | Tool entry point |
| `adapt/extend/infrastructure/test_add_request_tracing_ui.py` | 24-test structural test suite |
| `app/tracing_ui/__init__.py` | TracingBuffer, get_tracing_buffer, make_request_id, record, get_all, get_by_id, get_slow |
| `app/tracing_ui/collector.py` | TimingCollector, span(), record_span() |
| `app/tracing_ui/middleware.py` | TracingMiddleware |
| `app/tracing_ui/templates/dashboard.html` | Auto-refresh HTML dashboard |
| `app/api/routes/tracing.py` | /requests, /{request_id}, /slow, /dashboard |
| `app/core/config.py` | Patched with TRACING_UI_ENABLED, TRACING_UI_BUFFER_SIZE, TRACING_UI_AUTH_REQUIRED |
| `app/main.py` | Patched with tracing router |

---

## 16. Changelog

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-04-15 | Initial spec — 24 CCs, ring buffer, auto-refresh dashboard, TimingCollector |
