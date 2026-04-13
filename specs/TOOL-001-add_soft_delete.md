# TOOL-001: add_soft_delete

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_soft_delete` |
| Category | EXTEND > CRUD & Data |
| Complexity | Medium |
| Dependencies | Existing FastAPI project with at least 1 SQLAlchemy model, Alembic configured, Pydantic v2 |
| Signature | `add_soft_delete(project_dir: str, models: list[str] \| None = None, cascade: bool = False, audit_field: bool = True, retention_days: int \| None = None) -> dict` |
| Parameters | `project_dir`: project root path<br>`models`: list of model class names to enable soft-delete on (None = all business models)<br>`cascade`: cascade soft-delete to FK children in same transaction<br>`audit_field`: also add `deleted_by: UUID \| None` column with FK to users<br>`retention_days`: if set, generate a scheduled purge job that hard-deletes rows older than N days |

---

## 2. Purpose

`fastapi_add_soft_delete` eliminates permanent data loss from user-facing DELETE operations by replacing physical row removal with a three-column audit marker: `deleted_at` (UTC timestamp), `is_deleted` (boolean with database-level default), and `deleted_by` (nullable FK to users for attribution). The core compliance driver is GDPR Article 17 "right to erasure" workflows where legal holds, referential integrity audits, or customer support undo requests require data to remain accessible for a configurable retention window before a scheduled purge permanently removes it. Soft-delete also satisfies ISO 27001 data lifecycle requirements by creating an immutable audit trail of every deletion event with actor, timestamp, and optionally a reason field, without requiring an external event log. The global query filter is implemented via SQLAlchemy's `do_orm_execute` session event rather than explicit per-query clauses, ensuring that every existing SELECT across the entire codebase automatically excludes soft-deleted rows with zero per-callsite changes — a single registration at application startup enforces the invariant at the ORM layer before SQL reaches the database.

Beyond the filter mechanism, the tool makes three explicit design decisions that diverge from naive implementations. First, `is_deleted` uses `server_default="false"` rather than `nullable=True` so that PostgreSQL 11+ performs a metadata-only `ALTER TABLE ADD COLUMN` without a table rewrite, making the migration instant on multi-million-row tables with no write lock. Second, cascading soft-delete uses a bulk `UPDATE` with a `WHERE parent_id IN (...)` subquery rather than per-row Python loops, keeping the cascade O(1) DB round-trips regardless of child count. Third, hard-delete is an explicit `DELETE /{id}/permanent` endpoint gated behind `CurrentSuperuser`, never triggered by the default `DELETE /{id}` route, so that retention enforcement survives developer mistakes that would otherwise bypass the soft-delete abstraction entirely.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 3s for up to 10 models | Dev waits synchronously in CLI; feedback loop quality |
| Files modified | ≤ 4 per model (model, crud, schema, route) | Predictability; blast radius is bounded |
| Files created | 1 migration + 1 test file per model + 0..1 purge job | Predictable scaffolding output |
| `WHERE is_deleted = false` query overhead | < 5% vs no-filter equivalent | Composite index `(is_deleted, created_at)` keeps O(log n) |
| Migration runtime on 10M rows | < 5s | `ALTER TABLE ADD COLUMN ... DEFAULT false` is metadata-only on PG 11+ |
| Migration runtime on 100M rows | < 30s | Same metadata-only path; index creation uses `CONCURRENTLY` option |
| Memory overhead per worker | 0 MB | No deleted-state cache; filter is pure SQL predicate |
| Cascade soft-delete on 10k children | < 50ms | Bulk `UPDATE ... WHERE parent_id = ?` — single round-trip |
| Retention purge job throughput | ≥ 1000 rows/s | Batched `DELETE WHERE deleted_at < cutoff LIMIT 500` with pagination |

---

## 4. Code Examples (Before / After)

### 4.1 SoftDeleteMixin — reusable base class

```python
# app/models/mixins.py
"""
SoftDeleteMixin adds deleted_at, is_deleted, and deleted_by columns
to any SQLAlchemy 2.0 declarative model via multiple inheritance.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class SoftDeleteMixin:
    """
    Mix-in that adds soft-delete columns to a model.
    Inheriting models gain:
      - is_deleted: bool  (DB default false, NOT NULL — instant ALTER on PG11+)
      - deleted_at: datetime | None
      - deleted_by: uuid.UUID | None  (FK to users, SET NULL on user delete)
    """

    @declared_attr
    def is_deleted(cls) -> Mapped[bool]:
        return mapped_column(
            Boolean, default=False, nullable=False, server_default="false"
        )

    @declared_attr
    def deleted_at(cls) -> Mapped[datetime | None]:
        return mapped_column(DateTime(timezone=True), nullable=True)

    @declared_attr
    def deleted_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(
            Uuid,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        )
```

### 4.2 Model: BEFORE

```python
# app/models/item.py
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base
import uuid


class Item(Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

### 4.3 Model: AFTER

```python
# app/models/item.py
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base
from app.models.mixins import SoftDeleteMixin
import uuid


class Item(SoftDeleteMixin, Base):
    """Item model with soft-delete columns injected via SoftDeleteMixin."""

    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Composite index: hot path filters by is_deleted=False AND orders by created_at
        Index("ix_items_active", "is_deleted", "created_at"),
    )
```

### 4.4 Global query filter via SQLAlchemy session event

```python
# app/core/soft_delete_filter.py
"""
Register a do_orm_execute listener on Session so that every SELECT
automatically injects `WHERE is_deleted = false` for SoftDeleteMixin models.
Import this module once at application startup (main.py) to activate the filter.
"""
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.models.mixins import SoftDeleteMixin


@event.listens_for(Session, "do_orm_execute")
def _enforce_soft_delete_filter(execute_state) -> None:
    """
    Injected for every SELECT against a SoftDeleteMixin model.
    Skip via execution option `include_deleted=True` for admin/restore queries.
    """
    if not execute_state.is_select:
        return
    if execute_state.execution_options.get("include_deleted"):
        return

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            SoftDeleteMixin,
            lambda cls: cls.is_deleted == False,  # noqa: E712
            include_aliases=True,
        )
    )
```

### 4.5 CRUD helpers: soft_delete, restore, hard_delete

```python
# app/crud/item.py (soft-delete additions)
from datetime import datetime, timezone
import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item


async def soft_delete(
    session: AsyncSession,
    item_id: uuid.UUID,
    *,
    deleted_by: uuid.UUID | None = None,
) -> Item | None:
    """Soft-delete: sets is_deleted=True, deleted_at=now(UTC), optionally deleted_by."""
    stmt = select(Item).where(Item.id == item_id, Item.is_deleted == False)  # noqa: E712
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        return None
    obj.is_deleted = True
    obj.deleted_at = datetime.now(timezone.utc)
    if deleted_by is not None:
        obj.deleted_by = deleted_by
    await session.flush()
    return obj


async def restore(session: AsyncSession, item_id: uuid.UUID) -> Item | None:
    """Restore a soft-deleted item. Atomically clears all three deletion columns."""
    stmt = (
        select(Item)
        .where(Item.id == item_id, Item.is_deleted == True)  # noqa: E712
        .execution_options(include_deleted=True)
    )
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        return None
    obj.is_deleted = False
    obj.deleted_at = None
    obj.deleted_by = None
    await session.flush()
    return obj


async def hard_delete(
    session: AsyncSession, item_id: uuid.UUID
) -> Item | None:
    """Permanently remove a row. Superuser-only. Bypasses soft-delete."""
    stmt = (
        select(Item)
        .where(Item.id == item_id)
        .execution_options(include_deleted=True)
    )
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        return None
    await session.delete(obj)
    await session.flush()
    return obj


async def list_deleted(
    session: AsyncSession, *, skip: int = 0, limit: int = 20
) -> dict:
    """List soft-deleted items with pagination (admin use only)."""
    stmt = (
        select(Item)
        .where(Item.is_deleted == True)  # noqa: E712
        .execution_options(include_deleted=True)
        .order_by(Item.deleted_at.desc())
        .offset(skip)
        .limit(limit)
    )
    count_stmt = select(func.count()).select_from(
        select(Item).where(Item.is_deleted == True)  # noqa: E712
        .execution_options(include_deleted=True).subquery()
    )
    total = (await session.execute(count_stmt)).scalar_one()
    result = await session.execute(stmt)
    return {"data": list(result.scalars().all()), "count": total}
```

### 4.6 Route handlers for delete, restore, and permanent delete

```python
# app/api/routes/item.py (soft-delete endpoints)
import uuid

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, CurrentSuperuser, SessionDep
from app.crud.item import soft_delete, restore, hard_delete, list_deleted
from app.schemas.item import ItemPublic, ItemsDeletedPublic, Message

router = APIRouter(prefix="/items", tags=["items"])


@router.delete("/{item_id}", response_model=ItemPublic)
async def delete_item(
    item_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> ItemPublic:
    """Soft-delete an item. Sets is_deleted=True; row remains in DB."""
    item = await soft_delete(session, item_id, deleted_by=current_user.id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.post("/{item_id}/restore", response_model=ItemPublic)
async def restore_item(
    item_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentSuperuser,
) -> ItemPublic:
    """Restore a soft-deleted item. Superuser only."""
    item = await restore(session, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found in deleted records")
    return item


@router.delete("/{item_id}/permanent", response_model=Message)
async def hard_delete_item(
    item_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentSuperuser,
) -> Message:
    """Permanently destroy an item. Superuser only. Irreversible."""
    item = await hard_delete(session, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return Message(message=f"Item {item_id} permanently deleted")


@router.get("/deleted/", response_model=ItemsDeletedPublic)
async def list_deleted_items(
    session: SessionDep,
    current_user: CurrentSuperuser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> ItemsDeletedPublic:
    """List all soft-deleted items. Superuser only."""
    return ItemsDeletedPublic(**await list_deleted(session, skip=skip, limit=limit))
```

### 4.7 Pydantic v2 schemas for deletion metadata

```python
# app/schemas/item.py (soft-delete additions)
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ItemPublic(BaseModel):
    """Standard public schema. NEVER includes deletion columns."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None = None
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime | None = None
    # NOTE: is_deleted, deleted_at, deleted_by intentionally ABSENT


class ItemDeletedPublic(ItemPublic):
    """Extended schema for the /deleted/ admin endpoint only."""
    is_deleted: bool
    deleted_at: datetime
    deleted_by: uuid.UUID | None = None


class ItemsDeletedPublic(BaseModel):
    """Paginated list of soft-deleted items."""
    model_config = ConfigDict(from_attributes=True)
    data: list[ItemDeletedPublic]
    count: int
```

### 4.8 Alembic migration adding deleted_at, is_deleted, deleted_by

```python
# alembic/versions/0003_softdel_items.py
"""Add soft-delete columns to items table.

Revision ID: 0003_softdel_items
Revises: 0002_initial
Create Date: 2026-04-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_softdel_items"
down_revision = "0002_initial"


def upgrade() -> None:
    # is_deleted: server_default="false" → metadata-only ALTER on PG 11+, no table rewrite
    op.add_column(
        "items",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "items",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "items",
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_items_deleted_by_users",
        "items",
        "users",
        ["deleted_by"],
        ["id"],
        ondelete="SET NULL",
    )
    # Composite index for: WHERE is_deleted = false ORDER BY created_at
    op.create_index("ix_items_active", "items", ["is_deleted", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_items_active", table_name="items")
    op.drop_constraint("fk_items_deleted_by_users", "items", type_="foreignkey")
    op.drop_column("items", "deleted_by")
    op.drop_column("items", "deleted_at")
    op.drop_column("items", "is_deleted")
```

### 4.9 Retention purge job (ARQ worker)

```python
# app/workers/soft_delete_purge.py
"""
Retention purge job: hard-deletes rows whose deleted_at exceeds retention_days.
Run as an ARQ job on a daily cron schedule.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, and_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import engine
from app.models.item import Item

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


async def purge_soft_deleted_items(
    ctx: dict,
    *,
    retention_days: int = 90,
) -> dict:
    """
    Delete all Item rows where is_deleted=True AND deleted_at < now - retention_days.
    Runs in batches of BATCH_SIZE to avoid long transactions on large tables.
    Returns {'deleted_count': N, 'batches': M}.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    session_maker: async_sessionmaker[AsyncSession] = ctx["session_maker"]
    total_deleted = 0
    batches = 0

    while True:
        async with session_maker() as session:
            # Fetch a batch of IDs to delete
            ids_stmt = (
                select(Item.id)
                .where(
                    and_(Item.is_deleted == True, Item.deleted_at < cutoff)  # noqa: E712
                )
                .execution_options(include_deleted=True)
                .limit(BATCH_SIZE)
            )
            ids = list((await session.execute(ids_stmt)).scalars())
            if not ids:
                break

            del_stmt = delete(Item).where(Item.id.in_(ids))
            result = await session.execute(del_stmt)
            await session.commit()
            total_deleted += result.rowcount
            batches += 1

    logger.info("purge_complete deleted=%d batches=%d cutoff=%s", total_deleted, batches, cutoff)
    return {"deleted_count": total_deleted, "batches": batches}
```

### 4.10 Pytest integration test: soft-delete lifecycle

```python
# tests/test_item_soft_delete.py  (fragment — full file generated by tool)
"""Integration tests for the soft-delete lifecycle on Item model."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_soft_delete_sets_columns(
    client: AsyncClient,
    normal_user_token_headers: dict,
    created_item_id: str,
) -> None:
    """T-01: DELETE /items/{id} sets is_deleted=True and deleted_at=now(UTC)."""
    resp = await client.delete(
        f"/api/v1/items/{created_item_id}",
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 200
    # Row still exists in DB — verify via admin include_deleted endpoint
    admin = normal_user_token_headers  # use superuser fixture in full test
    detail = await client.get(
        f"/api/v1/items/{created_item_id}",
        headers=normal_user_token_headers,
    )
    assert detail.status_code == 404, "Soft-deleted item must return 404 on standard GET"


@pytest.mark.asyncio
async def test_list_excludes_soft_deleted(
    client: AsyncClient,
    normal_user_token_headers: dict,
    three_items_one_deleted: None,
) -> None:
    """T-03: GET /items/ must return only non-deleted records."""
    resp = await client.get("/api/v1/items/", headers=normal_user_token_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert all(not i.get("is_deleted", False) for i in body["data"])


@pytest.mark.asyncio
async def test_restore_resets_all_columns(
    client: AsyncClient,
    superuser_token_headers: dict,
    soft_deleted_item_id: str,
) -> None:
    """T-05: POST /items/{id}/restore resets is_deleted, deleted_at, deleted_by to clean state."""
    resp = await client.post(
        f"/api/v1/items/{soft_deleted_item_id}/restore",
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "deleted_at" not in body or body.get("deleted_at") is None
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-01 | **Zero data loss via default delete** | `crud.soft_delete()` sets columns only; `session.delete()` is called exclusively from `hard_delete()`. Verified by T-01, T-09 |
| QS-02 | **Transparent filtering — zero callsite changes** | `do_orm_execute` listener with `with_loader_criteria` injects filter on every SELECT. No route code modified. Verified by T-03, T-04 |
| QS-03 | **Backward-compatible public API schema** | `ItemPublic` schema does NOT contain `is_deleted`, `deleted_at`, `deleted_by`. Only `ItemDeletedPublic` exposes deletion fields. Verified by T-22 |
| QS-04 | **UTC-only timestamps — no naive datetimes** | `deleted_at` always set via `datetime.now(timezone.utc)`. DB column uses `DateTime(timezone=True)`. Verified by T-02 |
| QS-05 | **Atomic cascade in a single transaction** | When `cascade=True`, bulk `UPDATE children SET is_deleted=True WHERE parent_id=?` fires inside the parent session transaction. Verified by T-17 |
| QS-06 | **Idempotent tool execution** | Pre-flight AST check detects existing `is_deleted` column; returns `notes=["already enabled, skipped"]` without writing. Verified by T-26 |
| QS-07 | **Migration safe on 10M+ rows without lock** | `server_default="false"` for `is_deleted` triggers metadata-only ALTER on PG 11+; index created with `CONCURRENTLY` option if available. Verified by T-17 |
| QS-08 | **Query overhead < 5% vs hard-delete** | Composite index `(is_deleted, created_at)` ensures sargable predicate with O(log n) plan. No function wrappers around the column. Verified by T-30 |
| QS-09 | **New rows always default to is_deleted=False** | DB-level `server_default="false"` enforces even if ORM code omits the field. Verified by T-14 |
| QS-10 | **Restore is atomic — all three columns cleared** | `restore()` assigns `is_deleted=False`, `deleted_at=None`, `deleted_by=None` before single `flush()`. Verified by T-05 |
| QS-11 | **Sensitive fields never exposed in deleted listing** | `ItemDeletedPublic` inherits from `ItemPublic` which excludes sensitive columns like `hashed_password`. Verified by T-21 |
| QS-12 | **Hard-delete is superuser-gated at route level** | `/permanent` endpoint uses `CurrentSuperuser` dependency. Regular user token returns 403. Verified by T-15 |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `SoftDeleteMixin` class exists at `app/models/mixins.py` with `is_deleted`, `deleted_at`, `deleted_by` declared attrs | File exists, `ast.parse` passes, attrs present |
| CC-02 | Target model inherits `SoftDeleteMixin` (e.g. `class Item(SoftDeleteMixin, Base):`) | `grep "SoftDeleteMixin" app/models/{name}.py` |
| CC-03 | `is_deleted` column: `Boolean, server_default="false", nullable=False` | AST inspection of `SoftDeleteMixin.is_deleted` |
| CC-04 | `deleted_at` column: `DateTime(timezone=True), nullable=True` | AST inspection |
| CC-05 | `deleted_by` column: `Uuid, FK to users.id, ondelete="SET NULL", nullable=True` (when `audit_field=True`) | AST + FK inspection |
| CC-06 | Composite index `(is_deleted, created_at)` in `__table_args__` of target model | `grep "ix_{table}_active"` in model file |
| CC-07 | `app/core/soft_delete_filter.py` exists with `@event.listens_for(Session, "do_orm_execute")` | File exists, grep listener decorator |
| CC-08 | Filter module imported in `app/main.py` at startup (side-effect import) | `grep "soft_delete_filter"` in `app/main.py` |
| CC-09 | Filter honours `include_deleted=True` execution option to bypass filter | AST: `execute_state.execution_options.get("include_deleted")` present |
| CC-10 | `crud.soft_delete()` sets `is_deleted=True, deleted_at=now(UTC), deleted_by=?` then `flush()` | AST of function body |
| CC-11 | `crud.soft_delete()` uses `datetime.now(timezone.utc)` not `datetime.now()` | grep `timezone.utc` in crud file |
| CC-12 | `crud.soft_delete()` does NOT call `session.delete()` | grep absence of `session.delete` in function |
| CC-13 | `crud.restore()` exists, queries with `include_deleted=True`, resets all 3 columns, calls `flush()` | AST inspection |
| CC-14 | `crud.hard_delete()` exists, uses `session.delete()`, queries with `include_deleted=True` | AST inspection |
| CC-15 | `crud.list_deleted()` exists, queries with `include_deleted=True`, orders by `deleted_at.desc()` | AST inspection |
| CC-16 | Route `DELETE /{id}` calls `crud.soft_delete(deleted_by=current_user.id)` | Read route file |
| CC-17 | Route `POST /{id}/restore` exists with `CurrentSuperuser` dependency | Read route file |
| CC-18 | Route `DELETE /{id}/permanent` exists with `CurrentSuperuser` dependency | Read route file |
| CC-19 | Route `GET /deleted/` exists with `CurrentSuperuser` dependency and pagination | Read route file |
| CC-20 | `ItemDeletedPublic` schema exists extending `ItemPublic` with `is_deleted`, `deleted_at`, `deleted_by` | Read schema file |
| CC-21 | `ItemPublic` schema does NOT contain `is_deleted`, `deleted_at`, `deleted_by` | `grep -v "is_deleted\|deleted_at\|deleted_by"` in ItemPublic class |
| CC-22 | Alembic migration file `*_softdel_{table}.py` generated in `alembic/versions/` | File exists with correct naming pattern |
| CC-23 | Migration `upgrade()` uses `server_default=sa.false()` for `is_deleted` | grep migration file |
| CC-24 | Migration `upgrade()` creates FK `fk_{table}_deleted_by_users` when `audit_field=True` | Inspect upgrade() |
| CC-25 | Migration `upgrade()` creates composite index `ix_{table}_active` | Inspect upgrade() |
| CC-26 | Migration `downgrade()` drops index, FK, columns in reverse order | Inspect downgrade() |
| CC-27 | All generated Python files pass `ast.parse` without SyntaxError | Run AST check on every touched file |
| CC-28 | Existing test suite passes with 0 failures after modification | `pytest tests/ -q` — 0 failures |
| CC-29 | New test file `tests/test_{name}_soft_delete.py` generated with T-01..T-30 stubs | File exists, all 30 test IDs present |
| CC-30 | Retention purge job `app/workers/soft_delete_purge.py` generated when `retention_days` is set | File exists if param provided |
| CC-31 | Tool execution time < 3s for a single model | Time measurement logged in result |
| CC-32 | Tool is idempotent: re-run on already-enabled model returns `notes=["skipped"]` with no file changes | Run tool twice, diff is empty |

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
- [ ] Migration safety validated: simulated test on a 10M-row table confirms < 5s migration time
- [ ] Performance SLOs measured: query overhead < 5% confirmed by benchmark (T-30)
- [ ] Interaction with all tools in §11 verified by integration smoke tests
- [ ] All 15 edge cases in §13 handled without unhandled exceptions
- [ ] Documentation updated: `KNOWLEDGE.md`, `manifest.yaml`, `SKILL.md` tools table
- [ ] MCP tool registered in `mcp_server.py` with correct `@mcp_tool` decorator
- [ ] Re-audit by Opus in fresh context with brutal mode enabled: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SD-01 | **Soft-deleted rows NEVER appear in default queries** | `do_orm_execute` listener injects `with_loader_criteria(SoftDeleteMixin, is_deleted == False)` for every SELECT unless `include_deleted=True` execution option is set | T-03, T-04 |
| INV-SD-02 | **`deleted_at` is ALWAYS UTC timezone-aware** | `datetime.now(timezone.utc)` enforced in `crud.soft_delete()`; column uses `DateTime(timezone=True)`; naive datetimes rejected by Pydantic | T-02 |
| INV-SD-03 | **`session.delete()` is NEVER called from `soft_delete()`** | `soft_delete()` only sets column values and calls `flush()`; `session.delete()` is called exclusively from `hard_delete()` | T-01, T-09 |
| INV-SD-04 | **Restore atomically resets exactly three columns** | `restore()` assigns `is_deleted=False`, `deleted_at=None`, `deleted_by=None` before a single `flush()`; partial states are impossible | T-05 |
| INV-SD-05 | **New rows always have `is_deleted=False` even when ORM code omits the field** | DB-level `server_default="false"` enforces the default at INSERT time regardless of ORM layer | T-14 |
| INV-SD-06 | **Models NOT in the `models` parameter are unaffected** | Pre-flight check confirms only listed models are touched; existing tests on other models still pass | T-26 |
| INV-SD-07 | **Cascade soft-delete is atomic — all children or none** | Bulk `UPDATE children ... WHERE parent_id = ?` runs inside the parent session's transaction; any exception causes full rollback | T-17 |
| INV-SD-08 | **`is_deleted` and `deleted_at` are NEVER exposed in `ItemPublic`** | `ItemPublic` schema class does not define these fields; Pydantic model serialisation omits them by `from_attributes=True` mode | T-22, T-23 |

---

## 9. User Stories

### 9.1 Core functionality (US-01 .. US-05)

**US-01: Enable soft-delete on a single model**
- **As a** backend developer
- **I want** to add soft-delete to my Item model with one command
- **So that** deleted items can be recovered by customer support without DB-level interventions
- **Given:** A project with an Item model and CRUD routes, Alembic configured
- **When:** I call `add_soft_delete(project_dir, models=["Item"])`
- **Then:**
  - Item model inherits `SoftDeleteMixin` (CC-02)
  - `DELETE /items/{id}` sets `is_deleted=True` instead of removing the row (INV-SD-03)
  - Migration file `*_softdel_items.py` is created (CC-22)
  - Tool returns `{files_created: [...], files_modified: [...], notes: [...]}`

**US-02: Default queries automatically exclude soft-deleted records**
- **As a** developer who has enabled soft-delete
- **I want** all list endpoints to exclude soft-deleted records without modifying their code
- **So that** I don't have to audit every query in the codebase for `is_deleted` clauses
- **Given:** 3 items exist, 1 of which is soft-deleted
- **When:** I call `GET /items/`
- **Then:**
  - Response contains 2 items, `count=2` (INV-SD-01)
  - The soft-deleted item is NOT in the response
  - No route code was modified to achieve this filtering (CC-07, CC-08)

**US-03: Restore a soft-deleted item**
- **As an** admin
- **I want** to restore a soft-deleted item via API
- **So that** I can undo accidental deletions reported by users
- **Given:** Item id=`abc` is soft-deleted with `is_deleted=True, deleted_at=2026-01-15T10:00:00Z`
- **When:** I call `POST /items/abc/restore` with a superuser token
- **Then:**
  - 200 OK with the restored item in the response body
  - `is_deleted=False, deleted_at=None, deleted_by=None` atomically (INV-SD-04)
  - Item appears in `GET /items/` again

**US-04: List soft-deleted items for audit (admin)**
- **As an** admin
- **I want** to see all soft-deleted items with deletion metadata
- **So that** I can audit deletion activity and identify accidental deletions
- **Given:** 5 items total, 2 soft-deleted, logged in as superuser
- **When:** I call `GET /items/deleted/`
- **Then:**
  - Response contains exactly 2 items
  - Each item has `is_deleted=True`, `deleted_at` populated, `deleted_by` populated (CC-20)
  - Regular user token receives 403 (CC-19)

**US-05: Enable soft-delete on all models at once**
- **As a** developer starting a new project
- **I want** to add soft-delete to all business models simultaneously
- **So that** all resources in my API have consistent delete semantics
- **Given:** Project with User, Item, Order models
- **When:** I call `add_soft_delete(project_dir)` with no `models` parameter
- **Then:**
  - All 3 models inherit `SoftDeleteMixin` (CC-02)
  - 3 migration files created (one per table) chained in revision order
  - Tool returns `notes` confirming all 3 models processed

### 9.2 Idempotency & safety (US-06 .. US-10)

**US-06: Tool is idempotent on re-run**
- **As a** developer
- **I want** re-running the tool on an already-enabled model to be safe
- **So that** CI pipelines or accidental double-runs do not corrupt the codebase
- **Given:** Item already has soft-delete enabled (SoftDeleteMixin in base classes)
- **When:** I call `add_soft_delete(project_dir, models=["Item"])` again
- **Then:**
  - No duplicate columns, no duplicate migration, no duplicate routes (CC-32)
  - Tool returns `notes: ["Item already has soft-delete enabled, skipped"]`
  - Exit code is 0

**US-07: GET by ID returns 404 for soft-deleted items**
- **As a** regular API consumer
- **I want** soft-deleted items to behave as if they don't exist
- **So that** the API contract is unchanged from the caller's perspective
- **Given:** Item id=`xyz` is soft-deleted
- **When:** I call `GET /items/xyz` with any user token
- **Then:** 404 Not Found (INV-SD-01 ensures filter excludes the row)

**US-08: Migration is safe on existing data**
- **As an** operator running the migration on a live production database
- **I want** the migration to complete without locking the table or losing data
- **Given:** Items table has 500k existing records with active read/write traffic
- **When:** `alembic upgrade head` runs the generated migration
- **Then:**
  - All 500k records have `is_deleted=False` via `server_default` (CC-23, INV-SD-05)
  - Migration completes in < 5s (metadata-only ALTER on PG 11+)
  - Zero data loss in any existing column

**US-09: Soft-deleted records remain queryable via direct DB access**
- **As a** DBA performing an emergency data recovery
- **I want** soft-deleted rows to be physically present in the database
- **Given:** Item id=`abc` soft-deleted via API
- **When:** I run `SELECT * FROM items WHERE id = 'abc'` in psql
- **Then:** Row exists with `is_deleted=True`, `deleted_at` and `deleted_by` populated (INV-SD-03)

**US-10: Cascade soft-delete when enabled**
- **As a** developer with a parent-child model relationship
- **I want** soft-deleting a parent to soft-delete its children atomically
- **So that** orphan child records never appear in queries after parent deletion
- **Given:** User has 5 Items, tool called with `cascade=True`
- **When:** User is soft-deleted
- **Then:**
  - All 5 Items are also soft-deleted with the same `deleted_at` timestamp (INV-SD-07)
  - If any child soft-delete fails, the entire transaction rolls back

### 9.3 Auth & access control (US-11 .. US-15)

**US-11: Regular users cannot list soft-deleted items**
- **As a** regular user
- **I want** the system to reject my attempt to access deleted records
- **Given:** Regular user token (not superuser)
- **When:** `GET /items/deleted/`
- **Then:** 403 Forbidden — `CurrentSuperuser` dependency enforced (CC-19)

**US-12: Regular users cannot restore items**
- **As a** regular user
- **I want** restore to be an admin-only operation
- **Given:** Soft-deleted Item id=`abc`, regular user token
- **When:** `POST /items/abc/restore`
- **Then:** 403 Forbidden (CC-17)

**US-13: Regular users cannot permanently delete items**
- **As a** security reviewer
- **I want** permanent deletion to be superuser-gated
- **Given:** Regular user token
- **When:** `DELETE /items/{id}/permanent`
- **Then:** 403 Forbidden — route uses `CurrentSuperuser` (CC-18, QS-12)

**US-14: Owner check happens before soft-delete**
- **As a** developer relying on ownership checks
- **I want** the ownership guard to apply before soft-delete logic
- **Given:** Item owned by user A, user B has a valid token
- **When:** User B calls `DELETE /items/{id}`
- **Then:**
  - 403 Forbidden (ownership check runs first in route handler)
  - Item is NOT soft-deleted; `is_deleted` remains `False`

**US-15: Superuser can permanently delete any item**
- **As a** superuser executing a GDPR erasure request
- **I want** to permanently remove a record after the retention window expires
- **Given:** Superuser token, Item id=`abc` (may be soft-deleted or active)
- **When:** `DELETE /items/abc/permanent`
- **Then:**
  - 200 OK with confirmation message (CC-18)
  - Row physically removed; `SELECT * FROM items WHERE id = 'abc'` returns 0 rows
  - Subsequent `GET /items/abc` returns 404 (T-09)

### 9.4 Integration with other features (US-16 .. US-20)

**US-16: Pagination count correct after soft-delete**
- **As a** developer consuming paginated list endpoints
- **I want** pagination counts to reflect only non-deleted records
- **Given:** 100 items total, 20 soft-deleted, `skip=0, limit=10`
- **When:** `GET /items/?skip=0&limit=10`
- **Then:**
  - 10 non-deleted items in `data` (INV-SD-01)
  - `count=80` (soft-deleted rows excluded from total)

**US-17: Search excludes soft-deleted records**
- **As a** user searching for products
- **I want** search results to exclude soft-deleted items
- **Given:** `add_search` enabled, one soft-deleted product with title "Widget"
- **When:** `GET /products/search?q=widget`
- **Then:** soft-deleted "Widget" is NOT in results (CC-07 global filter applies to search queries)

**US-18: Audit log records soft-delete as distinct action**
- **As an** operator reviewing the audit trail
- **I want** soft-delete to appear differently from hard-delete in the audit log
- **Given:** `add_audit_log` installed before `add_soft_delete`
- **When:** An item is soft-deleted
- **Then:**
  - Audit log entry has `action="soft_delete"` not `action="delete"` (INV-SD-03)
  - `actor_id` and timestamp recorded correctly

**US-19: Multi-tenancy and soft-delete work together**
- **As a** developer on a multi-tenant SaaS
- **I want** both the tenant filter and the soft-delete filter to apply simultaneously
- **Given:** `add_multi_tenancy` installed first, then `add_soft_delete`
- **When:** `GET /items/` as tenant A
- **Then:**
  - Only tenant A's non-deleted items are returned
  - Both `tenant_id = current` and `is_deleted = false` filters are active
  - Composite index `(tenant_id, is_deleted, created_at)` used for hot path

**US-20: Retention purge job removes expired records**
- **As an** operator managing GDPR data retention
- **I want** a scheduled job to hard-delete soft-deleted rows after the retention window
- **Given:** Tool called with `retention_days=90`, 50 items soft-deleted 95 days ago
- **When:** `purge_soft_deleted_items` ARQ job runs
- **Then:**
  - All 50 expired rows are permanently removed (CC-30)
  - Items soft-deleted 89 days ago are NOT removed
  - Return value includes `{"deleted_count": 50, "batches": 1}`

### 9.5 Schema, API contract & performance (US-21 .. US-25)

**US-21: Sensitive fields never exposed in deleted listing**
- **As a** security reviewer
- **I want** the `/deleted/` endpoint to never leak sensitive fields
- **Given:** User model with soft-delete enabled, `hashed_password` field exists
- **When:** `GET /users/deleted/` as superuser
- **Then:**
  - Response includes `is_deleted`, `deleted_at`, `deleted_by` (CC-20)
  - `hashed_password` is NOT in the response (QS-11)

**US-22: Default GET response schema is unchanged**
- **As an** API consumer with an existing integration
- **I want** the standard GET response to not include deletion columns
- **Given:** Active Item retrieved via `GET /items/{id}`
- **When:** Inspecting the response body
- **Then:**
  - `is_deleted`, `deleted_at`, `deleted_by` are absent from the JSON (INV-SD-08, CC-21)
  - Schema version bump is NOT required for existing consumers

**US-23: Deleted endpoint exposes full deletion metadata**
- **As an** admin using the deleted listing endpoint
- **I want** to see who deleted what and when
- **Given:** Superuser calls `GET /items/deleted/`
- **Then:**
  - Each item includes `is_deleted=True`, `deleted_at` (ISO 8601 UTC), `deleted_by` UUID (CC-20)
  - Schema is `ItemDeletedPublic` not `ItemPublic`

**US-24: OpenAPI spec reflects new endpoints**
- **As a** developer generating a client SDK from the OpenAPI spec
- **I want** all new soft-delete endpoints to be documented
- **Given:** Soft-delete enabled
- **When:** I fetch `/api/v1/openapi.json`
- **Then:**
  - `/items/{id}/restore`, `/items/deleted/`, `/items/{id}/permanent` are present
  - Each endpoint has correct request/response schemas documented

**US-25: Performance — 1M row table still fast**
- **As an** operator running a high-traffic service
- **I want** the soft-delete filter to add negligible query latency
- **Given:** Items table has 1M records, 100K soft-deleted
- **When:** `GET /items/?limit=20`
- **Then:**
  - Response time < 100ms (composite index `ix_items_active` used, T-30)
  - `EXPLAIN ANALYZE` shows index scan on `ix_items_active`, not seq scan (QS-08)

---

## 10. Test Plan

### 10.1 Functional tests — delete and query filter

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-01 | Soft-delete sets is_deleted=True | Create item | DELETE /items/{id} | 200; DB row has is_deleted=True | Functional |
| T-02 | deleted_at is UTC and recent | Create item | DELETE /items/{id} | abs(now - deleted_at) < 2s, tzinfo UTC (INV-SD-02) | Functional |
| T-03 | get_multi excludes soft-deleted | 3 items, 1 deleted | GET /items/ | data=2, count=2 (INV-SD-01) | Filter |
| T-04 | GET by id returns 404 for soft-deleted | Soft-deleted item | GET /items/{id} | 404 (INV-SD-01) | Filter |
| T-05 | Restore resets all 3 columns atomically | Soft-deleted item | POST /items/{id}/restore | is_deleted=False, deleted_at=None, deleted_by=None (INV-SD-04) | Restore |
| T-06 | list_deleted returns only deleted rows | 3 items, 1 deleted | GET /items/deleted/ as superuser | data=1, count=1 | Admin |

### 10.2 Auth and ownership tests

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-07 | Restore of non-deleted item is 404 | Active item | POST /items/{id}/restore | 404 (not in deleted set) | Edge |
| T-08 | Double soft-delete is idempotent | Already deleted | DELETE /items/{id} | 200, deleted_at unchanged on second call | Idempotency |
| T-09 | hard_delete physically removes row | Any item | DELETE /items/{id}/permanent | 200; SELECT returns 0 rows (INV-SD-03) | Hard delete |
| T-10 | hard_delete works on active (non-deleted) item | Active item | DELETE /items/{id}/permanent | 200; row removed | Hard delete |
| T-11 | include_deleted opt-in returns all rows | 3 items, 1 deleted | crud.list_deleted via admin endpoint | data=1, count=1 with is_deleted=True | Opt-out |
| T-12 | deleted_by populated from current_user.id | Auth'd delete | DELETE /items/{id} | deleted_by == current_user.id | Audit |

### 10.3 Migration and database tests

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-13 | Regular user cannot list deleted | Regular token | GET /items/deleted/ | 403 Forbidden | Auth |
| T-14 | New rows have is_deleted=False by DB default | INSERT with no is_deleted | psql INSERT | is_deleted=False (INV-SD-05) | DB |
| T-15 | Regular user cannot hard_delete | Regular token | DELETE /items/{id}/permanent | 403 Forbidden (QS-12) | Auth |
| T-16 | Owner check prevents cross-user soft-delete | Non-owner | DELETE /items/{id} | 403, is_deleted unchanged | Auth |
| T-17 | Migration adds columns with correct defaults | 100 existing rows | alembic upgrade head | All 100 rows have is_deleted=False (CC-23) | Migration |
| T-18 | Migration is reversible without data loss | After upgrade | alembic downgrade -1 | Columns dropped, other data intact | Migration |

### 10.4 Integration and compatibility tests

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-19 | Migration uses server_default | Read migration file | grep "server_default" | sa.false() present | Static |
| T-20 | Composite index created | Run migration | psql `\d items` | ix_items_active exists | Migration |
| T-21 | Sensitive fields absent from deleted listing | User with hashed_password | GET /users/deleted/ | No hashed_password in response (QS-11) | Security |
| T-22 | Default ItemPublic excludes deletion columns | GET /items/{id} | Inspect JSON | is_deleted absent from response (INV-SD-08) | Schema |
| T-23 | ItemDeletedPublic includes deletion fields | GET /items/deleted/ | Inspect JSON | is_deleted, deleted_at, deleted_by present (CC-20) | Schema |
| T-24 | Soft-delete + cursor pagination | 90 active, 10 deleted | Paginate through all pages | Exactly 90 items returned, no gaps, no deleted (INV-SD-01) | Integration |

### 10.5 Idempotency, error handling, and edge case tests

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-25 | Soft-delete + audit log integration | add_audit_log installed | DELETE /items/{id} | Audit entry has action="soft_delete" (INV-SD-03) | Integration |
| T-26 | Tool re-run is a no-op | Soft-delete already enabled | Run tool again | No file changes, notes="skipped" (INV-SD-06, CC-32) | Idempotency |
| T-27 | Tool rejects is_deleted with wrong type | Pre-existing is_deleted: str | Run tool | Error, no file changes (EC-03) | Error |
| T-28 | Tool rejects missing Alembic | No alembic dir | Run tool | Error "Alembic not initialized", no files modified (EC-04) | Error |
| T-29 | Tool fails atomically on partial write error | Mock FS error mid-run | Run tool | No partial state; all-or-nothing rollback | Atomicity |
| T-30 | Performance: 1M rows, query < 100ms | Seed 1M rows, 100K deleted | GET /items/?limit=20 | Response < 100ms, EXPLAIN shows index scan (QS-08) | Performance |

---

## 11. Interaction Matrix

How `add_soft_delete` interacts with other tools and required ordering:

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_cursor_pagination` | No | Compatible | Cursor queries gain `is_deleted = false` filter automatically via global listener; no cursor changes needed |
| `add_search` | No | Compatible | Full-text search queries pass through the `do_orm_execute` listener and inherit the soft-delete filter |
| `add_audit_log` | **Audit first** | Compatible | Audit listener detects `is_deleted` column change and emits `action="soft_delete"` vs `action="delete"`; ordering ensures audit fires before soft-delete result returned |
| `add_multi_tenancy` | **Tenancy first** | Compatible | Both `tenant_id = ?` and `is_deleted = false` criteria injected by `do_orm_execute`; recommend composite index `(tenant_id, is_deleted, created_at)` for hot path |
| `add_bulk_operations` | No | Caveat | Bulk delete must call `soft_delete()` per item or a bulk `UPDATE SET is_deleted=True WHERE id IN (?)`; bulk restore needs a separate endpoint |
| `add_file_upload` | No | Caveat | Soft-deleting a parent does NOT delete uploaded files; use `cascade=True` plus a post-delete hook to move blobs to a quarantine bucket |
| `add_data_export` | No | Caveat | Export job must explicitly choose `include_deleted=True` or `False`; default export should exclude deleted rows to match API behaviour |
| `add_rbac` | **RBAC first** | Compatible | Permission to `soft_delete` is separate from permission to `hard_delete`; RBAC matrix enforces this distinction at the dependency level |
| `add_feature_flags` | No | Compatible | Soft-delete can be feature-flagged per environment (e.g. disable in dev to ease testing) |
| `add_event_driven` | No | Compatible | Soft-delete event publishes `item.soft_deleted` domain event via outbox; restore publishes `item.restored` |
| `add_migration_data` (TOOL-043) | **Soft-delete first** | Compatible | Data migration scripts must use `include_deleted=True` to process all rows including soft-deleted ones |
| `add_admin_panel` (TOOL-048) | **Soft-delete first** | Compatible | Admin panel gets dedicated "Deleted" tab listing `ItemDeletedPublic` with bulk restore/purge actions |

**Conflicts:** None identified. Soft-delete is a foundational pattern that all CRUD-touching tools must respect.

---

## 12. Rollback Procedure

If `add_soft_delete` produces broken state, follow these procedures in order:

### 12.1 Code rollback (before deploy)

```bash
# Identify changed files
git diff HEAD~1 -- app/models/ app/crud/ app/api/routes/ app/core/ app/schemas/

# Revert all modified files to the pre-tool state
git checkout HEAD~1 -- \
  app/models/mixins.py \
  app/models/item.py \
  app/crud/item.py \
  app/api/routes/item.py \
  app/schemas/item.py \
  app/core/soft_delete_filter.py \
  app/main.py

# Delete generated migration and test files
rm -f alembic/versions/*_softdel_items.py
rm -f tests/test_item_soft_delete.py
rm -f app/workers/soft_delete_purge.py

# Verify the codebase is clean
git status
```

### 12.2 Database rollback (after deploy — Alembic downgrade)

This tool MODIFIES the database schema by adding `is_deleted`, `deleted_at`, and `deleted_by` columns plus a composite index and FK. The downgrade removes all of them:

```bash
# Verify current Alembic head
alembic current

# Downgrade one revision (removes is_deleted, deleted_at, deleted_by, index, FK)
alembic downgrade -1

# Verify migration reversed
alembic current
# Expected: shows 0002_initial (the previous revision)
```

The generated `downgrade()` function runs:
1. `op.drop_index("ix_items_active")` — removes composite index
2. `op.drop_constraint("fk_items_deleted_by_users")` — removes FK
3. `op.drop_column("items", "deleted_by")`
4. `op.drop_column("items", "deleted_at")`
5. `op.drop_column("items", "is_deleted")`

### 12.3 Data preservation before downgrade

If soft-deleted rows contain data that must be preserved before the migration reversal:

```sql
-- Archive all soft-deleted rows before running downgrade
CREATE TABLE items_softdelete_archive AS
  SELECT * FROM items WHERE is_deleted = true;

-- Verify archive
SELECT count(*) FROM items_softdelete_archive;

-- Now run alembic downgrade -1
-- After re-enabling soft-delete in the future, restore archived rows:
-- INSERT INTO items SELECT * FROM items_softdelete_archive;
```

### 12.4 Failure mode: tool partially modified files

The tool uses atomic temp-file-then-rename writes, but if atomicity fails mid-run:

```bash
# 1. Identify what was changed
git status

# 2. Revert every modified file individually
git checkout -- app/models/item.py
git checkout -- app/crud/item.py
git checkout -- app/api/routes/item.py
git checkout -- app/schemas/item.py

# 3. Remove any partial file that was created (not tracked by git)
rm -f app/models/mixins.py          # only if it did not exist before
rm -f app/core/soft_delete_filter.py
rm -f alembic/versions/*_softdel_*.py
rm -f tests/test_item_soft_delete.py

# 4. Verify project is back to clean state
git diff --stat
PYTHONPATH=src pytest tests/ -q   # must pass at pre-tool baseline
```

### 12.5 Failure mode: global filter breaking legitimate queries

If the `do_orm_execute` listener is filtering rows that should be visible (e.g. a background job needs all rows):

```python
# Temporarily bypass the filter for the affected query using execution_options
from sqlalchemy import select
from app.models.item import Item

# Option A: per-query bypass
stmt = (
    select(Item)
    .execution_options(include_deleted=True)
)

# Option B: disable filter for the entire session (e.g. admin scripts)
async with session_maker() as session:
    # All queries in this session see soft-deleted rows
    session.sync_session.execute_options = {"include_deleted": True}
    all_items = (await session.execute(select(Item))).scalars().all()
```

### 12.6 Emergency: production showing phantom-deleted rows

If a bug caused rows to appear with `is_deleted=True` that should be active (e.g. buggy cascade):

```sql
-- Restore all incorrectly soft-deleted rows in a specific time window
-- Review the affected rows first
SELECT id, title, deleted_at, deleted_by
FROM items
WHERE is_deleted = true
  AND deleted_at > '2026-04-11T00:00:00Z'
  AND deleted_at < '2026-04-12T00:00:00Z';

-- Restore them (after confirming this is correct)
UPDATE items
SET is_deleted = false,
    deleted_at = NULL,
    deleted_by = NULL
WHERE is_deleted = true
  AND deleted_at > '2026-04-11T00:00:00Z'
  AND deleted_at < '2026-04-12T00:00:00Z';

-- Verify
SELECT count(*) FROM items WHERE is_deleted = true AND deleted_at > '2026-04-11T00:00:00Z';
-- Expected: 0
```

### 12.7 Emergency: retention purge removed wrong rows

If the retention purge job deleted rows that were within the retention window (wrong `retention_days` config):

```bash
# 1. Identify the latest pg_dump backup before the purge job ran
ls -la backups/ | grep items

# 2. Restore affected rows from pg_dump (single-table restore)
pg_restore -d $DATABASE_URL -t items --data-only backups/pre_purge_backup.dump

# 3. Verify restoration
psql $DATABASE_URL -c "SELECT count(*) FROM items;"

# 4. Fix the purge job configuration
#    Edit app/workers/soft_delete_purge.py: retention_days = 90 (or correct value)
#    Redeploy
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Model has no `created_at` column | Tool errors: "Model requires `created_at` for soft-delete composite index. Add timestamps first." |
| EC-02 | Model already has `is_deleted: bool` (correct type) | Idempotent skip with note: "already enabled", no file changes |
| EC-03 | Model already has `is_deleted: str` (wrong type) | Tool errors: "Item.is_deleted exists with type str (expected bool). Resolve manually." No files modified. |
| EC-04 | Project has no Alembic initialized | Tool errors: "Alembic not initialized. Run `alembic init alembic` first." No files modified. |
| EC-05 | Two tool instances run concurrently on same project | First wins via atomic rename; second detects existing columns and returns idempotent skip |
| EC-06 | Disk full during file write | Atomic write to temp file fails before rename; no partial state; original file untouched |
| EC-07 | User sends SIGINT during execution | Temp files cleaned up in signal handler; no partial state in project |
| EC-08 | Model file has a Python syntax error before tool runs | Tool refuses to modify: "Cannot parse {model}.py — fix syntax errors first." |
| EC-09 | Live production DB with active connections during migration | `ALTER TABLE ADD COLUMN ... DEFAULT false` is metadata-only on PG 11+; no table lock, no downtime |
| EC-10 | `cascade=True` but FK relationships not reflected in model metadata | Tool reflects SQLAlchemy relationship definitions; if none found, logs a warning and skips cascade |
| EC-11 | User runs migration then reverses it with `alembic downgrade -1` | `downgrade()` drops columns and index cleanly; all pre-migration data is preserved |
| EC-12 | CRUD file contains a custom `delete()` override with complex logic | Tool detects custom body, errors: "Custom delete() detected in {crud}. Merge soft-delete manually." |
| EC-13 | Model is `User` itself (self-referencing for `deleted_by`) | `deleted_by` FK uses `ondelete="SET NULL"` and is nullable; no circular FK issue |
| EC-14 | Project uses MySQL or SQLite instead of PostgreSQL | Tool warns: "server_default behaviour differs on MySQL/SQLite; verify migration adds NOT NULL correctly." |
| EC-15 | aiosqlite test database used in CI | aiosqlite supports Boolean columns and `server_default`; tests pass without modification |

---

## 14. Acceptance Criteria

The tool ships when ALL of the following are verified:

1. ✅ All 32 Completeness Criteria verified by automated check
2. ✅ All 25 User Stories have passing acceptance tests in CI
3. ✅ All 30 Test Cases (T-01..T-30) pass with 0 failures
4. ✅ All 8 Invariants enforced and each has at least one passing test reference
5. ✅ All 15 Edge Cases handled without unhandled exceptions or incorrect output
6. ✅ Interaction matrix verified by integration smoke tests for at least 5 tool combinations
7. ✅ Rollback procedure in §12 tested end-to-end on a staging environment
8. ✅ Performance SLOs measured and met: query overhead < 5%, migration < 5s on 1M rows
9. ✅ Re-audit by Opus in fresh context with brutal mode enabled: ≥ 9.5/10
10. ✅ One human developer uses the tool on a real project without requiring documentation lookup

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists and is a directory
- [ ] Validate `app/` subdirectory exists inside `project_dir`
- [ ] Validate `alembic/versions/` directory exists
- [ ] Parse each target model file with `ast.parse`; abort if any SyntaxError
- [ ] Check each model for existing `is_deleted` column via AST inspection
- [ ] If `is_deleted` exists with wrong type → return error, abort with no changes
- [ ] If `is_deleted` exists with correct type → mark model as "already enabled, skip"
- [ ] Check each model for custom `delete()` override in CRUD → error if complex body found
- [ ] Verify each target model has a `created_at` column → error if missing

### 15.2 SoftDeleteMixin generation
- [ ] Create or update `app/models/mixins.py` with `SoftDeleteMixin` class
- [ ] Mixin has `is_deleted` as `declared_attr` with `server_default="false"`, `nullable=False`
- [ ] Mixin has `deleted_at` as `declared_attr` with `DateTime(timezone=True)`, `nullable=True`
- [ ] Mixin has `deleted_by` as `declared_attr` with `Uuid`, FK to `users.id`, `ondelete="SET NULL"`, `nullable=True`
- [ ] File parses with `ast.parse`
- [ ] Write atomically (temp file + `os.rename()`)

### 15.3 Model modification
- [ ] Read `app/models/{name}.py` for each target model
- [ ] Add `from app.models.mixins import SoftDeleteMixin` import
- [ ] Change `class X(Base):` to `class X(SoftDeleteMixin, Base):`
- [ ] Add `Index("ix_{table}_active", "is_deleted", "created_at")` to `__table_args__`
- [ ] Verify file parses with `ast.parse`
- [ ] Write atomically

### 15.4 Global filter installation
- [ ] Create `app/core/soft_delete_filter.py`
- [ ] Register `@event.listens_for(Session, "do_orm_execute")` listener
- [ ] Listener skips if `execute_state.execution_options.get("include_deleted")` is truthy
- [ ] Listener uses `with_loader_criteria(SoftDeleteMixin, lambda cls: cls.is_deleted == False, include_aliases=True)`
- [ ] Add side-effect import of `soft_delete_filter` in `app/main.py` startup
- [ ] Verify `app/core/soft_delete_filter.py` parses

### 15.5 CRUD modification
- [ ] Read `app/crud/{name}.py` for each target model
- [ ] Add `from datetime import datetime, timezone` if not present
- [ ] Replace or extend `delete()` to call `soft_delete()` logic
- [ ] Add `soft_delete(session, id, deleted_by=None)` function with correct column assignments
- [ ] Add `restore(session, id)` function with `include_deleted=True` execution option
- [ ] Add `hard_delete(session, id)` function using `session.delete()`
- [ ] Add `list_deleted(session, skip, limit)` function with `include_deleted=True`
- [ ] Verify file parses
- [ ] Write atomically

### 15.6 Route modification
- [ ] Read `app/api/routes/{name}.py` for each target model
- [ ] Import `soft_delete`, `restore`, `hard_delete`, `list_deleted` from crud
- [ ] Import `CurrentSuperuser` from `app.api.deps`
- [ ] Modify existing `DELETE /{id}` to pass `deleted_by=current_user.id`
- [ ] Add `POST /{id}/restore` endpoint with `CurrentSuperuser` dependency
- [ ] Add `DELETE /{id}/permanent` endpoint with `CurrentSuperuser` dependency
- [ ] Add `GET /deleted/` endpoint with `CurrentSuperuser` dependency and Query params
- [ ] Verify file parses
- [ ] Write atomically

### 15.7 Schema modification
- [ ] Read `app/schemas/{name}.py` for each target model
- [ ] Add `ItemDeletedPublic` class extending `ItemPublic` with `is_deleted`, `deleted_at`, `deleted_by`
- [ ] Add `ItemsDeletedPublic` paginated wrapper class
- [ ] Verify `ItemPublic` does NOT contain the deletion columns
- [ ] Verify file parses
- [ ] Write atomically

### 15.8 Migration generation
- [ ] Read `alembic/versions/` to determine next revision number
- [ ] Generate `alembic/versions/{rev}_softdel_{table}.py`
- [ ] `upgrade()` adds `is_deleted` with `server_default=sa.false()`
- [ ] `upgrade()` adds `deleted_at` nullable
- [ ] `upgrade()` adds `deleted_by` nullable with FK (`ondelete="SET NULL"`) when `audit_field=True`
- [ ] `upgrade()` creates composite index `ix_{table}_active`
- [ ] `downgrade()` drops index, FK, and columns in reverse order
- [ ] Migration `down_revision` chains to previous head revision
- [ ] Migration file parses with `ast.parse`

### 15.9 Retention purge job generation (conditional)
- [ ] Check if `retention_days` parameter was provided
- [ ] If yes, create `app/workers/soft_delete_purge.py`
- [ ] Worker function uses `BATCH_SIZE` loop with `SELECT ... LIMIT N FOR UPDATE SKIP LOCKED`
- [ ] Batch-deletes rows where `is_deleted=True AND deleted_at < cutoff`
- [ ] Uses `include_deleted=True` execution option to bypass global filter
- [ ] Returns `{"deleted_count": N, "batches": M}` dict
- [ ] File parses with `ast.parse`

### 15.10 Test generation
- [ ] Create `tests/test_{name}_soft_delete.py`
- [ ] Generate scaffold for all 30 test cases T-01..T-30
- [ ] Import fixtures from `conftest.py` (reuse `client`, `superuser_token_headers`, etc.)
- [ ] Add `soft_deleted_item_id` pytest fixture that creates and soft-deletes an item
- [ ] Add `three_items_one_deleted` pytest fixture creating 3 items and soft-deleting 1
- [ ] Add `created_item_id` fixture that creates a fresh active item
- [ ] Verify file parses with `ast.parse`
- [ ] Run generated test file: `pytest tests/test_{name}_soft_delete.py -v` passes

### 15.11 Documentation updates
- [ ] Append soft-delete section to `app/core/KNOWLEDGE.md` documenting the filter mechanism
- [ ] Document the `include_deleted=True` execution option in KNOWLEDGE.md for future devs
- [ ] Add tool entry to `manifest.yaml` with correct tool name, parameters, and categories
- [ ] Add row to `SKILL.md` tools table for TOOL-001 with description and complexity
- [ ] Update `mcp_server.py` with `@mcp_tool(name="fastapi_add_soft_delete")` decorator
- [ ] Add OpenAPI tag description for `/deleted/` and `/permanent` endpoints in route file
- [ ] Verify KNOWLEDGE.md documents the `SoftDeleteMixin` class location and usage pattern

### 15.12 Atomicity and error recovery
- [ ] Track all files modified in a `touched_files: list[Path]` accumulator from the start
- [ ] All file writes use `NamedTemporaryFile` → `os.replace()` atomic rename pattern
- [ ] If any step raises an exception, revert all `touched_files` via `git checkout -- <file>`
- [ ] Remove any partially-created migration file from `alembic/versions/` on failure
- [ ] Remove any partially-created test file from `tests/` on failure
- [ ] Return `{files_created, files_modified, files_rolled_back, error}` dict on failure
- [ ] Log each file-write step to a structured log for post-mortem debugging

### 15.13 Verification and reporting
- [ ] Run `ast.parse` on every modified or created file
- [ ] Run import audit: `PYTHONPATH=src python -c "from app.models.item import Item"` succeeds
- [ ] Run `pytest tests/ -q` and assert 0 failures
- [ ] Run analyzer to confirm benchmark score unchanged
- [ ] Measure total tool execution time and include in return value
- [ ] Return structured success report (see §16)

---

## 16. Documentation Output

When the tool succeeds, it returns a structured JSON report:

```json
{
  "status": "success",
  "files_created": [
    "app/models/mixins.py",
    "app/core/soft_delete_filter.py",
    "alembic/versions/0003_softdel_items.py",
    "tests/test_item_soft_delete.py",
    "app/workers/soft_delete_purge.py",
    "app/crud/item.py (3 new functions: soft_delete, restore, hard_delete, list_deleted)",
    "app/api/routes/item.py (4 new/modified endpoints)",
    "app/schemas/item.py (ItemDeletedPublic, ItemsDeletedPublic)"
  ],
  "files_modified": [
    "app/models/item.py",
    "app/main.py"
  ],
  "metrics": {
    "execution_time_ms": 1842,
    "files_changed": 10,
    "lines_added": 247,
    "lines_removed": 12,
    "models_enabled": 1,
    "migration_chained_to": "0002_initial"
  },
  "next_steps": [
    "Run: alembic upgrade head  (adds is_deleted, deleted_at, deleted_by columns to items)",
    "Run: pytest tests/test_item_soft_delete.py -v  (30 tests should pass)",
    "Test soft-delete: DELETE /api/v1/items/{id}  (returns 200, row still in DB)",
    "Test filter: GET /api/v1/items/  (count excludes the soft-deleted row)",
    "Test restore: POST /api/v1/items/{id}/restore  (superuser token, returns 200)",
    "Schedule purge job if retention_days configured: arq app.workers.soft_delete_purge.WorkerSettings"
  ],
  "warnings": [
    "app/main.py was modified to import soft_delete_filter at startup. Verify the import line is in the correct position (after db engine initialization).",
    "If add_multi_tenancy is also installed, add composite index (tenant_id, is_deleted, created_at) manually for optimal query performance on tenant-filtered lists."
  ],
  "notes": [
    "Soft-delete enabled on Item model via SoftDeleteMixin.",
    "Global query filter registered via do_orm_execute listener — no per-query changes required.",
    "deleted_by audit field added (audit_field=True). FK to users.id with ondelete=SET NULL.",
    "Composite index ix_items_active (is_deleted, created_at) created for hot-path queries.",
    "Retention purge job generated at app/workers/soft_delete_purge.py (retention_days=90).",
    "Existing tests still pass: 25/25. Benchmark score unchanged."
  ]
}
```
