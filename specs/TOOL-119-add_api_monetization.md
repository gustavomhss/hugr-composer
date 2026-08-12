---
spec_id: "TOOL-119"
tool_name: "add_api_monetization"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-MON-001"
  - "INV-MON-002"
  - "INV-MON-003"
  - "INV-MON-004"
  - "INV-MON-005"
  - "INV-MON-006"
  - "INV-MON-007"
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
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-13"
  - "QS-14"
  - "QS-15"
  - "QS-16"
  - "QS-17"
  - "QS-18"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
tags:
  - "performance"
  - "payments"
  - "data"
  - "resiliency"
  - "realtime"
---
# TOOL-119 — add_api_monetization

## 1. Overview

| Field | Value |
|---|---|
| **Tool ID** | TOOL-119 |
| **MCP name** | `fastapi_add_api_monetization` |
| **Entry point** | `adapt/extend/infrastructure/add_api_monetization.py::add_api_monetization` |
| **Tags** | `billing`, `metering`, `stripe`, `usage`, `quota`, `monetization` |
| **Input** | `ToolInput(project_dir, dry_run=False)` |
| **Output** | `ToolResult(status, files_created, files_modified, notes, next_steps, execution_time_ms)` |
| **Idempotency fingerprint** | `"MeteringMiddleware" in app/billing/metering.py` |
| **Prerequisite check** | `app/` directory exists |
| **Files created (min)** | 6 (`metering.py`, `rules.py`, `stripe_meter_sync.py`, `usage_record.py`, `billing.py` route, migration) |
| **Files modified (min)** | 2 (`app/core/config.py`, routes `__init__.py`) |
| **Test file** | `adapt/extend/infrastructure/test_add_api_monetization.py` |

---

## 2. Purpose

Turning an API into a revenue-generating product requires four things: event capture, quota enforcement, billing sync, and a self-service portal. `add_api_monetization` installs the full stack in six generated modules:

1. **`app/billing/metering.py`** — Core metering:
   - `MeteringMiddleware` — ASGI middleware that intercepts every request, evaluates applicable metering rules, and adds a usage event to `MeterEventBuffer`. Checks `TenantQuota` and returns `HTTP 429` when quota is exhausted.
   - `MeterEventBuffer` — in-memory batch buffer. Accumulates events until `METERING_BATCH_SIZE` is reached, then calls `flush_meter_events()`.
   - `TenantQuota` — lightweight quota tracker per `tenant_id`.
   - `_check_usage_alerts()` — emits log events at 80%, 90%, and 100% of quota thresholds.

2. **`app/billing/rules.py`** — Metering DSL:
   - `meter(endpoint, method, unit, cost)` — decorator-style DSL for defining metering rules.
   - `MeteringRule` — dataclass capturing endpoint, method, unit name, and cost per call.
   - `get_rules()` — returns all registered rules.

3. **`app/billing/stripe_meter_sync.py`** — Stripe integration:
   - `flush_meter_events(events)` — batches events and submits them to the Stripe Billing Meters v2 API.
   - `_submit_with_retry(event)` — exponential backoff retry (3 attempts).
   - `_DEAD_LETTER` — module-level list for events that exhausted all retries.
   - `stripe` is imported lazily inside `flush_meter_events` — never at module top level.

4. **`app/models/usage_record.py`** — SQLAlchemy model:
   - `UsageRecord` — columns: `id`, `tenant_id`, `endpoint`, `method`, `status_code`, `timestamp`, `cost_units`.

5. **`app/api/routes/billing.py`** — Self-service portal routes:
   - `GET /usage` — current period usage summary.
   - `GET /history` — paginated historical usage.
   - `GET /limits` — current quota limits.
   - `POST /upgrade` — initiates a tier upgrade.
   - `GET /plans` — available billing plans.

6. **Alembic migration** — `alembic/versions/<hash>_add_usage_record.py`.

Config fields (`METERING_ENABLED`, `STRIPE_METER_API_KEY`, `METERING_BATCH_SIZE`) are injected with 4-space indent. `UsageRecord` is registered in `app/models/__init__.py`. The billing router is registered in `app/routes/__init__.py`.

---

## 3. Performance SLOs

| Metric | Target |
|---|---|
| Tool execution time | < 3 s on a cold fixture project |
| `execution_time_ms` field | > 0 (always recorded) |
| Metering overhead per request | < 2 ms (in-memory buffer append) |
| Stripe batch flush latency | Non-blocking (async background task) |
| Files created | ≥ 6 |
| Files modified | ≥ 2 |
| Max function LOC in generated `app/` | ≤ 50 |

---

## 4. Before / After

### 4.1 Project state — before

```
app/
  core/
    config.py        # No METERING_* fields
  models/
    __init__.py
  routes/
    __init__.py
```

### 4.2 Project state — after

```
app/
  core/
    config.py                    # METERING_ENABLED, STRIPE_METER_API_KEY, METERING_BATCH_SIZE
  billing/
    metering.py                  # MeteringMiddleware, MeterEventBuffer, TenantQuota,
                                 # _check_usage_alerts
    rules.py                     # meter() DSL, MeteringRule, get_rules()
    stripe_meter_sync.py         # flush_meter_events, _submit_with_retry, _DEAD_LETTER
  models/
    usage_record.py              # UsageRecord SQLAlchemy model
    __init__.py                  # UsageRecord registered
  api/
    routes/
      billing.py                 # /usage, /history, /limits, /upgrade, /plans
  routes/
    __init__.py                  # billing_router registered
alembic/
  versions/
    <hash>_add_usage_record.py   # Migration
```

### 4.3 MeteringMiddleware with quota enforcement

```python
# app/billing/metering.py (generated excerpt)
class MeteringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        tenant_id = _extract_tenant(request)
        quota = TenantQuota.get(tenant_id)
        if quota and quota.is_exhausted():
            return Response(status_code=429, content=b'{"detail": "Quota exhausted"}')
        response = await call_next(request)
        rules = get_rules()
        for rule in rules:
            if rule.matches(request):
                _buffer.add(tenant_id, rule, response.status_code)
        _check_usage_alerts(tenant_id, quota)
        return response
```

### 4.4 meter() DSL

```python
# app/billing/rules.py (generated)
@dataclass
class MeteringRule:
    endpoint: str
    method: str
    unit: str
    cost: float = 1.0


_rules: list[MeteringRule] = []


def meter(endpoint: str, method: str = "GET", unit: str = "call", cost: float = 1.0) -> None:
    """Register a metering rule for the given endpoint and method."""
    _rules.append(MeteringRule(endpoint=endpoint, method=method, unit=unit, cost=cost))


def get_rules() -> list[MeteringRule]:
    """Return all registered metering rules."""
    return list(_rules)
```

### 4.5 stripe lazy import + dead-letter queue

```python
# app/billing/stripe_meter_sync.py (generated)
_DEAD_LETTER: list[dict] = []


def flush_meter_events(events: list[dict]) -> None:
    """Submit events to Stripe Billing Meters v2. stripe is lazily imported."""
    import stripe  # lazy — only when METERING_ENABLED and flush is called
    for event in events:
        _submit_with_retry(event)


def _submit_with_retry(event: dict, max_retries: int = 3) -> None:
    import stripe
    for attempt in range(max_retries):
        try:
            stripe.billing.MeterEvent.create(**event)
            return
        except stripe.StripeError:
            if attempt == max_retries - 1:
                _DEAD_LETTER.append(event)
```

### 4.6 Config patch

```python
    # --- API monetization — added by add_api_monetization tool ---
    METERING_ENABLED: bool = False
    STRIPE_METER_API_KEY: str = ""
    METERING_BATCH_SIZE: int = 100
```

---

## 5. Quality Standards

| ID | Standard |
|---|---|
| QS-1 | `status == "success"` on first run against a fresh fixture project |
| QS-2 | Second run returns `status == "no_op"` |
| QS-3 | `dry_run=True` returns success without writing any bytes |
| QS-4 | `files_created` contains ≥ 6 entries; all paths exist on disk |
| QS-5 | `files_modified` contains ≥ 2 entries; all paths exist on disk |
| QS-6 | Every generated `.py` file passes `ast.parse()` |
| QS-7 | No function in `app/` exceeds 50 LOC |
| QS-8 | `METERING_ENABLED`, `STRIPE_METER_API_KEY`, `METERING_BATCH_SIZE` in `config.py` with 4-space indent |
| QS-9 | `UsageRecord` registered in `app/models/__init__.py` |
| QS-10 | Billing router registered in `app/routes/__init__.py` |
| QS-11 | `MeteringMiddleware`, `MeterEventBuffer`, `TenantQuota` in `metering.py` |
| QS-12 | `meter()` DSL, `MeteringRule`, `get_rules()` in `rules.py` |
| QS-13 | `flush_meter_events`, `_submit_with_retry`, `_DEAD_LETTER` in `stripe_meter_sync.py` |
| QS-14 | `UsageRecord` model with `tenant_id`, `endpoint`, `method`, `status_code` in `usage_record.py` |
| QS-15 | All 5 billing endpoints in `billing.py`: `/usage`, `/history`, `/limits`, `/upgrade`, `/plans` |
| QS-16 | `stripe` NOT imported at module top level in `stripe_meter_sync.py` |
| QS-17 | `_check_usage_alerts` present in `metering.py`; references 80, 90, 100 thresholds |
| QS-18 | `429` status code present in `MeteringMiddleware` for quota exhaustion |

---

## 6. Completeness Criteria

| ID | Test function | What it verifies |
|---|---|---|
| CC-01 | `test_success_status` | Tool returns `status='success'` on a fresh project |
| CC-02 | `test_idempotent` | Second run returns `status='no_op'`; no files created or modified |
| CC-03 | `test_dry_run` | `dry_run=True` returns success without writing any bytes |
| CC-04 | `test_files_created_count` | At least 6 files created; all exist on disk |
| CC-05 | `test_files_modified_count` | At least 2 files modified; all exist on disk |
| CC-06 | `test_all_py_parse` | Every generated `.py` file AST-parses clean |
| CC-07 | `test_no_function_over_50_loc` | No function in `app/` exceeds 50 LOC |
| CC-08 | `test_config_fields_patched` | `METERING_ENABLED`, `STRIPE_METER_API_KEY`, `METERING_BATCH_SIZE` with 4-space indent |
| CC-09 | `test_models_init_patched` | `UsageRecord` registered in `app/models/__init__.py` |
| CC-10 | `test_routes_registered` | `billing_router` or `billing` in `app/routes/__init__.py` |
| CC-11 | `test_metering_middleware_created` | `MeteringMiddleware`, `MeterEventBuffer`, `TenantQuota` present |
| CC-12 | `test_metering_rules_dsl_created` | `def meter(`, `MeteringRule`, `get_rules` in `rules.py` |
| CC-13 | `test_stripe_meter_sync_created` | `flush_meter_events`, `_submit_with_retry`, `_DEAD_LETTER` present |
| CC-14 | `test_usage_record_model_created` | `UsageRecord` class with all required fields |
| CC-15 | `test_billing_routes_endpoints` | All 5 endpoints: `/usage`, `/history`, `/limits`, `/upgrade`, `/plans` |
| CC-16 | `test_stripe_lazy_import_in_sync` | `stripe` NOT at module top level (AST walk) |
| CC-17 | `test_usage_alerts_in_middleware` | `_check_usage_alerts` and 80/90/100 thresholds present |
| CC-18 | `test_tier_enforcement_429` | `429` and `quota` present in `metering.py` |
| CC-19 | `test_execution_time_recorded` | `execution_time_ms > 0` |
| CC-20 | `test_next_steps_present` | `next_steps` non-empty; mentions `alembic` |
| CC-21 | `test_idempotent_project_still_parses` | All `.py` files parse after two consecutive runs |

---

## 7. Definition of Done

- [ ] All 21 tests in `test_add_api_monetization.py` pass
- [ ] `MeteringMiddleware` returns 429 on quota exhaustion; calls `_check_usage_alerts`
- [ ] `meter()` DSL, `MeteringRule`, `get_rules()` generated in `rules.py`
- [ ] `flush_meter_events`, `_submit_with_retry`, `_DEAD_LETTER` in `stripe_meter_sync.py`
- [ ] `stripe` imported lazily inside `flush_meter_events` — never at module top level
- [ ] `UsageRecord` SQLAlchemy model with required columns
- [ ] All 5 billing route endpoints present in `billing.py`
- [ ] Alembic migration created for `usage_record` table
- [ ] `next_steps` mentions `alembic`

---

## 8. Invariants

| ID | Invariant |
|---|---|
| INV-MON-001 | `stripe` is NEVER imported at module top level in `stripe_meter_sync.py` |
| INV-MON-002 | `_DEAD_LETTER` MUST capture events that exhaust all retry attempts |
| INV-MON-003 | Middleware MUST return 429 when `TenantQuota.is_exhausted()` returns True |
| INV-MON-004 | `_check_usage_alerts` MUST reference 80%, 90%, and 100% thresholds |
| INV-MON-005 | Idempotency fingerprint is `"MeteringMiddleware" in app/billing/metering.py` |
| INV-MON-006 | `UsageRecord` model MUST include `tenant_id`, `endpoint`, `method`, `status_code` |
| INV-MON-007 | All generated `.py` files pass `ast.parse()` before `ToolResult` is returned |

---

## 9. User Stories

| ID | Story |
|---|---|
| US-01 | As a product manager, I want `GET /usage` so that customers can track their API consumption in real time. |
| US-02 | As a platform engineer, I want `_DEAD_LETTER` so that failed Stripe events are not silently lost. |
| US-03 | As a billing engineer, I want the `meter()` DSL so that I can define pricing rules declaratively. |
| US-04 | As an operator, I want quota enforcement returning 429 so that over-limit tenants are blocked automatically. |
| US-05 | As a developer, I want `stripe` lazily imported so that the app boots without it when `METERING_ENABLED=false`. |
| US-06 | As a customer, I want usage alerts at 80/90/100% so that I am notified before hitting my quota. |

---

## 10. Design Decisions

| Decision | Rationale |
|---|---|
| In-memory `MeterEventBuffer` with batch flush | Low-latency event capture; Stripe API called in batches |
| `_DEAD_LETTER` module-level list | Simplest durable fallback; production would use Redis/DB |
| Lazy `stripe` import | App boots without Stripe SDK when billing is disabled |
| `meter()` DSL as a registry pattern | Declarative pricing rules; no per-route middleware boilerplate |
| 80/90/100% alert thresholds | Industry standard for SaaS quota warning tiers |
| Alembic migration included | `usage_record` table must be migrated before metering starts |
| All 5 self-service routes in one file | Customers interact with billing as a cohesive feature |

---

## 11. Dependencies

| Package | Version | Purpose | Import style |
|---|---|---|---|
| `stripe` | `>=9.0.0` | Stripe Billing Meters v2 API | Lazy (inside `flush_meter_events`) |
| `sqlalchemy` | `>=2.0` | `UsageRecord` ORM model | Top-level |
| `alembic` | `>=1.13` | Database migration | CLI |
| `starlette` | (FastAPI dep) | `BaseHTTPMiddleware` | Top-level |

---

## 12. Error Handling

| Scenario | Behavior |
|---|---|
| `metering.py` already contains `MeteringMiddleware` | Return `status="no_op"` |
| `app/` directory missing | Return `status="error"` |
| Generated `.py` has `SyntaxError` | Return `status="error"`; file NOT committed |
| Stripe SDK not installed at runtime | `ImportError` from lazy import inside `flush_meter_events` |
| Stripe API returns error | `_submit_with_retry` retries 3 times; failed events go to `_DEAD_LETTER` |
| `TenantQuota` check raises exception | Middleware catches exception; request passes through (fail-open) |

---

## 13. Security Considerations

- `STRIPE_METER_API_KEY` must NEVER be committed to source control — use `.env`.
- `MeterEventBuffer` is in-memory: server restart loses buffered events. Use `_DEAD_LETTER` pattern to detect and recover lost events.
- The `POST /upgrade` endpoint must authenticate the requesting tenant before initiating a tier change.
- Usage data in `UsageRecord` may be PII-adjacent (endpoint + tenant_id combinations can reveal business behaviour) — apply appropriate retention policies.

---

## 14. Testing Guide

```bash
# Run full test suite
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_api_monetization.py -v

# Run standalone
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_api_monetization.py

# Verify stripe is not at module top level
python3 -c "
import ast
from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_api_monetization import add_api_monetization
from tests.common.fixture_factory import create_fixture_project
p = create_fixture_project(name='mon_manual')
add_api_monetization(ToolInput(project_dir=str(p)))
tree = ast.parse((p / 'app' / 'billing' / 'stripe_meter_sync.py').read_text())
top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
print('Top-level imports:', [getattr(n,'module',None) or [a.name for a in n.names] for n in top])
"
```

---

## 15. Files Reference

| File | Role |
|---|---|
| `adapt/extend/infrastructure/add_api_monetization.py` | Tool entry point |
| `adapt/extend/infrastructure/test_add_api_monetization.py` | 21-test structural test suite |
| `app/billing/metering.py` | MeteringMiddleware, MeterEventBuffer, TenantQuota, _check_usage_alerts |
| `app/billing/rules.py` | meter() DSL, MeteringRule, get_rules() |
| `app/billing/stripe_meter_sync.py` | flush_meter_events, _submit_with_retry, _DEAD_LETTER |
| `app/models/usage_record.py` | UsageRecord SQLAlchemy model |
| `app/api/routes/billing.py` | /usage, /history, /limits, /upgrade, /plans |
| `app/core/config.py` | Patched with METERING_ENABLED, STRIPE_METER_API_KEY, METERING_BATCH_SIZE |
| `app/models/__init__.py` | Patched with UsageRecord registration |
| `app/routes/__init__.py` | Patched with billing_router |

---

## 16. Changelog

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-04-15 | Initial spec — 21 CCs, Stripe Meters v2, dead-letter queue, self-service billing portal |
