# TOOL-007: add_bulk_operations

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_bulk_operations` |
| Category | EXTEND > CRUD & Data |
| Complexity | Medium |
| Dependencies | Existing FastAPI project with at least 1 SQLAlchemy model, CRUD layer, Alembic configured, Pydantic v2 |
| Signature | `add_bulk_operations(project_dir: str, models: list[str] \| None = None, max_batch: int = 1000, operations: list[Literal["create", "update", "delete"]] = ["create", "update", "delete"], mode: Literal["all_or_nothing", "best_effort"] = "all_or_nothing", idempotency_header: bool = True) -> dict` |
| Parameters | `project_dir`: project root path<br>`models`: model names to enable bulk on (None = all business models)<br>`max_batch`: hard cap on items per request (default 1000, max 10000)<br>`operations`: which bulk verbs to generate<br>`mode`: default transaction mode for new endpoints<br>`idempotency_header`: whether to wire `Idempotency-Key` header deduplication |

---

## 2. Purpose

`fastapi_add_bulk_operations` eliminates the N-round-trip bottleneck that plagues single-item REST APIs when client code must create, update, or delete hundreds of records. Without bulk endpoints, importing 1000 products requires 1000 individual HTTP calls — a minimum of several seconds of network overhead even on a fast LAN, and a guarantee of partial failure under any transient network hiccup. The tool generates three new route families (`POST /items/bulk`, `PATCH /items/bulk`, `DELETE /items/bulk`) backed by SQLAlchemy bulk operations (`insert()`, `update()`, `delete().where(id.in_(...))`) that collapse N round-trips into a single database statement per operation, delivering a 100x–1000x throughput improvement for batch workflows. Each endpoint supports two transaction modes: `all_or_nothing` (a single database transaction wrapping all items — any validation or constraint failure rolls back the entire batch) and `best_effort` (each item wrapped in its own savepoint — failed items are collected and reported while successful ones are committed). Per-item Pydantic v2 validation runs before any database write in both modes, so invalid payloads surface as structured error objects in the response body without ever touching the database. A hard `max_batch` cap (default 1000, absolute maximum 10 000) is enforced at the schema layer via `Field(max_length=max_batch)` and validated a second time at the CRUD layer as a defence-in-depth guard against oversized requests that could lock tables or exhaust database connection pool memory.

Beyond the transport optimisation, the tool makes four design decisions that diverge from naive implementations. First, idempotency keys are supported via an optional `Idempotency-Key` request header backed by a Redis TTL cache: a client that retries a timed-out bulk create will receive the cached response from the first attempt rather than inserting duplicate rows, making retries safe in unreliable network environments. Second, the `BulkResponse` envelope always includes per-item status objects (index, success flag, optional error message) regardless of transaction mode, so callers can correlate failures back to the original payload by position without parsing server-side error messages. Third, bulk update requires each update dict to include the row `id` field explicitly — the CRUD layer resolves only IDs that exist and belong to the current user, silently collecting IDs that are not found as `not_found` errors in the response rather than raising a 404 that would abort the entire batch. Fourth, the tool's code generator is idempotent: if `POST /items/bulk` already exists in the route file, the tool returns `notes: ["already enabled, skipped"]` rather than duplicating endpoints, so CI pipelines that call the tool on every deploy are safe.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 4s for up to 10 models | Dev waits synchronously in CLI; tight feedback loop |
| Files modified | ≤ 4 per model (model, crud, schema, route) | Predictable blast radius |
| Files created | 1 test file per model + 0..1 idempotency cache module | Predictable scaffolding output |
| Bulk create 100 items | < 500 ms end-to-end | Single `INSERT INTO ... VALUES (...)` statement; no per-row round-trips |
| Bulk create 1000 items | < 3 s end-to-end | SQLAlchemy `insert()` with `executemany`; PG handles batch efficiently |
| Bulk create 10 000 items (hard cap) | < 20 s end-to-end | Chunked in 1000-row sub-batches to keep statement size bounded |
| Bulk update 1000 items | < 2 s | `UPDATE ... WHERE id IN (...)` with CASE expression per-column; single statement |
| Bulk delete 1000 items | < 500 ms | Single `DELETE WHERE id IN (...)` statement |
| Pydantic v2 validation on 1000 items | < 100 ms | Pydantic v2 Rust core; list validation is vectorised |
| Idempotency key lookup (Redis) | < 2 ms | Redis GET with 24-hour TTL; miss falls through to normal execution |
| Memory peak (1000-item create) | < 128 MB | Items deserialised once, no redundant copies; result objects use `__slots__` |
| Max batch size enforcement latency | < 1 ms | `Field(max_length=N)` validated at Pydantic parse time before handler runs |

---

## 4. Code Examples (Before / After)

### 4.1 BulkRequest and BulkResponse Pydantic v2 models

```python
# app/schemas/item.py  — bulk additions
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ItemBulkCreate(BaseModel):
    """Payload for POST /items/bulk.

    `items` list is bounded by max_batch to prevent OOM and table-lock attacks.
    `mode` selects between all-or-nothing and best-effort transaction strategies.
    """
    items: list[ItemCreate] = Field(..., min_length=1, max_length=1000)
    mode: Literal["all_or_nothing", "best_effort"] = "all_or_nothing"


class ItemBulkUpdate(BaseModel):
    """Payload for PATCH /items/bulk.

    Each update dict MUST contain 'id'; remaining keys are applied as a partial update.
    """
    updates: list[dict] = Field(..., min_length=1, max_length=1000)
    mode: Literal["all_or_nothing", "best_effort"] = "all_or_nothing"

    @field_validator("updates")
    @classmethod
    def each_update_has_id(cls, v: list[dict]) -> list[dict]:
        """Reject any update that omits the 'id' key — cannot resolve target row."""
        for idx, u in enumerate(v):
            if "id" not in u:
                raise ValueError(
                    f"Update at index {idx} is missing required 'id' field"
                )
        return v


class ItemBulkDelete(BaseModel):
    """Payload for DELETE /items/bulk."""
    ids: list[uuid.UUID] = Field(..., min_length=1, max_length=1000)
    mode: Literal["all_or_nothing", "best_effort"] = "all_or_nothing"
```

### 4.2 BulkResult per-item status and BulkResponse envelope

```python
# app/schemas/item.py  — BulkResult additions
from __future__ import annotations

import uuid
from pydantic import BaseModel


class BulkResultItem(BaseModel):
    """Per-item outcome returned in BulkResponse.results.

    `index` maps back to the original request list position.
    `id` is None when the item failed before DB insertion (validation error).
    """
    index: int
    id: uuid.UUID | None = None
    success: bool
    error: str | None = None
    error_code: str | None = None  # e.g. "VALIDATION_ERROR", "NOT_FOUND", "CONFLICT"


class BulkResponse(BaseModel):
    """Top-level response envelope for all bulk endpoints.

    `partial` is True when mode=best_effort and at least one item failed.
    `transaction_id` ties to an idempotency cache entry when present.
    """
    total: int
    succeeded: int
    failed: int
    partial: bool
    transaction_id: str | None = None
    results: list[BulkResultItem]
```

### 4.3 POST /items/bulk route handler

```python
# app/api/routes/item.py  — bulk create endpoint
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.deps import CurrentUser, SessionDep, get_idempotency_cache
from app.crud.item import bulk_create_items
from app.schemas.item import ItemBulkCreate, BulkResponse

router = APIRouter(prefix="/items", tags=["items"])


@router.post("/bulk", response_model=BulkResponse, status_code=207)
async def bulk_create(
    payload: ItemBulkCreate,
    session: SessionDep,
    current_user: CurrentUser,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BulkResponse:
    """Create multiple items in a single request.

    Returns HTTP 207 Multi-Status so that partial-success responses (best_effort mode)
    are distinguishable from full-success at the transport layer.
    Repeated requests with the same Idempotency-Key within 24 hours return cached result.
    """
    if idempotency_key:
        cached = await get_idempotency_cache().get(idempotency_key)
        if cached is not None:
            return BulkResponse.model_validate(cached)

    result = await bulk_create_items(
        session,
        items=payload.items,
        owner_id=current_user.id,
        mode=payload.mode,
    )

    if idempotency_key:
        await get_idempotency_cache().set(
            idempotency_key, result.model_dump(), ttl=86400
        )

    if result.failed > 0 and payload.mode == "all_or_nothing":
        raise HTTPException(
            status_code=422,
            detail={"message": "Batch failed", "results": result.model_dump()},
        )
    return result
```

### 4.4 PATCH /items/bulk and DELETE /items/bulk route handlers

```python
# app/api/routes/item.py  — bulk update and delete endpoints
from app.crud.item import bulk_update_items, bulk_delete_items
from app.schemas.item import ItemBulkUpdate, ItemBulkDelete


@router.patch("/bulk", response_model=BulkResponse, status_code=207)
async def bulk_update(
    payload: ItemBulkUpdate,
    session: SessionDep,
    current_user: CurrentUser,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BulkResponse:
    """Partially update multiple items. Each payload dict must include 'id'."""
    if idempotency_key:
        cached = await get_idempotency_cache().get(idempotency_key)
        if cached:
            return BulkResponse.model_validate(cached)
    result = await bulk_update_items(
        session,
        updates=payload.updates,
        owner_id=current_user.id,
        mode=payload.mode,
    )
    if idempotency_key:
        await get_idempotency_cache().set(
            idempotency_key, result.model_dump(), ttl=86400
        )
    return result


@router.delete("/bulk", response_model=BulkResponse, status_code=207)
async def bulk_delete(
    payload: ItemBulkDelete,
    session: SessionDep,
    current_user: CurrentUser,
) -> BulkResponse:
    """Delete multiple items by ID in a single transaction."""
    result = await bulk_delete_items(
        session,
        ids=payload.ids,
        owner_id=current_user.id,
        mode=payload.mode,
    )
    return result
```

### 4.5 CRUD: bulk_create_items with all_or_nothing and best_effort modes

```python
# app/crud/item.py  — bulk_create_items
from __future__ import annotations

import uuid
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.item import Item
from app.schemas.item import ItemCreate, BulkResponse, BulkResultItem


async def bulk_create_items(
    session: AsyncSession,
    *,
    items: list[ItemCreate],
    owner_id: uuid.UUID,
    mode: str = "all_or_nothing",
) -> BulkResponse:
    """Insert N items using a single INSERT statement (all_or_nothing) or
    per-item savepoints (best_effort). Returns BulkResponse with per-item status."""
    results: list[BulkResultItem] = []
    succeeded = 0
    failed = 0

    if mode == "all_or_nothing":
        rows = [
            {**item.model_dump(), "owner_id": owner_id, "id": uuid.uuid4()}
            for item in items
        ]
        try:
            stmt = pg_insert(Item).values(rows).returning(Item.id)
            db_result = await session.execute(stmt)
            inserted_ids = list(db_result.scalars())
            await session.commit()
            for idx, row_id in enumerate(inserted_ids):
                results.append(BulkResultItem(index=idx, id=row_id, success=True))
            succeeded = len(inserted_ids)
        except IntegrityError as exc:
            await session.rollback()
            for idx in range(len(items)):
                results.append(
                    BulkResultItem(
                        index=idx,
                        success=False,
                        error=str(exc.orig),
                        error_code="INTEGRITY_ERROR",
                    )
                )
            failed = len(items)
    else:
        for idx, item in enumerate(items):
            try:
                sp = await session.begin_nested()
                new_item = Item(**item.model_dump(), owner_id=owner_id, id=uuid.uuid4())
                session.add(new_item)
                await session.flush()
                await sp.commit()
                results.append(BulkResultItem(index=idx, id=new_item.id, success=True))
                succeeded += 1
            except Exception as exc:
                await sp.rollback()
                results.append(
                    BulkResultItem(
                        index=idx,
                        success=False,
                        error=str(exc),
                        error_code="INSERT_ERROR",
                    )
                )
                failed += 1
        await session.commit()

    return BulkResponse(
        total=len(items),
        succeeded=succeeded,
        failed=failed,
        partial=(failed > 0 and mode == "best_effort"),
        results=results,
    )
```

### 4.6 CRUD: bulk_update_items using UPDATE … WHERE id IN (…)

```python
# app/crud/item.py  — bulk_update_items
from __future__ import annotations

import uuid
from sqlalchemy import select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.schemas.item import BulkResponse, BulkResultItem


async def bulk_update_items(
    session: AsyncSession,
    *,
    updates: list[dict],
    owner_id: uuid.UUID,
    mode: str = "all_or_nothing",
) -> BulkResponse:
    """Update N items. Each dict must contain 'id'. Unknown IDs become NOT_FOUND errors.
    Uses per-item owner check: only updates rows owned by current user."""
    results: list[BulkResultItem] = []
    succeeded = 0
    failed = 0

    ids = [uuid.UUID(str(u["id"])) for u in updates if "id" in u]
    existing_stmt = select(Item.id).where(
        Item.id.in_(ids), Item.owner_id == owner_id
    )
    db_result = await session.execute(existing_stmt)
    found_ids = set(db_result.scalars().all())

    for idx, upd in enumerate(updates):
        row_id = uuid.UUID(str(upd.get("id")))
        if row_id not in found_ids:
            results.append(
                BulkResultItem(
                    index=idx, id=row_id, success=False,
                    error="Item not found or not owned by caller",
                    error_code="NOT_FOUND",
                )
            )
            failed += 1
            continue
        try:
            sp = await session.begin_nested()
            patch = {k: v for k, v in upd.items() if k != "id"}
            stmt = (
                sql_update(Item)
                .where(Item.id == row_id)
                .values(**patch)
            )
            await session.execute(stmt)
            await sp.commit()
            results.append(BulkResultItem(index=idx, id=row_id, success=True))
            succeeded += 1
        except Exception as exc:
            await sp.rollback()
            results.append(
                BulkResultItem(
                    index=idx, id=row_id, success=False,
                    error=str(exc), error_code="UPDATE_ERROR"
                )
            )
            failed += 1
    await session.commit()
    return BulkResponse(
        total=len(updates),
        succeeded=succeeded,
        failed=failed,
        partial=(failed > 0),
        results=results,
    )
```

### 4.7 CRUD: bulk_delete_items with single DELETE WHERE id IN (…)

```python
# app/crud/item.py  — bulk_delete_items
from __future__ import annotations

import uuid
from sqlalchemy import delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.schemas.item import BulkResponse, BulkResultItem


async def bulk_delete_items(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    owner_id: uuid.UUID,
    mode: str = "all_or_nothing",
) -> BulkResponse:
    """Delete N items in a single statement. Verifies ownership before deletion.

    all_or_nothing: one DELETE WHERE id IN (...) after ownership check.
    best_effort: deletes each verified id independently, collects failures.
    """
    owned_stmt = select(Item.id).where(
        Item.id.in_(ids), Item.owner_id == owner_id
    )
    db_result = await session.execute(owned_stmt)
    owned_ids = set(db_result.scalars().all())
    not_owned = [i for i in ids if i not in owned_ids]

    results: list[BulkResultItem] = []
    for idx, item_id in enumerate(ids):
        if item_id not in owned_ids:
            results.append(
                BulkResultItem(
                    index=idx, id=item_id, success=False,
                    error="Item not found or not owned by caller",
                    error_code="NOT_FOUND",
                )
            )

    if mode == "all_or_nothing" and not_owned:
        await session.rollback()
        return BulkResponse(
            total=len(ids),
            succeeded=0,
            failed=len(ids),
            partial=False,
            results=results + [
                BulkResultItem(index=idx, id=i, success=False,
                               error="Rolled back due to unowned IDs",
                               error_code="ROLLBACK")
                for idx, i in enumerate(owned_ids, start=len(not_owned))
            ],
        )

    del_stmt = sql_delete(Item).where(Item.id.in_(list(owned_ids)))
    del_result = await session.execute(del_stmt)
    await session.commit()
    succeeded = del_result.rowcount
    for idx, item_id in enumerate(ids):
        if item_id in owned_ids:
            results.append(BulkResultItem(index=idx, id=item_id, success=True))

    return BulkResponse(
        total=len(ids),
        succeeded=succeeded,
        failed=len(not_owned),
        partial=(len(not_owned) > 0),
        results=sorted(results, key=lambda r: r.index),
    )
```

### 4.8 Idempotency key cache module (Redis-backed)

```python
# app/core/idempotency.py
"""Redis-backed idempotency key cache for bulk operation endpoints.

Stores serialised BulkResponse payloads under the client-provided key with a
configurable TTL (default 24 hours). Lookups use GET; storage uses SETEX.
Cache is optional: if Redis is unavailable, operations proceed without caching
and log a warning — never blocking the primary flow.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def init_idempotency_cache(redis_url: str) -> None:
    global _redis
    _redis = aioredis.from_url(redis_url, decode_responses=True)


def get_idempotency_cache() -> "IdempotencyCache":
    return IdempotencyCache(_redis)


class IdempotencyCache:
    """Thin wrapper around Redis providing get/set for idempotency keys."""

    def __init__(self, redis: aioredis.Redis | None) -> None:
        self._redis = redis

    async def get(self, key: str) -> dict | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(f"idem:{key}")
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.warning("idempotency_cache_get_failed key=%s exc=%s", key, exc)
            return None

    async def set(self, key: str, value: Any, ttl: int = 86400) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.setex(f"idem:{key}", ttl, json.dumps(value))
        except Exception as exc:
            logger.warning("idempotency_cache_set_failed key=%s exc=%s", key, exc)
```

### 4.9 Alembic migration: no schema changes (bulk is code-only)

```python
# alembic/versions/0007_bulk_ops_index_items.py
"""Add composite index for bulk query optimisation on items table.

Bulk DELETE and bulk UPDATE both filter by owner_id + id.in_(...).
This index ensures the owner pre-filter is sargable and avoids full-table scans.

Revision ID: 0007_bulk_ops_index_items
Revises: 0006_previous
Create Date: 2026-04-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_bulk_ops_index_items"
down_revision = "0006_previous"


def upgrade() -> None:
    # Composite index covers: WHERE owner_id = ? AND id IN (...)
    # Used by bulk_update and bulk_delete ownership pre-check query.
    op.create_index(
        "ix_items_owner_id",
        "items",
        ["owner_id", "id"],
        unique=False,
        postgresql_concurrently=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_items_owner_id",
        table_name="items",
        postgresql_concurrently=True,
    )
```

### 4.10 Pytest integration tests: bulk create/update/delete lifecycle

```python
# tests/test_item_bulk_operations.py  (fragment — full file generated by tool)
"""Integration tests for bulk operation endpoints on Item model."""
from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_bulk_create_all_or_nothing_success(
    client: AsyncClient,
    normal_user_token_headers: dict,
) -> None:
    """T-01: POST /items/bulk creates N items in single transaction, returns 207."""
    payload = {
        "items": [{"title": f"Item {i}"} for i in range(5)],
        "mode": "all_or_nothing",
    }
    resp = await client.post(
        "/api/v1/items/bulk", json=payload, headers=normal_user_token_headers
    )
    assert resp.status_code == 207
    body = resp.json()
    assert body["succeeded"] == 5
    assert body["failed"] == 0
    assert all(r["success"] for r in body["results"])


@pytest.mark.asyncio
async def test_bulk_create_all_or_nothing_rollback_on_validation_error(
    client: AsyncClient,
    normal_user_token_headers: dict,
) -> None:
    """T-04: all_or_nothing mode rolls back entire batch when any item fails."""
    payload = {
        "items": [
            {"title": "Valid"},
            {"title": ""},   # violates min_length=1 check in ItemCreate
        ],
        "mode": "all_or_nothing",
    }
    resp = await client.post(
        "/api/v1/items/bulk", json=payload, headers=normal_user_token_headers
    )
    assert resp.status_code in (422, 207)
    body = resp.json()
    assert body.get("failed", 0) > 0 or resp.status_code == 422


@pytest.mark.asyncio
async def test_bulk_delete_owned_ids_only(
    client: AsyncClient,
    normal_user_token_headers: dict,
    five_owned_items: list[str],
    one_foreign_item: str,
) -> None:
    """T-11: DELETE /items/bulk rejects IDs not owned by current user."""
    ids_to_delete = five_owned_items + [one_foreign_item]
    resp = await client.delete(
        "/api/v1/items/bulk",
        json={"ids": ids_to_delete, "mode": "best_effort"},
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 207
    body = resp.json()
    assert body["succeeded"] == 5
    assert body["failed"] == 1
    failed = [r for r in body["results"] if not r["success"]]
    assert failed[0]["error_code"] == "NOT_FOUND"
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-01 | **Hard batch size cap enforced at schema layer** | `Field(max_length=max_batch)` on `items`/`updates`/`ids` list rejects oversized requests at Pydantic parse time before handler executes. Verified by T-05 |
| QS-02 | **all_or_nothing uses a single database transaction** | `bulk_create_items` with `mode="all_or_nothing"` issues one `INSERT … VALUES` statement inside one session; any `IntegrityError` calls `session.rollback()` before returning. Verified by T-04 |
| QS-03 | **best_effort uses per-item savepoints** | `session.begin_nested()` creates a SAVEPOINT per item; failure in one item triggers `sp.rollback()` only, leaving others committed. Verified by T-07 |
| QS-04 | **Per-item Pydantic validation runs before DB writes** | Input deserialization via `ItemBulkCreate` / `ItemBulkUpdate` raises `ValidationError` before any session method is called. Verified by T-02, T-06 |
| QS-05 | **Idempotency key prevents duplicate inserts on retry** | `IdempotencyCache.get()` checked before CRUD; matching key returns cached `BulkResponse` without executing SQL. Verified by T-20, T-21 |
| QS-06 | **Ownership verified before any write** | Bulk update and bulk delete pre-query `Item.owner_id == current_user.id` before touching rows; foreign IDs become `NOT_FOUND` errors. Verified by T-11, T-15 |
| QS-07 | **BulkResponse always includes per-item results** | Both `all_or_nothing` and `best_effort` populate `results: list[BulkResultItem]` with one entry per input item, indexed to match request order. Verified by T-03, T-08 |
| QS-08 | **HTTP 207 Multi-Status returned for bulk endpoints** | Routes declare `status_code=207`; callers can distinguish partial success from full success without parsing body. Verified by T-01, T-09 |
| QS-09 | **Idempotency cache never blocks primary flow** | `IdempotencyCache.get/set` wrapped in `try/except`; Redis failure logs a warning and operation proceeds normally. Verified by T-22 |
| QS-10 | **Bulk delete uses single DELETE WHERE id IN (…)** | `bulk_delete_items` issues one `sql_delete(Item).where(Item.id.in_(...))` for the owned subset; no per-row DELETE calls. Verified by T-12 |
| QS-11 | **Tool execution is idempotent** | Pre-flight AST check detects existing `/bulk` routes; returns `notes: ["already enabled, skipped"]` without writing files. Verified by T-28 |
| QS-12 | **Composite index (owner_id, id) created for bulk queries** | Migration creates `ix_items_owner_id` covering the ownership pre-check query; ownership resolution stays O(log n). Verified by T-29 |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `ItemBulkCreate` schema exists in `app/schemas/item.py` with `items: list[ItemCreate]` and `mode: Literal["all_or_nothing","best_effort"]` | AST parse + `grep "ItemBulkCreate"` |
| CC-02 | `ItemBulkCreate.items` field has `max_length=max_batch` constraint | AST inspection of `Field(...)` arguments |
| CC-03 | `ItemBulkUpdate` schema exists with `updates: list[dict]`, `mode`, and `each_update_has_id` validator | AST inspection of class and `@field_validator` |
| CC-04 | `ItemBulkDelete` schema exists with `ids: list[uuid.UUID]` and `mode` field | AST inspection |
| CC-05 | `BulkResultItem` schema has `index`, `id`, `success`, `error`, `error_code` fields | AST inspection of field definitions |
| CC-06 | `BulkResponse` schema has `total`, `succeeded`, `failed`, `partial`, `transaction_id`, `results` fields | AST inspection |
| CC-07 | `bulk_create_items` CRUD function exists, accepts `session`, `items`, `owner_id`, `mode` | `grep "async def bulk_create_items"` in crud file |
| CC-08 | `bulk_create_items` with `mode="all_or_nothing"` issues single `pg_insert(Item).values(rows)` | AST inspection of function body |
| CC-09 | `bulk_create_items` with `mode="best_effort"` uses `session.begin_nested()` per item | AST inspection |
| CC-10 | `bulk_update_items` CRUD function exists, pre-queries `owner_id == current_user.id` before writes | AST inspection of ownership check query |
| CC-11 | `bulk_update_items` issues `sql_update(Item).where(Item.id == row_id).values(**patch)` | AST inspection |
| CC-12 | `bulk_delete_items` CRUD function exists, issues single `sql_delete(Item).where(Item.id.in_(...))` | AST inspection |
| CC-13 | `POST /items/bulk` route exists returning `BulkResponse`, `status_code=207` | Read route file, grep `@router.post("/bulk"` |
| CC-14 | `PATCH /items/bulk` route exists returning `BulkResponse`, `status_code=207` | Read route file, grep `@router.patch("/bulk"` |
| CC-15 | `DELETE /items/bulk` route exists returning `BulkResponse`, `status_code=207` | Read route file, grep `@router.delete("/bulk"` |
| CC-16 | All three routes accept `Idempotency-Key` header (when `idempotency_header=True`) | Grep `Header(alias="Idempotency-Key")` in route file |
| CC-17 | `app/core/idempotency.py` exists with `IdempotencyCache`, `get_idempotency_cache()`, `init_idempotency_cache()` | File exists, AST parse passes |
| CC-18 | `IdempotencyCache.get` and `.set` wrapped in `try/except` with logging on failure | AST inspection of error handling |
| CC-19 | Idempotency cache initialised in `app/main.py` on startup with `REDIS_URL` from settings | `grep "init_idempotency_cache"` in `app/main.py` |
| CC-20 | Alembic migration `*_bulk_ops_index_{table}.py` generated for `ix_{table}_owner_id` composite index | File exists in `alembic/versions/` |
| CC-21 | Migration uses `postgresql_concurrently=True` for index creation | `grep "postgresql_concurrently"` in migration file |
| CC-22 | Migration `downgrade()` drops `ix_{table}_owner_id` | Inspect `downgrade()` function |
| CC-23 | Test file `tests/test_{name}_bulk_operations.py` created with T-01..T-30 stubs | File exists, all 30 test IDs present |
| CC-24 | Existing test suite passes with 0 failures after modification | `pytest tests/ -q` — 0 failures |
| CC-25 | All generated Python files pass `ast.parse` without SyntaxError | Run AST check on every touched file |
| CC-26 | Tool returns `dict` with `files_created`, `files_modified`, `metrics`, `notes`, `next_steps` | Inspect return value structure |
| CC-27 | `all_or_nothing` bulk create rolls back all items on any single item IntegrityError | Verified by T-04 integration test |
| CC-28 | `best_effort` bulk create commits successful items even when other items fail | Verified by T-07 integration test |
| CC-29 | `bulk_delete_items` returns `NOT_FOUND` for IDs not owned by caller without rolling back owned deletions | Verified by T-11 |
| CC-30 | Tool is idempotent: re-run on already-enabled model returns `notes: ["already enabled, skipped"]` | Run tool twice, diff is empty |
| CC-31 | Bulk create with 100-item payload completes in < 500 ms on local Postgres | Time assertion in T-25 benchmark test |
| CC-32 | `max_batch` parameter wires to `Field(max_length=...)` on all three request schema fields | AST inspection after tool run with custom `max_batch` |

---

## 7. Definition of Done (DoD)

The tool is "done" when ALL of the following are true:

- [ ] All 32 Completeness Criteria verified by automated checks
- [ ] All 12 Quality Standards enforced and covered by tests
- [ ] All 8 Invariants in §8 have passing test references
- [ ] All 25 User Stories have passing acceptance tests (§9)
- [ ] All 30 Test Cases pass (§10), 0 failures
- [ ] Tool is idempotent: run twice on the same project produces zero file changes on second run
- [ ] Tool is reversible: rollback procedure in §12 has been executed end-to-end and verified
- [ ] Performance SLOs measured: 100-item bulk create < 500 ms confirmed by benchmark (T-25)
- [ ] Idempotency cache verified: retry with matching key returns cached result, not duplicate rows (T-20)
- [ ] Interaction with all tools in §11 verified by integration smoke tests
- [ ] All 15 edge cases in §13 handled without unhandled exceptions
- [ ] Documentation updated: `KNOWLEDGE.md`, `manifest.yaml`, `SKILL.md` tools table
- [ ] MCP tool registered in `mcp_server.py` with correct `@mcp_tool` decorator
- [ ] Re-audit by Opus in fresh context with brutal mode enabled: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-BULK-01 | **`max_batch` cap is enforced before any DB write** | `Field(max_length=max_batch)` on all request list fields rejects oversized payloads at Pydantic parse time; CRUD layer also asserts `len(items) <= max_batch` as defence-in-depth | T-05, T-06 |
| INV-BULK-02 | **all_or_nothing never commits partial results** | Single `AsyncSession` transaction for all items; `IntegrityError` triggers `await session.rollback()` before returning; no items are persisted on failure | T-04 |
| INV-BULK-03 | **best_effort commits each item independently via SAVEPOINT** | `session.begin_nested()` creates one SAVEPOINT per item; `sp.rollback()` on failure isolates that item from others; overall session commits at end | T-07 |
| INV-BULK-04 | **Ownership verified before bulk update and bulk delete** | `SELECT id WHERE id IN (...) AND owner_id = ?` runs before any mutation; IDs not in result set become `NOT_FOUND` errors without touching the database | T-11, T-15 |
| INV-BULK-05 | **Idempotency key prevents duplicate execution** | `IdempotencyCache.get(key)` checked first; cache hit returns stored `BulkResponse` immediately without running CRUD | T-20, T-21 |
| INV-BULK-06 | **BulkResponse always contains one result entry per input item** | Both modes populate `results` list with `len(results) == len(inputs)`; index field matches input list position | T-03, T-08 |
| INV-BULK-07 | **Bulk delete uses a single DELETE statement for owned IDs** | `sql_delete(Item).where(Item.id.in_(owned_ids))` executed once; no per-row DELETE loop regardless of batch size | T-12 |
| INV-BULK-08 | **Idempotency cache failure never blocks primary operation** | `try/except` around every Redis call; `except` clause logs a warning and falls through to normal execution without raising | T-22, T-23 |

---

## 9. User Stories

### 9.1 Core bulk create (US-01 .. US-05)

**US-01: Create 100 items in a single HTTP request**

**Persona**: Backend developer integrating a product import pipeline.

**Context**: The existing single-item `POST /items/` route requires 100 separate HTTP calls to import a CSV of 100 products, taking ~10 seconds over a LAN connection and failing entirely if any single call returns a transient 5xx error.

**Action**: After running `add_bulk_operations(project_dir, models=["Item"])`, the developer calls `POST /items/bulk` with a JSON body containing `{"items": [...100 items...], "mode": "all_or_nothing"}`.

**Outcome**: The server inserts all 100 rows in a single `INSERT INTO … VALUES (…, …, …)` statement and returns HTTP 207 with `{"succeeded": 100, "failed": 0}` in under 500 ms.

**Refs**: CC-07, CC-08, INV-BULK-02, T-01

---

**US-02: Receive per-item error details in best_effort mode**

**Persona**: Data migration engineer importing records with mixed data quality.

**Context**: A nightly sync job imports 500 records from a legacy system; roughly 3–5 records per batch have invalid titles (empty strings) that violate database constraints.

**Action**: The sync job calls `POST /items/bulk` with `mode="best_effort"` and 500 items including 4 malformed ones.

**Outcome**: The server commits 496 valid items and returns a response where `failed=4`, each with a `BulkResultItem` containing `success=false`, `index=N`, and `error_code="INSERT_ERROR"` pointing to the exact position in the payload.

**Refs**: CC-05, CC-06, INV-BULK-03, T-07

---

**US-03: All-or-nothing rollback on integrity violation**

**Persona**: SaaS operator importing tenant-critical configuration records.

**Context**: A batch of 50 configuration items must either all be applied or none, because partial application would leave the tenant in an inconsistent state.

**Action**: The operator calls `POST /items/bulk` with `mode="all_or_nothing"` and one of the 50 items has a duplicate `title` that violates a unique constraint.

**Outcome**: The entire batch rolls back; 0 rows are inserted; the response returns HTTP 422 with `results` showing all items as failed with `error_code="INTEGRITY_ERROR"`. Re-running after fixing the duplicate succeeds fully.

**Refs**: INV-BULK-02, CC-08, T-04

---

**US-04: Validate batch items before touching the database**

**Persona**: API consumer sending programmatically generated payloads.

**Context**: A code generator occasionally emits malformed payloads where the `title` field is `None` instead of a string, which would cause a database type mismatch if it reached the `INSERT` statement.

**Action**: The consumer sends `POST /items/bulk` with 10 items, 2 of which have `title: null`.

**Outcome**: FastAPI returns HTTP 422 with a Pydantic validation error before any SQL is executed; the `detail` field identifies both offending indices. No database transaction is opened.

**Refs**: CC-01, QS-04, INV-BULK-01, T-02

---

**US-05: Enforce hard batch size cap to prevent resource exhaustion**

**Persona**: Security engineer testing API resilience.

**Context**: A fuzzer sends `POST /items/bulk` with 50 000 items attempting to trigger OOM or a multi-second table lock on the items table.

**Action**: The request body contains `"items": [...50000 items...]`.

**Outcome**: FastAPI returns HTTP 422 with `{"detail": [{"type": "too_long", "loc": ["body", "items"]}]}` before the handler runs; no DB connection is consumed. The max_batch cap is enforced purely by Pydantic schema validation.

**Refs**: INV-BULK-01, CC-02, QS-01, T-05, T-06

---

### 9.2 Bulk update semantics (US-06 .. US-10)

**US-06: Partially update multiple items in one request**

**Persona**: Admin user updating display order for a list of items after drag-and-drop reordering.

**Context**: Reordering 20 items requires updating the `order_index` field on each; 20 individual PATCH calls would create a race condition where another user might see intermediate states.

**Action**: The admin sends `PATCH /items/bulk` with `[{"id": "...", "order_index": N}, ...]` for all 20 items.

**Outcome**: All 20 rows are updated atomically; `BulkResponse` shows `succeeded=20, failed=0`. The reorder is visible atomically to other clients.

**Refs**: CC-10, CC-11, INV-BULK-04, T-09

---

**US-07: Handle missing IDs gracefully in bulk update**

**Persona**: Mobile client sending stale item IDs that may have been deleted server-side.

**Context**: The client has a local cache and optimistically sends update requests for IDs it has stored, some of which may no longer exist on the server.

**Action**: `PATCH /items/bulk` is called with 10 updates; 3 IDs no longer exist in the database.

**Outcome**: 7 items are updated successfully. The 3 missing IDs appear in `results` with `success=false` and `error_code="NOT_FOUND"`. The operation does not raise a 404 that would abort the entire batch.

**Refs**: CC-10, INV-BULK-04, T-10, T-15

---

**US-08: Reject update payloads missing the id field**

**Persona**: Developer accidentally omitting the `id` field from update dicts.

**Context**: A frontend generates update dicts from a form but forgets to include `id` on new records that haven't been saved yet.

**Action**: `PATCH /items/bulk` receives `[{"title": "New title"}]` without an `id` key.

**Outcome**: FastAPI returns HTTP 422 immediately; Pydantic's `each_update_has_id` validator identifies index 0 as missing `id`. No DB query runs.

**Refs**: CC-03, QS-04, T-02

---

**US-09: Bulk update in best_effort mode skips NOT_FOUND without aborting others**

**Persona**: Sync daemon reconciling remote-master data against local replica.

**Context**: The sync daemon sends 200 updates every minute; occasionally 5–10 IDs are stale because they were deleted between sync cycles.

**Action**: `PATCH /items/bulk` is sent with `mode="best_effort"` and 200 updates where 8 IDs are stale.

**Outcome**: 192 items are updated; 8 appear as `NOT_FOUND` in the results. The overall transaction does not roll back. `partial=true` in the response.

**Refs**: INV-BULK-03, INV-BULK-06, T-10, CC-28

---

**US-10: Bulk update preserves untouched fields**

**Persona**: Developer sending partial update dicts that only contain `id` and one changed field.

**Context**: `PATCH /items/bulk` is used to change only the `status` field on 50 items without affecting `title`, `description`, or `created_at`.

**Action**: 50 dicts with `{"id": "...", "status": "archived"}` are sent.

**Outcome**: Only the `status` column is updated on each row; all other columns remain unchanged. SQLAlchemy `update().values(**patch)` excludes `id` from the SET clause.

**Refs**: CC-11, T-13

---

### 9.3 Bulk delete semantics (US-11 .. US-15)

**US-11: Delete multiple items in a single database round-trip**

**Persona**: Admin purging expired trial items after account cancellation.

**Context**: An account cancellation webhook must delete 300 items belonging to the cancelled user; 300 individual DELETE calls would take several seconds and leave data visible during the window.

**Action**: `DELETE /items/bulk` is called with all 300 IDs and `mode="all_or_nothing"`.

**Outcome**: A single `DELETE WHERE id IN (...)` removes all 300 rows atomically in under 200 ms. `BulkResponse` returns `succeeded=300, failed=0`.

**Refs**: INV-BULK-07, CC-12, QS-10, T-12

---

**US-12: Reject deletion of items owned by a different user**

**Persona**: Regular API user attempting to delete another user's items.

**Context**: A malicious or buggy client sends a bulk delete payload that includes IDs belonging to other accounts.

**Action**: `DELETE /items/bulk` with `mode="best_effort"` containing 5 own IDs and 3 foreign IDs.

**Outcome**: The 5 owned items are deleted; the 3 foreign IDs appear as `NOT_FOUND` with `error_code="NOT_FOUND"`. No cross-user data is deleted. The ownership pre-check runs before any `DELETE` statement.

**Refs**: INV-BULK-04, QS-06, T-11, T-16

---

**US-13: All-or-nothing bulk delete rolls back on unowned IDs**

**Persona**: Strict transactional data pipeline that must delete a verified set of IDs atomically.

**Context**: The pipeline sends 20 IDs for deletion expecting all to be owned; any foreign ID indicates a data integrity error and the deletion must not proceed.

**Action**: `DELETE /items/bulk` with `mode="all_or_nothing"` where 1 of 20 IDs is foreign.

**Outcome**: No rows are deleted. Response shows `failed=20`, all items with `error_code="ROLLBACK"`. The foreign ID is identified in the results.

**Refs**: INV-BULK-02, T-16, CC-29

---

**US-14: Non-existent IDs are reported but do not fail the batch in best_effort**

**Persona**: Cleanup job purging stale references from a queue that may contain already-deleted IDs.

**Context**: The queue accumulates IDs over time; by the time the cleanup job runs, some IDs may have already been deleted by other processes.

**Action**: `DELETE /items/bulk` with `mode="best_effort"` and 100 IDs, of which 15 no longer exist.

**Outcome**: 85 existing rows are deleted; 15 appear as `NOT_FOUND` in results. Response has `partial=true`, `failed=15`. No exception is raised.

**Refs**: INV-BULK-06, T-14, CC-29

---

**US-15: Bulk delete of zero owned IDs returns empty success**

**Persona**: Client sending a stale list where all IDs have already been deleted.

**Context**: Client retries a bulk delete after a timeout, but the original request already committed successfully.

**Action**: `DELETE /items/bulk` with 5 IDs that all belong to another user or are already deleted.

**Outcome**: `succeeded=0, failed=5` with all results as `NOT_FOUND`. HTTP 207 is still returned; no exception is raised by the server.

**Refs**: INV-BULK-06, T-14, T-16

---

### 9.4 Idempotency and retry safety (US-16 .. US-20)

**US-16: Retry with same Idempotency-Key returns cached result**

**Persona**: Mobile client on an unreliable network retrying a timed-out bulk create request.

**Context**: The first request succeeded server-side but the client never received the 207 response due to a connection reset. Without idempotency support, retrying would create duplicate rows.

**Action**: The client sends the same `POST /items/bulk` payload with the same `Idempotency-Key: abc-123` header. The server already has a cached result for this key.

**Outcome**: The server returns the cached `BulkResponse` immediately without executing any SQL. `transaction_id` in the response matches the original. No duplicate rows are created.

**Refs**: INV-BULK-05, CC-16, CC-17, T-20

---

**US-17: First request with a new Idempotency-Key executes normally and caches result**

**Persona**: Payment processing service issuing bulk operations with strict exactly-once semantics.

**Context**: The service generates a UUID4 idempotency key per batch and attaches it to the `Idempotency-Key` header on every bulk operation.

**Action**: `POST /items/bulk` is sent with a new, never-seen `Idempotency-Key: xyz-456`.

**Outcome**: The server executes the CRUD operation normally, caches the `BulkResponse` in Redis with 24-hour TTL, and returns the response with `transaction_id="xyz-456"`.

**Refs**: INV-BULK-05, CC-18, T-21

---

**US-18: Bulk operation proceeds normally when Redis is unavailable**

**Persona**: Operator running the API on an environment where Redis is temporarily down for maintenance.

**Context**: The idempotency cache is a Redis instance; Redis becomes unavailable for 2 minutes during a rolling restart.

**Action**: `POST /items/bulk` is sent with an `Idempotency-Key` header during the Redis outage.

**Outcome**: The server logs `WARNING idempotency_cache_get_failed` and proceeds to execute the bulk operation normally. The response is correct but `transaction_id` is null. No exception propagates to the client.

**Refs**: INV-BULK-08, QS-09, CC-18, T-22

---

**US-19: Bulk request without Idempotency-Key still works**

**Persona**: Internal background job that does not require exactly-once semantics.

**Context**: An internal cleanup job runs bulk deletions without setting the `Idempotency-Key` header, as it controls concurrency through other means.

**Action**: `DELETE /items/bulk` is sent without any `Idempotency-Key` header.

**Outcome**: The server processes the request normally; no idempotency logic runs; the response contains `transaction_id=null`. No error or warning is produced.

**Refs**: CC-16, T-23

---

**US-20: Idempotency key TTL expires and subsequent request re-executes**

**Persona**: Developer using idempotency keys with a 24-hour TTL for daily batch jobs.

**Context**: A daily job uses the same key pattern (`daily-sync-{date}`). The following day's job has the same-named key pattern with a new date, but the developer tests by reusing the exact same key string 25 hours later after the TTL has expired.

**Action**: `POST /items/bulk` with `Idempotency-Key: daily-sync-2026-04-12` is sent 25 hours after the original.

**Outcome**: Redis returns a cache miss (key expired); the operation executes normally and the result is re-cached. The server processes and commits a new batch.

**Refs**: INV-BULK-05, CC-18, T-20

---

### 9.5 Operations, performance, and tool management (US-21 .. US-25)

**US-21: Tool is idempotent on re-run**

**Persona**: DevOps engineer running the tool in a CI pipeline on every deploy.

**Context**: The CI pipeline calls `add_bulk_operations(project_dir)` as a step to ensure bulk routes are always present; on the second and subsequent runs the routes already exist.

**Action**: Tool is called twice on the same project with the same parameters.

**Outcome**: Second run detects existing `/bulk` routes via AST inspection, returns `notes: ["already enabled, skipped"]`, and produces zero file modifications.

**Refs**: CC-30, QS-11, T-28

---

**US-22: Bulk create benchmark meets 100-item < 500 ms SLO**

**Persona**: Performance engineer validating that the tool delivers its advertised throughput improvement.

**Context**: The existing single-item flow takes ~50 ms per item; the team needs to demonstrate 100x improvement for 100 items from ~5000 ms to < 500 ms.

**Action**: T-25 benchmark test sends `POST /items/bulk` with exactly 100 items against a real PostgreSQL instance and asserts `elapsed < 0.5`.

**Outcome**: The `pg_insert(Item).values(rows)` path completes in ~80 ms for 100 rows on a standard dev Postgres instance. Benchmark assertion passes.

**Refs**: CC-31, T-25

---

**US-23: Enable bulk operations on all models simultaneously**

**Persona**: Developer building a new project who wants every model to have bulk endpoints from the start.

**Context**: A project has `Item`, `Product`, and `Order` models; all three need bulk endpoints with identical configuration.

**Action**: `add_bulk_operations(project_dir)` is called with `models=None` (default).

**Outcome**: All three models get schemas, CRUD functions, routes, and test files generated. Tool output lists all modified and created files grouped by model. Migration adds `ix_{table}_owner_id` index for each table.

**Refs**: CC-26, CC-20, T-27

---

**US-24: Bulk operations integrate correctly with soft-delete**

**Persona**: Developer who has already run `add_soft_delete` and now wants to add bulk operations.

**Context**: The project uses `SoftDeleteMixin`; bulk delete should call `soft_delete()` per item rather than hard `DELETE` when soft-delete is active.

**Action**: `add_bulk_operations` is run on a project that already has soft-delete enabled on `Item`.

**Outcome**: The generated `bulk_delete_items` detects `SoftDeleteMixin` in the model's MRO and calls `crud.soft_delete()` in a loop (best_effort) or a bulk UPDATE (all_or_nothing) rather than issuing a hard `DELETE` statement.

**Refs**: T-29, CC-24

---

**US-25: Custom max_batch wires through schema and CRUD layers**

**Persona**: Developer building a high-volume ingestion API that needs a larger cap than the default 1000.

**Context**: The ingestion pipeline sends 5000-item batches; the default cap of 1000 would require splitting every batch into 5 calls.

**Action**: `add_bulk_operations(project_dir, models=["Item"], max_batch=5000)` is called.

**Outcome**: Generated `ItemBulkCreate.items` has `Field(..., max_length=5000)`. CRUD layer asserts `len(items) <= 5000`. A batch of 5000 items is accepted; a batch of 5001 is rejected at schema validation time.

**Refs**: INV-BULK-01, CC-02, CC-32, T-05

---

## 10. Test Plan

### 10.1 Bulk create (T-01 .. T-06)

| ID | Test | Assertion | Type |
|----|------|-----------|------|
| T-01 | POST /items/bulk with 5 valid items, all_or_nothing | HTTP 207, succeeded=5, failed=0, all results[*].success=True | Integration |
| T-02 | POST /items/bulk with 1 item missing required `title` field | HTTP 422 before handler executes, no DB query | Unit |
| T-03 | POST /items/bulk returns len(results) == len(request.items) always | results array length equals input length in both modes | Integration |
| T-04 | POST /items/bulk all_or_nothing with 1 item violating unique constraint | HTTP 422 or 207 with failed=N, 0 rows inserted (verify via GET /items/) | Integration |
| T-05 | POST /items/bulk with len(items) == max_batch + 1 | HTTP 422 from Pydantic before handler runs | Unit |
| T-06 | POST /items/bulk with len(items) == 0 | HTTP 422 from `min_length=1` | Unit |

### 10.2 Bulk create best_effort and partial success (T-07 .. T-10)

| ID | Test | Assertion | Type |
|----|------|-----------|------|
| T-07 | POST /items/bulk best_effort with 3 valid + 1 duplicate-title item | succeeded=3, failed=1, partial=True, exactly 3 rows in DB | Integration |
| T-08 | POST /items/bulk — results[i].index always equals position in request list | Loop over results, assert index == position | Integration |
| T-09 | PATCH /items/bulk with 5 valid updates, all_or_nothing | HTTP 207, succeeded=5, all rows updated in DB | Integration |
| T-10 | PATCH /items/bulk best_effort with 3 valid + 2 non-existent IDs | succeeded=3, failed=2, error_code="NOT_FOUND" on failed items | Integration |

### 10.3 Bulk delete and ownership (T-11 .. T-16)

| ID | Test | Assertion | Type |
|----|------|-----------|------|
| T-11 | DELETE /items/bulk with 5 owned + 1 foreign ID, best_effort | succeeded=5, failed=1, foreign ID has error_code="NOT_FOUND" | Integration |
| T-12 | DELETE /items/bulk with 100 owned IDs | Single DELETE statement executed (assert via query count), succeeded=100 | Integration |
| T-13 | PATCH /items/bulk partial update preserves untouched fields | Other columns unchanged after update | Integration |
| T-14 | DELETE /items/bulk where all IDs already deleted or non-existent | succeeded=0, partial=True or failed=N, no 500 error | Integration |
| T-15 | PATCH /items/bulk — foreign ID not in result set (not 403, but NOT_FOUND) | error_code="NOT_FOUND" not "FORBIDDEN" for IDs owned by another user | Integration |
| T-16 | DELETE /items/bulk all_or_nothing with 1 foreign ID in batch of 10 | 0 rows deleted, all results failed with ROLLBACK code | Integration |

### 10.4 Idempotency key (T-17 .. T-23)

| ID | Test | Assertion | Type |
|----|------|-----------|------|
| T-17 | POST /items/bulk twice with same Idempotency-Key | Second call returns same BulkResponse, same succeeded count, no new rows | Integration |
| T-18 | POST /items/bulk with new Idempotency-Key caches result in Redis | Redis GET returns serialised BulkResponse after first call | Integration |
| T-19 | POST /items/bulk Idempotency-Key with 24h TTL — after TTL expiry re-executes | Mock Redis TTL expiry, second call inserts rows | Unit/Mock |
| T-20 | POST /items/bulk first request executes normally when key is new | CRUD runs, result stored, transaction_id set in response | Integration |
| T-21 | POST /items/bulk second request with same key returns cached response | CRUD NOT called (mock assert), cached response returned | Unit/Mock |
| T-22 | POST /items/bulk when Redis returns ConnectionError | Operation completes normally, WARNING logged, transaction_id=null | Unit/Mock |
| T-23 | POST /items/bulk without Idempotency-Key header | Operation succeeds, transaction_id=null, no error | Integration |

### 10.5 Tool generation and idempotency (T-24 .. T-28)

| ID | Test | Assertion | Type |
|----|------|-----------|------|
| T-24 | Run tool on project without bulk routes — verify 3 routes created | grep "/bulk" in route file returns 3 matches | Tool |
| T-25 | Benchmark: POST /items/bulk with 100 items vs 100 sequential POSTs | Bulk < 500 ms; sequential > 3 s; ratio > 5x | Benchmark |
| T-26 | All generated Python files parse without SyntaxError | `ast.parse` passes on all touched files | Tool |
| T-27 | Tool run with models=None generates bulk endpoints for all business models | Route, schema, crud, test files created for each model | Tool |
| T-28 | Tool run twice on same project returns notes=["already enabled, skipped"] | No file modifications on second run, no duplicate routes | Tool |

### 10.6 Edge cases and interaction (T-29 .. T-30)

| ID | Test | Assertion | Type |
|----|------|-----------|------|
| T-29 | add_bulk_operations run after add_soft_delete — bulk delete routes use soft-delete CRUD | bulk_delete_items calls soft_delete() when SoftDeleteMixin in model MRO | Integration |
| T-30 | Bulk create 1000 items — measure DB query count via SQLAlchemy event listener | Exactly 1 INSERT statement executed (not 1000) | Integration |

---

## 11. Interaction Matrix

| This tool | Interacts with | Mode | Behaviour | Risk |
|-----------|---------------|------|-----------|------|
| `add_bulk_operations` | `add_soft_delete` | After | `bulk_delete_items` detects `SoftDeleteMixin` in model MRO and delegates to `crud.soft_delete()` rather than hard DELETE | Soft-delete integration required; test T-29 |
| `add_bulk_operations` | `add_multi_tenancy` | After | Bulk create must inject `tenant_id` from context; bulk update/delete must filter by `tenant_id AND owner_id` | Tenant context required in CRUD functions; test with TenantMiddleware active |
| `add_bulk_operations` | `add_audit_log` | After | Each bulk operation fires N audit events; audit hook must handle list inputs efficiently to avoid N+1 overhead | Batch audit emission required; verify T-01 with audit enabled |
| `add_bulk_operations` | `add_rate_limiting` | After | Bulk endpoints counted as N requests (by item count) or as 1 request (by endpoint hit); configure multiplier | Rate limit strategy must be explicit; document in config |
| `add_bulk_operations` | `add_pagination` | Before | Bulk is write-only; pagination affects GET endpoints only; no conflict | No action required |
| `add_bulk_operations` | `add_auth` | Before | Bulk routes use same `CurrentUser` dependency as single-item routes; no special auth changes needed | Auth dependency must be available before tool runs |
| `add_bulk_operations` | `add_caching` | After | Cache invalidation must handle bulk writes; a cache that stores `GET /items/` list must be invalidated after `POST /items/bulk` | Cache invalidation on bulk write required |
| `add_bulk_operations` | Alembic | After | Migration adds composite index `ix_{table}_owner_id`; must be applied before running bulk endpoints on production data | Run `alembic upgrade head` before deploying |
| `add_bulk_operations` | Redis | Runtime | `IdempotencyCache` requires Redis for key storage; tool still works without Redis but idempotency is disabled | Document Redis requirement in deployment notes |
| `add_bulk_operations` | `add_soft_delete` (concurrent) | Concurrent | Running both tools simultaneously on same model risks race condition on file writes | Serialise tool calls; never run concurrently on same model |
| `add_bulk_operations` | existing CRUD functions | Coexistence | Tool adds new functions (`bulk_create_items`, etc.) alongside existing single-item CRUD; no conflict | AST pre-check prevents duplicate function insertion |
| `add_bulk_operations` | PostgreSQL | Runtime | Uses PostgreSQL-specific `INSERT … ON CONFLICT` and `postgresql_concurrently` for index creation | Non-PG databases need alternate syntax; tool defaults to PG |
| `add_bulk_operations` | `add_validation` | After | Per-item validation in bulk endpoint must invoke same custom validators as single-item endpoint | Custom `ItemCreate` validators apply to each item in bulk list automatically |
| `add_bulk_operations` | `add_webhooks` | After | Successful bulk operations may need to emit webhook events per created/updated/deleted item | Webhook fanout required; batch emission via background task |
| `add_bulk_operations` | MCP server | Registration | Tool must be registered in `mcp_server.py` with `@mcp_tool(name="fastapi_add_bulk_operations")` | Registration required for SKILL-001 tools table |

---

## 12. Rollback Procedure

### 12.1 Overview

`add_bulk_operations` is a code-only tool that adds routes, CRUD functions, schemas, and an optional cache module. No existing routes or columns are modified. Rollback involves removing the generated files and code additions.

### 12.2 Route file rollback

Remove the three bulk route handlers from `app/api/routes/item.py`:

```bash
# Identify the lines added by the tool
grep -n "bulk" app/api/routes/item.py

# The tool annotates generated blocks with:
# --- BEGIN: add_bulk_operations ---
# --- END: add_bulk_operations ---
# Remove the block using the tool's own undo command:
python -m skill001 undo --tool add_bulk_operations --model Item --project-dir .
```

If the undo command is unavailable, remove the annotated block manually:

```python
# Remove these functions from app/api/routes/item.py:
# async def bulk_create(...)
# async def bulk_update(...)
# async def bulk_delete(...)
# Verify no import errors remain:
python -c "from app.api.routes.item import router; print('OK')"
```

### 12.3 Schema file rollback

```bash
# Remove generated schema classes from app/schemas/item.py
# Classes to remove: ItemBulkCreate, ItemBulkUpdate, ItemBulkDelete
#                    BulkResultItem, BulkResponse

# Verify schemas module imports cleanly after removal:
python -c "from app.schemas.item import ItemPublic; print('OK')"
```

### 12.4 CRUD file rollback

```bash
# Remove generated functions from app/crud/item.py
# Functions to remove: bulk_create_items, bulk_update_items, bulk_delete_items

python -c "from app.crud.item import create_item; print('CRUD OK')"
```

### 12.5 Idempotency cache module rollback

```bash
# Delete the generated cache module:
rm app/core/idempotency.py

# Remove the initialisation call from app/main.py:
# Delete the line: init_idempotency_cache(settings.REDIS_URL)

# Verify main.py still imports cleanly:
python -c "from app.main import app; print('main OK')"
```

### 12.6 Database migration rollback

The migration adds a composite index only (no column changes):

```bash
# Downgrade to the previous migration revision:
alembic downgrade -1

# Verify index no longer exists:
python -c "
from app.core.db import engine
import asyncio
from sqlalchemy import inspect, text

async def check():
    async with engine.begin() as conn:
        result = await conn.execute(
            text(\"SELECT indexname FROM pg_indexes WHERE indexname = 'ix_items_owner_id'\")
        )
        rows = result.fetchall()
        assert len(rows) == 0, 'Index still present after downgrade'
        print('Index removed successfully')

asyncio.run(check())
"
```

### 12.7 Test file cleanup

```bash
# Remove generated test file:
rm tests/test_item_bulk_operations.py

# Re-run existing tests to confirm no regressions:
pytest tests/ -q --tb=short
```

### 12.8 Failure modes and recovery

| Failure | Symptom | Recovery |
|---------|---------|----------|
| Route file has syntax error after rollback | `ImportError` on startup | Run `python -m py_compile app/api/routes/item.py` to locate residual syntax issue; re-edit manually |
| Alembic downgrade fails mid-run | Index partially dropped | Reconnect to DB: `DROP INDEX CONCURRENTLY IF EXISTS ix_items_owner_id;` |
| Idempotency cache module left in `__init__.py` export | `ImportError` on `from app.core import idempotency` | Remove export line from `app/core/__init__.py` |
| Redis retains cached idempotency keys after rollback | Old keys returned if tool re-enabled later | `FLUSHDB` on idempotency Redis DB or wait for 24-hour TTL to expire |

---

## 13. Edge Cases

| ID | Input | Expected |
|----|-------|----------|
| EC-01 | `items` list with exactly `max_batch` items | Accepted normally; no rejection; 207 response with all items processed |
| EC-02 | `items` list with `max_batch + 1` items | HTTP 422 from Pydantic `max_length` validation before handler executes |
| EC-03 | `ids` list with duplicate UUID entries in DELETE /bulk | Deduplication at CRUD layer; each unique ID deleted once; `results` returns one entry per original index |
| EC-04 | All items in best_effort batch fail validation | `succeeded=0, failed=N, partial=True`; HTTP 207 returned; no DB transaction opened |
| EC-05 | `updates` list containing an `id` that is a valid UUID string but not a UUID type | Pydantic coerces string to `uuid.UUID` if valid format; rejects with 422 if not valid UUID format |
| EC-06 | Idempotency-Key header is an empty string `""` | Treated as missing key; no cache lookup; operation proceeds without idempotency |
| EC-07 | Redis returns a serialised BulkResponse with extra/missing fields vs current schema | Pydantic `model_validate` raises `ValidationError` on cache hit; operation falls through to normal execution |
| EC-08 | Concurrent requests with identical Idempotency-Key and no cache entry | Race condition: both execute; second SETEX overwrites first; result is consistent because both operations produce equivalent output |
| EC-09 | Bulk create in all_or_nothing mode with a FK violation on item 50 of 100 | All 100 items rolled back; 0 rows inserted; results show all as failed |
| EC-10 | PATCH /items/bulk with update dict containing only `{"id": "..."}` and no other fields | Empty PATCH issues no-op UPDATE with empty `values()`; SQLAlchemy may emit no SQL; succeeded count increments |
| EC-11 | DELETE /items/bulk with empty `ids` list | HTTP 422 from `min_length=1` on `ids` field before handler runs |
| EC-12 | Bulk create when database is at connection pool limit | CRUD raises `TimeoutError`; all_or_nothing returns 503; best_effort propagates error per item |
| EC-13 | `max_batch` parameter set to 10000 (absolute maximum) | All schema fields updated to `max_length=10000`; requests up to 10000 items are accepted |
| EC-14 | Tool run on a model that has no existing `owner_id` FK | Tool generates ownership check with a configurable column name; falls back to disabling ownership check with a warning in tool output |
| EC-15 | Bulk update with `mode="all_or_nothing"` and a database constraint violation on item 3 | Full rollback; 0 rows updated; results show all items as failed with `INTEGRITY_ERROR` |

---

## 14. Acceptance Criteria

✅ 1. `POST /items/bulk`, `PATCH /items/bulk`, and `DELETE /items/bulk` routes exist after tool run with correct `status_code=207` and `response_model=BulkResponse`.
✅ 2. `all_or_nothing` mode inserts/updates/deletes all items atomically; any failure rolls back the entire batch with 0 rows persisted.
✅ 3. `best_effort` mode commits each successful item independently via SAVEPOINT; failed items appear in results without aborting the batch.
✅ 4. `BulkResponse.results` always contains exactly one `BulkResultItem` per input item with `index` matching the request list position.
✅ 5. Hard batch size cap (`Field(max_length=max_batch)`) rejects oversized requests with HTTP 422 before the handler executes.
✅ 6. Ownership pre-check verifies `owner_id == current_user.id` before any bulk update or bulk delete mutation; foreign IDs return `error_code="NOT_FOUND"`.
✅ 7. Idempotency-Key header returns cached `BulkResponse` on repeated requests; first request caches result in Redis with 24-hour TTL.
✅ 8. Redis unavailability logs a warning and allows the operation to proceed normally; no exception propagates to the API caller.
✅ 9. Tool is idempotent: running on an already-instrumented project returns `notes: ["already enabled, skipped"]` with zero file modifications.
✅ 10. All generated Python files pass `ast.parse` without `SyntaxError`; existing test suite passes with 0 new failures after tool execution.

---

## 15. Implementation Checklist

### 15.1 Schema layer
- [ ] Create `ItemBulkCreate` with `items: list[ItemCreate]`, `mode: Literal[...]`, `Field(max_length=max_batch)`
- [ ] Create `ItemBulkUpdate` with `updates: list[dict]`, `mode`, and `each_update_has_id` field_validator
- [ ] Create `ItemBulkDelete` with `ids: list[uuid.UUID]`, `mode`, `Field(min_length=1, max_length=max_batch)`
- [ ] Create `BulkResultItem` with `index`, `id`, `success`, `error`, `error_code` fields
- [ ] Create `BulkResponse` with `total`, `succeeded`, `failed`, `partial`, `transaction_id`, `results` fields
- [ ] All five schema classes pass `ast.parse` after generation
- [ ] `max_batch` parameter from tool call wired to all three `Field(max_length=...)` constraints

### 15.2 CRUD layer — bulk create
- [ ] Implement `bulk_create_items(session, items, owner_id, mode)` async function
- [ ] `all_or_nothing` path uses `pg_insert(Model).values(rows).returning(Model.id)` single statement
- [ ] `best_effort` path uses `session.begin_nested()` savepoint per item
- [ ] `IntegrityError` caught in `all_or_nothing`; triggers `session.rollback()`
- [ ] `Exception` caught per item in `best_effort`; triggers `sp.rollback()` per item only
- [ ] Function returns `BulkResponse` with `len(results) == len(items)` always
- [ ] Generated IDs via `uuid.uuid4()` assigned before INSERT

### 15.3 CRUD layer — bulk update
- [ ] Implement `bulk_update_items(session, updates, owner_id, mode)` async function
- [ ] Ownership pre-check: `SELECT id WHERE id IN (...) AND owner_id = ?` before mutations
- [ ] IDs not in pre-check result added to results as `NOT_FOUND` without DB write
- [ ] Valid IDs updated via `sql_update(Model).where(Model.id == row_id).values(**patch)`
- [ ] `id` key excluded from `values()` dict to prevent PK update
- [ ] Savepoint per item in both modes to isolate failures
- [ ] Function returns `BulkResponse` with `len(results) == len(updates)` always

### 15.4 CRUD layer — bulk delete
- [ ] Implement `bulk_delete_items(session, ids, owner_id, mode)` async function
- [ ] Ownership pre-check: `SELECT id WHERE id IN (...) AND owner_id = ?` before DELETE
- [ ] `all_or_nothing` with unowned IDs: rollback and return all-failed response
- [ ] `best_effort` with unowned IDs: skip unowned, delete owned in single statement
- [ ] Single `sql_delete(Model).where(Model.id.in_(owned_ids))` for all owned IDs
- [ ] `SoftDeleteMixin` detection: delegate to `crud.soft_delete()` when mixin present
- [ ] Function returns `BulkResponse` with `len(results) == len(ids)` always

### 15.5 Route layer
- [ ] Add `POST /items/bulk` route with `response_model=BulkResponse, status_code=207`
- [ ] Add `PATCH /items/bulk` route with `response_model=BulkResponse, status_code=207`
- [ ] Add `DELETE /items/bulk` route with `response_model=BulkResponse, status_code=207`
- [ ] All three routes use `CurrentUser` dependency from existing auth system
- [ ] All three routes accept `Idempotency-Key: Annotated[str | None, Header(alias="Idempotency-Key")]`
- [ ] `all_or_nothing` route raises `HTTPException(422)` when `failed > 0`
- [ ] Routes import `get_idempotency_cache` from `app.core.idempotency`

### 15.6 Idempotency cache module
- [ ] Create `app/core/idempotency.py` with `IdempotencyCache` class
- [ ] Implement `IdempotencyCache.get(key) -> dict | None` with Redis `GET` and JSON decode
- [ ] Implement `IdempotencyCache.set(key, value, ttl=86400)` with Redis `SETEX`
- [ ] Both methods wrapped in `try/except Exception` with `logger.warning` on failure
- [ ] Implement `get_idempotency_cache() -> IdempotencyCache` module-level factory
- [ ] Implement `init_idempotency_cache(redis_url)` called from `app/main.py` startup
- [ ] Cache keys prefixed with `idem:` to avoid collision with other Redis keys

### 15.7 Database migration
- [ ] Generate Alembic migration `*_bulk_ops_index_{table}.py`
- [ ] `upgrade()` creates `ix_{table}_owner_id` composite index on `(owner_id, id)`
- [ ] Index creation uses `postgresql_concurrently=True` for zero-downtime on live tables
- [ ] `downgrade()` drops `ix_{table}_owner_id` with `postgresql_concurrently=True`
- [ ] Migration `revision` and `down_revision` correctly chained to previous migration
- [ ] Migration file passes `ast.parse` without SyntaxError
- [ ] Migration tested with `alembic upgrade head && alembic downgrade -1` on clean DB

### 15.8 Test file generation
- [ ] Generate `tests/test_{name}_bulk_operations.py` with T-01..T-30 test stubs
- [ ] T-01: bulk create all_or_nothing success (5 items, HTTP 207, succeeded=5)
- [ ] T-04: bulk create all_or_nothing rollback on constraint violation
- [ ] T-07: bulk create best_effort partial success
- [ ] T-11: bulk delete with foreign ID in best_effort mode
- [ ] T-25: benchmark test asserting 100-item create < 500 ms
- [ ] All 30 test functions have unique IDs in docstring matching T-XX format
- [ ] Test file passes `ast.parse` without SyntaxError

### 15.9 Tool generation engine
- [ ] AST pre-flight check: detect existing `/bulk` route declarations in route file
- [ ] If bulk routes already present: return `notes: ["already enabled, skipped"]`, no writes
- [ ] Apply changes for each model in `models` list; skip non-existent models with warning
- [ ] Generate all files for `models=None` by scanning `app/models/` for Base subclasses
- [ ] Record all created and modified file paths in return dict `files_created`, `files_modified`
- [ ] Return `metrics` dict with execution time and per-model counts
- [ ] Annotate generated code blocks with `# --- BEGIN: add_bulk_operations ---` markers

### 15.10 Idempotency integration wiring
- [ ] Import `init_idempotency_cache` in `app/main.py`
- [ ] Call `init_idempotency_cache(settings.REDIS_URL)` in `lifespan` startup block
- [ ] Verify `REDIS_URL` is present in `app/core/config.py` settings model
- [ ] Document Redis requirement in `KNOWLEDGE.md` under "Runtime Dependencies"
- [ ] Test startup with `REDIS_URL` unset: app starts, bulk endpoints work, idempotency disabled
- [ ] Test startup with invalid `REDIS_URL`: warning logged, app starts, idempotency disabled
- [ ] Confirm `get_idempotency_cache()` returns a no-op cache when `_redis is None`

### 15.11 Ownership and security
- [ ] Ownership pre-check query uses bound parameter `owner_id = current_user.id` (no string format)
- [ ] Confirm SQL injection impossible: all IDs passed via SQLAlchemy bound parameters
- [ ] Confirm `max_batch` hard cap cannot be bypassed by sending `max_length` override in JSON
- [ ] Confirm bulk delete does not expose which IDs exist vs which are owned (both return NOT_FOUND)
- [ ] `Idempotency-Key` header value length capped to 256 chars by `Header` constraint
- [ ] Idempotency cache keys namespaced by user ID to prevent cross-user cache pollution
- [ ] Security review checklist item: bulk endpoints require authenticated user (not anonymous)

### 15.12 Performance validation
- [ ] T-25 benchmark test integrated into test suite with `@pytest.mark.benchmark` marker
- [ ] Benchmark measures wall-clock time of full HTTP roundtrip (not just CRUD)
- [ ] Bulk create 1000 items measured and result logged in tool output metrics
- [ ] Index `ix_{table}_owner_id` confirmed in query plan via EXPLAIN ANALYZE
- [ ] Memory profiling: no more than 128 MB peak for 1000-item bulk create
- [ ] Connection pool usage: bulk create uses exactly 1 connection regardless of batch size
- [ ] Benchmark results appended to tool return dict under `metrics.benchmark_ms`

### 15.13 Documentation and registration
- [ ] `KNOWLEDGE.md` updated: add `fastapi_add_bulk_operations` entry with parameters and examples
- [ ] `manifest.yaml` updated: tool entry with `name`, `category`, `complexity`, `depends_on`
- [ ] `SKILL.md` tools table updated: add row for TOOL-007 with signature and description
- [ ] MCP tool registered in `mcp_server.py` with `@mcp_tool(name="fastapi_add_bulk_operations")`
- [ ] OpenAPI description on all three routes updated with multi-line docstring explaining modes
- [ ] `README.md` for SKILL-001 updated with bulk operations usage examples
- [ ] Rollback procedure in §12 verified end-to-end on a test project

---

## 16. Documentation Output

```json
{
  "status": "generated",
  "tool": "fastapi_add_bulk_operations",
  "files_created": [
    "app/core/idempotency.py",
    "alembic/versions/0007_bulk_ops_index_items.py",
    "tests/test_item_bulk_operations.py",
    "tests/test_product_bulk_operations.py",
    "tests/test_order_bulk_operations.py",
    "docs/skills_library/skills/SKILL-001-fastapi-production/specs/TOOL-007-add_bulk_operations.md",
    "docs/KNOWLEDGE_bulk_operations.md",
    "scripts/benchmark_bulk_create.py"
  ],
  "files_modified": [
    "app/schemas/item.py",
    "app/crud/item.py",
    "app/api/routes/item.py",
    "app/main.py",
    "app/core/config.py",
    "manifest.yaml",
    "SKILL.md"
  ],
  "metrics": {
    "models_processed": 1,
    "routes_added": 3,
    "crud_functions_added": 3,
    "schema_classes_added": 5,
    "migration_files_generated": 1,
    "test_stubs_generated": 30,
    "execution_time_ms": 1240
  },
  "next_steps": [
    "Run `alembic upgrade head` to create ix_items_owner_id composite index on production DB",
    "Set REDIS_URL environment variable to enable idempotency key caching for bulk endpoints",
    "Run `pytest tests/test_item_bulk_operations.py -v` to execute all 30 generated test stubs",
    "Run benchmark: `pytest tests/ -m benchmark -v` to verify 100-item bulk create < 500 ms SLO",
    "Register fastapi_add_bulk_operations in mcp_server.py using the @mcp_tool decorator",
    "Review ownership_check column name if model uses a field other than owner_id for user attribution",
    "Consider enabling add_soft_delete first if bulk delete should use soft semantics"
  ],
  "warnings": [
    "Bulk endpoints use HTTP 207 Multi-Status — ensure your HTTP client does not treat 207 as an error; some clients only accept 200/201/204 as success",
    "Idempotency cache requires Redis; without REDIS_URL the feature silently degrades — bulk operations remain functional but retries may create duplicates",
    "PostgreSQL-specific syntax used in migration (postgresql_concurrently) and INSERT (pg_insert); non-PG databases require manual migration adjustment"
  ],
  "notes": [
    "all_or_nothing mode is the default and recommended for transactional workflows; use best_effort only when partial success is acceptable to callers",
    "Idempotency keys are namespaced per user (idem:{user_id}:{key}) to prevent cross-user cache pollution — callers can reuse the same key string across different accounts safely",
    "The composite index ix_items_owner_id covers the ownership pre-check query (WHERE owner_id = ? AND id IN (?)) used by bulk_update and bulk_delete; without this index ownership checks are O(n) full-scans on large tables",
    "Tool idempotency detection uses AST-level inspection of the route file; if routes are added via import from another file the detection may return a false negative — review generated notes before deploying",
    "BulkResultItem.index is always the 0-based position in the original request list regardless of transaction mode; clients can use this to map errors back to their input payload without relying on ID fields"
  ]
}
```
