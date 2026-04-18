# TOOL-120 — add_cost_tracker

## 1. Overview

| Field | Value |
|---|---|
| **Tool ID** | TOOL-120 |
| **MCP name** | `fastapi_add_cost_tracker` |
| **Entry point** | `adapt/extend/infrastructure/add_cost_tracker.py::add_cost_tracker` |
| **Tags** | `observability`, `cost`, `tracking`, `middleware`, `db`, `s3`, `api` |
| **Input** | `ToolInput(project_dir, dry_run=False)` |
| **Output** | `ToolResult(status, files_created, files_modified, notes, next_steps, execution_time_ms)` |
| **Idempotency fingerprint** | `"CostTracker" in app/costs/tracker.py` |
| **Prerequisite check** | `app/` directory exists |
| **Files created (min)** | 4 (`tracker.py`, `estimators.py`, `cost_tracker.py` middleware, `costs.py` route) |
| **Files modified (min)** | 2 (`app/core/config.py`, routes `__init__.py`) |
| **Test file** | `adapt/extend/infrastructure/test_add_cost_tracker.py` |

---

## 2. Purpose

Cloud infrastructure costs are invisible inside a FastAPI app until the bill arrives. `add_cost_tracker` instruments every request with per-component cost estimates, exposes them as an `X-Request-Cost-Estimate` response header, and aggregates them into daily/weekly/monthly summaries. It installs four components:

1. **`app/costs/tracker.py`** — Core tracker:
   - `CostTracker` — thread-safe accumulator. Stores `CostEstimate` instances keyed by `(endpoint, method)` tuple.
   - `RequestContext` — dataclass capturing per-request metadata (endpoint, method, start time, component costs).
   - `CostEstimate` — dataclass with `total`, per-component breakdown, and `as_header_value()` which returns a `$`-prefixed string (e.g., `"$0.0023"`).
   - `get_by_endpoint(endpoint)` — returns aggregated cost stats for a specific endpoint.
   - `get_summary()` — returns a dict with `"daily"`, `"weekly"`, `"monthly"` keys.

2. **`app/costs/estimators.py`** — Three pluggable estimators:
   - `DBQueryCostEstimator` — `component = "db"`, uses `COST_DB_QUERY_RATE` from settings.
   - `S3CostEstimator` — `component = "s3"`, uses `COST_S3_PER_GB`.
   - `APICostEstimator` — `component = "api"`, uses `COST_API_CALL_RATE`.
   - Each estimator exposes an `estimate(context: RequestContext) -> float` method.

3. **`app/middleware/cost_tracker.py`** — ASGI middleware:
   - `CostMiddleware` — wraps every request; calls each estimator; sets `X-Request-Cost-Estimate` on the response.
   - Catches `except Exception` and continues — cost tracking must NEVER block a request (non-blocking pattern).

4. **`app/api/routes/costs.py`** — Two management routes:
   - `GET /costs/summary` — returns daily/weekly/monthly aggregates.
   - `GET /costs/by-endpoint` — returns per-endpoint breakdown.

Config fields (`COST_TRACKING_ENABLED`, `COST_DB_QUERY_RATE`, `COST_S3_PER_GB`, `COST_API_CALL_RATE`) are injected with 4-space indent. The costs router is registered in `app/routes/__init__.py`.

---

## 3. Performance SLOs

| Metric | Target |
|---|---|
| Tool execution time | < 2 s on a cold fixture project |
| `execution_time_ms` field | > 0 (always recorded) |
| Cost estimation overhead per request | < 1 ms (three estimator calls) |
| Files created | ≥ 4 |
| Files modified | ≥ 2 |
| Max function LOC in generated `app/` | ≤ 50 |

---

## 4. Before / After

### 4.1 Project state — before

```
app/
  core/
    config.py    # No COST_* fields
  routes/
    __init__.py
```

### 4.2 Project state — after

```
app/
  core/
    config.py                     # 4 COST_* fields injected
  costs/
    tracker.py                    # CostTracker, RequestContext, CostEstimate
    estimators.py                 # DBQueryCostEstimator, S3CostEstimator, APICostEstimator
  middleware/
    cost_tracker.py               # CostMiddleware
  api/
    routes/
      costs.py                    # GET /costs/summary, GET /costs/by-endpoint
  routes/
    __init__.py                   # costs_router registered
```

### 4.3 CostEstimate — as_header_value

```python
# app/costs/tracker.py (generated)
@dataclass
class CostEstimate:
    """Per-request cost estimate with component breakdown."""

    total: float = 0.0
    components: dict[str, float] = field(default_factory=dict)

    def as_header_value(self) -> str:
        """Return a $-prefixed string for the X-Request-Cost-Estimate header.

        Returns:
            String like "$0.0023".
        """
        return f"${self.total:.4f}"
```

### 4.4 Estimators with component attribute

```python
# app/costs/estimators.py (generated)
class DBQueryCostEstimator:
    component = "db"

    def estimate(self, context: RequestContext) -> float:
        rate = getattr(settings, "COST_DB_QUERY_RATE", 0.0001)
        return float(rate) * context.db_query_count


class S3CostEstimator:
    component = "s3"

    def estimate(self, context: RequestContext) -> float:
        rate_per_gb = getattr(settings, "COST_S3_PER_GB", 0.023)
        return float(rate_per_gb) * context.s3_bytes_transferred / (1024 ** 3)


class APICostEstimator:
    component = "api"

    def estimate(self, context: RequestContext) -> float:
        rate = getattr(settings, "COST_API_CALL_RATE", 0.000001)
        return float(rate)
```

### 4.5 CostMiddleware — non-blocking pattern

```python
# app/middleware/cost_tracker.py (generated)
class CostMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        try:
            ctx = RequestContext(endpoint=request.url.path, method=request.method)
            estimate = CostEstimate()
            for estimator in _ESTIMATORS:
                try:
                    cost = estimator.estimate(ctx)
                    estimate.components[estimator.component] = cost
                    estimate.total += cost
                except Exception:
                    pass  # never block the request
            response.headers["X-Request-Cost-Estimate"] = estimate.as_header_value()
        except Exception:
            pass  # non-blocking
        return response
```

### 4.6 get_summary — daily/weekly/monthly

```python
def get_summary(self) -> dict[str, float]:
    """Return aggregated costs keyed by period.

    Returns:
        Dict with 'daily', 'weekly', 'monthly' keys.
    """
    return {
        "daily": self._sum_period(86_400),
        "weekly": self._sum_period(604_800),
        "monthly": self._sum_period(2_592_000),
    }
```

### 4.7 Config patch (4 fields)

```python
    # --- Cost tracker — added by add_cost_tracker tool ---
    COST_TRACKING_ENABLED: bool = True
    COST_DB_QUERY_RATE: float = 0.0001
    COST_S3_PER_GB: float = 0.023
    COST_API_CALL_RATE: float = 0.000001
```

---

## 5. Quality Standards

| ID | Standard |
|---|---|
| QS-1 | `status == "success"` on first run against a fresh fixture project |
| QS-2 | Second run returns `status == "no_op"` |
| QS-3 | `dry_run=True` returns success without writing any bytes |
| QS-4 | `files_created` contains ≥ 4 entries; all paths exist on disk |
| QS-5 | `files_modified` contains ≥ 2 entries; all paths exist on disk |
| QS-6 | Every generated `.py` file passes `ast.parse()` |
| QS-7 | No function in `app/` exceeds 50 LOC |
| QS-8 | All 4 `COST_*` fields in `config.py` with 4-space indent |
| QS-9 | `costs_router` or `costs` in `app/routes/__init__.py` |
| QS-10 | `CostTracker`, `RequestContext`, `CostEstimate` in `tracker.py` |
| QS-11 | `DBQueryCostEstimator`, `S3CostEstimator`, `APICostEstimator` in `estimators.py` |
| QS-12 | `CostMiddleware` in `middleware/cost_tracker.py` with `X-Request-Cost-Estimate` header |
| QS-13 | `/summary` and `/by-endpoint` endpoints in `costs.py` |
| QS-14 | `as_header_value` method exists; returns `$`-prefixed string |
| QS-15 | `component = "db"`, `component = "s3"`, `component = "api"` in `estimators.py` |
| QS-16 | `def get_by_endpoint` exists in `tracker.py` |
| QS-17 | `"daily"`, `"weekly"`, `"monthly"` keys in `get_summary()` |
| QS-18 | `except Exception` in `CostMiddleware` (non-blocking pattern) |

---

## 6. Completeness Criteria

| ID | Test function | What it verifies |
|---|---|---|
| CC-01 | `test_success_status` | Tool returns `status='success'` on a fresh project |
| CC-02 | `test_idempotent` | Second run returns `status='no_op'`; no files created or modified |
| CC-03 | `test_dry_run` | `dry_run=True` returns success without writing any bytes |
| CC-04 | `test_files_created_count` | At least 4 files created; all exist on disk |
| CC-05 | `test_files_modified_count` | At least 2 files modified; all exist on disk |
| CC-06 | `test_all_py_parse` | Every generated `.py` file AST-parses clean |
| CC-07 | `test_no_function_over_50_loc` | No function in `app/` exceeds 50 LOC |
| CC-08 | `test_config_fields_patched` | All 4 `COST_*` fields present with 4-space indent |
| CC-09 | `test_routes_registered` | `costs_router` or `costs` in routes `__init__` |
| CC-10 | `test_cost_tracker_core_created` | `CostTracker`, `RequestContext`, `CostEstimate` in `tracker.py` |
| CC-11 | `test_estimators_created` | All 3 estimators present in `estimators.py` |
| CC-12 | `test_cost_middleware_created` | `CostMiddleware` with `X-Request-Cost-Estimate` header |
| CC-13 | `test_cost_routes_endpoints` | `/summary` and `/by-endpoint` present in `costs.py` |
| CC-14 | `test_header_value_format` | `as_header_value` exists; returns `$`-prefixed string |
| CC-15 | `test_estimator_components_named` | `component = "db"`, `"s3"`, `"api"` all present |
| CC-16 | `test_get_by_endpoint_exists` | `def get_by_endpoint` in `tracker.py` |
| CC-17 | `test_get_summary_periods` | `"daily"`, `"weekly"`, `"monthly"` in `tracker.py` |
| CC-18 | `test_execution_time_recorded` | `execution_time_ms > 0` |
| CC-19 | `test_next_steps_present` | `next_steps` non-empty; mentions `cost` or `enabled` |
| CC-20 | `test_idempotent_project_still_parses` | All `.py` files parse after two consecutive runs |
| CC-21 | `test_cost_middleware_non_blocking` | `except Exception` present in `CostMiddleware` |

---

## 7. Definition of Done

- [ ] All 21 tests in `test_add_cost_tracker.py` pass
- [ ] `CostTracker`, `RequestContext`, `CostEstimate` (with `as_header_value` returning `$`-prefix) generated
- [ ] Three estimators with `component` attributes: `"db"`, `"s3"`, `"api"`
- [ ] `CostMiddleware` sets `X-Request-Cost-Estimate` header; catches all exceptions (non-blocking)
- [ ] `get_summary()` returns `"daily"`, `"weekly"`, `"monthly"` keys
- [ ] `get_by_endpoint()` method present in `CostTracker`
- [ ] 4 `COST_*` config fields with 4-space indent
- [ ] `next_steps` mentions cost tracking configuration

---

## 8. Invariants

| ID | Invariant |
|---|---|
| INV-COST-001 | `CostMiddleware` MUST catch `except Exception` — cost tracking must NEVER block a request |
| INV-COST-002 | `as_header_value()` MUST return a `$`-prefixed string |
| INV-COST-003 | Each estimator MUST expose a `component` class attribute: `"db"`, `"s3"`, or `"api"` |
| INV-COST-004 | `get_summary()` MUST return a dict with exactly `"daily"`, `"weekly"`, `"monthly"` keys |
| INV-COST-005 | Idempotency fingerprint is `"CostTracker" in app/costs/tracker.py` |
| INV-COST-006 | All generated `.py` files pass `ast.parse()` before `ToolResult` is returned |

---

## 9. User Stories

| ID | Story |
|---|---|
| US-01 | As a cloud architect, I want per-request cost estimates so that I can identify expensive endpoints before the bill arrives. |
| US-02 | As a developer, I want `X-Request-Cost-Estimate` in the response header so that I can inspect costs during local development. |
| US-03 | As a finance team member, I want `GET /costs/summary` so that I can review monthly infrastructure cost trends. |
| US-04 | As an SRE, I want `GET /costs/by-endpoint` so that I can find the most expensive API paths. |
| US-05 | As a platform engineer, I want cost tracking to be non-blocking so that an estimator bug never causes 500 errors. |
| US-06 | As a developer, I want three pluggable estimators (`db`, `s3`, `api`) so that I can extend the system with custom components. |

---

## 10. Design Decisions

| Decision | Rationale |
|---|---|
| `component` class attribute on estimators | Enables dynamic aggregation without hardcoded keys |
| `$`-prefix in `as_header_value()` | Immediately recognisable as a monetary value in logs and clients |
| `except Exception` wrapping entire middleware logic | Cost tracking is observability; it must never degrade user experience |
| `get_summary()` daily/weekly/monthly periods | Aligns with standard SaaS cost reporting periods |
| Three concrete estimators as separate classes | Each is independently testable; new components are additive |
| Routes in `app/api/routes/costs.py` | Consistent with other management route modules |

---

## 11. Dependencies

| Package | Version | Purpose | Import style |
|---|---|---|---|
| `starlette` | (FastAPI dep) | `BaseHTTPMiddleware` | Top-level |
| `dataclasses` | stdlib | `@dataclass` for `CostEstimate`, `RequestContext` | Top-level |

---

## 12. Error Handling

| Scenario | Behavior |
|---|---|
| `tracker.py` already contains `CostTracker` | Return `status="no_op"` |
| `app/` directory missing | Return `status="error"` |
| Generated `.py` has `SyntaxError` | Return `status="error"`; file NOT committed |
| Estimator raises exception during request | Caught by `except Exception`; request continues unaffected |
| `get_summary()` called with no recorded data | Returns `{"daily": 0.0, "weekly": 0.0, "monthly": 0.0}` |

---

## 13. Security Considerations

- Cost data in `CostTracker` may reveal request patterns. Restrict `GET /costs/summary` and `GET /costs/by-endpoint` to admin roles.
- `COST_DB_QUERY_RATE`, `COST_S3_PER_GB`, `COST_API_CALL_RATE` are configurable pricing constants — set them in `.env`, not in source code.
- The non-blocking pattern (`except Exception: pass`) must not swallow security-relevant exceptions from upstream middleware — cost tracking should run AFTER auth middleware.

---

## 14. Testing Guide

```bash
# Run full test suite
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_cost_tracker.py -v

# Run standalone
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_cost_tracker.py

# Verify non-blocking pattern
python3 -c "
from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_cost_tracker import add_cost_tracker
from tests.common.fixture_factory import create_fixture_project
p = create_fixture_project(name='cost_manual')
add_cost_tracker(ToolInput(project_dir=str(p)))
content = (p / 'app' / 'middleware' / 'cost_tracker.py').read_text()
print('except Exception:', 'except Exception' in content)
print('X-Request-Cost-Estimate:', 'X-Request-Cost-Estimate' in content)
"
```

---

## 15. Files Reference

| File | Role |
|---|---|
| `adapt/extend/infrastructure/add_cost_tracker.py` | Tool entry point |
| `adapt/extend/infrastructure/test_add_cost_tracker.py` | 21-test structural test suite |
| `app/costs/tracker.py` | CostTracker, RequestContext, CostEstimate |
| `app/costs/estimators.py` | DBQueryCostEstimator, S3CostEstimator, APICostEstimator |
| `app/middleware/cost_tracker.py` | CostMiddleware |
| `app/api/routes/costs.py` | GET /costs/summary, GET /costs/by-endpoint |
| `app/core/config.py` | Patched with COST_TRACKING_ENABLED, COST_DB_QUERY_RATE, COST_S3_PER_GB, COST_API_CALL_RATE |
| `app/routes/__init__.py` | Patched with costs_router |

---

## 16. Changelog

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-04-15 | Initial spec — 21 CCs, three-component estimator, non-blocking middleware, daily/weekly/monthly summaries |
