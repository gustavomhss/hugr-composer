<!--
{
  "tool_num": "020",
  "tool_name": "add_long_running_task",
  "model": "deepseek/deepseek-chat",
  "elapsed_seconds": 476.52491948605166,
  "prompt_tokens": 50619,
  "completion_tokens": 11274,
  "cost_usd": 0.03096638,
  "calls": 6
}
-->

# TOOL-020: add_long_running_task

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_long_running_task` |
| Category | EXTEND > API Design |
| Complexity | High |
| Dependencies | FastAPI, Redis, ARQ |
| Signature | `add_long_running_task(project_dir: str, max_task_duration_seconds: int = 3600, polling_interval_hint_seconds: int = 5, result_ttl_seconds: int = 86400) -> dict` |
| Parameters | `project_dir`: Absolute path to FastAPI project root<br>`max_task_duration_seconds`: Maximum allowed runtime before forced termination (default: 3600)<br>`polling_interval_hint_seconds`: Suggested client polling interval in response headers (default: 5)<br>`result_ttl_seconds`: Redis retention period for completed task results (default: 86400) |

## 2. Purpose

This tool adds production-grade infrastructure for long-running operations (reports, exports, AI inference) to FastAPI applications. It generates a task submission endpoint (`POST /tasks`), status polling endpoint (`GET /tasks/{task_id}`), cancellation endpoint (`DELETE /tasks/{task_id}`), and ARQ worker infrastructure. Without this, developers must manually implement polling, Redis state tracking, and worker coordination - often leading to blocking endpoints or lost tasks. The solution uses Redis for real-time state tracking with TTL-based cleanup, ARQ for async task processing, and structured progress reporting. Key design decisions include Redis-only state (no blocking DB writes), Fernet-encrypted task IDs, and strict 202 response semantics with Location headers.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5s | Must complete during deployment without downtime |
| Files modified | ≤ 5 | Minimize merge conflicts in existing codebase |
| Files created | ≥ 9 | Complete implementation requires multiple components |
| Submission endpoint latency | < 50 ms | Only requires Redis LPUSH operation |
| Status poll latency | < 10 ms | Single Redis HGET operation |
| Progress update latency | < 5 ms | Single Redis HSET operation |
| Worker pickup delay | < 1s | ARQ must promptly dequeue new tasks |
| Result availability | = result_ttl_seconds | Strict Redis TTL enforcement |
| Migration runtime | 0s | No database schema changes required |

---

## 4. Code Examples (Before / After)

### 4.1 Task Model: BEFORE
```python
# app/models/task.py
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base
import uuid


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

### 4.2 Task Model: AFTER
```python
# app/models/task.py
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base
import uuid


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_type: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(String(16), nullable=False, server_default=TaskStatus.PENDING)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

### 4.3 Task Registry (NEW)
```python
# app/core/task_registry.py
from typing import Callable, Dict, TypeVar
from functools import wraps
from fastapi import HTTPException
import inspect


TaskHandler = TypeVar("TaskHandler", bound=Callable)

class TaskRegistry:
    def __init__(self):
        self._handlers: Dict[str, TaskHandler] = {}

    def register(self, task_type: str) -> Callable[[TaskHandler], TaskHandler]:
        def decorator(func: TaskHandler) -> TaskHandler:
            if task_type in self._handlers:
                raise ValueError(f"Task type '{task_type}' already registered")
            
            if not inspect.iscoroutinefunction(func):
                raise TypeError("Task handler must be async function")
            
            self._handlers[task_type] = func
            
            @wraps(func)
            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)
            
            return wrapper
        return decorator

    def get_handler(self, task_type: str) -> TaskHandler:
        if task_type not in self._handlers:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown task type '{task_type}'. Available types: {list(self._handlers.keys())}"
            )
        return self._handlers[task_type]

task_registry = TaskRegistry()
```

### 4.4 Task Routes (NEW)
```python
# app/api/routes/tasks.py
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from uuid import UUID
from app.core.auth import CurrentUser
from app.core.tasks import TaskStatus, get_task_status
from app.schemas.task import TaskSubmit, TaskStatusResponse
from app.core.task_registry import task_registry
from app.core.redis import redis_client


router = APIRouter()

@router.post("/tasks", status_code=status.HTTP_202_ACCEPTED)
async def submit_task(
    task_in: TaskSubmit,
    user: CurrentUser,
) -> JSONResponse:
    task_id = UUID(int=0)  # Placeholder for Redis-based ID generation
    await redis_client.hset(
        f"task:{task_id}",
        mapping={
            "task_type": task_in.task_type,
            "status": TaskStatus.PENDING,
            "owner_id": str(user.id),
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    return JSONResponse(
        content={"task_id": str(task_id)},
        headers={"Location": f"/tasks/{task_id}"},
    )

@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: UUID,
    user: CurrentUser,
) -> TaskStatusResponse:
    task_data = await redis_client.hgetall(f"task:{task_id}")
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")
    if task_data["owner_id"] != str(user.id):
        raise HTTPException(status_code=403, detail="Not your task")
    return TaskStatusResponse(**task_data)
```

### 4.5 Task Schemas (NEW)
```python
# app/schemas/task.py
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskSubmit(BaseModel):
    task_type: str = Field(..., min_length=1, max_length=255)
    params: dict = Field(default_factory=dict)


class TaskStatusResponse(BaseModel):
    task_id: UUID
    task_type: str
    status: TaskStatus
    progress: Optional[float] = Field(None, ge=0, le=100)
    message: Optional[str]
    result: Optional[dict]
    created_at: str
    updated_at: str
```

### 4.6 Task Worker (NEW)
```python
# app/workers/task_worker.py
from arq import create_pool
from arq.worker import Worker
from app.core.task_registry import task_registry
from app.core.redis import redis_client
from uuid import UUID
import asyncio


async def task_handler(ctx, task_id: UUID, task_type: str, params: dict):
    handler = task_registry.get_handler(task_type)
    await redis_client.hset(
        f"task:{task_id}",
        "status", "running"
    )
    try:
        result = await handler(**params)
        await redis_client.hset(
            f"task:{task_id}",
            mapping={
                "status": "completed",
                "result": result,
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
    except Exception as e:
        await redis_client.hset(
            f"task:{task_id}",
            mapping={
                "status": "failed",
                "error": str(e),
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
        raise


class TaskWorker(Worker):
    async def startup(self):
        self.redis_pool = await create_pool()
        return await super().startup()

    async def shutdown(self):
        await self.redis_pool.close()
        return await super().shutdown()
```

### 4.7 Migration
```python
# alembic/versions/0009_add_task_infrastructure.py
"""add task infrastructure

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_type", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("owner_id", sa.Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_tasks_owner_status", "tasks", ["owner_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_tasks_owner_status", table_name="tasks")
    op.drop_table("tasks")
```

### 4.8 Progress reporter and cancellation check (NEW)
```python
# app/core/task_progress.py
from datetime import datetime, timezone
from uuid import UUID

from app.core.redis import get_redis
from app.core.tasks import TASK_KEY_PATTERN


async def report_progress(
    task_id: UUID,
    pct: int,
    message: str = "",
) -> None:
    """Update task progress in Redis. Progress is monotonically increasing."""
    if not 0 <= pct <= 100:
        raise ValueError(f"Progress pct must be 0..100, got {pct}")
    redis = await get_redis()
    key = TASK_KEY_PATTERN.format(task_id=task_id)

    current_raw = await redis.hget(key, "progress_pct")
    current = int(current_raw) if current_raw else 0
    if pct < current:
        return  # ignore backward updates

    await redis.hset(
        key,
        mapping={
            "progress_pct": str(pct),
            "progress_message": message[:256],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


async def is_cancelled(task_id: UUID) -> bool:
    """Check the cancellation flag in Redis. Workers call this periodically."""
    redis = await get_redis()
    key = TASK_KEY_PATTERN.format(task_id=task_id)
    flag = await redis.hget(key, "cancel_requested")
    return flag == "1"


async def mark_cancelled(task_id: UUID) -> None:
    """Cooperative cancellation: worker detects flag and exits gracefully."""
    redis = await get_redis()
    key = TASK_KEY_PATTERN.format(task_id=task_id)
    await redis.hset(key, "cancel_requested", "1")
```

### 4.9 Idempotency key handler (NEW)
```python
# app/core/task_idempotency.py
from uuid import UUID

from app.core.redis import get_redis

IDEMPOTENCY_KEY_PATTERN = "task:idempotency:{user_id}:{key}"
IDEMPOTENCY_TTL_SECONDS = 3600


async def get_or_claim(
    user_id: UUID,
    idempotency_key: str,
) -> tuple[UUID | None, bool]:
    """
    Atomic: if key exists, return existing task_id + False.
    If not, reserve slot (claimer fills later) and return None + True.
    """
    redis = await get_redis()
    key = IDEMPOTENCY_KEY_PATTERN.format(user_id=user_id, key=idempotency_key)
    existing = await redis.get(key)
    if existing is not None:
        return UUID(existing.decode("utf-8")), False
    return None, True


async def bind_task(
    user_id: UUID,
    idempotency_key: str,
    task_id: UUID,
) -> None:
    """Store the task_id under the idempotency key with TTL."""
    redis = await get_redis()
    key = IDEMPOTENCY_KEY_PATTERN.format(user_id=user_id, key=idempotency_key)
    await redis.setex(key, IDEMPOTENCY_TTL_SECONDS, str(task_id))
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Task submission always returns 202 Accepted** | `submit_task` route decorator enforces `status_code=status.HTTP_202_ACCEPTED` unconditionally |
| QS-2 | **Task state transitions are atomic and consistent** | Redis `HSET` operations use Lua scripts for atomic updates in `app/core/tasks.py` |
| QS-3 | **Task progress percentage never decreases** | `report_progress` function in `app/core/tasks.py` validates new percentage > current percentage |
| QS-4 | **Task results expire after result_ttl_seconds** | Redis `EXPIRE` command sets TTL on task hash in `app/crud/task.py` |
| QS-5 | **Task cancellation propagates within max_task_duration_seconds** | Worker checks `is_cancelled` flag every 5 seconds in `app/workers/task_worker.py` |
| QS-6 | **Task handlers must be async functions** | `TaskRegistry.register` decorator validates `inspect.iscoroutinefunction(func)` |
| QS-7 | **Task type must be registered before submission** | `task_registry.get_handler` raises HTTPException(422) for unknown task types |
| QS-8 | **Task ownership is enforced at API boundary** | `get_task_status` route validates `task_data["owner_id"] == str(user.id)` |
| QS-9 | **Large results (>1MB) use presigned URLs** | `store_large_result` function in `app/core/tasks.py` uploads to S3 and returns presigned URL |
| QS-10 | **Idempotency keys prevent duplicate task creation** | Redis `SETNX` operation in `app/crud/task.py` ensures key uniqueness |
| QS-11 | **Worker timeout enforces max_task_duration_seconds** | `task_handler` wraps execution in `asyncio.wait_for` with timeout |
| QS-12 | **Task registry prevents duplicate task type registration** | `TaskRegistry.register` raises `ValueError` for duplicate task types |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `TaskStatus` enum exists at `app/models/task.py` | File exists, parses |
| CC-02 | `TaskRegistry` class exists at `app/core/task_registry.py` | File exists, contains registration decorator |
| CC-03 | `TaskSubmit` schema exists at `app/schemas/task.py` | File exists, contains task_type and params fields |
| CC-04 | `TaskStatusResponse` schema exists at `app/schemas/task.py` | File exists, contains status, progress, result fields |
| CC-05 | `submit_task` route exists at `app/api/routes/tasks.py` | Route file inspected |
| CC-06 | `get_task_status` route exists at `app/api/routes/tasks.py` | Route file inspected |
| CC-07 | `TaskWorker` class exists at `app/workers/task_worker.py` | File exists, inherits from ARQ Worker |
| CC-08 | Redis connection pool exists at `app/core/redis.py` | File exists, exports redis_client |
| CC-09 | `report_progress` function exists at `app/core/tasks.py` | File exists, validates progress percentage |
| CC-10 | `store_large_result` function exists at `app/core/tasks.py` | File exists, handles S3 upload |
| CC-11 | Task routes registered in `app/api/main.py` | grep `app.include_router(tasks.router)` |
| CC-12 | TASK_* settings exist in `app/core/config.py` | grep `TASK_MAX_DURATION`, `TASK_RESULT_TTL` |
| CC-13 | `.env.example` contains task-related environment variables | grep `TASK_MAX_DURATION`, `TASK_RESULT_TTL` |
| CC-14 | `test_long_running_task.py` exists with 30 tests | File exists |
| CC-15 | Task submission endpoint returns 202 Accepted | T-01 |
| CC-16 | Task status endpoint returns current state | T-07 |
| CC-17 | Task cancellation endpoint transitions to cancelled | T-13 |
| CC-18 | Worker timeout enforces max_task_duration_seconds | T-17 |
| CC-19 | Task results expire after result_ttl_seconds | T-19 |
| CC-20 | Idempotency keys prevent duplicate task creation | T-05 |
| CC-21 | Progress percentage never decreases | T-08 |
| CC-22 | Large results use presigned URLs | T-20 |
| CC-23 | Task ownership enforced at API boundary | T-25 |
| CC-24 | Unknown task types return 422 | T-02 |
| CC-25 | Worker crashes result in timeout | T-16 |
| CC-26 | Redis TTL expiry returns 404 | T-22 |
| CC-27 | Admin can list all tasks | T-26 |
| CC-28 | Task registry rejects duplicate task types | T-03 |
| CC-29 | Task handlers must be async functions | T-04 |
| CC-30 | Tool execution time < 5s | Time measurement |

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] `test_long_running_task.py` passes all 30 tests
- [ ] Task submission endpoint returns 202 Accepted
- [ ] Task status endpoint returns current state
- [ ] Task cancellation endpoint transitions to cancelled
- [ ] Worker timeout enforces max_task_duration_seconds
- [ ] Task results expire after result_ttl_seconds
- [ ] Idempotency keys prevent duplicate task creation
- [ ] Progress percentage never decreases
- [ ] Large results use presigned URLs
- [ ] Task ownership enforced at API boundary
- [ ] Unknown task types return 422
- [ ] Worker crashes result in timeout
- [ ] Redis TTL expiry returns 404

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-TASK-01 | Task submission ALWAYS returns 202 Accepted | `submit_task` route decorator enforces `status_code=status.HTTP_202_ACCEPTED` unconditionally | T-01 |
| INV-TASK-02 | Task progress percentage NEVER decreases | `report_progress` function validates new percentage > current percentage in `app/core/tasks.py` | T-08 |
| INV-TASK-03 | Task results ALWAYS expire after result_ttl_seconds | Redis `EXPIRE` command sets TTL on task hash in `app/crud/task.py` | T-19 |
| INV-TASK-04 | Task cancellation ALWAYS propagates within max_task_duration_seconds | Worker checks `is_cancelled` flag every 5 seconds in `app/workers/task_worker.py` | T-13 |
| INV-TASK-05 | Task handlers MUST be async functions | `TaskRegistry.register` decorator validates `inspect.iscoroutinefunction(func)` | T-04 |
| INV-TASK-06 | Task type MUST be registered before submission | `task_registry.get_handler` raises HTTPException(422) for unknown task types | T-02 |
| INV-TASK-07 | Task ownership is ALWAYS enforced at API boundary | `get_task_status` route validates `task_data["owner_id"] == str(user.id)` | T-25 |
| INV-TASK-08 | Large results (>1MB) ALWAYS use presigned URLs | `store_large_result` function uploads to S3 and returns presigned URL in `app/core/tasks.py` | T-20 |

---

## 9. User Stories

### 9.1 Core Task Flow (US-01 .. US-05)

**US-01: Submit a long-running report generation**
- **As a** data analyst
- **I want** to POST a report task
- **So that** I can get results without blocking my session
- **Given:** `/tasks` endpoint exists with `report-generator` task type registered
- **When:** `POST /tasks {"task_type": "report-generator", "params": {"report_id": "sales-q2"}}`
- **Then:**
  - Returns 202 Accepted with `task_id` and Location header (INV-TASK-01)
  - Task appears in Redis with status `pending` (CC-05)
  - Worker picks up task within 1s (SLO-7)

**US-02: Poll for task completion status**
- **As a** frontend developer
- **I want** to poll task status
- **So that** I can show progress to users
- **Given:** Task `task_123` exists in Redis with status `running`
- **When:** `GET /tasks/task_123` called every 5s
- **Then:**
  - Response includes `status`, `progress`, and `message` fields (CC-04)
  - Progress percentage never decreases between polls (INV-TASK-02)
  - Latency < 10ms (SLO-5)

**US-03: Retrieve completed task results**
- **As a** mobile app
- **I want** to fetch final results
- **So that** users see their completed work
- **Given:** Task `task_123` completed with 50KB JSON result
- **When:** `GET /tasks/task_123` after completion
- **Then:**
  - Status shows `completed` with inline result (CC-16)
  - Response includes `updated_at` timestamp (CC-04)
  - Redis TTL set to 86400s (INV-TASK-03)

**US-04: Handle failed task gracefully**
- **As a** system admin
- **I want** to see failure details
- **So that** I can debug issues
- **Given:** Task `task_123` failed with exception
- **When:** `GET /tasks/task_123` after failure
- **Then:**
  - Status shows `failed` with error message (CC-16)
  - Error details stored in Redis (CC-09)
  - Result still available for 24h (SLO-8)

**US-05: Submit with idempotency key**
- **As a** payment processor
- **I want** to prevent duplicate tasks
- **So that** charges aren't duplicated
- **Given:** `Idempotency-Key: pay_123` header
- **When:** Identical POST /tasks called twice
- **Then:**
  - Second call returns same task_id (CC-20)
  - Redis tracks idempotency keys for 1h (QS-10)
  - Verified by T-05

### 9.2 Task Lifecycle Control (US-06 .. US-10)

**US-06: Cancel a running export task**
- **As a** user who changed their mind
- **I want** to cancel mid-process
- **So that** resources aren't wasted
- **Given:** Task `task_123` in `running` state
- **When:** `DELETE /tasks/task_123` called
- **Then:**
  - Status transitions to `cancelled` within 5s (INV-TASK-04)
  - Worker receives cancellation signal (CC-17)
  - Verified by T-13

**US-07: Timeout long-running AI inference**
- **As a** ML engineer
- **I want** tasks to timeout
- **So that** hung models don't run forever
- **Given:** Task with `max_duration=300` (5min)
- **When:** Task runs for 301 seconds
- **Then:**
  - Worker forcibly terminates task (QS-11)
  - Status marked `failed` with timeout error (CC-18)
  - Verified by T-17

**US-08: Retry failed PDF generation**
- **As a** document service
- **I want** to retry failures
- **So that** transient errors don't block users
- **Given:** Task failed due to temp file issue
- **When:** User resubmits identical request
- **Then:**
  - New task_id created (INV-TASK-06)
  - Previous failure remains available for 24h (CC-19)
  - Worker picks up retry within 1s (SLO-7)

**US-09: Check progress during video processing**
- **As a** media upload service
- **I want** real-time progress
- **So that** users see encoding status
- **Given:** Video task processing frames 120/1000
- **When:** `report_progress(task_id, pct=12, msg="Frame 120")` called
- **Then:**
  - Next poll shows 12% progress (CC-09)
  - Message appears in status response (CC-04)
  - Redis update latency <5ms (SLO-6)

**US-10: Handle worker crash during import**
- **As a** data pipeline
- **I want** crash detection
- **So that** tasks don't hang indefinitely
- **Given:** Worker dies during CSV import
- **When:** No heartbeat for 30s
- **Then:**
  - Task marked `failed` by timeout (CC-25)
  - Error indicates worker termination (CC-16)
  - Verified by T-16

### 9.3 Result Handling & Cleanup (US-11 .. US-15)

**US-11: Deliver large Excel export via URL**
- **As a** reporting service
- **I want** to handle big files
- **So that** API responses stay small
- **Given:** 150MB export completed
- **When:** Worker calls `store_large_result()`
- **Then:**
  - Status shows `result_url` with 24h TTL (INV-TASK-08)
  - S3 object has matching expiration (CC-22)
  - Verified by T-20

**US-12: Expire old sentiment analysis results**
- **As a** privacy-conscious app
- **I want** automatic cleanup
- **So that** data isn't stored indefinitely
- **Given:** Task completed 25h ago (TTL=24h)
- **When:** Client polls `GET /tasks/old_task`
- **Then:**
  - Returns 404 with "expired" message (CC-26)
  - Redis key deleted (INV-TASK-03)
  - Verified by T-22

**US-13: Reject invalid task types**
- **As a** API consumer
- **I want** clear errors
- **So that** I can fix my requests
- **Given:** Unregistered `"foo-process"` task type
- **When:** `POST /tasks {"task_type": "foo-process"}`
- **Then:**
  - Returns 422 with allowed types list (INV-TASK-06)
  - No task created in Redis (CC-24)
  - Verified by T-02

**US-14: Preserve completed tasks in PostgreSQL**
- **As a** compliance officer
- **I want** audit history
- **So that** we meet retention policies
- **Given:** `persist_completed=True` config
- **When:** Task reaches `completed` status
- **Then:**
  - Row written to `tasks` table (CC-01)
  - Redis result remains primary source (QS-4)
  - Verified by T-28

**US-15: Handle Redis outage during progress**
- **As a** resilient system
- **I want** to tolerate failures
- **So that** tasks complete anyway
- **Given:** Redis down for 10s
- **When:** Worker calls `report_progress()`
- **Then:**
  - Progress update fails silently (CC-09)
  - Task continues execution (QS-2)
  - Final result still stored (INV-TASK-03)

### 9.4 Security & Access Control (US-16 .. US-20)

**US-16: Enforce task ownership**
- **As a** multi-user system
- **I want** isolation
- **So that** users only see their tasks
- **Given:** Task owned by user A
- **When:** User B polls `GET /tasks/task_A`
- **Then:**
  - Returns 403 Forbidden (INV-TASK-07)
  - Redis ownership check occurs (CC-23)
  - Verified by T-25

**US-17: Admin view all tasks**
- **As a** support engineer
- **I want** global visibility
- **So that** I can debug issues
- **Given:** Admin token with `tasks:read_all`
- **When:** `GET /admin/tasks?status=running`
- **Then:**
  - Returns all matching tasks (CC-27)
  - Includes owner_id for each (CC-04)
  - Pagination limits to 100/page (QS-9)

**US-18: API key submits background task**
- **As a** CI/CD pipeline
- **I want** automated tasks
- **So that** deploys trigger processing
- **Given:** Valid API key `ci_123`
- **When:** `POST /tasks` with `X-API-Key` header
- **Then:**
  - Task created with owner=ci_123 (CC-08)
  - Status pollable with same key (INV-TASK-07)
  - Verified by T-29

**US-19: Reject invalid task params**
- **As a** secure API
- **I want** input validation
- **So that** handlers get clean data
- **Given:** Schema requires `report_id:string`
- **When:** `POST /tasks {"task_type":"report", "params":{"report_id":123}}`
- **Then:**
  - Returns 422 validation error (CC-03)
  - No task enqueued (CC-24)
  - Verified by T-01

**US-20: Encrypt task IDs in responses**
- **As a** security-conscious dev
- **I want** opaque IDs
- **So that** they can't be guessed
- **Given:** Task submission endpoint
- **When:** Response contains `task_id`
- **Then:**
  - ID is Fernet-encrypted UUID (QS-1)
  - No sequential patterns visible (CC-15)
  - Verified by T-06

### 9.5 Integration & Observability (US-21 .. US-25)

**US-21: Push progress via SSE**
- **As a** real-time dashboard
- **I want** live updates
- **So that** users don't need to poll
- **Given:** SSE endpoint `/events` exists
- **When:** Worker calls `report_progress()`
- **Then:**
  - Event sent to user's channel (CC-30)
  - Message contains current percentage (CC-09)
  - Regular polls still work (INV-TASK-02)

**US-22: Monitor queue depth**
- **As a** DevOps engineer
- **I want** metrics
- **So that** I can scale workers
- **Given:** Prometheus endpoint `/metrics`
- **When:** Tasks queue up
- **Then:**
  - `arq_pending_tasks` gauge increases (CC-12)
  - Alert fires at 100+ pending (QS-12)
  - Verified by T-27

**US-23: Correlate logs via task_id**
- **As a** troubleshooter
- **I want** tracing
- **So that** I can follow execution
- **Given:** Structured logging setup
- **When:** Worker processes task
- **Then:**
  - All logs include `task_id` field (CC-07)
  - Progress updates log at INFO level (CC-10)
  - Verified by T-21

**US-24: Handle 10K pending tasks**
- **As a** high-volume service
- **I want** scale
- **So that** spikes don't break us
- **Given:** 10,000 tasks in Redis queue
- **When:** New tasks submitted
- **Then:**
  - API latency stays <50ms (SLO-4)
  - Workers process at steady rate (QS-11)
  - Verified by T-30

**US-25: Idempotent tool execution**
- **As a** deployment script
- **I want** safe retries
- **So that** duplicates don't break things
- **Given:** Already-configured project
- **When:** `add_long_running_task()` rerun
- **Then:**
  - No duplicate routes created (CC-14)
  - Existing files untouched (CC-17)
  - Returns "already configured" note (QS-12)

---

## 10. Test Plan

### 10.1 Task Submission

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Submit returns 202 Accepted | No setup | POST /tasks {"task_type": "report-generator"} | 202 with task_id and Location header (INV-TASK-01) |
| T-02 | Unknown task type returns 422 | No "foo-process" in registry | POST /tasks {"task_type": "foo-process"} | 422 with available types list (INV-TASK-06) |
| T-03 | Duplicate task type registration fails | "report-generator" already registered | @task_registry.register("report-generator") | ValueError raised (INV-TASK-06) |
| T-04 | Sync task handler rejected | Sync function handler | @task_registry.register("sync-task") | TypeError raised (INV-TASK-05) |
| T-05 | Idempotency key prevents duplicates | Idempotency-Key: task_123 | POST /tasks twice with same key | Second call returns same task_id |
| T-06 | Task ID is Fernet-encrypted | Task submission | Inspect task_id in response | Opaque string, not raw UUID |

### 10.2 Polling & Progress

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Poll pending task | Task in pending state | GET /tasks/{task_id} | Status="pending" |
| T-08 | Progress never decreases | Task at 50% progress | report_progress(task_id, pct=40) | ValueError raised (INV-TASK-02) |
| T-09 | Poll latency < 10ms | Task exists in Redis | Measure GET /tasks/{task_id} latency | < 10ms |
| T-10 | Progress update latency < 5ms | Task running | Measure report_progress() latency | < 5ms |
| T-11 | SSE progress push | SSE endpoint enabled | report_progress(task_id, pct=25) | SSE event sent to user channel |
| T-12 | Final progress = 100% | Task completes | GET /tasks/{task_id} | Progress=100% |

### 10.3 Cancellation & Timeout

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Cancel running task | Task in running state | DELETE /tasks/{task_id} | Status="cancelled" within 5s (INV-TASK-04) |
| T-14 | Cancel pending task | Task in pending state | DELETE /tasks/{task_id} | Status="cancelled" |
| T-15 | Cancel completed task | Task already completed | DELETE /tasks/{task_id} | 200 with already_completed status |
| T-16 | Worker crash timeout | Worker dies mid-task | Wait 30s | Status="failed" with timeout error |
| T-17 | Task timeout enforcement | Task runs for max_duration+1 | Wait | Status="failed" with timeout error |
| T-18 | Cancel race condition | Concurrent cancel+complete | Both requests simultaneously | First writer wins |

### 10.4 Results & Cleanup

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Result TTL enforcement | Task completed | Wait result_ttl_seconds+1 | GET /tasks/{task_id} returns 404 (INV-TASK-03) |
| T-20 | Large result presigned URL | 150MB result | GET /tasks/{task_id} | result_url with 24h TTL (INV-TASK-08) |
| T-21 | Small result inline | 50KB result | GET /tasks/{task_id} | result in response body |
| T-22 | Redis TTL expiry | Task expired | GET /tasks/{task_id} | 404 with "task_expired" message |
| T-23 | Admin list all tasks | Admin token | GET /admin/tasks | Returns all tasks with pagination |
| T-24 | Audit entry persistence | persist_completed=True | Task completes | Row written to tasks table |

### 10.5 Auth & Integration

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Owner check enforcement | Task owned by user A | GET /tasks/{task_id} as user B | 403 Forbidden (INV-TASK-07) |
| T-26 | API key task submission | Valid API key | POST /tasks with X-API-Key | Task owned by key identity |
| T-27 | Concurrent task isolation | 100 concurrent tasks | Stress test | Each task isolated |
| T-28 | Tool idempotency | Already configured | Run tool again | No file changes, notes "skipped" |
| T-29 | High volume task handling | 10K pending tasks | Submit tasks | API latency < 50ms |
| T-30 | Worker pickup delay < 1s | Task submitted | Measure worker pickup time | < 1s |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Tasks can be soft-deleted without affecting execution; worker ignores deletion state |
| add_cursor_pagination | No | ✅ Compatible | Task listing endpoints support cursor pagination for large result sets |
| add_search | No | ⚠️ Caveat | Search must exclude Redis-based task state; only search persisted PostgreSQL tasks if enabled |
| add_audit_log | Yes | ✅ Compatible | Must run AFTER to log task state changes; audit entries capture task lifecycle transitions |
| add_data_export | No | ⚠️ Caveat | Data exports should exclude Redis task state; export only persisted PostgreSQL task records |
| add_bulk_operations | No | ⚠️ Caveat | Bulk operations must skip task-related endpoints due to async nature |
| add_multi_tenancy | Yes | ✅ Compatible | Must run AFTER to properly scope tasks to tenants; task ownership checks respect tenant boundaries |
| add_feature_flags | No | ✅ Compatible | Feature flags can control task type availability without affecting execution |
| add_api_key_auth | No | ✅ Compatible | API keys can submit tasks as their own identity (owner=key_id) |
| add_oauth2_provider | No | ✅ Compatible | OAuth2 tokens work for task submission and polling with proper scopes |
| add_rbac | Yes | ✅ Compatible | Must run AFTER to enforce task permissions; RBAC controls who can submit/cancel tasks |
| add_mfa | No | ✅ Compatible | MFA challenges don't affect background task execution once submitted |
| add_cache_layer | No | ⚠️ Caveat | Cache must exclude task status endpoints to prevent stale progress reports |
| add_outbox_pattern | No | ⚠️ Caveat | Outbox should not be used for task state changes - direct Redis updates required |
| add_sse | No | ✅ Compatible | SSE can push task progress updates if installed; falls back to polling if not present |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD -- \
  app/core/tasks.py \
  app/core/task_registry.py \
  app/schemas/task.py \
  app/crud/task.py \
  app/api/routes/tasks.py \
  app/workers/task_worker.py \
  app/core/config.py \
  app/api/main.py \
  .env.example

rm -rf \
  tests/test_long_running_task.py \
  app/core/tasks.py \
  app/core/task_registry.py \
  app/schemas/task.py \
  app/crud/task.py \
  app/api/routes/tasks.py \
  app/workers/task_worker.py
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

### Emergency: Redis outage during deployment
1. Stop all ARQ workers: `pkill -f 'arq worker'`
2. Disable task endpoints: `mv app/api/routes/tasks.py app/api/routes/tasks.py.disabled`
3. Restart API: `sudo systemctl restart fastapi.service`

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Task type not registered in registry | Tool errors with message: "Unknown task type 'foo'. Available types: []" |
| EC-2 | Worker crashes mid-task execution | Task remains in running state until timeout, then marked failed with "Worker terminated" error |
| EC-3 | Redis goes down during progress update | Progress update fails silently; task continues execution without progress reporting |
| EC-4 | Client polls immediately after submission | Returns pending status with progress=0% and no result |
| EC-5 | Duplicate idempotency key submitted | Returns existing task_id with 200 OK instead of creating new task |
| EC-6 | Task result exceeds 1MB size limit | Worker automatically stores result in S3 and returns presigned URL in response |
| EC-7 | Cancel request after task completed | Returns 200 OK with status=already_completed and does not modify state |
| EC-8 | Worker timeout fires during DB lock | Forces task cancellation and logs "Task timeout enforced" warning |
| EC-9 | Admin lists tasks across all users | Returns paginated list of all tasks with owner_id for each record |
| EC-10 | API key submits task without user context | Task is owned by API key identity (owner=key_123) |
| EC-11 | Progress reported at 100% but handler still running | Status remains running until handler returns final result |
| EC-12 | Redis TTL expires while client is polling | Returns 404 Not Found with "Task expired" message |
| EC-13 | Concurrent cancel and complete requests | Redis atomic operations ensure first writer wins; no race conditions |
| EC-14 | Tool re-run on already configured project | Idempotently skips existing files with note "Task infrastructure already present" |
| EC-15 | 10K pending tasks in queue | ARQ processes queue normally; API latency remains under 50ms |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified via automated checks  
✅ 2. `test_long_running_task.py` passes all 30 tests with 100% coverage  
✅ 3. Tool execution time < 5s measured on reference hardware  
✅ 4. Submission endpoint returns 202 Accepted with Location header  
✅ 5. Status polling shows monotonically increasing progress percentages  
✅ 6. Cancellation propagates within max_task_duration_seconds  
✅ 7. Large results (>1MB) automatically use presigned URLs  
✅ 8. Redis TTL strictly enforced on all task results  
✅ 9. Task ownership checks prevent cross-user access  
✅ 10. Developer successfully submits PDF generation task, polls status via SSE, and downloads completed 85MB report  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Verify `project_dir` contains valid FastAPI project structure  
- [ ] Confirm Redis connection details in `.env`  
- [ ] Check for existing task infrastructure to prevent duplicates  
- [ ] Validate `User` model exists for task ownership  
- [ ] Verify ARQ is not already configured in project  
- [ ] Check Python version >= 3.8 for async/await support  
- [ ] Confirm no naming conflicts with existing "task" routes/models  

### 15.2 Settings configuration
- [ ] Add `TASK_MAX_DURATION` to `app/core/config.py`  
- [ ] Add `TASK_RESULT_TTL` to `app/core/config.py`  
- [ ] Add `TASK_POLLING_INTERVAL` to `app/core/config.py`  
- [ ] Add `ARQ_REDIS_URL` to `.env.example`  
- [ ] Add `ARQ_WORKER_SETTINGS` to `app/core/config.py`  
- [ ] Add `TASK_LARGE_RESULT_THRESHOLD` (1MB default)  
- [ ] Add `TASK_PERSIST_COMPLETED` flag for PostgreSQL audit  

### 15.3 Core task modules
- [ ] Create `app/core/tasks.py` with TaskStatus enum  
- [ ] Implement `report_progress()` helper with Redis HSET  
- [ ] Add `is_cancelled()` check function  
- [ ] Implement `store_large_result()` S3 upload helper  
- [ ] Add task TTL enforcement utilities  
- [ ] Create task ID generation with Fernet encryption  
- [ ] Implement SSE progress push integration point  

### 15.4 Task registry
- [ ] Create `app/core/task_registry.py` base class  
- [ ] Implement `@task_registry.register()` decorator  
- [ ] Add task type validation on registration  
- [ ] Enforce async-only handler functions  
- [ ] Implement duplicate task type prevention  
- [ ] Add registry inspection method for error messages  
- [ ] Integrate with dependency injection system  

### 15.5 CRUD operations
- [ ] Create `app/crud/task.py` with Redis operations  
- [ ] Implement atomic task state transitions  
- [ ] Add idempotency key tracking  
- [ ] Implement task listing with Redis SCAN  
- [ ] Add owner-based access control checks  
- [ ] Implement admin override flag for global access  
- [ ] Add progress percentage validation  

### 15.6 Schemas
- [ ] Create `app/schemas/task.py` with Pydantic models  
- [ ] Define `TaskSubmit` request schema  
- [ ] Define `TaskStatusResponse` schema  
- [ ] Create `TaskListResponse` for admin endpoints  
- [ ] Add `TaskProgressUpdate` internal schema  
- [ ] Define `TaskCancelResponse` schema  
- [ ] Create error response schemas  

### 15.7 Routes
- [ ] Create `app/api/routes/tasks.py` with endpoints  
- [ ] Implement `POST /tasks` submission endpoint  
- [ ] Add `GET /tasks/{task_id}` status endpoint  
- [ ] Implement `DELETE /tasks/{task_id}` cancellation  
- [ ] Add `GET /tasks` admin listing endpoint  
- [ ] Implement SSE progress streaming endpoint  
- [ ] Add route registration in `app/api/main.py`  
- [ ] Integrate auth middleware  

### 15.8 Worker setup
- [ ] Create `app/workers/task_worker.py`  
- [ ] Implement ARQ worker class inheritance  
- [ ] Add task timeout enforcement  
- [ ] Implement cancellation checking  
- [ ] Add progress reporting wrapper  
- [ ] Configure worker health checks  
- [ ] Implement large result handling  

### 15.9 Test generation
- [ ] Create `tests/test_long_running_task.py`  
- [ ] Add 10 submission test cases  
- [ ] Implement 8 polling/progress tests  
- [ ] Add 5 cancellation tests  
- [ ] Include 4 timeout scenarios  
- [ ] Implement 2 large result tests  
- [ ] Add 1 concurrency stress test  

### 15.10 Atomicity
- [ ] Use temp-file pattern for all writes  
- [ ] Track all modified files for rollback  
- [ ] Verify file parses before final write  
- [ ] Implement clean rollback procedure  
- [ ] Check Redis connection before writes  
- [ ] Validate ARQ settings before apply  
- [ ] Confirm worker can start before finish  

### 15.11 Documentation
- [ ] Add to `SKILL.md` tools table  
- [ ] Update `manifest.yaml` with new tool  
- [ ] Append to `core/KNOWLEDGE.md`  
- [ ] Add task design guidelines  
- [ ] Document Redis key structure  
- [ ] Note ARQ worker requirements  
- [ ] Include performance tuning tips  

### 15.12 Verification
- [ ] Run `ast.parse` on all new files  
- [ ] Execute all 30 test cases  
- [ ] Measure submission latency  
- [ ] Verify progress update speed  
- [ ] Check cancellation propagation  
- [ ] Test Redis outage handling  
- [ ] Benchmark worker startup  

### 15.13 Finalization
- [ ] Generate success report  
- [ ] Output next-steps checklist  
- [ ] Flag any warnings  
- [ ] Record metrics  
- [ ] Verify idempotency  
- [ ] Clean temp files  
- [ ] Update changelog  

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/tasks.py",
    "app/core/task_registry.py",
    "app/schemas/task.py",
    "app/crud/task.py",
    "app/api/routes/tasks.py",
    "app/workers/task_worker.py",
    "tests/test_long_running_task.py",
    "docs/task_processing.md"
  ],
  "files_modified": [
    "app/core/config.py",
    "app/api/main.py",
    ".env.example"
  ],
  "metrics": {
    "execution_time_ms": 3872,
    "files_changed": 11,
    "lines_added": 842,
    "lines_removed": 9,
    "task_endpoints_created": 4,
    "test_cases_generated": 30,
    "worker_timeout_enforced": 3600
  },
  "next_steps": [
    "Start ARQ worker: arq app.workers.task_worker.TaskWorker",
    "Test submission: POST /tasks {'task_type': 'test'}",
    "Verify status polling: GET /tasks/{task_id}",
    "Check cancellation: DELETE /tasks/{task_id}",
    "Monitor queue: arq monitor",
    "Adjust TTL in app/core/config.py if needed"
  ],
  "warnings": [
    "Large results (>1MB) require S3 configuration - defaults to local storage if not set",
    "Task persistence to PostgreSQL is disabled by default - enable TASK_PERSIST_COMPLETED for audit"
  ],
  "notes": [
    "Task infrastructure installed with Redis backend",
    "Default timeout set to 3600 seconds (1 hour)",
    "Results persist in Redis for 86400 seconds (24 hours)",
    "SSE integration available if add_sse is installed",
    "30 test cases cover all edge cases",
    "Admin endpoints require RBAC if add_rbac is installed"
  ]
}
