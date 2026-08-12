---
spec_id: "TOOL-116"
tool_name: "add_adaptive_throttle"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-AT-001"
  - "INV-AT-002"
  - "INV-AT-003"
  - "INV-AT-004"
  - "INV-AT-005"
  - "INV-AT-006"
  - "INV-AT-007"
  - "INV-AT-008"
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
  - "CC-23"
  - "CC-24"
  - "CC-25"
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
  - "QS-19"
  - "QS-2"
  - "QS-20"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
tags:
  - "performance"
  - "data"
  - "resiliency"
  - "realtime"
  - "api"
---
# TOOL-116 — add_adaptive_throttle

## 1. Overview

| Field | Value |
|---|---|
| **Tool ID** | TOOL-116 |
| **MCP name** | `fastapi_add_adaptive_throttle` |
| **Entry point** | `adapt/extend/infrastructure/add_adaptive_throttle.py::add_adaptive_throttle` |
| **Tags** | `security`, `rate-limiting`, `throttle`, `redis`, `behavioral`, `fingerprinting` |
| **Input** | `ToolInput(project_dir, dry_run=False)` |
| **Output** | `ToolResult(status, files_created, files_modified, notes, next_steps, execution_time_ms)` |
| **Idempotency fingerprint** | `"AdaptiveThrottleConfig" in app/core/adaptive_throttle.py` |
| **Prerequisite check** | `app/` directory exists |
| **Files created (min)** | 3 (`adaptive_throttle.py` core, middleware, `throttle_status.py` route) |
| **Files modified (min)** | 2 (`app/core/config.py`, `app/main.py`) |
| **Test file** | `adapt/extend/infrastructure/test_add_adaptive_throttle.py` |

---

## 2. Purpose

Standard rate limiting counts requests per IP per time window. Adaptive throttling goes further by profiling each client's baseline behaviour during a learning period, then tightening quotas for clients whose cost-weighted request rate exceeds a configurable sensitivity threshold. `add_adaptive_throttle` installs three components:

1. **`app/core/adaptive_throttle.py`** — Engine + configuration.
   - `AdaptiveThrottleConfig` — frozen dataclass populated from `Settings` fields.
   - `build_config()` — factory that reads settings and returns an `AdaptiveThrottleConfig`.
   - `fingerprint_request(request)` — hashes the client IP and ordered header names using SHA-256, producing a 16-character hex fingerprint. This detects IP rotation by the same client (same header order from different IPs returns the same fingerprint).
   - `cost_weight(endpoint, weights)` — returns the cost multiplier for an endpoint (default 1; expensive endpoints like `/export` can be configured to consume more quota per call).
   - `penalty_seconds_for_tier(tier)` — maps a tier index to cooldown duration.
   - `PENALTY_SECONDS: list[int] = [0, 60, 300, 1800, 86400]` — exactly 5 tiers: tier 0 = no penalty, tier 4 = 24-hour ban.

2. **`app/middleware/adaptive_throttle.py`** — ASGI middleware.
   - `AdaptiveThrottleMiddleware` — computes client fingerprint, checks penalty state, escalates tier on quota breach.
   - `register_adaptive_throttle(app)` — factory function patched into `app/main.py`.
   - When a client is in a penalty tier: returns `HTTP 429` with a `Retry-After` header.
   - Tier escalation is capped at tier 4: `min(current + 1, 4)`.

3. **`app/api/routes/throttle_status.py`** — Status endpoint.
   - `GET /throttle/status` returns a `ThrottleStatus` schema with `penalty_tier`, `fingerprint`, and quota metadata for the requesting client.

Config injection: five `ADAPTIVE_THROTTLE_*` fields are added to `app/core/config.py` inside the `Settings` class body. `register_adaptive_throttle(app)` is appended to `app/main.py` AFTER the `app = FastAPI(...)` line.

---

## 3. Performance SLOs

| Metric | Target |
|---|---|
| Tool execution time | < 2 s on a cold fixture project |
| `execution_time_ms` field | > 0 (always recorded) |
| Fingerprint computation | < 0.5 ms per request |
| Penalty state lookup (Redis) | < 2 ms (single GET) |
| Files created | ≥ 3 |
| Files modified | ≥ 2 |
| Max function LOC in generated `app/` | ≤ 50 |

---

## 4. Before / After

### 4.1 Project state — before

```
app/
  core/
    config.py    # Settings class; no ADAPTIVE_THROTTLE_* fields
  main.py        # app = FastAPI(...); no throttle middleware
```

### 4.2 Project state — after

```
app/
  core/
    config.py                       # 5 new fields injected
    adaptive_throttle.py            # AdaptiveThrottleConfig, build_config,
                                    # fingerprint_request, cost_weight,
                                    # penalty_seconds_for_tier, PENALTY_SECONDS
  middleware/
    adaptive_throttle.py            # AdaptiveThrottleMiddleware,
                                    # register_adaptive_throttle
  api/
    routes/
      throttle_status.py            # GET /throttle/status
  main.py                           # register_adaptive_throttle(app) appended
```

### 4.3 PENALTY_SECONDS — five tiers

```python
# app/core/adaptive_throttle.py (generated)
PENALTY_SECONDS: list[int] = [0, 60, 300, 1800, 86400]
# tier 0 = no penalty (normal)
# tier 1 = 1-minute cooldown
# tier 2 = 5-minute cooldown
# tier 3 = 30-minute cooldown
# tier 4 = 24-hour ban
```

### 4.4 fingerprint_request — IP + header order

```python
def fingerprint_request(request: Request) -> str:
    """Build a behavioral fingerprint from header order and IP.

    Combines ordered header names (not values) with remote IP using SHA-256.
    Detects IP rotation: same header order from a new IP = same fingerprint.

    Args:
        request: Incoming Starlette request.

    Returns:
        16-character hex fingerprint string.
    """
    header_order = ",".join(k.lower() for k in request.headers.keys())
    raw = f"{request.client.host if request.client else 'unknown'}|{header_order}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

### 4.5 Middleware — 429 with Retry-After

```python
class AdaptiveThrottleMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not config.enabled:
            return await call_next(request)
        fp = fingerprint_request(request)
        tier = _get_penalty_tier(fp)  # reads from Redis
        if tier > 0:
            retry_after = penalty_seconds_for_tier(tier)
            return Response(
                status_code=429,
                headers={"Retry-After": str(retry_after),
                         "X-Penalty-Tier": str(tier)},
                content=b'{"detail": "Too many requests"}',
            )
        ...
```

### 4.6 Config patch (5 fields)

```python
    # --- Adaptive throttle — added by add_adaptive_throttle tool ---
    ADAPTIVE_THROTTLE_ENABLED: bool = False
    ADAPTIVE_THROTTLE_SENSITIVITY: float = 1.5
    ADAPTIVE_THROTTLE_LEARNING_PERIOD_H: int = 24
    ADAPTIVE_THROTTLE_BASE_QUOTA: int = 1000
    ADAPTIVE_THROTTLE_PENALTY_ESCALATION: bool = True
```

---

## 5. Quality Standards

| ID | Standard |
|---|---|
| QS-1 | `status == "success"` on first run against a fresh fixture project |
| QS-2 | Second run returns `status == "no_op"` with empty `files_created` and `files_modified` |
| QS-3 | `dry_run=True` returns success without writing any bytes to disk |
| QS-4 | `files_created` contains ≥ 3 entries; all paths exist on disk |
| QS-5 | `files_modified` contains ≥ 2 entries; all paths exist on disk |
| QS-6 | Every generated `.py` file passes `ast.parse()` without `SyntaxError` |
| QS-7 | No function in generated `app/` exceeds 50 LOC |
| QS-8 | All 5 `ADAPTIVE_THROTTLE_*` fields present in `config.py` with 4-space indent |
| QS-9 | `app/core/adaptive_throttle.py` contains `AdaptiveThrottleConfig`, `build_config`, `fingerprint_request` |
| QS-10 | `PENALTY_SECONDS` list has exactly 5 entries; tier 0 = 0, tier 4 = 86400 |
| QS-11 | `app/middleware/adaptive_throttle.py` contains `AdaptiveThrottleMiddleware` and `register_adaptive_throttle` |
| QS-12 | Middleware returns `status_code=429` with `Retry-After` header when `penalty_tier > 0` |
| QS-13 | `app/api/routes/throttle_status.py` exists with `/throttle` prefix and `ThrottleStatus` and `penalty_tier` |
| QS-14 | `fingerprint_request` uses `request.headers.keys()`, `hashlib`, and `sha256` |
| QS-15 | `app/main.py` contains `register_adaptive_throttle` import and call |
| QS-16 | `def cost_weight` exists in `app/core/adaptive_throttle.py` |
| QS-17 | `def penalty_seconds_for_tier` exists in `app/core/adaptive_throttle.py` |
| QS-18 | `register_adaptive_throttle(app)` call appears AFTER `app = FastAPI(...)` in `main.py` |
| QS-19 | Tier escalation capped at 4: `min(current + 1, 4)` present in middleware |
| QS-20 | `ADAPTIVE_THROTTLE_*` fields count is exactly 5 (deduplicated check) |

---

## 6. Completeness Criteria

| ID | Test function | What it verifies |
|---|---|---|
| CC-01 | `test_success_status` | Tool returns `status='success'` on a fresh project |
| CC-02 | `test_idempotent` | Second run returns `status='no_op'`; no files created or modified |
| CC-03 | `test_dry_run` | `dry_run=True` returns success without writing any bytes to disk |
| CC-04 | `test_files_created_count` | At least 3 files created; all exist on disk |
| CC-05 | `test_files_modified_count` | At least 2 files modified; all exist on disk |
| CC-06 | `test_all_py_parse` | Every generated `.py` file AST-parses clean |
| CC-07 | `test_no_function_over_50_loc` | No function in `app/` exceeds 50 LOC |
| CC-08 | `test_config_fields_patched` | All 5 `ADAPTIVE_THROTTLE_*` fields present with 4-space indent |
| CC-09 | `test_core_module_created` | `AdaptiveThrottleConfig`, `build_config`, `fingerprint_request` present |
| CC-10 | `test_penalty_ladder_defined` | `PENALTY_SECONDS` contains exactly 5 tiers; tier 4 = 86400 |
| CC-11 | `test_middleware_module_created` | `AdaptiveThrottleMiddleware` and `register_adaptive_throttle` present |
| CC-12 | `test_middleware_returns_429_on_penalty` | Middleware has `status_code=429`, `Retry-After`, `penalty_tier` |
| CC-13 | `test_status_route_created` | `throttle_status.py` exists with `/throttle`, `ThrottleStatus`, `penalty_tier` |
| CC-14 | `test_fingerprint_uses_header_order` | `request.headers.keys()`, `hashlib`, `sha256` all present |
| CC-15 | `test_main_registers_throttle` | `main.py` imports and calls `register_adaptive_throttle` |
| CC-16 | `test_cost_weight_function_present` | `def cost_weight` exists in core module |
| CC-17 | `test_penalty_seconds_for_tier_function_present` | `def penalty_seconds_for_tier` exists |
| CC-18 | `test_execution_time_recorded` | `execution_time_ms > 0` |
| CC-19 | `test_next_steps_present` | `next_steps` mentions `REDIS_URL` and `adaptive_throttle` |
| CC-20 | `test_idempotent_project_still_parses` | All `.py` files parse after two consecutive runs |
| CC-21 | `test_five_penalty_tiers_distinct` | AST walk confirms `PENALTY_SECONDS` is a 5-element list with tier 0=0, tier 4=86400 |
| CC-22 | `test_escalation_caps_at_tier_4` | `min(current + 1, 4)` present in middleware |
| CC-23 | `test_register_throttle_positioned_after_fastapi` | `register_adaptive_throttle(app)` index > `app = FastAPI(` index in `main.py` |
| CC-24 | `test_config_has_five_fields` | Exactly 5 `ADAPTIVE_THROTTLE_*` field definition lines in `config.py` |
| CC-25 | `test_no_files_mutated_outside_scope` | No file outside `files_created`/`files_modified` was changed |

---

## 7. Definition of Done

- [ ] All 25 tests in `test_add_adaptive_throttle.py` pass
- [ ] `PENALTY_SECONDS` list has exactly 5 tiers: `[0, 60, 300, 1800, 86400]`
- [ ] `fingerprint_request()` uses `hashlib.sha256` over `IP|header_order`
- [ ] `AdaptiveThrottleMiddleware` returns `429` + `Retry-After` for penalised clients
- [ ] Tier escalation capped at 4: `min(current + 1, 4)`
- [ ] `register_adaptive_throttle(app)` injected into `main.py` AFTER `app = FastAPI(...)`
- [ ] `GET /throttle/status` endpoint exposes `ThrottleStatus` schema with `penalty_tier`
- [ ] `cost_weight()` and `penalty_seconds_for_tier()` utility functions present
- [ ] All 5 `ADAPTIVE_THROTTLE_*` config fields present with 4-space indent

---

## 8. Invariants

| ID | Invariant |
|---|---|
| INV-AT-001 | `PENALTY_SECONDS` MUST have exactly 5 elements: `[0, 60, 300, 1800, 86400]` |
| INV-AT-002 | Tier escalation MUST be capped at 4: `min(current + 1, 4)` |
| INV-AT-003 | `register_adaptive_throttle(app)` MUST appear after `app = FastAPI(...)` in `main.py` |
| INV-AT-004 | Idempotency fingerprint is `"AdaptiveThrottleConfig" in app/core/adaptive_throttle.py` |
| INV-AT-005 | Config block must contain exactly 5 `ADAPTIVE_THROTTLE_*` field definition lines |
| INV-AT-006 | `fingerprint_request()` must hash IP AND header order together |
| INV-AT-007 | All generated `.py` files pass `ast.parse()` before `ToolResult` is returned |
| INV-AT-008 | Tool MUST NOT modify files outside `files_created` / `files_modified` |

---

## 9. User Stories

| ID | Story |
|---|---|
| US-01 | As a platform engineer, I want behavioral fingerprinting so that IP-rotating attackers are throttled even when they change IPs. |
| US-02 | As an operator, I want a 24-hour ban tier so that repeat offenders are automatically blocked without manual intervention. |
| US-03 | As a developer, I want `cost_weight()` so that expensive endpoints consume more quota per request than cheap health checks. |
| US-04 | As a client developer, I want `Retry-After` in the 429 response so that I can implement proper backoff without polling. |
| US-05 | As an ops engineer, I want `GET /throttle/status` so that I can inspect a client's penalty state without checking Redis directly. |
| US-06 | As a security engineer, I want a learning period before tightening thresholds, so that legitimate bursty clients are not penalised during deployment. |

---

## 10. Design Decisions

| Decision | Rationale |
|---|---|
| 5-tier penalty ladder | Gradual escalation avoids over-penalising first-time burst |
| Header-order fingerprint + IP | IP alone is insufficient; header order persists across IP rotation |
| SHA-256 truncated to 16 hex chars | Compact Redis key; collision probability negligible at this scale |
| `min(current + 1, 4)` cap | Prevents unbounded tier accumulation |
| `register_adaptive_throttle(app)` factory | Allows middleware registration without patching import paths |
| Redis for penalty state | Multi-worker deployments share penalty state |
| Learning period before tightening | Prevents false positives during normal burst windows |

---

## 11. Dependencies

| Package | Version | Purpose | Import style |
|---|---|---|---|
| `starlette` | (FastAPI dep) | `BaseHTTPMiddleware`, `Request` | Top-level |
| `redis` | optional | Multi-worker penalty state storage | Optional (app gracefully degrades) |
| `hashlib` | stdlib | SHA-256 fingerprinting | Top-level |

---

## 12. Error Handling

| Scenario | Behavior |
|---|---|
| `adaptive_throttle.py` already contains `AdaptiveThrottleConfig` | Return `status="no_op"` |
| `app/` directory missing | Return `status="error"` with descriptive message |
| Generated `.py` has `SyntaxError` | Return `status="error"`; file NOT committed |
| Redis unavailable | Middleware degrades gracefully; all requests pass through |
| `penalty_seconds_for_tier()` called with tier > 4 | Returns `PENALTY_SECONDS[4]` (24h cap) |

---

## 13. Security Considerations

- Fingerprint collisions (two different clients mapping to the same fingerprint) would cause incorrect penalisation. SHA-256 with 16 hex chars gives 2^64 unique values — collision probability is negligible in practice.
- Penalty state stored in Redis must use authenticated connections (`REDIS_URL` with password).
- `Retry-After` values must not be so large that they constitute a DoS against legitimate clients.
- The status endpoint (`GET /throttle/status`) should be rate-limited itself to prevent enumeration.

---

## 14. Testing Guide

```bash
# Run full test suite
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_adaptive_throttle.py -v

# Run standalone
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_adaptive_throttle.py

# Verify PENALTY_SECONDS via AST
python3 -c "
import ast
from pathlib import Path
from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_adaptive_throttle import add_adaptive_throttle
from tests.common.fixture_factory import create_fixture_project
p = create_fixture_project(name='at_manual')
add_adaptive_throttle(ToolInput(project_dir=str(p)))
content = (p / 'app' / 'core' / 'adaptive_throttle.py').read_text()
print('PENALTY_SECONDS' in content, '86400' in content)
"
```

---

## 15. Files Reference

| File | Role |
|---|---|
| `adapt/extend/infrastructure/add_adaptive_throttle.py` | Tool entry point |
| `adapt/extend/infrastructure/test_add_adaptive_throttle.py` | 25-test structural test suite |
| `app/core/adaptive_throttle.py` | AdaptiveThrottleConfig, PENALTY_SECONDS, fingerprint_request, cost_weight, penalty_seconds_for_tier |
| `app/middleware/adaptive_throttle.py` | AdaptiveThrottleMiddleware, register_adaptive_throttle |
| `app/api/routes/throttle_status.py` | GET /throttle/status |
| `app/core/config.py` | Patched with 5 ADAPTIVE_THROTTLE_* fields |
| `app/main.py` | Patched with register_adaptive_throttle(app) call |

---

## 16. Changelog

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-04-15 | Initial spec — 25 CCs, 5-tier penalty ladder, behavioral fingerprinting, Redis penalty state |
