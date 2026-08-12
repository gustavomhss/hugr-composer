---
spec_id: "TOOL-022"
tool_name: "add_circuit_breaker"
primitive: "resiliency/CircuitBreaker"
primitive_path: "core.venous.resiliency.CircuitBreaker"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-CB-01"
  - "INV-CB-02"
  - "INV-CB-03"
  - "INV-CB-04"
  - "INV-CB-05"
  - "INV-CB-06"
  - "INV-CB-07"
  - "INV-CB-08"
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
  - "CC-26"
  - "CC-27"
  - "CC-28"
  - "CC-29"
  - "CC-30"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
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
  - "T-21"
  - "T-22"
  - "T-23"
  - "T-24"
  - "T-25"
  - "T-26"
  - "T-27"
  - "T-28"
  - "T-29"
  - "T-30"
tags:
  - "performance"
  - "payments"
  - "data"
  - "resiliency"
  - "realtime"
---
# TOOL-022: add_circuit_breaker

> **Status**: SPEC v2 (rigorous)  
> **Last updated**: 2026-04-08  

---

## 1. Overview  

| **Field**       | **Value**                                                                 |
|------------------|---------------------------------------------------------------------------|
| Tool name        | `fastapi_add_circuit_breaker`                                             |
| Category         | EXTEND > Infrastructure                                                   |
| Complexity       | Medium                                                                    |
| Dependencies     | existing FastAPI project, Redis (shared state across workers), httpx      |
| Signature        | `add_circuit_breaker(project_dir: str, failure_threshold: int = 5, recovery_timeout_seconds: int = 30, half_open_max_calls: int = 3, failure_window_seconds: int = 60) -> dict` |
| Parameters       | `project_dir`: project root path<br>`failure_threshold`: consecutive failures to open circuit (default 5)<br>`recovery_timeout_seconds`: wait before half-open attempt (default 30s)<br>`half_open_max_calls`: max probe calls in half-open state (default 3)<br>`failure_window_seconds`: sliding window for counting failures (default 60s) |

## 2. Purpose  

The `fastapi_add_circuit_breaker` tool implements a production-grade circuit breaker pattern for every outbound dependency call a FastAPI app makes — downstream HTTP services, payment gateways, search APIs, or any third-party integration. It generates a `@circuit_breaker("service_name")` decorator that wraps service functions with a distributed state machine (`CLOSED → OPEN → HALF_OPEN`), admin endpoints (`GET/POST /admin/circuits/{name}`) for manual overrides, Prometheus metrics for each transition, and per-service configuration via environment variables. Without a circuit breaker, a single flaky downstream causes the entire FastAPI worker pool to block on timeouts — 2000 requests stuck waiting 30 s each exhausts connection pools, drains the event loop, and cascades into a full outage within minutes.

The state is stored in Redis so every uvicorn worker and every pod sees the same circuit state in sub-millisecond SCAN time, with atomic transitions guaranteed by a Lua script that runs inside Redis (never client-side race conditions across workers). Key design decisions: a sliding-window failure counter (not a naive count so a burst 5 minutes ago does not pre-trip today), a strict fast-fail response within 1 ms when the circuit is OPEN (raises `CircuitOpenError` before any network attempt so the caller can return a graceful degradation immediately), and a HALF_OPEN probe window where a bounded number of trial calls decides whether the downstream has recovered. Operators retain full control through the admin endpoints — force-open during a known incident, force-close after a deploy, inspect the per-service failure counters, and pull live metrics into Grafana via the `fastapi_circuit_state` gauge.

## 3. Performance SLOs  

| **Metric**                     | **Target**                          | **Why**                                                                 |
|--------------------------------|-------------------------------------|-------------------------------------------------------------------------|
| Tool execution time            | < 3s                               | Minimize impact on development workflow                                |
| Files modified                 | ≤ 4                                | Limit changes to existing project files                                |
| Files created                  | ≥ 7                                | Ensure all necessary components are generated                          |
| State lookup (Redis GET)       | < 1 ms                             | Maintain low overhead for state checks                                 |
| Decorator overhead when closed | < 0.5 ms                           | Minimize latency impact on successful calls                           |
| Open state fast-fail response  | < 0.5 ms                           | Ensure rapid failure when circuit is open                              |
| Failure count update (Redis INCR) | < 1 ms                           | Keep failure counting efficient                                         |
| State propagation across workers | < 100 ms                         | Ensure all workers see state changes promptly                          |
| Migration runtime              | 0s — no DB changes                 | Avoid database schema modifications                                    |

---

## 4. Code Examples (Before / After)

### 4.1 HTTP Client: BEFORE
```python
# app/core/http_client.py
import httpx
from contextlib import asynccontextmanager
from typing import AsyncIterator

class HTTPClient:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    @asynccontextmanager
    async def request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> AsyncIterator[httpx.Response]:
        async with self.client as client:
            try:
                response = await client.request(method, url, **kwargs)
                yield response
            except httpx.HTTPError as e:
                raise ServiceUnavailableError(f"HTTP call failed: {str(e)}") from e

http_client = HTTPClient()
```

### 4.2 HTTP Client: AFTER
```python
# app/core/http_client.py
import httpx
from contextlib import asynccontextmanager
from typing import AsyncIterator
from app.core.circuit_breaker import circuit_breaker

class CircuitBreakerHTTPClient:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    @asynccontextmanager
    @circuit_breaker("external_http")
    async def request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> AsyncIterator[httpx.Response]:
        async with self.client as client:
            try:
                response = await client.request(method, url, **kwargs)
                if 500 <= response.status_code < 600:
                    raise ServiceUnavailableError(f"HTTP {response.status_code}")
                yield response
            except httpx.HTTPError as e:
                raise ServiceUnavailableError(f"HTTP call failed: {str(e)}") from e

http_client = CircuitBreakerHTTPClient()
```

### 4.3 Circuit Breaker Core (NEW)
```python
# app/core/circuit_breaker.py
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional, TypeVar
import asyncio
import redis.asyncio as redis
import logging

logger = logging.getLogger(__name__)

class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class CircuitBreakerOpenError(Exception):
    """Raised when circuit is open and call is rejected"""

T = TypeVar("T")

def circuit_breaker(
    service_name: str,
    failure_threshold: int = 5,
    recovery_timeout: int = 30,
    half_open_max_calls: int = 3,
    failure_window: int = 60,
    fallback: Optional[Callable[..., T]] = None,
) -> Callable[..., Callable[..., T]]:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            redis_client = get_redis_client()
            state_key = f"circuit:{service_name}"

            # Check current state
            state_data = await redis_client.hgetall(state_key)
            current_state = state_data.get("state", CircuitState.CLOSED)

            if current_state == CircuitState.OPEN:
                if fallback:
                    return await fallback(*args, **kwargs)
                raise CircuitBreakerOpenError(f"Circuit open for {service_name}")

            # Execute call and handle state transitions
            try:
                result = await func(*args, **kwargs)
                if current_state == CircuitState.HALF_OPEN:
                    await _handle_half_open_success(redis_client, state_key)
                return result
            except Exception as e:
                await _handle_failure(
                    redis_client,
                    state_key,
                    current_state,
                    failure_threshold,
                    recovery_timeout,
                    failure_window,
                )
                raise

        return wrapper
    return decorator

async def _handle_failure(
    redis_client: redis.Redis,
    state_key: str,
    current_state: str,
    failure_threshold: int,
    recovery_timeout: int,
    failure_window: int,
) -> None:
    now = datetime.utcnow().timestamp()
    failure_key = f"{state_key}:failures"

    # Record failure in sorted set with timestamp
    await redis_client.zadd(failure_key, {str(now): now})
    await redis_client.zremrangebyscore(failure_key, "-inf", now - failure_window)

    # Count failures in window
    failures = await redis_client.zcard(failure_key)

    if current_state == CircuitState.CLOSED and failures >= failure_threshold:
        await redis_client.hset(
            state_key,
            mapping={
                "state": CircuitState.OPEN,
                "opened_at": now,
                "failure_count": failures,
            }
        )
        logger.warning(f"Circuit opened for {state_key}")
```

### 4.4 Admin Routes (NEW)
```python
# app/api/endpoints/circuit.py
from fastapi import APIRouter, HTTPException
from fastapi.params import Depends
from app.core.circuit_breaker import CircuitState
from app.core.redis import get_redis_client
from app.core.security import require_admin

router = APIRouter()

@router.get("/circuit/{service_name}", dependencies=[Depends(require_admin)])
async def get_circuit_state(service_name: str):
    redis_client = get_redis_client()
    state = await redis_client.hgetall(f"circuit:{service_name}")
    return {
        "service": service_name,
        "state": state.get("state", CircuitState.CLOSED),
        "failure_count": int(state.get("failure_count", 0)),
        "opened_at": state.get("opened_at"),
    }

@router.post("/circuit/{service_name}/open", dependencies=[Depends(require_admin)])
async def force_open_circuit(service_name: str):
    redis_client = get_redis_client()
    await redis_client.hset(
        f"circuit:{service_name}",
        mapping={
            "state": CircuitState.OPEN,
            "opened_at": datetime.utcnow().timestamp(),
            "forced": "true",
        }
    )
    return {"status": "opened"}

@router.post("/circuit/{service_name}/close", dependencies=[Depends(require_admin)])
async def force_close_circuit(service_name: str):
    redis_client = get_redis_client()
    await redis_client.hset(
        f"circuit:{service_name}",
        mapping={
            "state": CircuitState.CLOSED,
            "failure_count": 0,
            "forced": "true",
        }
    )
    return {"status": "closed"}
```

### 4.5 Redis Configuration (NEW)
```python
# app/core/redis.py
import redis.asyncio as redis
from app.core.config import settings

_redis_client: redis.Redis | None = None

async def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client

async def close_redis_client() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
```

### 4.6 State Transition Lua Script (NEW)
```python
# app/core/circuit_scripts.py
TRANSITION_SCRIPT = """
local key = KEYS[1]
local new_state = ARGV[1]
local current_state = redis.call('HGET', key, 'state')
local forced = redis.call('HGET', key, 'forced')

-- Only allow transition if not manually forced
if forced == 'true' and new_state ~= current_state then
    return {err = 'Cannot transition: circuit is manually forced'}
end

-- State transition logic
if new_state == 'half_open' and current_state == 'open' then
    redis.call('HSET', key, 'state', 'half_open', 'probe_count', 0)
    return {ok = 'transitioned'}
elseif new_state == 'closed' and current_state == 'half_open' then
    redis.call('HSET', key, 'state', 'closed', 'failure_count', 0)
    return {ok = 'transitioned'}
elseif new_state == 'open' and current_state == 'half_open' then
    redis.call('HSET', key, 'state', 'open', 'opened_at', ARGV[2])
    return {ok = 'transitioned'}
end

return {err = 'Invalid transition'}
"""
```

### 4.7 Middleware (NEW)
```python
# app/api/middleware/circuit.py
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE
from app.core.circuit_breaker import CircuitBreakerOpenError

class CircuitBreakerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except CircuitBreakerOpenError as e:
            return Response(
                content={"detail": str(e)},
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
                media_type="application/json",
            )
```

### 4.8 Migration (NEW)
```python
# alembic/versions/0009_add_circuit_breaker.py
"""Add circuit breaker support

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'

def upgrade() -> None:
    # No schema changes, just ensure Redis is configured
    op.execute("""
    INSERT INTO settings (key, value, description)
    VALUES ('REDIS_URL', 'redis://localhost:6379/0', 'Circuit breaker state storage')
    ON CONFLICT (key) DO NOTHING
    """)

def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'REDIS_URL'")
```

### 4.9 Circuit Breaker Settings (NEW)
```python
# app/core/config.py
from pydantic import BaseSettings, RedisDsn

class Settings(BaseSettings):
    REDIS_URL: RedisDsn = "redis://localhost:6379/0"
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT: int = 30
    CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS: int = 3
    CIRCUIT_BREAKER_FAILURE_WINDOW: int = 60

    class Config:
        env_file = ".env"

settings = Settings()

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | State transitions are atomic and race-free | Redis Lua script in `app/core/circuit_scripts.py` ensures atomic check-and-update |
| QS-2 | Circuit state is shared across workers | Redis hash `circuit:{service_name}` stores state with pubsub notifications |
| QS-3 | Failure counting respects sliding window | Redis sorted set `circuit:{service_name}:failures` tracks timestamps and expires old entries |
| QS-4 | Open circuit fast-fails within 1 ms | Decorator in `app/core/circuit_breaker.py` checks state before attempting call |
| QS-5 | Half-open state allows limited probes | Redis counter `half_open_probe_count` enforces `half_open_max_calls` limit |
| QS-6 | Admin overrides persist until cleared | Redis hash field `forced="true"` prevents automatic state transitions |
| QS-7 | Decorator preserves original exceptions | `circuit_breaker` decorator only wraps calls, does not catch or modify exceptions |
| QS-8 | Metrics track state transitions | `logging.getLogger(__name__)` emits transition events with timestamps |
| QS-9 | Redis failures degrade gracefully | `CircuitBreakerHTTPClient` falls back to closed state when Redis is unavailable |
| QS-10 | Decorator only works on async functions | `ast.parse` validates decorated functions contain `async def` |
| QS-11 | Admin endpoints require authentication | `require_admin` dependency in `app/api/endpoints/circuit.py` enforces access control |
| QS-12 | State changes propagate within 100 ms | Redis pubsub channel `circuit_state` broadcasts transitions to all workers |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `circuit_breaker` decorator exists at `app/core/circuit_breaker.py` | File exists, parses |
| CC-02 | Redis Lua script exists at `app/core/circuit_scripts.py` | File exists, contains TRANSITION_SCRIPT |
| CC-03 | Admin endpoints exist at `app/api/endpoints/circuit.py` | Routes file inspected |
| CC-04 | Middleware exists at `app/api/middleware/circuit.py` | File exists, contains `CircuitBreakerMiddleware` |
| CC-05 | Redis client exists at `app/core/redis.py` | File exists, exports `get_redis_client` |
| CC-06 | Migration exists at `alembic/versions/0009_add_circuit_breaker.py` | File exists, contains Redis URL config |
| CC-07 | Circuit states `CLOSED`, `OPEN`, `HALF_OPEN` defined as Enum | Inspect `CircuitState` enum |
| CC-08 | Decorator accepts `fallback` function parameter | grep `fallback: Optional[Callable[..., T]]` |
| CC-09 | Redis hash contains `state`, `failure_count`, `opened_at` fields | Inspect `redis_client.hset` calls |
| CC-10 | Failure counting uses Redis sorted set with timestamps | grep `redis_client.zadd` |
| CC-11 | Admin endpoints require `require_admin` dependency | grep `dependencies=[Depends(require_admin)]` |
| CC-12 | Middleware catches `CircuitBreakerOpenError` | grep `except CircuitBreakerOpenError` |
| CC-13 | Lua script enforces state transition rules | Inspect TRANSITION_SCRIPT logic |
| CC-14 | Decorator overhead < 0.5 ms when closed | Benchmark T-25 |
| CC-15 | Open state fast-fail < 0.5 ms | Benchmark T-26 |
| CC-16 | State propagation < 100 ms across workers | Benchmark T-27 |
| CC-17 | Redis GET latency < 1 ms | Benchmark T-28 |
| CC-18 | Redis INCR latency < 1 ms | Benchmark T-29 |
| CC-19 | Tool execution time < 3s | Time measurement |
| CC-20 | Files modified ≤ 4 | Count modified files |
| CC-21 | Files created ≥ 7 | Count new files |
| CC-22 | Decorator raises on sync functions | ast.parse validates async def |
| CC-23 | Admin endpoints return correct state | Inspect `GET /circuit/{service}` response |
| CC-24 | Force open persists until cleared | Test T-13 |
| CC-25 | Half-open allows max probes | Test T-07 |
| CC-26 | Failure window expires old entries | Test T-08 |
| CC-27 | Redis down falls back to closed | Test T-25 |
| CC-28 | Metrics emit state transitions | grep `logger.warning` |
| CC-29 | Tool idempotent on re-run | Test T-30 |
| CC-30 | Decorator preserves exceptions | Test T-24 |

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] Tests T-01 through T-30 pass
- [ ] Performance benchmarks meet SLOs
- [ ] Redis Lua script validates state transitions
- [ ] Admin endpoints enforce authentication
- [ ] Decorator preserves original exceptions
- [ ] Failure counting respects sliding window
- [ ] Half-open state allows limited probes
- [ ] Admin overrides persist until cleared
- [ ] State changes propagate within 100 ms
- [ ] Redis failures degrade gracefully
- [ ] Metrics track state transitions
- [ ] Documentation covers all user stories

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-CB-01 | State transitions are atomic | Redis Lua script in `app/core/circuit_scripts.py` ensures atomic check-and-update | T-01, T-02 |
| INV-CB-02 | Open circuit fast-fails within 1 ms | Decorator in `app/core/circuit_breaker.py` checks state before attempting call | T-03, T-04 |
| INV-CB-03 | Half-open state allows limited probes | Redis counter `half_open_probe_count` enforces `half_open_max_calls` limit | T-05, T-06 |
| INV-CB-04 | Failure count respects sliding window | Redis sorted set `circuit:{service_name}:failures` tracks timestamps and expires old entries | T-07, T-08 |
| INV-CB-05 | Admin overrides persist until cleared | Redis hash field `forced="true"` prevents automatic state transitions | T-13, T-14 |
| INV-CB-06 | State changes propagate within 100 ms | Redis pubsub channel `circuit_state` broadcasts transitions to all workers | T-27, T-28 |
| INV-CB-07 | Decorator preserves original exceptions | `circuit_breaker` decorator only wraps calls, does not catch or modify exceptions | T-24, T-29 |
| INV-CB-08 | Redis failures degrade gracefully | `CircuitBreakerHTTPClient` falls back to closed state when Redis is unavailable | T-25, T-30 |

---

## 9. User Stories

### 9.1 Core functionality (US-01 .. US-05)

**US-01: Protect external HTTP calls with circuit breaker**
- **As a** dev integrating with Stripe API
- **I want** to wrap my payment client with `@circuit_breaker("stripe")`
- **So that** repeated Stripe failures don't cascade to my app
- **Given:** `POST /payments` endpoint calling Stripe
- **When:** Stripe fails 5 times in 60s (HTTP 500)
- **Then:**
  - Circuit opens and subsequent calls fail fast with 503 (INV-CB-02)
  - Admin endpoint `GET /circuit/stripe` shows `state: "open"` (CC-23)
  - Redis hash `circuit:stripe` records failure count and timestamp (CC-09)

**US-02: Automatic recovery after service heals**
- **As a** SRE monitoring payment service
- **I want** the circuit to automatically retry after timeout
- **So that** I don't need manual intervention for transient issues
- **Given:** Circuit open for Stripe for 30s (recovery_timeout)
- **When:** First probe call succeeds (HTTP 200)
- **Then:**
  - Circuit transitions to half_open then closed (INV-CB-01)
  - Redis updates `state: "closed"` and clears failure_count (T-01)
  - Subsequent calls proceed normally (CC-14)

**US-03: Half-open state limits probe traffic**
- **As a** platform engineer
- **I want** only 3 concurrent calls during half-open state
- **So that** a recovering service isn't overwhelmed
- **Given:** Circuit in half_open state for "email_service"
- **When:** 4th concurrent call arrives during probes
- **Then:**
  - Extra call fast-fails with 503 (INV-CB-03)
  - Redis counter `half_open_probe_count` enforces limit (CC-25)
  - Logs show "Rejected call in half_open state" (CC-28)

**US-04: Failed probes re-open circuit**
- **As a** backend developer
- **I want** the circuit to re-open if probes fail
- **So that** we don't flood a still-failing service
- **Given:** Circuit in half_open state for "sms_gateway"
- **When:** Any probe call fails (HTTP 503)
- **Then:**
  - Circuit immediately re-opens (T-06)
  - Redis sets `state: "open"` and new `opened_at` (CC-09)
  - Recovery timeout restarts (30s default) (CC-03)

**US-05: Sliding window failure counting**
- **As a** data engineer
- **I want** only recent failures to count toward threshold
- **So that** old failures don't incorrectly keep circuit open
- **Given:** 4 failures in last 30s, 2 failures 70s ago
- **When:** New failure occurs
- **Then:**
  - Only 5 recent failures counted (INV-CB-04)
  - Redis sorted set expires old entries (T-08)
  - Circuit opens when threshold reached (CC-10)

### 9.2 Admin controls (US-06 .. US-10)

**US-06: Force-open circuit for maintenance**
- **As a** operations lead
- **I want** to manually open a circuit
- **So that** I can block traffic during planned downtime
- **Given:** Admin access to `POST /circuit/shipping/open`
- **When:** I force-open shipping service circuit
- **Then:**
  - Circuit opens immediately (INV-CB-05)
  - Redis sets `forced: "true"` flag (T-13)
  - Auto-recovery disabled until manual close (CC-24)

**US-07: Force-close circuit for critical path**
- **As a** incident responder
- **I want** to override an open circuit
- **So that** critical transactions proceed during partial outages
- **Given:** Circuit open for "auth_service" with 10 failures
- **When:** Admin calls `POST /circuit/auth_service/close`
- **Then:**
  - Circuit closes immediately (T-14)
  - Subsequent calls attempt real requests (CC-14)
  - Forced state persists until next threshold breach (INV-CB-05)

**US-08: View circuit state via API**
- **As a** monitoring system
- **I want** to query circuit status
- **So that** I can alert on open circuits
- **Given:** Circuit "search_service" with 3 failures
- **When:** Calling `GET /circuit/search_service`
- **Then:**
  - Response includes state, failure_count, opened_at (CC-23)
  - Redis hash fields exposed verbatim (CC-09)
  - 200 OK with JSON body (T-17)

**US-09: Bypass circuit for health checks**
- **As a** load balancer
- **I want** to check service health without tripping breaker
- **So that** monitoring isn't affected by failure thresholds
- **Given:** `/healthz` endpoint with no circuit breaker
- **When:** Health check fails 10 times
- **Then:**
  - No circuit state changes occur (CC-07)
  - Regular endpoints still protected (US-01)
  - Health metrics unaffected (CC-28)

**US-10: Customize thresholds per service**
- **As a** payment service owner
- **I want** stricter thresholds for PCI services
- **So that** we fail fast on payment issues
- **Given:** `@circuit_breaker("pci", failure_threshold=3)`
- **When:** PCI service fails 3 times in 60s
- **Then:**
  - Circuit opens faster than default (CC-01)
  - Threshold respected exactly (T-07)
  - Other services use default 5 failures (CC-03)

### 9.3 Edge cases (US-11 .. US-15)

**US-11: Redis unavailable falls back to closed**
- **As a** reliability engineer
- **I want** graceful degradation when Redis is down
- **So that** outages don't break all external calls
- **Given:** Redis connection timeout
- **When:** Making HTTP call with `@circuit_breaker`
- **Then:**
  - Circuit treated as closed (INV-CB-08)
  - Call proceeds normally (T-25)
  - Error logged but not raised (CC-28)

**US-12: Decorator rejects sync functions**
- **As a** tool developer
- **I want** clear errors for misconfigured breakers
- **So that** devs don't accidentally bypass protection
- **Given:** `@circuit_breaker` on sync function `def process()`
- **When:** Tool applies decorator
- **Then:**
  - Raises TypeError "Async functions only" (CC-22)
  - No files modified (CC-20)
  - Error message suggests async alternative (CC-10)

**US-13: Concurrent state transitions race-free**
- **As a** distributed systems engineer
- **I want** atomic state changes across workers
- **So that** two workers can't conflict on transitions
- **Given:** 10 workers detecting failure simultaneously
- **When:** Threshold reached at same moment
- **Then:**
  - Only one transition occurs (INV-CB-01)
  - Lua script ensures atomicity (CC-13)
  - Redis pubsub broadcasts final state (CC-12)

**US-14: Fallback function on open circuit**
- **As a** frontend developer
- **I want** cached responses when circuit is open
- **So that** users see stale data instead of errors
- **Given:** `@circuit_breaker(fallback=get_cached_data)`
- **When:** Circuit opens for "product_service"
- **Then:**
  - Fallback called instead of raising (CC-08)
  - Original exception still logged (INV-CB-07)
  - User gets 200 with cached data (T-19)

**US-15: Websockets ignore circuit breaker**
- **As a** real-time service developer
- **I want** websocket endpoints exempt
- **So that** long-lived connections aren't affected
- **Given:** `/ws/notifications` endpoint
- **When:** Adding `@circuit_breaker` to handler
- **Then:**
  - Tool skips websocket routes (CC-22)
  - Documentation warns about incompatibility (CC-30)
  - Regular HTTP endpoints still protected (US-01)

### 9.4 Integration (US-16 .. US-20)

**US-16: Pre-configured HTTP client wrapper**
- **As a** API client developer
- **I want** a ready-to-use HTTP client
- **So that** I don't manually wrap every call
- **Given:** new `CircuitBreakerHTTPClient()`
- **When:** Making GET request to flaky service
- **Then:**
  - Auto-applies circuit breaker (CC-04)
  - Same thresholds as decorator (CC-03)
  - Preserves all httpx.AsyncClient features (CC-30)

**US-17: Combine with retry logic**
- **As a** resilience engineer
- **I want** retries before tripping circuit
- **So that** transient blips don't open breaker
- **Given:** `@retry(times=3) @circuit_breaker("inventory")`
- **When:** Temporary 500 error occurs
- **Then:**
  - Retries exhausted before failure counted (T-24)
  - Only permanent failures trip circuit (CC-07)
  - Decorator order preserved (CC-01)

**US-18: Multiple services share HTTP client**
- **As a** microservice developer
- **I want** independent breakers per service
- **So that** one outage doesn't affect all
- **Given:** client calling "billing" and "shipping"
- **When:** Billing fails 5 times
- **Then:**
  - Only billing circuit opens (INV-CB-04)
  - Shipping calls continue normally (CC-03)
  - Separate Redis keys track state (CC-09)

**US-19: Async context manager support**
- **As a** resource management conscious dev
- **I want** breakers to work with `async with`
- **So that** connections are properly cleaned up
- **Given:** `async with client.request() as response`
- **When:** Circuit opens mid-request
- **Then:**
  - Fast-fail before connection attempt (INV-CB-02)
  - Context manager still enters/exits cleanly (CC-30)
  - No resource leaks (CC-07)

**US-20: Tool idempotent on re-run**
- **As a** CI/CD pipeline
- **I want** safe multiple executions
- **So that** deployments are repeatable
- **Given:** Existing circuit breaker setup
- **When:** Running `add_circuit_breaker` again
- **Then:**
  - No duplicate files created (CC-21)
  - Existing config preserved (CC-29)
  - Returns "already configured" status (T-30)

### 9.5 Observability (US-21 .. US-25)

**US-21: Log state transitions**
- **As a** log analyst
- **I want** clear circuit state changes
- **So that** I can track outage timelines
- **Given:** Circuit for "email_service"
- **When:** State changes from closed → open
- **Then:**
  - Structured log emitted (CC-28)
  - Includes timestamp and failure count (CC-09)
  - Log level WARNING for opens (INV-CB-07)

**US-22: Metrics for circuit state**
- **As a** dashboard engineer
- **I want** Prometheus metrics
- **So that** I can graph breaker activity
- **Given:** Open circuit for "search_service"
- **When:** Scraping metrics endpoint
- **Then:**
  - `circuit_state{service="search"} 1` (1=open) (CC-28)
  - `circuit_failures_total` counter (CC-10)
  - Metrics updated in <100ms (CC-16)

**US-23: Monitor half-open probes**
- **As a** SRE debugging recovery
- **I want** visibility into probe attempts
- **So that** I can verify service health
- **Given:** Circuit in half_open state
- **When:** Probe calls execute
- **Then:**
  - Logs show probe success/failure (CC-28)
  - Metrics track probe count (INV-CB-03)
  - Admin endpoint shows attempts (CC-23)

**US-24: Performance overhead minimal**
- **As a** latency-sensitive application
- **I want** low breaker overhead
- **So that** fast paths stay fast
- **Given:** Circuit closed, healthy service
- **When:** Making 1000 calls with decorator
- **Then:**
  - <0.5ms added latency (CC-14)
  - No Redis bottlenecks (CC-17)
  - 99th percentile <1ms (CC-15)

**US-25: OpenAPI documents admin endpoints**
- **As a** API consumer
- **I want** breaker docs in OpenAPI
- **So that** I can discover controls
- **Given:** `/openapi.json` endpoint
- **When:** Checking circuit operations
- **Then:**
  - `GET /circuit/{service}` documented (CC-23)
  - `POST /circuit/{service}/open` included (CC-11)
  - Auth requirements shown (INV-CB-08)

---

## 10. Test Plan

### 10.1 State Machine Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Closed → Open transition | 4 failures in last 59s | Make 5th failing call | Circuit opens, state=OPEN |
| T-02 | Open → Half-open transition | Circuit open for 30s | Make probe call | State=HALF_OPEN |
| T-03 | Half-open → Closed transition | Circuit half_open, 3 successful probes | Make 4th call | State=CLOSED |
| T-04 | Half-open → Open transition | Circuit half_open, 1 failed probe | Make 2nd call | State=OPEN |
| T-05 | Concurrent transitions race-free | 10 workers detect failure simultaneously | Make concurrent calls | Only one transition occurs |
| T-06 | State persists across workers | Worker A opens circuit | Worker B makes call | Fast-fail with state=OPEN |

### 10.2 Failure Counting Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Failure threshold respected | failure_threshold=3 | Make 3 failing calls | Circuit opens |
| T-08 | Sliding window expiration | 5 failures, oldest 61s ago | Make new call | Only 4 failures counted |
| T-09 | Concurrent failures counted | 10 workers make failing calls simultaneously | Inspect Redis | Exactly 10 failures recorded |
| T-10 | 4xx responses don't count | HTTP 400 response | Make call | Failure count unchanged |
| T-11 | Failure window = 0 | failure_window_seconds=0 | Make 1 failing call | Circuit opens |
| T-12 | Recovery timeout = 0 | recovery_timeout_seconds=0 | Make failing call | Immediate half_open |

### 10.3 Admin Control Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Force open circuit | Circuit closed | POST /circuit/service/open | State=OPEN, forced=true |
| T-14 | Force close circuit | Circuit open | POST /circuit/service/close | State=CLOSED, forced=true |
| T-15 | View circuit state | Circuit half_open | GET /circuit/service | Returns state=HALF_OPEN |
| T-16 | Force override persists | Circuit force-opened | Make successful probe | State remains OPEN |
| T-17 | Admin endpoint auth | No admin token | GET /circuit/service | 403 Forbidden |
| T-18 | Multiple services independent | Circuit A open, B closed | Make call to B | Call succeeds |

### 10.4 Integration Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Fallback function | Circuit open, fallback=lambda: "cached" | Make call | Returns "cached" |
| T-20 | Decorator preserves exceptions | Circuit closed, service raises ValueError | Make call | ValueError raised |
| T-21 | Decorator rejects sync functions | @circuit_breaker on sync def | Apply decorator | TypeError raised |
| T-22 | HTTP client wrapper | CircuitBreakerHTTPClient | Make GET request | Applies breaker |
| T-23 | Combine with retries | @retry(times=3) @circuit_breaker | Make failing call | Retries before counting failure |
| T-24 | Websockets ignored | @circuit_breaker on websocket handler | Apply decorator | Warning emitted |

### 10.5 Edge Case & Performance Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Redis down falls back | Redis unavailable | Make call | Circuit treated as CLOSED |
| T-26 | Decorator overhead | Circuit closed | Benchmark 1000 calls | < 0.5ms overhead |
| T-27 | Open state fast-fail | Circuit open | Benchmark response time | < 0.5ms response |
| T-28 | State propagation | Worker A opens circuit | Worker B makes call | Sees OPEN state in <100ms |
| T-29 | Tool idempotency | Circuit breaker already configured | Run tool again | No changes, "skipped" status |
| T-30 | Redis GET latency | Circuit closed | Benchmark state lookup | < 1ms latency |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Circuit breaker wraps external calls while soft delete handles internal DB operations - no overlap |
| add_cursor_pagination | No | ✅ Compatible | Pagination operates on query results while breaker protects HTTP calls - independent concerns |
| add_search | No | ✅ Compatible | Search indexing calls can be wrapped with circuit breaker for external search services |
| add_audit_log | Yes | ⚠️ Caveat | Audit logging middleware must run AFTER circuit breaker to log fast-fail events |
| add_data_export | No | ✅ Compatible | Export operations that call external services should use circuit breaker decorator |
| add_bulk_operations | No | ✅ Compatible | Bulk API calls to external systems benefit from circuit breaker protection |
| add_multi_tenancy | No | ✅ Compatible | Tenant context propagates through circuit breaker calls automatically |
| add_feature_flags | No | ✅ Compatible | Feature flags can control circuit breaker thresholds dynamically |
| add_api_key_auth | Yes | ⚠️ Caveat | API key auth middleware must run BEFORE circuit breaker to validate credentials |
| add_oauth2_provider | Yes | ⚠️ Caveat | OAuth token validation must complete before circuit breaker checks |
| add_rbac | Yes | ⚠️ Caveat | RBAC checks must run BEFORE circuit breaker admin endpoints |
| add_mfa | No | ✅ Compatible | MFA flows that call external services (SMS/email) should use circuit breaker |
| add_cache_layer | No | ✅ Compatible | Cache misses can fall through to circuit-protected external calls |
| add_outbox_pattern | No | ✅ Compatible | Outbox processors calling external systems benefit from circuit protection |
| add_sse | Yes | ⚠️ Caveat | Server-Sent Events should NOT use circuit breaker as they're long-lived connections |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout -- app/core/http_client.py
rm -f app/core/circuit_breaker.py
rm -f app/core/circuit_scripts.py
rm -f app/api/endpoints/circuit.py
rm -f app/api/middleware/circuit.py
rm -f app/core/redis.py
rm -f alembic/versions/0009_add_circuit_breaker.py
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
If the generator crashed halfway and left an inconsistent tree (decorator applied to some services, not others), restore cleanly before re-running:
```bash
# 1. Inspect what changed relative to HEAD
git status --short

# 2. Revert any tool-written files + delete any new files
git checkout HEAD -- app/ alembic/
git clean -fd app/core/circuit_breaker.py app/api/endpoints/circuit.py

# 3. Verify the tree matches HEAD exactly before re-running
git diff HEAD --exit-code && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: circuit breaker deployed but stuck OPEN
If a production circuit is stuck OPEN after the downstream has recovered (stale state, bad threshold, or a Redis key that was manually tampered with), force-close it without a redeploy:
```bash
# 1. Inspect live state of every circuit
curl -H "Authorization: Bearer $ADMIN_TOKEN" https://api.example.com/admin/circuits

# 2. Force-close the specific circuit
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
    https://api.example.com/admin/circuits/payments/close

# 3. Watch the failure rate and confirm traffic flows again
watch 'curl -s https://api.example.com/admin/circuits/payments | jq .state'
```
If the admin endpoint itself is broken, delete the Redis key directly: `redis-cli DEL circuit:payments:state` — the next request re-initializes it as CLOSED.

### Emergency: Redis unavailable
If Redis becomes unreachable the circuit breaker defaults to **closed** (fail-open) to preserve request throughput, but emits `circuit_redis_errors_total` and logs each failure. To keep the app functional during a Redis outage:
1. Verify Redis health: `redis-cli -h $REDIS_HOST ping` — expected `PONG`
2. Check the Prometheus counter: `rate(circuit_redis_errors_total[5m])` — any non-zero rate means the fallback is active
3. If Redis is expected to be down for > 10 min, set `CIRCUIT_BREAKER_ENABLED=false` and roll the pods — this bypasses Redis entirely and disables breaking, accepting the risk of cascading failures but preventing the Redis-errors log spam
4. Once Redis recovers, set `CIRCUIT_BREAKER_ENABLED=true` and roll again; state starts fresh (all circuits CLOSED)

### Emergency: circuit breaker consuming too much Redis memory
Each service tracked adds a small sliding-window list plus a state key. If someone wraps every internal function (anti-pattern) or the window is set too large, Redis memory can balloon. Containment:
1. Count breaker keys: `redis-cli --scan --pattern 'circuit:*' | wc -l` — should be < 100 typical
2. Inspect the biggest offender: `redis-cli --scan --pattern 'circuit:*:window' | xargs -L 1 redis-cli LLEN | sort -n | tail`
3. Shrink `CIRCUIT_WINDOW_SIZE` from the default 100 to 50 via env + roll
4. If still ballooning, audit which services are wrapped — the decorator should only appear on *external* calls, not internal ones

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Redis connection fails during state check | Circuit treated as CLOSED and call proceeds with warning logged |
| EC-2 | Two workers simultaneously detect threshold breach | Redis Lua script ensures only one transition to OPEN occurs |
| EC-3 | Admin force-opens circuit while auto-recovery tries to close | Manual override persists with `forced=true` in Redis state |
| EC-4 | Decorator applied to synchronous function | Tool raises TypeError: "@circuit_breaker only supports async functions" |
| EC-5 | Failure window set to 0 seconds | Treats every failure as immediate threshold breach |
| EC-6 | Recovery timeout set to 0 seconds | Immediately transitions to HALF_OPEN state after OPEN |
| EC-7 | Half-open probe succeeds but another fails mid-flight | Circuit re-opens and cancels pending probes |
| EC-8 | Circuit name contains special characters | Tool sanitizes to alphanumeric+underscore (e.g. "stripe-payments" → "stripe_payments") |
| EC-9 | Fallback function raises exception | Original exception propagates to caller, not CircuitBreakerOpenError |
| EC-10 | Multiple services share same HTTP client | Each service name gets independent circuit state in Redis |
| EC-11 | Admin endpoint called without credentials | Returns 403 Forbidden as require_admin dependency enforces auth |
| EC-12 | Tool run on project without Redis config | Errors with "Redis URL not configured in settings.REDIS_URL" |
| EC-13 | Concurrent calls exceed half_open_max_calls | Excess calls fast-fail with CircuitBreakerOpenError |
| EC-14 | Old failures remain in Redis sorted set | Automatic expiry via ZREMRANGEBYSCORE keeps window accurate |
| EC-15 | Pubsub message lost during state change | TTL on Redis state record acts as safety net for stale state |

## 14. Acceptance Criteria (Final Sign-off)

✅ All 30 Completeness Criteria verified via checklist  
✅ Tests T-01 through T-30 pass with 100% coverage  
✅ Performance benchmarks meet all SLOs in section 3  
✅ Redis Lua script validates state transitions atomically  
✅ Admin endpoints enforce authentication via require_admin  
✅ Decorator preserves original exception types and traces  
✅ Failure counting respects sliding window configuration  
✅ Half-open state correctly limits probe call volume  
✅ State changes propagate to all workers within 100ms  
✅ Developer successfully wraps Stripe API client and observes circuit opening after 5 test failures  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists and contains FastAPI project
- [ ] Verify `app/core/http_client.py` exists with HTTP client
- [ ] Check Redis connection with `redis-cli ping`
- [ ] Validate `settings.REDIS_URL` is configured
- [ ] Confirm `httpx` is in project dependencies
- [ ] Check for existing circuit breaker files to ensure idempotency
- [ ] Verify Python version >= 3.8 for async/await support

### 15.2 Core circuit breaker module
- [ ] Create `app/core/circuit_breaker.py` with CircuitState enum
- [ ] Implement `circuit_breaker` decorator function
- [ ] Add `CircuitBreakerOpenError` exception class
- [ ] Include failure counting with sliding window logic
- [ ] Implement state transition handling
- [ ] Add fallback function support
- [ ] Include logging for state transitions

### 15.3 Redis integration
- [ ] Create `app/core/redis.py` with connection pool
- [ ] Implement `get_redis_client` async context manager
- [ ] Add connection health check
- [ ] Configure encoding/decoding settings
- [ ] Implement close_redis_client cleanup
- [ ] Add pubsub support for state propagation
- [ ] Set appropriate timeouts for circuit operations

### 15.4 State machine scripts
- [ ] Create `app/core/circuit_scripts.py`
- [ ] Implement TRANSITION_SCRIPT Lua for atomic state changes
- [ ] Add FAILURE_COUNT_SCRIPT for windowed counting
- [ ] Include HALF_OPEN_PROBE_SCRIPT for concurrency control
- [ ] Add script loading on startup
- [ ] Implement script error handling
- [ ] Test scripts in Redis CLI before deployment
- [ ] Document script invariants

### 15.5 Admin endpoints
- [ ] Create `app/api/endpoints/circuit.py`
- [ ] Implement GET /circuit/{service} endpoint
- [ ] Add POST /circuit/{service}/open endpoint
- [ ] Add POST /circuit/{service}/close endpoint
- [ ] Include require_admin dependency
- [ ] Document endpoints in OpenAPI schema
- [ ] Add rate limiting to admin endpoints
- [ ] Include request/response models

### 15.6 Middleware
- [ ] Create `app/api/middleware/circuit.py`
- [ ] Implement CircuitBreakerMiddleware class
- [ ] Catch CircuitBreakerOpenError and return 503
- [ ] Preserve original error details in response
- [ ] Add middleware to app startup sequence
- [ ] Configure middleware ordering
- [ ] Include metrics for fast-fail responses
- [ ] Document middleware behavior

### 15.7 HTTP client wrapper
- [ ] Modify `app/core/http_client.py`
- [ ] Rename HTTPClient to CircuitBreakerHTTPClient
- [ ] Add @circuit_breaker decorator to request method
- [ ] Preserve existing client functionality
- [ ] Update imports to use new client
- [ ] Handle 5xx responses as failures
- [ ] Document client usage examples
- [ ] Add timeout configuration

### 15.8 Migration
- [ ] Generate `alembic/versions/0009_add_circuit_breaker.py`
- [ ] Add Redis URL to settings table
- [ ] Include documentation in migration
- [ ] Set appropriate downgrade steps
- [ ] Verify migration runs successfully
- [ ] Test migration rollback
- [ ] Include Redis connection check in migration
- [ ] Document Redis requirements

### 15.9 Test generation
- [ ] Create `tests/test_circuit_breaker.py`
- [ ] Implement all 30 test cases from section 10
- [ ] Add Redis mock for unit tests
- [ ] Include integration test with real Redis
- [ ] Test concurrent state transitions
- [ ] Verify failure window behavior
- [ ] Benchmark performance metrics
- [ ] Document test coverage

### 15.10 Documentation
- [ ] Append circuit breaker section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Update `SKILL.md` tools table
- [ ] Document decorator usage examples
- [ ] Explain admin endpoint security
- [ ] Provide troubleshooting guide
- [ ] Include Redis sizing recommendations
- [ ] Document monitoring best practices

### 15.11 Atomicity
- [ ] Use temp-file + rename pattern for all writes
- [ ] Track all modified files for rollback
- [ ] Verify Redis operations succeed before committing changes
- [ ] Implement cleanup on failure
- [ ] Check file permissions before writing
- [ ] Validate file contents after write
- [ ] Document rollback procedure
- [ ] Test partial failure scenarios

### 15.12 Verification
- [ ] Run `ast.parse` on all modified files
- [ ] Verify imports resolve correctly
- [ ] Run pytest with 100% coverage
- [ ] Benchmark against performance SLOs
- [ ] Test idempotent re-runs
- [ ] Validate Redis state persistence
- [ ] Check admin endpoint security
- [ ] Document verification steps

### 15.13 Metrics
- [ ] Add state transition counters
- [ ] Track failure rates per service
- [ ] Measure time in each state
- [ ] Record fast-fail response times
- [ ] Monitor Redis operation latency
- [ ] Track fallback function usage
- [ ] Document key metrics
- [ ] Integrate with Prometheus

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/circuit_breaker.py",
    "app/core/circuit_scripts.py",
    "app/api/endpoints/circuit.py",
    "app/api/middleware/circuit.py",
    "app/core/redis.py",
    "alembic/versions/0009_add_circuit_breaker.py",
    "tests/test_circuit_breaker.py",
    "docs/circuit_breaker.md"
  ],
  "files_modified": [
    "app/core/http_client.py",
    "app/main.py",
    "app/core/config.py"
  ],
  "metrics": {
    "execution_time_ms": 2874,
    "files_changed": 11,
    "lines_added": 842,
    "lines_removed": 32,
    "services_protected": 1,
    "redis_latency_ms": 0.8
  },
  "next_steps": [
    "Run: alembic upgrade head",
    "Run: pytest tests/test_circuit_breaker.py -v",
    "Test circuit opening: make 5 failing calls to a wrapped service",
    "Verify admin endpoints: GET /circuit/{service}",
    "Monitor metrics: circuit_state gauge and circuit_failures counter"
  ],
  "warnings": [
    "Existing HTTP client was renamed to CircuitBreakerHTTPClient - update imports",
    "Redis connection pooling may require tuning for high traffic systems"
  ],
  "notes": [
    "Circuit breaker installed with default threshold=5 failures in 60s window",
    "Admin endpoints require authentication via require_admin dependency",
    "Redis used for shared state with pubsub propagation <100ms",
    "Middleware added to handle CircuitBreakerOpenError with 503 responses",
    "Existing HTTP calls now protected by circuit breaker automatically"
  ]
}
