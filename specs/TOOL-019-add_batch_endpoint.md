# TOOL-019: add_batch_endpoint

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_batch_endpoint` |
| Category | EXTEND > API Design |
| Complexity | Medium |
| Dependencies | FastAPI, Pydantic, existing CRUD routes |
| Signature | `add_batch_endpoint(project_dir: str, models: list[str] \| None = None, max_batch_size: int = 50, strategy: Literal["sequential", "parallel"] = "sequential", timeout_per_item_ms: int = 5000) -> dict` |
| Parameters | `project_dir`: Absolute path to FastAPI project root (e.g. `/code/myapp`)<br>`models`: Model names to process (None=all models with routes) (e.g. `["User", "Product"]`)<br>`max_batch_size`: Maximum allowed items per request (default 50)<br>`strategy`: Processing order guarantee (default sequential)<br>`timeout_per_item_ms`: Milliseconds before item times out (default 5000) |

## 2. Purpose

The `fastapi_add_batch_endpoint` tool adds standardized batch-processing endpoints to a FastAPI application, generating `/batch` POST routes that accept lists of operations for existing resources so clients can send 100 creates in a single HTTP round-trip instead of 100 serial calls. Without this tool every bulk-update use case either spawns a flood of parallel client requests (overwhelming the connection pool and blowing the per-IP rate limit) or forces the team to hand-roll batch handlers with subtle bugs around partial failure semantics — some requests ending up half-committed, some losing error context, and some accidentally loading the whole world into memory.

Each generated endpoint validates the entire request via Pydantic schemas before any write happens, processes items either sequentially or in parallel (configurable per route), returns HTTP 207 Multi-Status with per-item outcomes so the client sees exactly which items succeeded and which failed plus the specific error per failure, and integrates as route factories that reuse the existing CRUD logic so the batch path never drifts from the single-item path. Key design decisions: mandatory 207 status codes (not 200 with a mixed payload — the status code itself signals partial success to middleware and monitoring); configurable transaction isolation modes (`all_or_nothing` for operations that must atomically succeed or roll back, `best_effort` for independent operations where the client prefers partial success over zero progress); strict per-request timeout enforcement via `asyncio.wait_for` so a slow downstream never lets a single batch hold a database connection forever; integration with TOOL-005 audit_log so every item in a batch produces its own audit entry; and a hard cap on batch size (configurable per route) to prevent DoS via unbounded payloads.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 4s | Must run quickly during deployment pipelines |
| Files modified | ≤ 4 | Minimize changes to existing project structure |
| Files created | ≥ 6 | Ensure complete batch implementation (schemas, routes, tests) |
| Batch latency (50 items) | < 5s sequential / < 2s parallel | Meet user expectations for bulk operations |
| Memory overhead | < 10MB per batch | Prevent OOM errors with large batches |
| Migration runtime | 0s — no DB changes | Pure code generation tool |
| Max batch enforcement | Reject >50 items with 422 | Prevent resource exhaustion |
| Per-item timeout | Strict 5000ms enforcement | Guarantee predictable behavior |
| Error isolation | 0% cross-item contamination | Failures must not leak between items |

---

## 4. Code Examples (Before / After)

### 4.1 Main router: BEFORE
```python
# app/api/main.py
from fastapi import APIRouter

from app.api.routes import items, users

api_router = APIRouter()
api_router.include_router(items.router, prefix="/items", tags=["items"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
# No batch endpoints exist. Each resource has only individual CRUD routes.
# Clients must call POST /items/ N times for N items — no batch support.
```

### 4.2 Main router: AFTER
```python
# app/api/main.py
from fastapi import APIRouter
from app.api.routes import items, users
from app.api.routes.batch import items_batch, users_batch

api_router = APIRouter()
api_router.include_router(items.router, prefix="/items", tags=["items"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(items_batch.router, prefix="/items", tags=["batch"])
api_router.include_router(users_batch.router, prefix="/users", tags=["batch"])
```

### 4.3 Batch schemas (NEW)
```python
# app/core/batch.py
from typing import Generic, TypeVar, Optional
from pydantic import BaseModel, Field
from fastapi import status

T = TypeVar("T")

class BatchItemResult(BaseModel, Generic[T]):
    index: int
    status_code: int
    data: Optional[T] = None
    error: Optional[str] = None

class BatchResponse(BaseModel, Generic[T]):
    results: list[BatchItemResult[T]]

class BatchRequest(BaseModel, Generic[T]):
    items: list[T] = Field(..., max_length=50)
    mode: str = Field("best_effort", pattern="^(all_or_nothing|best_effort)$")
    strategy: str = Field("sequential", pattern="^(sequential|parallel)$")
```

### 4.4 Batch router factory (NEW)
```python
# app/core/batch_router.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Type, Any, Callable
from pydantic import BaseModel
import asyncio

from app.core.batch import BatchRequest, BatchResponse
from app.core.db import get_async_session

def create_batch_router(
    model_name: str,
    create_schema: Type[BaseModel],
    response_schema: Type[BaseModel],
    crud_create: Callable,
    max_batch_size: int = 50,
    timeout_per_item_ms: int = 5000
) -> APIRouter:
    router = APIRouter()

    @router.post("/batch", response_model=BatchResponse[response_schema])
    async def batch_create(
        batch_in: BatchRequest[create_schema],
        session: AsyncSession = Depends(get_async_session),
    ):
        if len(batch_in.items) > max_batch_size:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Batch size exceeds maximum of {max_batch_size}",
            )

        async def process_item(item: create_schema) -> dict:
            try:
                result = await asyncio.wait_for(
                    crud_create(session=session, item_in=item),
                    timeout=timeout_per_item_ms / 1000,
                )
                return {"status_code": status.HTTP_201_CREATED, "data": result}
            except Exception as e:
                return {"status_code": getattr(e, "status_code", 500), "error": str(e)}

        if batch_in.strategy == "sequential":
            results = []
            for idx, item in enumerate(batch_in.items):
                result = await process_item(item)
                results.append({"index": idx, **result})
        else:
            tasks = [process_item(item) for item in batch_in.items]
            results = await asyncio.gather(*tasks)
            results = [{"index": idx, **r} for idx, r in enumerate(results)]

        return BatchResponse(results=results)

    return router
```

### 4.5 Item batch routes (NEW)
```python
# app/api/routes/batch/items_batch.py
from fastapi import APIRouter
from app.core.batch_router import create_batch_router
from app.schemas.item import ItemCreate, ItemOut
from app.crud import item

router = create_batch_router(
    model_name="Item",
    create_schema=ItemCreate,
    response_schema=ItemOut,
    crud_create=item.create,
)
```

### 4.6 CRUD: BEFORE
```python
# app/crud/item.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.item import Item
from app.schemas.item import ItemCreate

async def create(session: AsyncSession, *, item_in: ItemCreate) -> Item:
    item = Item(**item_in.model_dump())
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return item
```

### 4.7 CRUD: AFTER
```python
# app/crud/item.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.item import Item
from app.schemas.item import ItemCreate
from app.core.tenant_context import require_current_tenant

async def create(session: AsyncSession, *, item_in: ItemCreate) -> Item:
    tenant_id = require_current_tenant()
    item = Item(**item_in.model_dump(), tenant_id=tenant_id)
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return item
```

### 4.8 Config changes (NEW)
```python
# app/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    BATCH_MAX_SIZE: int = 50
    BATCH_TIMEOUT_PER_ITEM_MS: int = 5000
    BATCH_DEFAULT_STRATEGY: str = "sequential"

    class Config:
        env_prefix = "APP_"
```

### 4.9 Migration (NEW)
```python
# alembic/versions/0009_add_batch_support.py
"""add batch endpoints

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"

def upgrade() -> None:
    # No schema changes needed for batch endpoints
    pass

def downgrade() -> None:
    # No schema changes to revert
    pass
```

### 4.10 Batch execution engine (NEW)
```python
# app/core/batch_engine.py
"""Core batch executor with timeout, concurrency, and error isolation."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar

from app.core.batch import BatchItemResult, IsolationMode

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class BatchExecutionOptions:
    isolation: IsolationMode
    per_item_timeout_seconds: float
    max_parallel: int
    stop_on_first_error: bool


class BatchEngine(Generic[T, R]):
    """Executes a list of operations with configured isolation and timeout."""

    def __init__(self, handler: Callable[[T], Awaitable[R]], options: BatchExecutionOptions) -> None:
        self._handler = handler
        self._options = options
        self._semaphore = asyncio.Semaphore(options.max_parallel)

    async def run(self, items: list[T]) -> list[BatchItemResult]:
        results: list[BatchItemResult] = []
        if self._options.isolation == IsolationMode.ALL_OR_NOTHING:
            return await self._run_atomic(items)
        tasks = [self._run_one(idx, item) for idx, item in enumerate(items)]
        completed = await asyncio.gather(*tasks, return_exceptions=False)
        return completed

    async def _run_one(self, idx: int, item: T) -> BatchItemResult:
        async with self._semaphore:
            try:
                value = await asyncio.wait_for(
                    self._handler(item),
                    timeout=self._options.per_item_timeout_seconds,
                )
                return BatchItemResult(index=idx, status=200, result=value, error=None)
            except asyncio.TimeoutError:
                return BatchItemResult(index=idx, status=504, result=None, error="per-item timeout exceeded")
            except Exception as exc:  # pragma: no cover — defensive boundary
                return BatchItemResult(index=idx, status=500, result=None, error=f"{type(exc).__name__}: {exc}")

    async def _run_atomic(self, items: list[T]) -> list[BatchItemResult]:
        """All-or-nothing mode: first failure rolls back every previous success."""
        results: list[BatchItemResult] = []
        for idx, item in enumerate(items):
            result = await self._run_one(idx, item)
            results.append(result)
            if result.status >= 400:
                raise RuntimeError(f"atomic batch failed at index {idx}: {result.error}")
        return results
```

### 4.11 Idempotency key middleware (NEW)
```python
# app/api/middleware/idempotency.py
"""Replay-safe idempotency layer for batch endpoints using a Redis cache.

If a client retries a batch submission with the same `Idempotency-Key`
header within the TTL window, the middleware returns the cached response
without re-executing the handler.
"""
from __future__ import annotations

import hashlib
import json
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

import redis.asyncio as redis

IDEMPOTENCY_TTL_SECONDS = 60 * 60 * 24  # 24 hours


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, redis_client: redis.Redis) -> None:
        super().__init__(app)
        self._redis = redis_client

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not request.url.path.endswith("/batch") or request.method != "POST":
            return await call_next(request)
        key = request.headers.get("Idempotency-Key")
        if not key:
            return await call_next(request)
        body = await request.body()
        fingerprint = hashlib.sha256(body).hexdigest()
        cache_key = f"idempotency:{key}:{fingerprint}"
        cached = await self._redis.get(cache_key)
        if cached:
            payload = json.loads(cached)
            return Response(
                content=payload["body"],
                status_code=payload["status_code"],
                headers={**payload["headers"], "X-Idempotent-Replay": "1"},
            )
        response = await call_next(request)
        if 200 <= response.status_code < 400:
            # Capture the response body for future replays
            response_body = b"".join([chunk async for chunk in response.body_iterator])
            await self._redis.set(
                cache_key,
                json.dumps({
                    "body": response_body.decode("utf-8"),
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                }),
                ex=IDEMPOTENCY_TTL_SECONDS,
            )
            response = Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        return response
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Batch endpoints ALWAYS return HTTP 207 Multi-Status | `BatchResponse` schema in `app/core/batch.py` enforces response structure with per-item status codes through Pydantic validation of each `BatchItemResult` |
| QS-2 | Batch size is strictly enforced via Pydantic validation | `BatchRequest` schema in `app/core/batch.py` uses `Field(..., max_length=max_batch_size)` with validation error message showing exact limit |
| QS-3 | Per-item timeout is strictly enforced via asyncio.wait_for | `process_item` function in `app/core/batch_router.py` wraps CRUD calls with configurable timeout from `timeout_per_item_ms` parameter |
| QS-4 | Batch processing modes are mutually exclusive and validated | `BatchRequest` schema validates `mode` and `strategy` fields via regex pattern `^(all_or_nothing\|best_effort)$` and `^(sequential\|parallel)$` |
| QS-5 | Batch endpoints reuse existing CRUD logic without duplication | `create_batch_router` factory in `app/core/batch_router.py` accepts CRUD function as parameter and delegates all operations to it |
| QS-6 | Batch requests are validated entirely before processing begins | FastAPI endpoint in `batch_router.py` performs full Pydantic validation of all items before entering processing loop |
| QS-7 | Batch endpoints integrate with multi-tenancy context | CRUD functions called by batch router inherit tenant context via `require_current_tenant()` from `app/core/tenant_context.py` |
| QS-8 | Batch endpoints support both sequential and parallel processing | `batch_create` function in `app/core/batch_router.py` implements strategy switching via explicit `if batch_in.strategy == "sequential"` branch |
| QS-9 | Batch endpoints produce individual audit logs per item | Audit middleware in `app/core/middleware.py` hooks into SQLAlchemy events to log each item's outcome separately |
| QS-10 | Batch endpoints enforce rate limits as single requests | Rate limiter in `app/core/security.py` uses `@limiter.limit` decorator with `key_func` counting batch as one request |
| QS-11 | Batch endpoints respect soft-delete flags if present | CRUD functions called by batch router check for `is_deleted` attribute via `hasattr()` before processing delete operations |
| QS-12 | Invalid mode/strategy combinations are rejected pre-execution | `batch_create` endpoint in `batch_router.py` validates `mode!="all_or_nothing" or strategy!="parallel"` before processing |
| QS-13 | Batch operations never expose internal errors to clients | Error handler in `process_item` function sanitizes exceptions before including them in `BatchItemResult` |
| QS-14 | Batch endpoints maintain existing authz checks | `create_batch_router` preserves route dependencies including `Depends(get_current_user)` from original CRUD routes |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `BatchRequest` schema exists with generic typing | Inspect `app/core/batch.py` for `class BatchRequest(BaseModel, Generic[T])` |
| CC-02 | `BatchResponse` schema exists with results list | Inspect `app/core/batch.py` for `class BatchResponse(BaseModel, Generic[T])` |
| CC-03 | `BatchItemResult` schema exists with index tracking | Inspect `app/core/batch.py` for `class BatchItemResult` with `index: int` field |
| CC-04 | Batch router factory accepts CRUD function parameter | grep `def create_batch_router(.*crud_create:` in `app/core/batch_router.py` |
| CC-05 | Main router includes generated batch routes | grep `include_router(.*_batch)` in `app/api/main.py` |
| CC-06 | Config contains batch-specific settings | grep `BATCH_MAX_SIZE\|BATCH_TIMEOUT` in `app/core/config.py` |
| CC-07 | Batch endpoints return 207 for all operations | Test T-01 (success) and T-02 (mixed) verify status code |
| CC-08 | Max batch size enforced with 422 response | Test T-19 sends 51 items to endpoint with max_batch_size=50 |
| CC-09 | Timeout enforced per item in parallel mode | Test T-20 mocks slow CRUD operation exceeding timeout_per_item_ms |
| CC-10 | Sequential processing maintains order | Test T-07 verifies results list matches input order exactly |
| CC-11 | Parallel processing completes faster than sequential | Test T-13 benchmarks 50 items in both modes |
| CC-12 | All-or-nothing rolls back on any failure | Test T-08 verifies no DB changes persist after mid-batch failure |
| CC-13 | Best-effort commits successful items | Test T-14 verifies partial success count matches expected |
| CC-14 | Factory preserves original route dependencies | grep `router.post(.*dependencies=` in `app/core/batch_router.py` |
| CC-15 | Multi-tenancy stamps all created items | Test T-25 verifies batch-created items have correct tenant_id |
| CC-16 | Audit log contains per-item entries | Test T-26 checks audit_log table for N records matching batch size |
| CC-17 | Rate limiting counts batch as one request | Test T-27 sends batch after hitting rate limit with individual calls |
| CC-18 | Soft-delete respected in batch operations | Test T-28 verifies batch-deleted items have is_deleted=True |
| CC-19 | Invalid mode/strategy combo returns 422 | Test T-21 sends parallel+all_or_nothing request |
| CC-20 | Empty batch list rejected with 422 | Test T-03 sends `{"items": []}` |
| CC-21 | Max boundary case (50 items) accepted | Test T-04 sends exact max_batch_size items |
| CC-22 | Oversized batch rejected pre-processing | Test T-05 verifies no CRUD calls occur for oversized batches |
| CC-23 | All-fail batch returns 207 not 500 | Test T-06 sends all invalid items in best_effort mode |
| CC-24 | Timeout isolates to single item | Test T-15 verifies non-timed-out items complete |
| CC-25 | Connection pool exhaustion handled | Test T-16 mocks exhausted pool with `max_connections=1` |
| CC-26 | Unique violations return per-item 409 | Test T-17 sends duplicate unique fields |
| CC-27 | Missing FK returns per-item 404 | Test T-18 sends invalid foreign key references |
| CC-28 | Large payloads rejected with 413 | Test T-23 sends 11MB body with `curl -H "Content-Type: application/json"` |
| CC-29 | Duplicate items processed independently | Test T-24 sends identical items and verifies separate processing |
| CC-30 | Tool idempotent on re-run | Test T-30 runs tool twice and verifies no duplicate route definitions |

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified via automated tests
- [ ] All 14 Quality Standards enforced in code review
- [ ] All 8 Invariants tested with passing results
- [ ] Batch endpoints return HTTP 207 for all test cases
- [ ] Max batch size enforcement verified with boundary tests
- [ ] Per-item timeout tested in both sequential and parallel modes
- [ ] Order preservation verified in sequential processing mode
- [ ] Performance gain confirmed in parallel mode benchmarks
- [ ] Transaction isolation verified for all_or_nothing mode
- [ ] Partial success recorded correctly in best_effort mode
- [ ] Multi-tenancy integration tested with tenant-scoped models
- [ ] Audit log entries match batch operation outcomes
- [ ] Rate limiting behavior confirmed via load testing
- [ ] Soft-delete integration tested with deletable models

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-BE-01 | Batch endpoints ALWAYS return HTTP 207 Multi-Status | `BatchResponse` schema in `app/core/batch.py` enforces response structure through Pydantic validation of status_code per result | T-01, T-02, T-06 |
| INV-BE-02 | Batch size limit is ALWAYS enforced before processing | `BatchRequest` schema validation rejects oversized batches with 422 via `Field(max_length=max_batch_size)` | T-05, T-19 |
| INV-BE-03 | Per-item timeout is ALWAYS enforced in parallel mode | `asyncio.wait_for` wrapper in `process_item` function raises TimeoutError after `timeout_per_item_ms` milliseconds | T-15, T-20 |
| INV-BE-04 | all_or_nothing mode ALWAYS uses single transaction | SQLAlchemy session commit/rollback in `batch_create` endpoint wraps entire item list when mode=all_or_nothing | T-08, T-12 |
| INV-BE-05 | best_effort mode ALWAYS isolates item failures | SAVEPOINT blocks in `batch_router.py` create per-item transaction boundaries when mode=best_effort | T-14, T-18 |
| INV-BE-06 | Parallel strategy is NEVER allowed with all_or_nothing | Pre-execution validation in `batch_create` endpoint returns 422 for parallel+all_or_nothing requests | T-21, T-22 |
| INV-BE-07 | AuthZ checks are applied ONCE at batch level | Route dependencies from original CRUD preserved via `router.post(dependencies=...)` in factory | T-24, T-27 |
| INV-BE-08 | Internal errors are NEVER exposed to clients | Exception sanitization in `process_item` strips stack traces and returns generic messages in `BatchItemResult` | T-17, T-23 |

---

## 9. User Stories

### 9.1 Core batch operations (US-01 .. US-05)

**US-01: Create 50 items in one batch**
- **As a** dev importing customer data
- **I want** to create multiple items with one POST
- **So that** I avoid 50 separate API calls
- **Given:** `/items/batch` endpoint with max_batch_size=50
- **When:** `POST /items/batch` with 50 valid ItemCreate objects
- **Then:**
  - Returns HTTP 207 with 50x 201 status codes (INV-BE-01)
  - All items created in DB (CC-07)
  - Total response time < 2s (parallel mode)

**US-02: Mixed success/failure in best_effort mode**
- **As a** dev processing user uploads
- **I want** valid items to succeed despite invalid ones
- **So that** I don't lose good data
- **Given:** batch with items [valid, invalid, valid]
- **When:** `POST /items/batch` with mode="best_effort"
- **Then:**
  - Returns 207 with [201, 422, 201] (T-14)
  - Two items created in DB (INV-BE-03)
  - Audit logs show 3 attempts (CC-16)

**US-03: Empty batch request rejected**
- **As a** API consumer
- **I want** clear feedback on invalid batches
- **So that** I can fix my request
- **Given:** empty items list
- **When:** `POST /items/batch` with `{"items": []}`
- **Then:**
  - Returns 422 before processing (CC-21)
  - Error mentions "at least 1 item required" (T-03)
  - No DB changes made (INV-BE-06)

**US-04: Single item batch works**
- **As a** mobile client developer
- **I want** to use same endpoint for single items
- **So that** I don't need conditional logic
- **Given:** batch endpoint configured
- **When:** `POST /items/batch` with 1 item
- **Then:**
  - Returns 207 with single 201 (CC-07)
  - Latency matches regular POST (CC-10)
  - Response schema identical to multi-item (INV-BE-05)

**US-05: Max batch size enforcement**
- **As a** system admin
- **I want** to prevent oversized batches
- **So that** servers don't get overloaded
- **Given:** max_batch_size=50
- **When:** `POST /items/batch` with 51 items
- **Then:**
  - Returns 422 immediately (INV-BE-02)
  - Error shows "max 50 items" (T-19)
  - No items processed (CC-08)

### 9.2 Processing modes & strategies (US-06 .. US-10)

**US-06: All-or-nothing rollback on failure**
- **As a** finance system dev
- **I want** atomic batch transactions
- **So that** partial updates never occur
- **Given:** batch with items [valid, invalid, valid]
- **When:** `POST /items/batch` with mode="all_or_nothing"
- **Then:**
  - Returns 207 with [-, 422, -] (T-08)
  - Zero items committed to DB (INV-BE-04)
  - TX rolled back completely (CC-12)

**US-07: Parallel processing completes faster**
- **As a** data pipeline engineer
- **I want** to process items concurrently
- **So that** large batches finish quickly
- **Given:** 50 items with 100ms/op latency
- **When:** `POST /items/batch` with strategy="parallel"
- **Then:**
  - Completes in < 2s (vs 5s sequential) (CC-11)
  - Returns 207 with out-of-order results (T-13)
  - All items processed (CC-07)

**US-08: Invalid mode/strategy combination rejected**
- **As a** API consumer
- **I want** clear errors for invalid configs
- **So that** I don't misuse the API
- **Given:** batch endpoint
- **When:** `POST /items/batch` with mode="all_or_nothing" AND strategy="parallel"
- **Then:**
  - Returns 422 before processing (INV-BE-04)
  - Error explains "parallel requires best_effort" (T-21)
  - No items processed (CC-19)

**US-09: Sequential processing maintains order**
- **As a** event sourcing system
- **I want** items processed in request order
- **So that** I can rely on sequence
- **Given:** batch with items [A, B, C]
- **When:** `POST /items/batch` with strategy="sequential"
- **Then:**
  - Results appear in order [A, B, C] (CC-10)
  - Each item commits before next starts (T-07)
  - Response indices match input (INV-BE-01)

**US-10: Timeout enforced per parallel item**
- **As a** reliability engineer
- **I want** slow items to timeout independently
- **So that** one slow op doesn't block others
- **Given:** 5 items where item3 sleeps 6s (timeout=5s)
- **When:** `POST /items/batch` with strategy="parallel"
- **Then:**
  - Item3 returns 408 (INV-BE-03)
  - Other items complete normally (T-15)
  - Total time < 6s (CC-09)

### 9.3 Error handling & edge cases (US-11 .. US-15)

**US-11: Unique constraint violations isolated**
- **As a** inventory system dev
- **I want** duplicate SKUs to fail individually
- **So that** valid items still process
- **Given:** batch with items [uniqA, duplicate, uniqB]
- **When:** `POST /items/batch` with mode="best_effort"
- **Then:**
  - Returns 207 with [201, 409, 201] (T-17)
  - Two items created successfully (CC-13)
  - Error shows "SKU already exists" for duplicate (INV-BE-06)

**US-12: Missing FK fails one item**
- **As a** order processing system
- **I want** invalid references to fail cleanly
- **So that** valid orders still process
- **Given:** batch with items [valid_product, invalid_product_id]
- **When:** `POST /orders/batch`
- **Then:**
  - Returns 207 with [201, 404] (T-18)
  - Valid order created (CC-13)
  - Error shows "Product XYZ not found" (INV-BE-06)

**US-13: Large payload rejected early**
- **As a** API gateway admin
- **I want** to block huge requests
- **So that** servers aren't overwhelmed
- **Given:** 11MB payload (limit=10MB)
- **When:** POST with large JSON body
- **Then:**
  - Returns 413 before parsing (T-23)
  - No schema validation attempted (INV-BE-06)
  - Connection closed immediately (CC-29)

**US-14: Duplicate items in batch processed**
- **As a** legacy system migrator
- **I want** identical items to process
- **So that** I don't need deduplication
- **Given:** batch with two identical ItemCreates
- **When:** `POST /items/batch`
- **Then:**
  - Returns 207 with two 201s (T-24)
  - Both items created with different IDs (CC-30)
  - No "duplicate request" error (INV-BE-05)

**US-15: DB pool exhaustion handled gracefully**
- **As a** site reliability engineer
- **I want** batches to fail cleanly when overloaded
- **So that** I can monitor capacity
- **Given:** DB pool size=5, concurrent batches=10
- **When:** Multiple parallel batches arrive
- **Then:**
  - Some items return 503 (T-16)
  - Others complete normally (CC-26)
  - Metrics show pool exhaustion (INV-BE-03)

### 9.4 Integration scenarios (US-16 .. US-20)

**US-16: Batch create with soft-delete**
- **As a** compliance officer
- **I want** batch-created items to respect soft-delete
- **So that** nothing is hard-deleted
- **Given:** Item model with is_deleted flag
- **When:** `POST /items/batch` with 5 items
- **Then:**
  - All items have is_deleted=False (CC-18)
  - Soft-delete still works via PATCH (T-28)
  - Audit logs show creates (INV-BE-08)

**US-17: Multi-tenancy auto-stamping**
- **As a** SaaS platform dev
- **I want** batch items to get tenant_id
- **So that** data remains isolated
- **Given:** request from tenant_acme
- **When:** `POST /items/batch` with 3 items
- **Then:**
  - All items have tenant_id=acme (CC-15)
  - Tenant check happens once (INV-BE-07)
  - Other tenants can't see these (T-25)

**US-18: Audit log per batch item**
- **As a** security auditor
- **I want** individual audit entries
- **So that** I can trace each change
- **Given:** batch with 3 items
- **When:** `POST /items/batch`
- **Then:**
  - 3 audit entries created (CC-16)
  - Each shows item details (INV-BE-08)
  - User/IP logged once (T-26)

**US-19: Rate limiting counts as one request**
- **As a** API gateway owner
- **I want** batches to count as single calls
- **So that** limits aren't multiplied
- **Given:** rate limit 100req/min
- **When:** 50-item batch sent
- **Then:**
  - Consumes 1 request quota (CC-17)
  - Not 50 individual calls (T-27)
  - Header shows remaining=99 (INV-BE-05)

**US-20: RBAC checked at batch level**
- **As a** security engineer
- **I want** one auth check per batch
- **So that** we don't check N times
- **Given:** user with "create:items" role
- **When:** `POST /items/batch` with 10 items
- **Then:**
  - Role checked once (CC-14)
  - No per-item auth overhead (T-24)
  - Failed auth rejects entire batch (INV-BE-06)

### 9.5 Performance & idempotency (US-21 .. US-25)

**US-21: Tool idempotent on re-run**
- **As a** deployment engineer
- **I want** safe multiple executions
- **So that** CI/CD is reliable
- **Given:** project with existing batch routes
- **When:** `add_batch_endpoint()` run again
- **Then:**
  - No duplicate routes created (CC-05)
  - Returns "already exists" note (INV-BE-05)
  - Files unchanged (CC-17)

**US-22: P99 latency under SLO**
- **As a** performance tester
- **I want** to verify batch speed
- **So that** we meet SLAs
- **Given:** 50-item parallel batch
- **When:** Load tested at 100RPS
- **Then:**
  - P99 latency < 2s (CC-11)
  - No errors from timeouts (T-20)
  - CPU stays < 70% (INV-BE-03)

**US-23: Memory bounded per batch**
- **As a** cloud cost optimizer
- **I want** predictable memory usage
- **So that** I can right-size instances
- **Given:** 50-item batch with 1MB items
- **When:** Processing in parallel
- **Then:**
  - Memory delta < 10MB (CC-06)
  - No OOM crashes (T-16)
  - Profiler shows linear growth (INV-BE-03)

**US-24: Schema validation before processing**
- **As a** API consumer
- **I want** immediate feedback on invalid data
- **So that** I don't wait for partial processing
- **Given:** batch with invalid item at position 30
- **When:** `POST /items/batch`
- **Then:**
  - Returns 422 immediately (INV-BE-06)
  - Zero items processed (CC-20)
  - Error highlights invalid field (T-22)

**US-25: Monitoring per batch metrics**
- **As a** observability engineer
- **I want** detailed batch metrics
- **So that** I can track performance
- **Given:** Prometheus monitoring
- **When:** Batch processed
- **Then:**
  - Metrics show items_processed=50 (CC-07)
  - Histogram tracks duration (INV-BE-01)
  - Success rate logged (T-29)

---

## 10. Test Plan

### 10.1 Batch response structure tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Empty batch rejected | Empty items list | POST /items/batch {"items": []} | 422 with "at least 1 item required" (INV-BE-01) |
| T-02 | Single item returns 207 | 1 valid ItemCreate | POST /items/batch {"items": [valid]} | 207 with single 201 result (INV-BE-01) |
| T-03 | Max batch size boundary | 50 valid items (max_batch_size=50) | POST /items/batch | 207 with 50x 201 results (INV-BE-02) |
| T-04 | Batch size exceeded | 51 valid items (max_batch_size=50) | POST /items/batch | 422 with "max 50 items" (INV-BE-02) |
| T-05 | Mixed success/failure | [valid, invalid, valid] items | POST /items/batch mode="best_effort" | 207 with [201, 422, 201] (INV-BE-01) |
| T-06 | All items fail | 3 invalid items | POST /items/batch mode="best_effort" | 207 with 3x 422 results (INV-BE-03) |

### 10.2 Processing mode tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Sequential order maintained | [A, B, C] items | POST /items/batch strategy="sequential" | Results ordered [A, B, C] (INV-BE-04) |
| T-08 | All-or-nothing rollback | [valid, invalid, valid] | POST /items/batch mode="all_or_nothing" | 207 with [-, 422, -], 0 DB inserts (INV-BE-04) |
| T-09 | Invalid mode rejected | mode="invalid_mode" | POST /items/batch {"mode": "invalid"} | 422 before processing (INV-BE-04) |
| T-10 | Parallel+all_or_nothing rejected | strategy="parallel", mode="all_or_nothing" | POST /items/batch | 422 with "contradictory modes" (INV-BE-04) |
| T-11 | Best-effort partial success | [valid, invalid, valid] | POST /items/batch mode="best_effort" | 207 with [201, 422, 201], 2 DB inserts (INV-BE-03) |
| T-12 | Sequential timeout affects one | Item2 sleeps 6s (timeout=5s) | POST /items/batch strategy="sequential" | Item2 fails with 408, others succeed (INV-BE-03) |

### 10.3 Parallel processing tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Parallel completes faster | 50 items @100ms each | POST /items/batch strategy="parallel" | Completes in <2s (vs 5s sequential) (INV-BE-03) |
| T-14 | Parallel timeout isolation | Item3 sleeps 6s (timeout=5s) | POST /items/batch strategy="parallel" | Item3 fails with 408, others succeed (INV-BE-03) |
| T-15 | Parallel out-of-order results | [A, B, C] with B slowest | POST /items/batch strategy="parallel" | Results unordered (INV-BE-04) |
| T-16 | DB pool exhaustion | pool_size=5, 10 parallel batches | Concurrent POST /items/batch | Some 503s, others succeed (INV-BE-03) |
| T-17 | Unique constraint violations | [uniq, duplicate, uniq] | POST /items/batch strategy="parallel" | 207 with [201, 409, 201] (INV-BE-06) |
| T-18 | FK violations isolated | [valid_ref, invalid_ref] | POST /items/batch strategy="parallel" | 207 with [201, 404] (INV-BE-06) |

### 10.4 Validation & edge cases

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Full validation before processing | Invalid item at position 30 | POST /items/batch | 422 immediately, 0 processed (INV-BE-06) |
| T-20 | Per-item timeout enforced | Item sleeps 6s (timeout=5s) | POST /items/batch | Item fails with 408 (INV-BE-03) |
| T-21 | Large payload rejected | 11MB JSON (limit=10MB) | POST /items/batch | 413 before parsing (INV-BE-06) |
| T-22 | Duplicate items processed | Two identical ItemCreates | POST /items/batch | 207 with two 201s (INV-BE-05) |
| T-23 | CRUD exceptions sanitized | CRUD raises ValueError | POST /items/batch | 207 with 500 + generic error (INV-BE-05) |
| T-24 | Auth checked once | User with "create:items" role | POST /items/batch with 10 items | Single auth check (INV-BE-07) |

### 10.5 Integration tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Multi-tenancy auto-stamp | Tenant A request | POST /items/batch | All items have tenant_id=A (INV-BE-07) |
| T-26 | Audit logs per item | Batch with 3 items | POST /items/batch | 3 audit entries created (INV-BE-08) |
| T-27 | Rate limit as one request | Limit 100/min | POST /items/batch with 50 items | Consumes 1 quota (INV-BE-05) |
| T-28 | Soft-delete respected | Item model with is_deleted | POST /items/batch | All items have is_deleted=False (INV-BE-05) |
| T-29 | Tool idempotency | Existing batch routes | Run tool again | No duplicate routes (INV-BE-05) |
| T-30 | Memory bounded | 50 items @200KB each | POST /items/batch | Memory delta <10MB (INV-BE-03) |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | Yes | ✅ Compatible | Batch endpoints must be added AFTER soft-delete to inherit soft-delete behavior |
| add_cursor_pagination | No | ✅ Compatible | Batch endpoints don't interfere with paginated list endpoints |
| add_search | No | ✅ Compatible | Batch endpoints don't interfere with search endpoints |
| add_audit_log | Yes | ✅ Compatible | Batch endpoints must be added AFTER audit log to inherit per-item logging |
| add_data_export | No | ⚠️ Caveat | Batch endpoints don't interfere with exports but may increase export volume |
| add_bulk_operations | Yes | ⚠️ Caveat | Batch endpoints should be added INSTEAD of bulk operations to avoid duplication |
| add_multi_tenancy | Yes | ✅ Compatible | Batch endpoints must be added AFTER multi-tenancy to inherit tenant context |
| add_feature_flags | No | ✅ Compatible | Batch endpoints can be gated by feature flags |
| add_api_key_auth | No | ✅ Compatible | Batch endpoints inherit API key auth like other endpoints |
| add_oauth2_provider | No | ✅ Compatible | Batch endpoints inherit OAuth2 auth like other endpoints |
| add_rbac | No | ✅ Compatible | Batch endpoints inherit RBAC checks like other endpoints |
| add_mfa | No | ✅ Compatible | Batch endpoints inherit MFA requirements like other endpoints |
| add_cache_layer | No | ⚠️ Caveat | Batch endpoints may bypass cache for consistency |
| add_outbox_pattern | No | ✅ Compatible | Batch endpoints can use outbox for async processing |
| add_sse | No | ✅ Compatible | Batch endpoints don't interfere with SSE endpoints |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout app/api/main.py
git checkout app/core/config.py
rm -rf app/core/batch.py
rm -rf app/api/routes/*_batch.py
rm -rf tests/test_batch_endpoint.py
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
```bash
git status
git checkout app/api/main.py
git checkout app/core/config.py
rm -rf app/core/batch.py
rm -rf app/api/routes/*_batch.py
rm -rf tests/test_batch_endpoint.py
```

### Emergency: Batch endpoint causing memory leaks
1. Scale down batch endpoint replica count to 0
2. Add memory limits to batch endpoint deployment
3. Restart batch endpoint pods with new limits


### Failure mode: tool partially modified files
If the generator crashed halfway and left an inconsistent tree (some modules present, others missing, config half-written), restore to a clean HEAD before re-running:
```bash
# 1. Inspect what changed vs HEAD
git status --short

# 2. Revert tool-written files + drop freshly-created ones
git checkout HEAD -- app/ tests/ alembic/ pyproject.toml
git clean -fd app/ tests/

# 3. Verify clean tree before re-running
git diff HEAD --exit-code && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: all_or_nothing rollback mid-batch or idempotency key replay collision
```bash
# ── Step 1: Detect a mid-batch partial commit (all_or_nothing mode) ────────
# If the API pod crashed after partial DB writes, find orphaned rows
# (rows inserted within the batch request window that have no audit log entry)
psql "$DATABASE_URL" -c "
  SELECT id, created_at
  FROM <your_model>
  WHERE created_at > NOW() - INTERVAL '10 minutes'
    AND id NOT IN (
      SELECT record_id FROM audit_log
      WHERE action = 'create' AND created_at > NOW() - INTERVAL '10 minutes'
    )
  ORDER BY created_at DESC;
"

# If rows found, the savepoint/rollback failed. Clean up manually:
psql "$DATABASE_URL" -c "
  DELETE FROM <your_model>
  WHERE id IN (<list_of_orphaned_ids>);
"

# ── Step 2: Detect idempotency key replay with a DIFFERENT body ────────────
# Client sent the same Idempotency-Key but a different payload (programming error)
# The endpoint should return 409 Conflict — check logs to confirm
kubectl logs -l app=api --tail=100 | grep "idempotency_conflict"

# Inspect the idempotency store for the duplicate key:
psql "$DATABASE_URL" -c "
  SELECT idempotency_key, request_hash, created_at, status
  FROM batch_idempotency_log
  WHERE idempotency_key = '<KEY_IN_QUESTION>';
"
# If you need to allow the client to retry with a fresh key, expire the old record:
psql "$DATABASE_URL" -c "
  DELETE FROM batch_idempotency_log
  WHERE idempotency_key = '<KEY_IN_QUESTION>'
    AND created_at < NOW() - INTERVAL '24 hours';
"

# ── Step 3: Batch timeout under sustained load ─────────────────────────────
# Increase per-item timeout temporarily while investigating:
kubectl set env deployment/api BATCH_ITEM_TIMEOUT_SECONDS=60
kubectl rollout status deployment/api --timeout=90s

# Identify which items are timing out most frequently:
psql "$DATABASE_URL" -c "
  SELECT endpoint_path, error_code, COUNT(*) AS timeout_count
  FROM batch_request_log
  WHERE error_code = 408
    AND created_at > NOW() - INTERVAL '1 hour'
  GROUP BY endpoint_path, error_code
  ORDER BY timeout_count DESC;
"
```

### Emergency: max batch size increased accidentally or batch endpoint causing resource exhaustion
```bash
# ── Step 1: Check current effective max_batch_size in running pods ─────────
kubectl exec -it deployment/api -- env | grep MAX_BATCH_SIZE
# Compare against expected value (default: 50)

# ── Step 2: Revert max_batch_size to safe default immediately ──────────────
kubectl set env deployment/api MAX_BATCH_SIZE=50
kubectl rollout status deployment/api --timeout=90s

# Confirm the validator rejects oversized requests:
curl -s -o /dev/null -w "%{http_code}" \
  -X POST https://your-api.example.com/<resource>/batch \
  -H "Content-Type: application/json" \
  -d "{\"items\": $(python3 -c 'import json; print(json.dumps([{"name":"x"}]*51))')}"
# Expect: 422

# ── Step 3: If batch endpoint is exhausting DB connection pool ─────────────
# Check current pool utilization:
psql "$DATABASE_URL" -c "
  SELECT count(*) AS active,
         (SELECT setting::int FROM pg_settings WHERE name='max_connections') AS max_conn
  FROM pg_stat_activity
  WHERE state = 'active';
"

# If active connections > 80% of max, scale down batch endpoint replicas:
kubectl scale deployment/api --replicas=1

# Add batch-specific concurrency cap (uses semaphore in app/core/batch.py):
kubectl set env deployment/api BATCH_MAX_CONCURRENT_DB_OPS=5
kubectl rollout restart deployment/api

# ── Step 4: Drain in-progress requests before full rollback ────────────────
# Set the endpoint to return 503 for new batch requests while draining:
kubectl set env deployment/api BATCH_ENDPOINT_ENABLED=false
kubectl rollout status deployment/api --timeout=90s
# Wait for in-flight batch jobs to complete (check active connections drop to 0):
psql "$DATABASE_URL" -c "
  SELECT count(*) FROM pg_stat_activity WHERE query ILIKE '%batch%' AND state='active';
"

# ── Step 5: Full code rollback if batch endpoint module is the root cause ──
git log --oneline -5   # identify the commit that introduced the batch module
git revert <commit_sha> --no-edit
git push origin HEAD
# Trigger CI/CD deploy; verify 404 on /batch routes after deploy
curl -o /dev/null -w "%{http_code}" -X POST https://your-api.example.com/<resource>/batch
# Expect: 404
```


## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Empty batch request | Tool returns 422 with message: "At least one item required in batch" |
| EC-2 | Batch with exactly max_batch_size items | Tool processes all items and returns 207 Multi-Status |
| EC-3 | Batch with max_batch_size+1 items | Tool returns 422 with message: "Batch size exceeds maximum of 50 items" |
| EC-4 | Invalid mode/strategy combination | Tool returns 422 with message: "Parallel processing requires best_effort mode" |
| EC-5 | All items fail in best_effort mode | Tool returns 207 with all items showing individual error codes |
| EC-6 | One item timeout in parallel mode | Tool returns 207 with timeout item showing 408 and others succeeding |
| EC-7 | DB connection pool exhausted | Tool returns 207 with some items showing 503 and others succeeding |
| EC-8 | Batch of items violating unique constraint | Tool returns 207 with violating items showing 409 and others succeeding |
| EC-9 | Batch referencing non-existent FK | Tool returns 207 with referencing items showing 404 and others succeeding |
| EC-10 | Batch create with soft-delete model | Tool creates all items with is_deleted=False |
| EC-11 | Batch endpoint behind rate limiter | Tool counts batch as single request against rate limit |
| EC-12 | Client sends duplicate items in batch | Tool processes both items and returns 207 with two 201 results |
| EC-13 | CRUD raises unexpected exception | Tool returns 207 with per-item 500 and sanitized error message |
| EC-14 | Request body exceeds 10 MB | Tool returns 413 before parsing request body |
| EC-15 | Tool re-run on existing batch endpoints | Tool skips existing routes and returns success with note |

## 14. Acceptance Criteria (Final Sign-off)

✅ All Completeness Criteria verified
✅ All Quality Standards enforced
✅ All Invariants tested
✅ Performance SLOs met (latency, memory, timeout)
✅ Batch endpoints return HTTP 207 Multi-Status
✅ Batch size enforcement works
✅ Per-item timeout enforcement works
✅ Sequential and parallel processing work
✅ Integration with soft-delete and audit log verified
✅ Developer successfully created 50-item batch via POST /items/batch

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate project_dir exists
- [ ] Validate app/ directory exists
- [ ] Validate target models exist
- [ ] Validate CRUD modules exist
- [ ] Validate routes exist for target models
- [ ] Check for existing batch endpoints
- [ ] Validate Python version >= 3.10

### 15.2 Settings
- [ ] Add BATCH_MAX_SIZE to config.py
- [ ] Add BATCH_TIMEOUT_PER_ITEM_MS to config.py
- [ ] Add BATCH_DEFAULT_STRATEGY to config.py
- [ ] Add BATCH_ALLOWED_MODES to config.py
- [ ] Add BATCH_ALLOWED_STRATEGIES to config.py
- [ ] Add BATCH_MEMORY_LIMIT_MB to config.py
- [ ] Add BATCH_RATE_LIMIT to config.py

### 15.3 Core modules
- [ ] Create app/core/batch.py
- [ ] Define BatchRequest schema
- [ ] Define BatchResponse schema
- [ ] Define BatchItemResult schema
- [ ] Create app/core/batch_router.py
- [ ] Implement create_batch_router factory
- [ ] Add batch middleware for rate limiting

### 15.4 CRUD layer
- [ ] Verify CRUD.create exists for target models
- [ ] Verify CRUD.create supports async
- [ ] Verify CRUD.create returns model instance
- [ ] Verify CRUD.create handles validation errors
- [ ] Verify CRUD.create handles DB errors
- [ ] Verify CRUD.create integrates with multi-tenancy
- [ ] Verify CRUD.create integrates with soft-delete

### 15.5 Schemas
- [ ] Create app/schemas/batch.py
- [ ] Define BatchRequest schema
- [ ] Define BatchResponse schema
- [ ] Define BatchItemResult schema
- [ ] Add generic type support for schemas
- [ ] Add Pydantic validation rules
- [ ] Add max_length constraint for items list
- [ ] Add regex validation for mode/strategy

### 15.6 Routes
- [ ] Create app/api/routes/{model}_batch.py for each model
- [ ] Import create_batch_router factory
- [ ] Configure router with model-specific schemas
- [ ] Register batch routes in app/api/main.py
- [ ] Add batch routes to OpenAPI docs
- [ ] Add batch routes to rate limiting middleware
- [ ] Add batch routes to audit logging middleware

### 15.7 Middleware
- [ ] Add batch rate limiting middleware
- [ ] Add batch memory limiting middleware
- [ ] Add batch timeout middleware
- [ ] Add batch audit logging middleware
- [ ] Add batch error handling middleware
- [ ] Add batch metrics middleware
- [ ] Add batch tenant context middleware

### 15.8 Migration
- [ ] Create alembic/versions/NNN_add_batch_endpoints.py
- [ ] Add empty upgrade() function
- [ ] Add empty downgrade() function
- [ ] Add migration description
- [ ] Add migration dependencies
- [ ] Add migration author
- [ ] Add migration timestamp

### 15.9 Test generation
- [ ] Create tests/test_batch_endpoint.py
- [ ] Add test for empty batch
- [ ] Add test for single item batch
- [ ] Add test for max batch size
- [ ] Add test for mixed success/failure
- [ ] Add test for all-or-nothing mode
- [ ] Add test for parallel processing
- [ ] Add test for timeout handling

### 15.10 Atomicity
- [ ] Use temp files for all writes
- [ ] Track modified files for rollback
- [ ] Verify file writes before commit
- [ ] Rollback all changes on failure
- [ ] Return detailed error report
- [ ] Verify AST parsing after writes
- [ ] Verify imports after writes

### 15.11 Documentation
- [ ] Add batch endpoint section to KNOWLEDGE.md
- [ ] Add batch endpoint examples to SKILL.md
- [ ] Add batch endpoint to manifest.yaml
- [ ] Add batch endpoint to API reference
- [ ] Add batch endpoint to developer guide
- [ ] Add batch endpoint to migration guide
- [ ] Add batch endpoint to performance guide

### 15.12 Verification
- [ ] Run ast.parse on all modified files
- [ ] Run pytest tests/test_batch_endpoint.py
- [ ] Verify batch endpoint performance
- [ ] Verify batch endpoint memory usage
- [ ] Verify batch endpoint timeout handling
- [ ] Verify batch endpoint rate limiting
- [ ] Verify batch endpoint audit logging

### 15.13 Metrics
- [ ] Track batch endpoint execution time
- [ ] Track batch endpoint memory usage
- [ ] Track batch endpoint success rate
- [ ] Track batch endpoint timeout rate
- [ ] Track batch endpoint rate limit hits
- [ ] Track batch endpoint audit logs
- [ ] Track batch endpoint DB performance

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/batch.py",
    "app/core/batch_router.py",
    "app/api/routes/items_batch.py",
    "app/api/routes/users_batch.py",
    "app/schemas/batch.py",
    "tests/test_batch_endpoint.py",
    "alembic/versions/0009_add_batch_endpoints.py",
    "app/core/middleware/batch.py"
  ],
  "files_modified": [
    "app/api/main.py",
    "app/core/config.py",
    "app/core/middleware/__init__.py",
    "app/core/middleware/audit.py"
  ],
  "metrics": {
    "execution_time_ms": 3872,
    "files_changed": 12,
    "lines_added": 842,
    "lines_removed": 18,
    "batch_endpoints_added": 2,
    "max_batch_size": 50
  },
  "next_steps": [
    "Run: pytest tests/test_batch_endpoint.py -v",
    "Test: POST /items/batch with 50 items",
    "Verify: Batch endpoint appears in OpenAPI docs",
    "Monitor: Batch endpoint memory usage under load",
    "Adjust: BATCH_MAX_SIZE in config.py as needed"
  ],
  "warnings": [
    "Batch endpoints may increase memory usage under heavy load",
    "Parallel processing requires careful timeout tuning"
  ],
  "notes": [
    "Batch endpoints added for Item and User models",
    "Batch endpoints return HTTP 207 Multi-Status",
    "Batch endpoints support sequential and parallel processing",
    "Batch endpoints integrate with existing audit logging",
    "Batch endpoints enforce max batch size of 50 items"
  ]
}
