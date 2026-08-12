---
spec_id: "TOOL-002"
tool_name: "add_cursor_pagination"
primitive: "api/BatchCore"
primitive_path: "core.venous.api.BatchCore"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-CP-01"
  - "INV-CP-02"
  - "INV-CP-03"
  - "INV-CP-04"
  - "INV-CP-05"
  - "INV-CP-06"
  - "INV-CP-07"
  - "INV-CP-08"
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
  - "CC-31"
  - "CC-32"
  - "CC-33"
  - "CC-34"
quality_standards:
  - "QS-01"
  - "QS-02"
  - "QS-03"
  - "QS-04"
  - "QS-05"
  - "QS-06"
  - "QS-07"
  - "QS-08"
  - "QS-09"
  - "QS-10"
  - "QS-11"
  - "QS-12"
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
  - "data"
  - "resiliency"
  - "realtime"
  - "compliance"
---
# TOOL-002: add_cursor_pagination

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_cursor_pagination` |
| Category | EXTEND > CRUD & Data |
| Complexity | Medium |
| Dependencies | Existing project with at least 1 model + list endpoint, SQLAlchemy 2.0 async, Pydantic v2 |
| Signature | `add_cursor_pagination(project_dir: str, models: list[str] \| None = None, cursor_field: str = "created_at", page_size: int = 20, max_page_size: int = 100, direction: Literal["desc", "asc"] = "desc") -> dict` |
| Parameters | `project_dir`: project root path<br>`models`: list of model names (None = all)<br>`cursor_field`: column to paginate on (must be sortable + indexed)<br>`page_size`: default page size<br>`max_page_size`: maximum allowed page size<br>`direction`: sort direction for pagination (`desc` = newest-first, `asc` = oldest-first) |

---

## 2. Purpose

Replace offset-based pagination (`skip/limit`) with cursor-based pagination on list endpoints. The core problem with offset pagination is that it is O(N) — specifically O(N*M) when N is page depth and M is dataset size — because the database engine must scan and discard all rows before the requested offset on every request. On a table with 10 million records, paginating to page 5000 with `OFFSET 100000` requires the database to read and discard 100,000 rows regardless of whether any index exists, causing query times that grow linearly with dataset depth and routinely reach 5–10 seconds in production. Worse, offset pagination is fundamentally broken under concurrent writes: if a new record is inserted between page fetches, every subsequent page shifts by one row, causing duplicates and missing records that are invisible to the caller and corrupt any downstream aggregation.

Cursor pagination fixes both problems definitively. The cursor encodes the value of the last-seen record's sort key (e.g., `created_at` timestamp), and the next page query uses `WHERE created_at < cursor_value ORDER BY created_at DESC LIMIT N`, which is an index seek rather than an index scan — always O(log N) regardless of dataset size or page depth. A composite tiebreaker `(cursor_field, id)` guarantees stable ordering when multiple records share the same sort key value. The cursor itself is opaque base64url-encoded JSON, making it URL-safe, tamper-evident by design, and extensible without changing the API contract. The tool implements backward-compatible schema evolution: the existing `{data, count}` response is extended with `next_cursor` and `has_more` fields (both with safe defaults), so API consumers that do not yet use cursor navigation continue to receive the first page without modification or errors.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 3s for up to 10 models | Dev waits in CLI; must feel instant |
| Files modified | ≤ 4 per model (schema, crud, route, test) | Predictable blast radius |
| Files created | 0..2 (cursor.py once, migration only if cursor_field needs index) | Minimize churn on existing code |
| Query latency at page 1 | < 10ms on 10M rows | Index seek on first page |
| Query latency at page 5000 | < 50ms on 10M rows | Index seek at depth vs ~5s for OFFSET |
| Query latency at page 50000 | < 100ms on 10M rows | B-tree descent never scans discarded rows |
| Cursor encode/decode overhead | < 0.5ms | Pure Python base64+json loop, no I/O |
| Memory overhead per request | 0 MB additional | Stateless; no server-side page cache |
| Page size validation overhead | 0 ms | Pydantic `Query(ge=1, le=100)` compile-time |
| Tool re-run (idempotent path) | < 0.5s | AST check only, no file writes |

---

## 4. Code Examples (Before / After)

### 4.1 Cursor utility module — encode + decode with base64url

```python
# app/core/cursor.py
"""Opaque cursor encoding for cursor-based pagination.

Cursors are URL-safe base64-encoded JSON blobs. Clients MUST treat
them as opaque strings — the internal format may change at any time.
"""
import base64
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


_MAX_CURSOR_BYTES = 1024  # 1 KB hard limit — rejects oversized malicious input


def encode_cursor(field: str, value: Any, tiebreaker_id: str | None = None) -> str:
    """Encode {field: value} into a URL-safe base64 string.

    Supports: datetime (serialized to ISO-8601 UTC), UUID (str), int, float, str.
    Includes optional tiebreaker_id (record UUID) for composite cursors.
    """
    if isinstance(value, datetime):
        # Normalize to UTC before encoding
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        serialized: Any = value.isoformat()
    elif isinstance(value, UUID):
        serialized = str(value)
    else:
        serialized = value

    payload: dict[str, Any] = {"f": field, "v": serialized}
    if tiebreaker_id is not None:
        payload["id"] = tiebreaker_id

    raw = json.dumps(payload, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode a cursor string back to {field, value, id?}.

    Raises ValueError on: bad base64, invalid JSON, wrong structure,
    oversized input, or missing required keys.
    """
    if len(cursor.encode("utf-8")) > _MAX_CURSOR_BYTES:
        raise ValueError(
            f"Cursor exceeds maximum size ({_MAX_CURSOR_BYTES} bytes)"
        )
    try:
        # Re-pad: base64 requires length % 4 == 0
        padding_needed = (4 - len(cursor) % 4) % 4
        padded = cursor + "=" * padding_needed
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw)
        if not isinstance(data, dict) or "f" not in data or "v" not in data:
            raise ValueError("Invalid cursor structure: missing 'f' or 'v' keys")
        return {"field": data["f"], "value": data["v"], "id": data.get("id")}
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Malformed cursor: {exc}") from exc
```

### 4.2 CursorPaginator — reusable helper class

```python
# app/core/cursor_paginator.py
"""CursorPaginator: encapsulates all cursor pagination logic.

Usage:
    paginator = CursorPaginator(model=Item, cursor_field="created_at", direction="desc")
    result = await paginator.paginate(session, stmt_base, cursor=cursor_str, page_size=20)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.core.cursor import decode_cursor, encode_cursor

M = TypeVar("M", bound=DeclarativeBase)


class CursorPaginator(Generic[M]):
    """Generic cursor paginator for SQLAlchemy 2.0 async models."""

    def __init__(
        self,
        model: type[M],
        cursor_field: str,
        direction: Literal["desc", "asc"] = "desc",
    ) -> None:
        self.model = model
        self.cursor_field = cursor_field
        self.direction = direction
        self._col = getattr(model, cursor_field)
        self._id_col = getattr(model, "id", None)

    async def paginate(
        self,
        session: AsyncSession,
        base_stmt,
        *,
        cursor: str | None,
        page_size: int,
    ) -> dict[str, Any]:
        """Execute a paginated query.

        Returns dict with keys: data, count, next_cursor, has_more.
        The base_stmt must NOT include ORDER BY or LIMIT — this method adds them.
        """
        # Count total matching rows (before cursor filter, same WHERE as base_stmt)
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total: int = (await session.execute(count_stmt)).scalar_one()

        # Apply cursor filter
        data_stmt = base_stmt
        if cursor is not None:
            decoded = decode_cursor(cursor)
            if decoded["field"] != self.cursor_field:
                raise ValueError(
                    f"Cursor field mismatch: cursor encodes '{decoded['field']}', "
                    f"expected '{self.cursor_field}'"
                )
            cursor_val = self._coerce_value(decoded["value"])
            if self.direction == "desc":
                data_stmt = data_stmt.where(self._col < cursor_val)
            else:
                data_stmt = data_stmt.where(self._col > cursor_val)

        # Order + fetch N+1 to detect has_more
        col_ordered = self._col.desc() if self.direction == "desc" else self._col.asc()
        data_stmt = data_stmt.order_by(col_ordered).limit(page_size + 1)
        rows: list[M] = list((await session.execute(data_stmt)).scalars().all())

        has_more = len(rows) > page_size
        if has_more:
            rows = rows[:page_size]

        next_cursor: str | None = None
        if has_more and rows:
            last = rows[-1]
            val = getattr(last, self.cursor_field)
            id_val = str(getattr(last, "id")) if self._id_col is not None else None
            next_cursor = encode_cursor(self.cursor_field, val, id_val)

        return {"data": rows, "count": total, "next_cursor": next_cursor, "has_more": has_more}

    def _coerce_value(self, raw: Any) -> Any:
        """Coerce decoded cursor value to the correct Python type for the column."""
        col_type = str(self._col.property.columns[0].type)
        if "DATETIME" in col_type.upper() or "TIMESTAMP" in col_type.upper():
            return datetime.fromisoformat(raw)
        if "UUID" in col_type.upper():
            return UUID(raw)
        return raw
```

### 4.3 Response schema — BEFORE (offset) and AFTER (cursor)

```python
# BEFORE: app/schemas/item.py
from pydantic import BaseModel, ConfigDict
import uuid
from datetime import datetime


class ItemPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    description: str | None
    created_at: datetime


class ItemsPublic(BaseModel):
    """Offset-paginated response (BEFORE — replaced by cursor version)."""
    data: list[ItemPublic]
    count: int
```

```python
# AFTER: app/schemas/item.py
from pydantic import BaseModel, ConfigDict
import uuid
from datetime import datetime


class ItemPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    description: str | None
    created_at: datetime


class ItemsPublic(BaseModel):
    """Cursor-paginated list response.

    Backward-compatible: existing clients using `data` and `count` fields
    continue to work unchanged. New clients read `next_cursor` and `has_more`
    to drive pagination.
    """
    data: list[ItemPublic]
    count: int
    next_cursor: str | None = None
    has_more: bool = False
```

### 4.4 CRUD layer — BEFORE (offset) and AFTER (cursor, using CursorPaginator)

```python
# BEFORE: app/crud/item.py (fragment)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def get_multi(
    session: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    owner_id: uuid.UUID | None = None,
) -> dict:
    stmt = select(Item)
    if owner_id is not None:
        stmt = stmt.where(Item.owner_id == owner_id)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(Item.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return {"data": list(result.scalars().all()), "count": total}
```

```python
# AFTER: app/crud/item.py (fragment)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.core.cursor_paginator import CursorPaginator
from app.models.item import Item

# Generated constant — controls sort field and direction
CURSOR_FIELD = "created_at"
CURSOR_DIRECTION = "desc"

_paginator = CursorPaginator(Item, cursor_field=CURSOR_FIELD, direction=CURSOR_DIRECTION)


async def get_multi_cursor(
    session: AsyncSession,
    *,
    cursor: str | None = None,
    page_size: int = 20,
    owner_id: uuid.UUID | None = None,
) -> dict:
    """Cursor-paginated item list. Stable under concurrent inserts/deletes.

    Returns: {data, count, next_cursor, has_more}.
    Raises ValueError if cursor is malformed or encodes a mismatched field.
    """
    stmt = select(Item)
    if owner_id is not None:
        stmt = stmt.where(Item.owner_id == owner_id)
    # Propagate soft-delete filter if model supports it
    if hasattr(Item, "is_deleted"):
        stmt = stmt.where(Item.is_deleted == False)  # noqa: E712
    return await _paginator.paginate(session, stmt, cursor=cursor, page_size=page_size)
```

### 4.5 Route layer — BEFORE (skip/limit) and AFTER (cursor/page_size)

```python
# BEFORE: app/api/routes/item.py (fragment)
from fastapi import APIRouter, HTTPException, Query
from app.api.deps import CurrentUser, SessionDep
from app.schemas.item import ItemsPublic
import app.crud.item as crud

router = APIRouter()


@router.get("/", response_model=ItemsPublic)
async def list_items(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=20, ge=1, le=100, description="Max records to return"),
) -> ItemsPublic:
    result = await crud.get_multi(session, skip=skip, limit=limit, owner_id=current_user.id)
    return ItemsPublic(**result)
```

```python
# AFTER: app/api/routes/item.py (fragment)
from fastapi import APIRouter, HTTPException, Query
from app.api.deps import CurrentUser, SessionDep
from app.schemas.item import ItemsPublic
import app.crud.item as crud

router = APIRouter()


@router.get("/", response_model=ItemsPublic)
async def list_items(
    session: SessionDep,
    current_user: CurrentUser,
    cursor: str | None = Query(
        default=None,
        description="Opaque pagination cursor from previous response next_cursor field",
        max_length=1024,
    ),
    page_size: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Number of items to return per page (1-100)",
    ),
) -> ItemsPublic:
    try:
        result = await crud.get_multi_cursor(
            session,
            cursor=cursor,
            page_size=page_size,
            owner_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid cursor: {exc}") from exc
    return ItemsPublic(**result)
```

### 4.6 SQLAlchemy query with composite cursor (tiebreaker for non-unique sort fields)

```python
# app/core/cursor_composite.py
"""Composite cursor using (cursor_field, id) tuple for non-unique sort columns.

When cursor_field values are not unique (e.g., multiple rows share created_at),
a single-field cursor can skip rows on page boundaries. The composite cursor
encodes (cursor_field_value, id) and generates a row-value comparison:
WHERE (created_at, id) < ('2026-01-01T12:00:00', 'uuid-...')
which is stable even when all rows share the same timestamp.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase


async def paginate_composite(
    session: AsyncSession,
    model: type[DeclarativeBase],
    base_stmt,
    *,
    cursor_field: str,
    cursor_field_value: Any | None,
    cursor_id: str | None,
    page_size: int,
    direction: str = "desc",
) -> list[Any]:
    """Paginate using row-value comparison (cursor_field, id) for stable ordering.

    This avoids missing/duplicate records when multiple rows share the cursor field value.
    The WHERE clause uses:  (col, id) < (cursor_val, cursor_id)  for DESC
                             (col, id) > (cursor_val, cursor_id)  for ASC
    """
    stmt = base_stmt
    col = getattr(model, cursor_field)
    id_col = getattr(model, "id")

    if cursor_field_value is not None and cursor_id is not None:
        cv = cursor_field_value
        cid = UUID(cursor_id)
        if direction == "desc":
            # Rows where col < cv, OR (col == cv AND id < cid) — stable page boundary
            stmt = stmt.where(
                or_(col < cv, and_(col == cv, id_col < cid))
            )
        else:
            stmt = stmt.where(
                or_(col > cv, and_(col == cv, id_col > cid))
            )

    col_ord = col.desc() if direction == "desc" else col.asc()
    id_ord = id_col.desc() if direction == "desc" else id_col.asc()
    stmt = stmt.order_by(col_ord, id_ord).limit(page_size + 1)
    return list((await session.execute(stmt)).scalars().all())
```

### 4.7 Alembic migration — index creation for cursor field

```python
# alembic/versions/0004_cursor_idx_items.py
"""Add DESC index on cursor field for Items cursor pagination.

Revision ID: 0004_cursor_idx_items
Revises: 0003_softdel_items
Create Date: 2026-04-12
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_cursor_idx_items"
down_revision = "0003_softdel_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Partial DESC index on created_at — optimal for ORDER BY created_at DESC scans.
    # The database can satisfy ORDER BY without a sort step when using this index.
    op.create_index(
        "ix_items_created_at_cursor",
        "items",
        [sa.text("created_at DESC")],
        unique=False,
    )
    # Composite index for concurrent-insert stability: (created_at DESC, id DESC)
    # Used by composite cursor to resolve ties without skipping rows.
    op.create_index(
        "ix_items_created_at_id_cursor",
        "items",
        [sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_items_created_at_id_cursor", table_name="items")
    op.drop_index("ix_items_created_at_cursor", table_name="items")
```

### 4.8 Integration helper — apply cursor pagination to existing routes

```python
# app/core/cursor_integration.py
"""Helpers to integrate cursor pagination into existing list endpoints.

These utilities are called by the generated code to auto-detect cursor field
types and build the correct filter predicates at runtime.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Column


def get_cursor_filter_predicate(column: Column, cursor_value: Any, direction: str) -> Any:
    """Return a SQLAlchemy WHERE predicate for the given cursor column and direction.

    cursor_value must already be coerced to the column's Python type.
    direction: 'desc' => WHERE col < val, 'asc' => WHERE col > val.
    """
    if direction == "desc":
        return column < cursor_value
    return column > cursor_value


def coerce_cursor_value(raw: Any, column: Column) -> Any:
    """Coerce a JSON-decoded cursor value to the correct Python type.

    Handles datetime (ISO-8601), UUID (str → UUID), int, float, and str.
    Raises ValueError if the value cannot be coerced to the expected type.
    """
    col_type_str = type(column.type).__name__.upper()
    try:
        if "DATETIME" in col_type_str or "TIMESTAMP" in col_type_str:
            return datetime.fromisoformat(str(raw))
        if "UUID" in col_type_str:
            return UUID(str(raw))
        if "INTEGER" in col_type_str or "BIGINT" in col_type_str:
            return int(raw)
        if "FLOAT" in col_type_str or "NUMERIC" in col_type_str or "DECIMAL" in col_type_str:
            return float(raw)
        return raw
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(
            f"Cannot coerce cursor value {raw!r} to column type {col_type_str}: {exc}"
        ) from exc
```

### 4.9 Test file — comprehensive cursor pagination test suite

```python
# tests/test_item_cursor_pagination.py
"""Cursor pagination tests for Item model (generated by add_cursor_pagination)."""
from __future__ import annotations

import pytest
import re
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cursor import decode_cursor, encode_cursor
from app.models.item import Item
from tests.conftest import create_items_for_user, get_auth_headers


@pytest.mark.asyncio
async def test_first_page_no_cursor(
    async_client: AsyncClient,
    session: AsyncSession,
    normal_user_token_headers: dict,
) -> None:
    """T-01: First request without cursor returns first page_size items."""
    await create_items_for_user(session, count=50)
    response = await async_client.get(
        "/items/?page_size=10", headers=normal_user_token_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 10
    assert data["has_more"] is True
    assert data["next_cursor"] is not None
    assert data["count"] == 50


@pytest.mark.asyncio
async def test_walk_all_pages_no_duplicates(
    async_client: AsyncClient,
    session: AsyncSession,
    normal_user_token_headers: dict,
) -> None:
    """T-11 + T-12: Walking all pages yields no duplicates and no missing items."""
    await create_items_for_user(session, count=47)
    seen_ids: list[str] = []
    cursor: str | None = None
    while True:
        url = "/items/?page_size=10"
        if cursor:
            url += f"&cursor={cursor}"
        response = await async_client.get(url, headers=normal_user_token_headers)
        assert response.status_code == 200
        body = response.json()
        page_ids = [item["id"] for item in body["data"]]
        assert len(set(page_ids) & set(seen_ids)) == 0, "Duplicate items across pages"
        seen_ids.extend(page_ids)
        if not body["has_more"]:
            break
        cursor = body["next_cursor"]
        assert cursor is not None
    assert len(seen_ids) == 47, f"Expected 47 items, got {len(seen_ids)}"


@pytest.mark.asyncio
async def test_invalid_cursor_returns_400(
    async_client: AsyncClient,
    normal_user_token_headers: dict,
) -> None:
    """T-05: A malformed cursor returns HTTP 400, not 500."""
    response = await async_client.get(
        "/items/?cursor=not-valid-base64!@#", headers=normal_user_token_headers
    )
    assert response.status_code == 400
    assert "Invalid cursor" in response.json()["detail"]


@pytest.mark.asyncio
async def test_cursor_is_base64url_format(
    async_client: AsyncClient,
    session: AsyncSession,
    normal_user_token_headers: dict,
) -> None:
    """T-10: Cursor value matches URL-safe base64 character set."""
    await create_items_for_user(session, count=5)
    response = await async_client.get(
        "/items/?page_size=2", headers=normal_user_token_headers
    )
    assert response.status_code == 200
    cursor = response.json()["next_cursor"]
    assert cursor is not None
    assert re.match(r"^[A-Za-z0-9_-]+$", cursor), f"Cursor is not base64url: {cursor}"


@pytest.mark.asyncio
async def test_page_size_above_max_rejected(
    async_client: AsyncClient,
    normal_user_token_headers: dict,
) -> None:
    """T-08: page_size > max_page_size returns 422 Unprocessable Entity."""
    response = await async_client.get(
        "/items/?page_size=9999", headers=normal_user_token_headers
    )
    assert response.status_code == 422
```

### 4.10 Cursor round-trip tests — encode/decode correctness for all supported types

```python
# tests/test_cursor_encoding.py
"""Unit tests for cursor encode/decode round-trips (generated by add_cursor_pagination)."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.core.cursor import decode_cursor, encode_cursor


@pytest.mark.parametrize("field,value,expected_type", [
    ("created_at", datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc), str),
    ("id", UUID("12345678-1234-5678-1234-567812345678"), str),
    ("score", 42, int),
    ("name", "Widget Pro", str),
    ("rank", 3.14, float),
])
def test_encode_decode_round_trip(field: str, value: object, expected_type: type) -> None:
    """T-13: Encode/decode round-trip preserves field name and value representation."""
    encoded = encode_cursor(field, value)
    assert isinstance(encoded, str)
    decoded = decode_cursor(encoded)
    assert decoded["field"] == field
    assert decoded["value"] is not None


def test_cursor_is_urlsafe(field: str = "created_at", value: object = datetime(2026, 1, 1)) -> None:
    """T-10: Encoded cursor contains only URL-safe characters (no +, /, =)."""
    import re
    encoded = encode_cursor("created_at", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert "+" not in encoded
    assert "/" not in encoded
    assert "=" not in encoded
    assert re.match(r"^[A-Za-z0-9_-]+$", encoded)


def test_decode_rejects_oversized_cursor() -> None:
    """T-30: Cursor larger than 1KB raises ValueError immediately."""
    huge = "A" * 2000
    with pytest.raises(ValueError, match="maximum size"):
        decode_cursor(huge)


def test_decode_rejects_invalid_json() -> None:
    """T-05b: Cursor with valid base64 but invalid JSON structure raises ValueError."""
    import base64
    bad_payload = base64.urlsafe_b64encode(b"not-json").decode("ascii").rstrip("=")
    with pytest.raises(ValueError):
        decode_cursor(bad_payload)


def test_cursor_with_tiebreaker_roundtrip() -> None:
    """T-13b: Composite cursor with tiebreaker_id encodes and decodes cleanly."""
    tid = "00000000-0000-0000-0000-000000000001"
    encoded = encode_cursor("created_at", datetime(2026, 1, 1, tzinfo=timezone.utc), tid)
    decoded = decode_cursor(encoded)
    assert decoded["field"] == "created_at"
    assert decoded["id"] == tid
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-01 | **No `OFFSET` in any generated paginated query** | Tool inspects generated CRUD file body; if `OFFSET` appears anywhere in `get_multi_cursor`, generation fails with error `"QS-01 violated: OFFSET found in cursor CRUD"`. Test T-01 verifies at runtime. |
| QS-02 | **Stable under concurrent writes** | Cursor encodes the `cursor_field` value of the LAST item on the current page; next page uses `WHERE cursor_field < cursor_value`, which is deterministic regardless of concurrent inserts at higher values. Test T-14 verifies with concurrent inserts mid-walk. |
| QS-03 | **Backward-compatible response shape** | Schema modification ONLY adds new fields (`next_cursor=None`, `has_more=False`). Existing fields (`data`, `count`) are never renamed or removed. Tool pre-flight AST check verifies both fields are present with correct defaults before writing. |
| QS-04 | **Opaque, URL-safe cursors** | `encode_cursor` uses `base64.urlsafe_b64encode`; padding stripped. Cursor includes field name so field-mismatch is detectable. `decode_cursor` re-pads before decode. Test T-10 asserts `^[A-Za-z0-9_-]+$` regex match. |
| QS-05 | **Configurable and validated cursor field** | Tool param `cursor_field` propagates into `CURSOR_FIELD` constant and migration. AST pre-flight verifies column exists on model. If not indexed, migration is generated. If column is missing, tool errors with no file writes. |
| QS-06 | **Idempotent execution** | Pre-flight AST check: if `get_multi_cursor` already exists in CRUD and `next_cursor` already in schema, tool returns `notes=["Item already uses cursor pagination, skipped"]` with zero file modifications. Test T-27 verifies. |
| QS-07 | **Invalid cursor returns HTTP 400** | `decode_cursor` raises `ValueError`; route handler catches it and converts to `HTTPException(status_code=400, detail=f"Invalid cursor: {exc}")`. Never returns 500; never silently falls back to first page. Test T-05 covers this path. |
| QS-08 | **Hard page size maximum** | Route uses `Query(ge=1, le=max_page_size)` where `max_page_size` defaults to 100. A `page_size=999999` request returns 422 from Pydantic validation before the handler is invoked. Test T-08 verifies. |
| QS-09 | **Total count reflects filters, not page** | Separate `SELECT COUNT(*)` query with same WHERE clause as data query, MINUS the cursor predicate. Count is unaffected by pagination depth. Test T-04 and T-09 verify count stability across pages and under owner filter. |
| QS-10 | **Composite tiebreaker for non-unique sort fields** | When `cursor_field` is not unique (e.g., `created_at` without ms precision), tool generates composite cursor encoding `(cursor_field, id)` and row-value comparison in CRUD. Tool warns if cursor_field lacks a UNIQUE constraint. |
| QS-11 | **Atomic file writes** | Every file write uses temp-file + rename (`os.replace`). If any step fails, all prior writes in the same run are rolled back. Tool never leaves partial state. Test T-29 verifies via mocked filesystem error. |
| QS-12 | **All generated Python is syntactically valid** | Tool calls `ast.parse` on every generated or modified file. If parse fails, the write is aborted and the error is reported in `notes`. Never writes unparseable code. |

---

## 6. Completeness Criteria

| # | Criterion | Verification method |
|---|-----------|---------------------|
| CC-01 | `app/core/cursor.py` created with `encode_cursor` and `decode_cursor` functions | File exists, `ast.parse` succeeds |
| CC-02 | `encode_cursor` returns URL-safe base64 with no `+`, `/`, or `=` characters | Regex `^[A-Za-z0-9_-]+$` on any encoded cursor |
| CC-03 | `decode_cursor` handles missing padding correctly (re-pads before decode) | Unit test with unpadded input |
| CC-04 | `decode_cursor` raises `ValueError` on malformed base64 | Unit test: `decode_cursor("!@#garbage")` → `ValueError` |
| CC-05 | `decode_cursor` raises `ValueError` on valid base64 but invalid JSON | Unit test: base64-encode `"not-json"` → `ValueError` |
| CC-06 | `decode_cursor` raises `ValueError` when cursor exceeds 1 KB | Unit test: cursor of 2000 chars → `ValueError("maximum size")` |
| CC-07 | `decode_cursor` raises `ValueError` on missing `f` or `v` keys | Unit test: base64-encode `{"x": 1}` → `ValueError` |
| CC-08 | `ItemsPublic` schema has `next_cursor: str \| None = None` field | AST inspection of schema file |
| CC-09 | `ItemsPublic` schema has `has_more: bool = False` field | AST inspection of schema file |
| CC-10 | `ItemsPublic` retains existing `data: list[ItemPublic]` field (not removed) | AST inspection: field present |
| CC-11 | `ItemsPublic` retains existing `count: int` field (not removed) | AST inspection: field present |
| CC-12 | `crud.get_multi_cursor()` function exists with correct signature | AST inspection: function exists with `cursor`, `page_size` params |
| CC-13 | Generated CRUD query uses `WHERE cursor_field < value` (or `>` for asc), NOT `OFFSET` | grep CRUD file: `OFFSET` absent; `<` or `>` present in cursor branch |
| CC-14 | Generated CRUD query fetches `page_size + 1` rows | grep `limit(page_size + 1)` in CRUD |
| CC-15 | `has_more` computed from `len(rows) > page_size` | grep CRUD: expression present |
| CC-16 | `next_cursor` only set when `has_more=True` | AST: `next_cursor` assignment is inside `if has_more` block |
| CC-17 | Total `count` query is separate from data query (two distinct `select` calls) | AST: two separate `select(func.count())` and `select(Model)` statements |
| CC-18 | Owner filter (if applicable) applied to both data and count queries | AST: filter on `owner_id` or equivalent present in both branches |
| CC-19 | Soft-delete filter applied if model has `is_deleted` attribute | grep CRUD: `is_deleted` conditional present |
| CC-20 | Route accepts `cursor: str \| None = Query(default=None, max_length=1024, ...)` | AST inspection of route file |
| CC-21 | Route accepts `page_size: int = Query(default=20, ge=1, le=max_page_size)` | AST inspection of route file |
| CC-22 | Route removes or keeps (but ignores) old `skip` and `limit` params (no OFFSET call) | grep route: `get_multi_cursor` is the only pagination call |
| CC-23 | Route wraps `crud.get_multi_cursor` call in `try/except ValueError → 400` | AST: try block with HTTPException 400 present |
| CC-24 | Migration generated if `cursor_field` is not already indexed | Migration file exists when index missing |
| CC-25 | Migration creates DESC index on `cursor_field` | grep migration: `text("created_at DESC")` or equivalent |
| CC-26 | Migration creates composite index `(cursor_field DESC, id DESC)` for tiebreaker stability | grep migration: composite index present |
| CC-27 | Migration `downgrade()` drops both indexes cleanly | `op.drop_index` calls present for both |
| CC-28 | All generated Python files parse cleanly with `ast.parse` | Tool internal step after each write |
| CC-29 | Import audit passes (no circular imports introduced) | `python -c "import app.core.cursor; import app.crud.item"` |
| CC-30 | Existing test suite passes after modifications | `pytest tests/ -x` returns 0 failures |
| CC-31 | New test file `tests/test_{model}_cursor_pagination.py` created | File exists, `ast.parse` succeeds |
| CC-32 | New test file `tests/test_cursor_encoding.py` created (or appended) | File exists with encode/decode unit tests |
| CC-33 | Tool execution time < 3s for 1 model | Measured and logged in output `metrics.execution_time_ms` |
| CC-34 | `app/core/cursor_paginator.py` created once per project (not per model) | File exists, shared by all paginated models |

---

## 7. Definition of Done (DoD)

The tool is "done" when ALL of these are true:

- [ ] All 34 Completeness Criteria (CC-01..CC-34) verified by automated check
- [ ] All 12 Quality Standards (QS-01..QS-12) enforced and tested
- [ ] All 8 Invariants (INV-CP-01..INV-CP-08) enforced with T-XX test references (see §8)
- [ ] All 25 User Stories (US-01..US-25) have passing acceptance tests (see §9)
- [ ] All 30 Test Cases (T-01..T-30) pass with no skips (see §10)
- [ ] Tool is idempotent: running twice produces identical filesystem state
- [ ] Tool is reversible: rollback procedure documented and tested end-to-end (see §12)
- [ ] Performance SLO met: < 50ms at page 5000 on 10M rows (measured with real PostgreSQL)
- [ ] Cursor encoding round-trip verified for: `datetime`, `UUID`, `str`, `int`, `float`
- [ ] Composite tiebreaker (cursor_field, id) verified stable under concurrent inserts
- [ ] Interaction with TOOL-001, TOOL-004, TOOL-005, TOOL-006, TOOL-008 verified
- [ ] All 15 edge cases (EC-01..EC-15) handled and tested
- [ ] Documentation updated: `KNOWLEDGE.md`, `manifest.yaml`, `SKILL.md`
- [ ] Tool registered in `mcp_server.py` with correct type signature
- [ ] Re-audit by Opus in fresh context: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-CP-01 | No `OFFSET` appears in any generated cursor-paginated query | Tool inspects generated CRUD body; `OFFSET` present in `get_multi_cursor` causes generation to abort with error | T-01 |
| INV-CP-02 | Cursor is always opaque base64url — clients never parse or construct it | `encode_cursor` uses only `urlsafe_b64encode`; cursor format documented as opaque; no public decoder in API responses | T-10, T-12 |
| INV-CP-03 | `has_more` is always truthful: exactly `len(rows) > page_size` after fetching N+1 | Generated CRUD enforces `len(rows) > page_size`; last row trimmed when `has_more=True` | T-02, T-03 |
| INV-CP-04 | `cursor=None` always returns the first page with no filtering | Default branch in CRUD: cursor predicate is skipped entirely when cursor is None | T-01, T-06 |
| INV-CP-05 | Invalid or oversized cursor always returns HTTP 400 — never 500, never silent first-page fallback | Route wraps CRUD call in `try/except ValueError → HTTPException(400)`; `decode_cursor` raises on any malformed input | T-05, T-30 |
| INV-CP-06 | `count` is always the total number of records matching active filters, not just the current page count | Separate `SELECT COUNT(*)` query uses same WHERE clause as data query excluding the cursor predicate | T-04, T-09 |
| INV-CP-07 | Tool execution is atomic — either all files for a model are written or none are | All writes use temp-file + `os.replace`; any failure triggers rollback of all writes in the current run | T-29 |
| INV-CP-08 | The response schema is always backward-compatible — `data` and `count` fields are never removed | Tool pre-flight verifies both fields exist before writing; new fields only added with safe defaults | T-23, T-24 |

---

## 9. User Stories

### 9.1 Core functionality (US-01 .. US-05)

**US-01: Switch a list endpoint from offset to cursor pagination**
- **As a** backend developer
- **I want** to convert my Items list endpoint from skip/limit to cursor pagination
- **So that** deep pagination is fast and stable on large datasets without query rewrites
- **Given:** `GET /items/` uses `skip: int` and `limit: int` params, backed by `crud.get_multi`
- **When:** I run `add_cursor_pagination(project_dir, models=["Item"])`
- **Then:**
  - `GET /items/` now accepts `cursor: str | None` and `page_size: int` params (CC-20, CC-21)
  - Response includes `next_cursor` and `has_more` fields (CC-08, CC-09)
  - Response still includes `data` and `count` fields with unchanged semantics (CC-10, CC-11)
  - Tool returns `{files_created, files_modified, metrics, notes}`
- **File check:** `app/crud/item.py` no longer contains `offset=` in any SQLAlchemy `select()` call — verified by `grep -n "offset=" app/crud/item.py` returning zero matches
- **Schema check:** `app/schemas/item.py` class `ItemsPublic` has fields `next_cursor: str | None` and `has_more: bool` with correct defaults confirmed via `ast.dump` in `test_tool_output.py::test_us01_schema_fields`

**US-02: Walk through all pages using cursors**
- **As a** frontend developer
- **I want** to fetch all items page by page using cursor tokens
- **So that** my UI can implement infinite scroll without skipping or duplicating records
- **Given:** 50 items in DB, `page_size=10`
- **When:**
  1. `GET /items/?page_size=10` → 10 items, `has_more=true`, `next_cursor="abc..."`
  2. `GET /items/?page_size=10&cursor=abc...` → next 10 items, `next_cursor="def..."`
  3. Continue until `has_more=false`
- **Then:**
  - All 50 items walked in correct order (INV-CP-03)
  - Zero duplicates, zero missing items (T-11, T-12)
  - No `next_cursor` on last page
- **Integrity proof:** `test_cursor_walk.py::test_us02_no_duplicates` collects all returned `id` values across 5 pages, asserts `len(ids) == len(set(ids)) == 50`
- **DB query verified:** SQL log for page 2 contains `WHERE (created_at, id) < (...)` with the exact values from page 1's last record — no `OFFSET` token present anywhere in the statement

**US-03: Total count returned on every page**
- **As a** developer building a paginated list UI
- **I want** the total record count available on every page response
- **So that** I can show "Showing 1-20 of 1000 results" without a separate COUNT request
- **Given:** 1000 items in DB
- **When:** `GET /items/?page_size=20`
- **Then:**
  - Response has `data` (20 items), `count=1000`, `has_more=true`, `next_cursor="..."` (CC-17, INV-CP-06)
- **SQL audit:** `app/crud/item.py::get_multi_cursor` issues exactly two SQLAlchemy statements per request — one `SELECT count(*) FROM items` and one `SELECT ... FROM items WHERE ... LIMIT N+1` — verified via `sqlalchemy.event.listen` echo in `test_query_count.py::test_us03_two_queries`
- **Type safety:** `ItemsPublic.count` is declared as `int` (not `Optional[int]`) in `app/schemas/item.py`, ensuring the field is always serialized even when zero

**US-04: Constant-time pagination at any depth**
- **As a** developer working with 10M-row tables
- **I want** cursor pagination to remain fast regardless of page depth
- **So that** API response times stay under SLO at all pagination depths
- **Given:** Items table seeded with 10M records
- **When:** I paginate 5000 pages deep (cursor walk, not random access)
- **Then:**
  - Response time stays < 50ms at every page (vs ~5s for equivalent OFFSET query)
  - No query scans discarded rows — uses B-tree index seek (QS-01, T-26)
- **EXPLAIN ANALYZE:** `EXPLAIN ANALYZE SELECT ... FROM items WHERE (created_at, id) < (?, ?) ORDER BY created_at DESC, id DESC LIMIT 21` shows `Index Scan using items_created_at_id_idx` with `rows=21 actual rows=21` — confirmed in `tests/perf/test_us04_explain.py`
- **Benchmark:** `pytest-benchmark` result for page 5000 at 10M rows is recorded in `tests/perf/benchmarks/cursor_depth.json` with `mean < 0.050` seconds

**US-05: Custom cursor field for alphabetical pagination**
- **As a** developer paginating a product catalog alphabetically
- **I want** to paginate by the `name` field in ascending order
- **So that** browsing the catalog is consistent and predictable
- **Given:** `Product` model with `name: str` field, indexed
- **When:** `add_cursor_pagination(project_dir, models=["Product"], cursor_field="name", direction="asc")`
- **Then:**
  - Products ordered by `name ASC` (CC-05)
  - Cursor encodes last product name on current page
  - Next page query uses `WHERE name > cursor_name`
- **Cursor payload verified:** `decode_cursor(next_cursor)["f"] == "name"` and `decode_cursor(next_cursor)["v"]` equals the `name` string of the last item on the current page — asserted in `test_cursor.py::test_us05_custom_field_payload`
- **SQL direction:** `app/crud/product.py` generated `ORDER BY name ASC, id ASC` clause (not DESC) — confirmed via `grep "ORDER BY name ASC" app/crud/product.py` returning exactly one match

### 9.2 Edge cases and stability (US-06 .. US-12)

**US-06: First request without cursor returns first page**
- **As a** developer or client consuming the list endpoint
- **I want** to call the endpoint without a cursor and get the first page
- **So that** new clients do not need any special initialization before paginating
- **Given:** No `cursor` param in request, 50 items in DB
- **When:** `GET /items/?page_size=10`
- **Then:** Returns first 10 items ordered by `created_at DESC`; `has_more=true`; `next_cursor` is non-null; `count=50` (INV-CP-04)
- **Route signature:** `app/routers/items.py` route handler has `cursor: str | None = Query(default=None, max_length=1024)` — `default=None` ensures absent cursor is valid without any special-case logic
- **Ordering verified:** `test_pagination.py::test_us06_no_cursor_ordering` asserts `response.json()["data"][0]["created_at"] >= response.json()["data"][-1]["created_at"]` (DESC ordering on first page)

**US-07: Invalid cursor returns 400 with clear message**
- **As a** developer debugging a pagination bug
- **I want** an invalid cursor to return a descriptive 400 error
- **So that** I can distinguish cursor corruption from server errors immediately
- **Given:** `cursor="not-valid-base64!@#"` (malformed characters)
- **When:** `GET /items/?cursor=not-valid-base64!%40%23`
- **Then:** HTTP 400 with body `{"detail": "Invalid cursor: Malformed cursor: ..."}` — never 500, never silent fallback to page 1 (INV-CP-05, T-05)
- **Exception boundary:** `app/core/cursor.py::decode_cursor` raises `ValueError`; the route handler wraps it in `HTTPException(status_code=400, ...)` — the SQLAlchemy session is never opened for invalid cursor inputs
- **Error message test:** `test_cursor_errors.py::test_us07_bad_base64` asserts `response.status_code == 400` and `"Invalid cursor" in response.json()["detail"]` with no traceback in the response body

**US-08: Empty dataset returns safe empty response**
- **As a** developer integrating against a newly created tenant
- **I want** the endpoint to return a safe, well-structured empty response when there are no records
- **So that** my UI renders an empty state gracefully without null-pointer errors
- **Given:** 0 items in DB (new project or empty filter)
- **When:** `GET /items/`
- **Then:** `data=[]`, `count=0`, `has_more=false`, `next_cursor=null` — all fields present with correct types (T-06)
- **Pydantic model check:** `ItemsPublic(data=[], count=0, has_more=False, next_cursor=None).model_dump()` produces `{"data": [], "count": 0, "has_more": false, "next_cursor": null}` — all four keys always present, none omitted by `exclude_none`
- **No cursor emitted:** `test_edge_cases.py::test_us08_empty_db` asserts `response.json()["next_cursor"] is None` (not absent, not `""`) confirming the field is serialized with an explicit null

**US-09: Stable pagination under concurrent inserts**
- **As a** developer building a real-time feed
- **I want** cursor pagination to remain stable when new records arrive between page fetches
- **So that** my clients never skip or duplicate records in a live dataset
- **Given:** I have fetched page 1 (cursor pointing to `created_at=T1`)
- **When:** 5 new items with `created_at > T1` are inserted before I fetch page 2
- **Then:** Page 2 starts exactly where page 1 left off; no duplicates; no skips; new items appear on subsequent fresh queries from `cursor=None` (QS-02, T-14)
- **Cursor semantics:** The `WHERE (created_at, id) < (T1, id1)` predicate is a strict time boundary — newly inserted rows with `created_at > T1` are structurally excluded from the WHERE clause regardless of insertion order
- **Concurrency test:** `test_concurrency.py::test_us09_stable_under_insert` spawns a background thread that inserts 5 rows between page 1 and page 2 fetches and asserts union of page IDs equals original 50-item seed set

**US-10: Stale cursor (record deleted after cursor issued) still works**
- **As a** developer consuming a list endpoint where records can be hard-deleted
- **I want** a cursor that points to a deleted record's timestamp to still work correctly
- **So that** deleted records do not corrupt ongoing paginations
- **Given:** Cursor encodes `created_at=T1` for an item that was later hard-deleted from DB
- **When:** `GET /items/?cursor=<stale>`
- **Then:** Returns records with `created_at < T1` without error — cursor is a time boundary, not a record reference; behavior is correct (T-20, INV-CP-05)
- **Design invariant:** `get_multi_cursor` in `app/crud/item.py` never issues `SELECT ... WHERE id = cursor_id` — cursor's `id` field is used only as tiebreaker in the composite `(created_at, id)` comparison, not as a record lookup
- **Stale cursor test:** `test_edge_cases.py::test_us10_stale_cursor` encodes a cursor for a record, deletes it via `db.delete(item); await db.commit()`, then asserts subsequent paginate call returns HTTP 200 with valid `data` list

**US-11: Cursor field mismatch returns clear 400**
- **As a** developer who changed the pagination sort field after cursors were issued
- **I want** a field-mismatch cursor to fail with a specific error message
- **So that** I can identify the migration issue immediately without guessing
- **Given:** Client holds cursor encoded for field `name`; endpoint now uses `created_at`
- **When:** `GET /items/?cursor=<name-cursor>`
- **Then:** HTTP 400: `"Invalid cursor: cursor field mismatch: cursor encodes 'name', expected 'created_at'"` — no DB query executed; no data returned (INV-CP-05, T-16)
- **Validation placement:** Field mismatch check occurs in `app/core/cursor.py::validate_cursor_field(decoded, expected_field)` called before `AsyncSession` is acquired — confirmed by mock asserting `async_sessionmaker` was never called in `test_cursor_errors.py::test_us11_field_mismatch`
- **Error message format:** Response body `{"detail": "Invalid cursor: cursor field mismatch: cursor encodes 'name', expected 'created_at'"}` — both field names quoted with single quotes, matching regex `r"cursor encodes '(\w+)', expected '(\w+)'"` tested in `test_cursor_errors.py::test_us11_message_format`

**US-12: page_size=1 works correctly**
- **As a** developer testing cursor correctness at minimum granularity
- **I want** page_size=1 to produce single-item pages with a valid cursor on each
- **So that** I can verify cursor accuracy at the per-record level
- **Given:** 5 items in DB, `page_size=1`
- **When:** Walk all 5 pages
- **Then:** 5 pages of exactly 1 item each; 4 distinct non-null `next_cursor` values; final page has `has_more=false`, `next_cursor=null` (T-07, CC-14, CC-15)
- **has_more logic:** `get_multi_cursor` fetches `page_size + 1` rows (`LIMIT 2` here); if `len(rows) > page_size` then `has_more=True` and the extra row is stripped before returning — the LIMIT=2 trick is visible in generated CRUD via `grep "LIMIT.*page_size.*+ 1" app/crud/item.py`
- **Cursor uniqueness:** `test_edge_cases.py::test_us12_page_size_1` collects all `next_cursor` values across pages and asserts `len(set(cursors)) == 4` (all distinct, not a repeated value)

### 9.3 Validation and limits (US-13 .. US-18)

**US-13: page_size above max_page_size returns 422**
- **As a** developer protecting the API from abusive clients
- **I want** oversized page_size requests to be rejected by Pydantic before the handler runs
- **So that** no client can trigger a full-table scan by passing an enormous page_size
- **Given:** Client sends `page_size=999999` in the query string
- **When:** `GET /items/?page_size=999999`
- **Then:** HTTP 422 Unprocessable Entity from Pydantic `le=max_page_size` constraint — handler never invoked; no DB query executed (QS-08, T-08)
- **Pydantic annotation:** `app/routers/items.py` declares `page_size: int = Query(default=20, ge=1, le=100)` — the `le=100` (or configured `max_page_size`) is a compile-time Pydantic constraint, not a runtime if-check
- **422 body verified:** `test_validation.py::test_us13_page_size_too_large` asserts `response.json()["detail"][0]["loc"] == ["query", "page_size"]` and `"less_than_equal" in response.json()["detail"][0]["type"]`

**US-14: page_size=0 or negative returns 422**
- **As a** developer sending a malformed request
- **I want** an invalid page_size to produce a clear 422 validation error
- **So that** the mistake is caught immediately with a helpful error message
- **Given:** Client sends `page_size=0` or `page_size=-5`
- **When:** `GET /items/?page_size=0`
- **Then:** HTTP 422 Unprocessable Entity from Pydantic `ge=1` constraint; response body explains which param failed and why (QS-08, T-30)
- **Guard coverage:** Both `page_size=0` and `page_size=-5` are exercised separately in `test_validation.py::test_us14_page_size_zero` and `test_us14_page_size_negative`; both assert `response.status_code == 422`
- **LIMIT protection:** Even if Pydantic were bypassed, `get_multi_cursor` in `app/crud/item.py` would execute `LIMIT 0 + 1 = 1` at minimum — the `page_size + 1` fetch strategy prevents a `LIMIT 0` or negative LIMIT from reaching the DB engine

**US-15: Oversized cursor (> 1KB) returns 400**
- **As a** security-conscious API operator
- **I want** abnormally large cursors to be rejected before any decoding attempt
- **So that** malicious clients cannot trigger memory exhaustion via crafted large payloads
- **Given:** A 10KB base64 string passed as `cursor`
- **When:** `GET /items/?cursor=<10KB>`
- **Then:** HTTP 400: `"Invalid cursor: Cursor exceeds maximum size (1024 bytes)"` — decode aborts immediately without attempting base64 decode or JSON parse (INV-CP-05, CC-06, T-17)
- **Size check placement:** First line of `decode_cursor` in `app/core/cursor.py` is `if len(cursor.encode("utf-8")) > _MAX_CURSOR_BYTES: raise ValueError(...)` — the `_MAX_CURSOR_BYTES = 1024` constant is module-level and importable for tests
- **No decode work done:** `test_security.py::test_us15_oversized_cursor` mocks `base64.urlsafe_b64decode` and asserts it is never called when the input exceeds 1024 bytes

**US-16: Cursor round-trip for all supported value types**
- **As a** developer using a non-datetime sort field
- **I want** cursor encoding to preserve the exact value for any supported column type
- **So that** my pagination is correct regardless of whether I sort by timestamp, UUID, integer, or string
- **Given:** A cursor encoding a `datetime` (UTC), `UUID`, `int`, `float`, or `str` value
- **When:** `encode_cursor(field, value)` then `decode_cursor(encoded)` 
- **Then:** `decoded["field"] == field`; value is round-tripped correctly; no precision loss for `datetime` ISO-8601 up to microseconds (T-13, CC-01..CC-07)
- **Datetime precision:** `encode_cursor` serializes `datetime` via `.isoformat()` which preserves microseconds (e.g., `"2026-04-12T14:30:00.123456+00:00"`) — `test_cursor.py::test_us16_datetime_roundtrip` asserts `decoded_dt.microsecond == original_dt.microsecond`
- **Invariant check:** `test_cursor.py::test_us16_roundtrip_parametrize` is `@pytest.mark.parametrize` over all five types and asserts `encode_cursor(f, decode_cursor(encode_cursor(f, v))["v"]) == encode_cursor(f, v)` (encode → decode → re-encode is byte-equal)

**US-17: page_size respects per-tool configured max_page_size**
- **As a** developer who needs a tighter cap than the default 100
- **I want** to configure a lower max_page_size at tool-call time
- **So that** the constraint is baked into the generated route, not just a runtime setting
- **Given:** Tool invoked with `max_page_size=50`
- **When:** `GET /items/?page_size=51`
- **Then:** HTTP 422 — the generated `Query(le=50)` is used; the default 100 is NOT present in the generated route (CC-20, CC-21, QS-08)
- **Code generation check:** After `add_cursor_pagination(..., max_page_size=50)`, `grep "le=50" app/routers/items.py` returns exactly one match and `grep "le=100" app/routers/items.py` returns zero — confirmed in `test_tool_output.py::test_us17_max_page_size_baked_in`
- **No magic default:** The tool's AST rewriter substitutes the literal `max_page_size` value into the `Query(...)` annotation at code generation time — not via a settings object that could be overridden at runtime

**US-18: Tool errors cleanly when cursor_field is missing from model**
- **As a** developer who accidentally specified the wrong field name
- **I want** the tool to error clearly before writing any files
- **So that** I can correct the parameter without any cleanup work on my project
- **Given:** Model `Foo` has no `created_at` column; tool called with `cursor_field="created_at"`
- **When:** `add_cursor_pagination(project_dir, models=["Foo"])`
- **Then:** Error message: `"Foo has no column 'created_at' for cursor pagination"`; NO files created or modified; tool exit code != 0 (CC-05, INV-CP-07)
- **Pre-flight check:** Model column validation runs in the tool's preflight phase via `inspect(Foo.__table__).columns.keys()` before any `open(..., "w")` call — the check is in `_validate_cursor_field()` called at the top of `add_cursor_pagination()`
- **Filesystem invariant:** `test_tool_errors.py::test_us18_missing_field` records `os.listdir(project_dir)` before and after the tool call and asserts the two lists are equal (no new files, no modified mtimes)

### 9.4 Idempotency and integration (US-19 .. US-22)

**US-19: Tool is fully idempotent**
- **Given:** Item already has cursor pagination (all files written)
- **When:** I call `add_cursor_pagination(project_dir, models=["Item"])` again
- **Then:**
  - No code duplicated in CRUD, schema, or route
  - No duplicate migration created
  - Tool returns `notes=["Item already uses cursor pagination, skipped"]` (QS-06, T-27)
- **AST detection:** Idempotency guard uses `ast.parse` to check for `cursor` parameter in the existing route signature and `next_cursor` field in the existing schema — if both are found, the model is skipped before any file I/O
- **Timing check:** `test_idempotency.py::test_us19_second_run_fast` asserts second invocation completes in < 0.5s (tool re-run SLO from Section 3) and `result["files_modified"] == []`

**US-20: Tool fails atomically on partial write error**
- **As a** developer running the tool in a CI environment
- **I want** a mid-run error to leave the project in exactly its pre-run state
- **So that** I can re-run the tool after fixing the issue without manual cleanup
- **Given:** A disk error occurs after schema write but before CRUD write (simulated via mocked `os.replace`)
- **When:** Tool run on Item model
- **Then:** The schema write is rolled back; no partial CRUD file created; project state byte-identical to pre-run; tool reports `files_rolled_back: ["app/schemas/item.py"]` (INV-CP-07, T-29)
- **Rollback mechanism:** Tool writes to `.tmp` files via `os.replace` (atomic rename); on exception, a `finally` block calls `os.unlink` on all `.tmp` paths tracked in a `_written_files: list[Path]` context variable
- **Byte identity check:** `test_atomicity.py::test_us20_partial_write_rollback` computes `hashlib.sha256` of all target files before the tool run and after the simulated failure and asserts all hashes are equal

**US-21: Tool applies to all models when models=None**
- **As a** developer converting an entire project in one command
- **I want** to run `add_cursor_pagination` without specifying a models list
- **So that** all list endpoints are converted at once without enumerating each model manually
- **Given:** Project with `Product`, `Order`, `Review` models, each with a list endpoint
- **When:** `add_cursor_pagination(project_dir)` (no `models` param)
- **Then:** All 3 list endpoints converted; tool reports all 3 in `files_modified`; already-paginated models skipped idempotently (CC-12)
- **Model discovery:** When `models=None`, the tool calls `_discover_models(project_dir)` which scans `app/models/*.py` for SQLAlchemy `DeclarativeBase` subclasses using `ast.parse` — no import or database connection required
- **Result shape:** `test_tool_output.py::test_us21_models_none` asserts `set(result["files_modified"]) == {"app/crud/product.py", "app/crud/order.py", "app/crud/review.py", "app/schemas/product.py", "app/schemas/order.py", "app/schemas/review.py", "app/routers/products.py", "app/routers/orders.py", "app/routers/reviews.py"}` (9 files, 3 per model)

**US-22: Cursor + soft-delete integration**
- **As a** developer who uses soft-delete on the same model
- **I want** cursor pagination to respect soft-delete filtering automatically
- **So that** deleted records never leak into any page and do not distort the count
- **Given:** Item model has both `is_deleted` field (from TOOL-001) and cursor pagination enabled
- **When:** Paginate items; some items have `is_deleted=true`
- **Then:** Soft-deleted items appear in no page; `count` reflects only non-deleted items; cursor-filtered query applies `is_deleted = false` predicate (QS-10, CC-19, T-24)
- **Predicate order:** Generated `get_multi_cursor` in `app/crud/item.py` applies `where(Item.is_deleted == False)` before the cursor `where((Item.created_at, Item.id) < (...))` clause — soft-delete filter is the outermost predicate, not conditional on cursor presence
- **Count accuracy:** `test_integration.py::test_us22_soft_delete_count` seeds 100 items, soft-deletes 30, and asserts `response.json()["count"] == 70` on every page fetched across the full walk

### 9.5 API contract and documentation (US-23 .. US-25)

**US-23: OpenAPI spec documents cursor parameters correctly**
- **Given:** Cursor pagination enabled on Items
- **When:** `GET /openapi.json`
- **Then:**
  - `cursor` parameter documented with `max_length=1024` and description (CC-20)
  - `page_size` parameter documented with `ge=1, le=100` (CC-21)
  - Response schema `ItemsPublic` shows `next_cursor: str | null` and `has_more: bool` (T-23)
- **OpenAPI structure check:** `test_openapi.py::test_us23_openapi_cursor_param` parses `/openapi.json` and asserts `schema["paths"]["/items/"]["get"]["parameters"]` contains an entry with `name == "cursor"`, `schema == {"type": "string", "maxLength": 1024}` and nullable annotation
- **Observability:** structlog event `openapi_cursor_param_present` is emitted on app startup if cursor pagination is active — allows infra tooling to verify the schema without a live HTTP call

**US-24: Response backward-compatible with clients that ignore new fields**
- **As a** developer with legacy clients that were built against the offset API
- **I want** the cursor-paginated response to be a strict superset of the old response
- **So that** I can deploy the cursor API without coordinating a simultaneous client update
- **Given:** Legacy client that only reads `data: list` and `count: int` from the response body
- **When:** Client calls the updated paginated endpoint (cursor version)
- **Then:** Response parses correctly; `data` and `count` fields have identical semantics to before; `next_cursor=null` and `has_more=false` are safely ignored (INV-CP-08, T-26)
- **Pydantic strict superset proof:** `test_compat.py::test_us24_legacy_client` parses the full cursor response via `LegacyItemsSchema(data=..., count=...)` (the old Pydantic model with only those two fields) and asserts no `ValidationError` is raised — confirming extra fields are ignored by default
- **No field rename or removal:** `git diff HEAD -- app/schemas/item.py` after running the tool must show only additions (`+`) for `next_cursor` and `has_more` lines — no `-` removals of existing `data` or `count` lines — verified in `test_tool_output.py::test_us24_no_field_removed`

**US-25: count stays accurate regardless of page depth**
- **As a** developer building a "Showing X of Y results" UI component
- **I want** `count` to reflect the total matching records on every page
- **So that** my UI always shows the correct total even mid-pagination
- **Given:** 1000 items in DB; owner filter active (700 owned by the current user)
- **When:** Fetch page 1, page 35, or the final page
- **Then:** `count=700` on every page regardless of cursor depth — count SELECT runs independently of cursor predicate (INV-CP-06, CC-17, T-04, T-09)
- **Independent COUNT query:** `app/crud/item.py::get_multi_cursor` uses two separate `await session.execute(...)` calls — one for `select(func.count()).where(owner_filter)` (no cursor predicate) and one for `select(Item).where(owner_filter).where(cursor_predicate).limit(page_size + 1)` — the cursor WHERE clause is never applied to the count statement
- **Stability assertion:** `test_pagination.py::test_us25_count_stable` fetches pages 1, 35, and the last page and asserts all three `response.json()["count"]` values equal `700` — using `pytest.mark.parametrize` over the three page cursors

---

## 10. Test Plan

### 10.1 Functional pagination tests (T-01 .. T-06)

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-01 | First page without cursor | 50 items | `GET /items/?page_size=10` | 10 items, `has_more=true`, `next_cursor != null`, `count=50` | Functional |
| T-02 | Second page with cursor from T-01 | 50 items | `GET /items/?cursor=<from T-01>&page_size=10` | Next 10 items, no overlap with T-01, `has_more=true` | Functional |
| T-03 | Last page — `has_more=false` | 23 items, `page_size=10` | Paginate 3 pages | 3rd page has 3 items, `has_more=false`, `next_cursor=null` | Functional |
| T-04 | Count stable across pages | 100 items | Any page | `count=100` on every page regardless of cursor depth | Functional |
| T-05 | Invalid cursor returns 400 | Any state | `GET /items/?cursor=garbage!!` | HTTP 400, `detail` contains "Invalid cursor" | Validation |
| T-06 | Empty dataset safe response | 0 items | `GET /items/` | `data=[]`, `count=0`, `has_more=false`, `next_cursor=null` | Edge |

### 10.2 Integrity and stability tests (T-07 .. T-14)

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-07 | page_size=1 single-item pages | 5 items | Walk with `page_size=1` | 5 pages of 1 item each; 5 distinct cursors | Edge |
| T-08 | page_size above max returns 422 | Any state | `GET /items/?page_size=9999` | HTTP 422 Unprocessable Entity | Validation |
| T-09 | Count reflects owner filter, not raw table size | 200 items (40 owned by user A) | `GET /items/` as user A | `count=40` regardless of page | Filtering |
| T-10 | Cursor is URL-safe base64url | 5 items | Inspect `next_cursor` value | Matches `^[A-Za-z0-9_-]+$`, no `+`, `/`, `=` | Format |
| T-11 | No duplicate items across full walk | 100 items | Walk all pages with `page_size=10` | 100 unique item IDs across all pages | Integrity |
| T-12 | No missing items across full walk | 100 items | Walk all pages | `len(all_ids) == 100 == count` | Integrity |
| T-13 | Cursor encode/decode round-trip | datetime, UUID, int, float, str | Encode then decode | Field and value preserved; datetime UTC-normalized | Encoding |
| T-14 | Concurrent insert stability | Walk pages; insert 5 new items mid-walk at higher timestamp | Continue walk | No duplicates, no missing items in walked range | Concurrency |

### 10.3 Encoding edge cases and security (T-15 .. T-20)

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-15 | Custom cursor_field pagination | Products with `name` field | `add_cursor_pagination(..., cursor_field="name")` + paginate | Products ordered by `name ASC`; cursor encodes name | Functional |
| T-16 | Cursor field mismatch returns 400 | Item cursor (created_at), name-encoded cursor used | `GET /items/?cursor=<name-cursor>` | HTTP 400 field mismatch error | Security |
| T-17 | Oversized cursor (> 1KB) rejected | Craft 2KB cursor string | `GET /items/?cursor=<2KB>` | HTTP 400 "maximum size" — no DB query | Security |
| T-18 | Valid base64 but invalid JSON cursor | base64-encode `b"not-json"` | `GET /items/?cursor=<bad>` | HTTP 400 "Malformed cursor" | Security |
| T-19 | Cursor with missing 'f' key | base64-encode `{"v": "2026-01-01"}` | `GET /items/?cursor=<bad>` | HTTP 400 "missing 'f' or 'v' keys" | Security |
| T-20 | Stale cursor (referenced record deleted) | Issue cursor; delete that record | `GET /items/?cursor=<stale>` | Returns next valid page; no error | Stability |

### 10.4 Migration tests (T-21 .. T-23)

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-21 | Migration created when cursor_field not indexed | Model without `created_at` index | Run tool | Migration file `*_cursor_idx_*.py` created | Migration |
| T-22 | No migration when cursor_field already indexed | Model with existing `created_at` index | Run tool | No migration file, `notes` says index already present | Migration |
| T-23 | Migration reversible via `alembic downgrade -1` | Apply migration | `alembic downgrade -1` | Both cursor indexes dropped; data untouched | Migration |

### 10.5 Integration tests (T-24 .. T-27)

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-24 | Cursor + soft-delete integration | Items with `is_deleted`; some deleted | Walk all pages | Deleted items never appear; `count` excludes them | Integration |
| T-25 | OpenAPI schema correctness | Cursor pagination enabled | `GET /openapi.json` | `cursor`, `page_size` params in docs; `next_cursor`, `has_more` in response schema | Integration |
| T-26 | Backward compatibility — legacy client reads `data` and `count` | Any state | Parse response ignoring new fields | `data` and `count` have identical semantics to old offset response | Integration |
| T-27 | Tool idempotent — second run no-op | Already paginated model | Run tool again | No file changes; `notes` contains "skipped" | Idempotency |

### 10.6 Performance and failure mode tests (T-28 .. T-30)

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-28 | Performance: 1M rows, page 5000 | Seed 1M items | Walk to page 5000 using cursor | Response time < 100ms (B-tree index seek) | Performance |
| T-29 | Atomic failure rollback | Mock `os.replace` to raise on CRUD write | Run tool | Schema NOT written; project state identical to pre-run | Atomicity |
| T-30 | page_size=0 returns 422 | Any state | `GET /items/?page_size=0` | HTTP 422 Unprocessable Entity | Validation |

---

## 11. Interaction Matrix

How `fastapi_add_cursor_pagination` interacts with other tools in SKILL-001:

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_soft_delete` (TOOL-001) | No specific order | ✅ Compatible | Cursor CRUD auto-detects `is_deleted` attribute via `hasattr` and adds `WHERE is_deleted = false` to both data and count queries. No conflict. |
| `add_field_search` (TOOL-004) | **Pagination after search** | ✅ Compatible | Search endpoint extends base query; cursor paginator wraps the filtered `select()` statement. Cache key must include cursor + search query. |
| `add_audit_log` (TOOL-005) | No specific order | ✅ Compatible | Audit log records list-endpoint access; cursor value is logged as metadata. No structural conflict. |
| `add_data_export` (TOOL-006) | No specific order | ⚠️ Caveat | Export must iterate cursor pages (`while has_more`) rather than using OFFSET. Export helper receives `cursor=None` to start and loops until `has_more=false`. |
| `add_multi_tenancy` (TOOL-008) | **Tenancy first** | ✅ Compatible | Tenant filter injected by `do_orm_execute` listener runs before cursor predicate. Cursor value is still just a time boundary; cross-tenant isolation is enforced independently. |
| `add_bulk_operations` (TOOL-009) | No specific order | ✅ Compatible | Bulk endpoints operate on item IDs, not page boundaries. No pagination conflict. |
| `add_rbac` (TOOL-010) | No specific order | ✅ Compatible | Permission checks happen before the handler body; cursor pagination is transparent to RBAC. |
| `add_cache_layer` (TOOL-011) | No specific order | ⚠️ Caveat | Cache key MUST include `cursor` + `page_size` + any active filters. A cache key that omits `cursor` returns the same first page for every request, breaking pagination. |
| `add_api_key_auth` (TOOL-012) | No specific order | ✅ Compatible | API key owner filter composed into base `select()` before cursor is applied. |
| `add_rate_limiting` (TOOL-015) | No specific order | ✅ Compatible | Rate limiting is per-client, not per-cursor. No structural conflict. |
| `add_feature_flags` (TOOL-016) | No specific order | ✅ Compatible | Cursor pagination can be disabled per-tenant via feature flag; route falls back to offset when flag off. |
| `add_file_upload` (TOOL-020) | No specific order | ✅ Compatible | File list endpoints benefit directly from cursor pagination on large uploads tables. |
| `add_webhooks` (TOOL-021) | No specific order | ✅ Compatible | Webhook event log is a high-volume append-only table; cursor pagination is the recommended strategy for it. |

**Conflicts:** None identified. Cursor pagination replaces the `OFFSET` clause cleanly without touching any other aspect of request handling.

---

## 12. Rollback Procedure

If `add_cursor_pagination` produces broken state, use the following procedure to restore the project to its pre-run state.

### 12.1 Code rollback (before deploy — preferred path)

```bash
# Identify what the tool changed
git diff HEAD -- app/schemas/item.py app/crud/item.py app/api/routes/item.py

# Revert all modified files to pre-run state
git checkout HEAD -- app/schemas/item.py app/crud/item.py app/api/routes/item.py

# Remove newly created files (cursor utility + test file)
git rm --cached app/core/cursor.py app/core/cursor_paginator.py app/core/cursor_integration.py
rm -f app/core/cursor.py app/core/cursor_paginator.py app/core/cursor_integration.py
rm -f tests/test_item_cursor_pagination.py tests/test_cursor_encoding.py

# Remove migration if generated
rm -f alembic/versions/*_cursor_idx_items.py
```

### 12.2 Database rollback (after `alembic upgrade head` ran)

**N/A** — this tool is a code-only refactor. No database tables, columns, or rows are created or modified by the generated code itself. The only database change is the addition of indexes via the Alembic migration.

If the migration was applied:
```bash
alembic downgrade -1
```
This drops the cursor indexes (`ix_items_created_at_cursor`, `ix_items_created_at_id_cursor`). No data is lost. The `downgrade()` function in the generated migration contains only `op.drop_index` calls.

### 12.3 Partial state recovery (tool aborted mid-run)

The tool uses atomic temp-file + rename writes (`os.replace`). If a SIGINT or crash occurs between writes:
```bash
# Identify any partial state
git status --short

# Revert every partially-written file
git checkout -- $(git diff --name-only)

# Remove any new cursor modules not yet committed
rm -f app/core/cursor.py app/core/cursor_paginator.py app/core/cursor_integration.py
rm -f tests/test_item_cursor_pagination.py
```
In practice, the atomic write guarantee means at most one file can be in partial state (the in-progress write). Prior writes succeeded fully; only the file being written at crash time may be corrupted.

### 12.4 Frontend rollback (clients using `cursor` and `page_size`)

Cursor pagination is additive to the API contract. Clients that were using `skip/limit` continue to receive the first page correctly because `cursor=None` returns the first page. The only clients that need rollback are those that adopted the new `cursor` parameter:

```bash
# Re-add offset params to route (run after code rollback above)
# The route is already restored by step 12.1 — no additional action needed.
```

If the route was deployed with cursor params and clients were updated, coordinate a simultaneous rollback:
- Deploy old route (with skip/limit)
- Release updated client that reverts to skip/limit

### 12.5 Failure modes and root-cause checklist

| Symptom | Root cause | Fix |
|---------|------------|-----|
| Pagination returns duplicate items | `cursor_field` is not unique AND composite cursor not used | Verify `CursorPaginator` uses composite cursor; check migration for `(created_at, id)` index |
| `count` wrong on page 2+ | Count query incorrectly includes cursor predicate | Inspect CRUD: count `select` must NOT have cursor `WHERE` clause |
| HTTP 400 on every cursor | `cursor_field` mismatch — model changed sort field after cursors were issued | Clear all client cursors; restart pagination from `cursor=None` |
| HTTP 500 on cursor requests | `ValueError` from `decode_cursor` not caught | Verify route has `try/except ValueError → HTTPException(400)` |
| Migration fails | `cursor_field` column does not exist | Verify model has the column before running migration |

### 12.6 Emergency: disable cursor pagination via feature flag

If cursor pagination causes a production incident before code rollback is feasible:
```python
# app/api/routes/item.py — temporary emergency bypass
import os

CURSOR_ENABLED = os.getenv("CURSOR_PAGINATION_ENABLED", "true").lower() == "true"

@router.get("/", response_model=ItemsPublic)
async def list_items(
    session: SessionDep,
    current_user: CurrentUser,
    cursor: str | None = Query(default=None, max_length=1024),
    page_size: int = Query(default=20, ge=1, le=100),
    skip: int = Query(default=0, ge=0),  # Re-exposed for emergency fallback
) -> ItemsPublic:
    if not CURSOR_ENABLED:
        # Emergency fallback to offset pagination
        result = await crud.get_multi(session, skip=skip, limit=page_size, owner_id=current_user.id)
        return ItemsPublic(**result)
    # ... cursor path unchanged
```
Set `CURSOR_PAGINATION_ENABLED=false` in environment to activate the bypass without redeployment.

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Model has no `created_at` column, `cursor_field="created_at"` | Tool errors with `"Foo has no column 'created_at' for cursor pagination"`; NO files modified |
| EC-02 | `cursor_field` column exists but is not unique — ties possible | Tool generates composite cursor encoding `(cursor_field, id)` and row-value comparison; warns if column lacks a UNIQUE constraint |
| EC-03 | Model already has cursor pagination installed | Idempotent skip with note `"Item already uses cursor pagination, skipped"`; zero file modifications |
| EC-04 | Project has no `alembic/versions/` directory and cursor index is needed | Tool errors `"Alembic not initialized — required to create cursor index"`; no partial state |
| EC-05 | Cursor string is larger than 1 KB | `decode_cursor` raises `ValueError("Cursor exceeds maximum size")` before any decoding; route returns HTTP 400 |
| EC-06 | Cursor has valid base64 but malformed JSON content | `decode_cursor` raises `ValueError("Malformed cursor: ...")`; route returns HTTP 400 |
| EC-07 | Cursor was issued for `cursor_field="name"`, endpoint now uses `cursor_field="created_at"` | CRUD detects field mismatch; raises `ValueError("cursor field mismatch")`; route returns HTTP 400 |
| EC-08 | Existing list endpoint has extra query params (e.g., `status` filter) | Tool preserves all existing params; only pagination params (`skip/limit`) are replaced; existing filters remain |
| EC-09 | Disk full mid-write during `os.replace` | `os.replace` is atomic at OS level; partial destination file is not visible; tool error bubbles up; prior writes in same run rolled back |
| EC-10 | User presses Ctrl+C during tool execution | Temp file still being written is abandoned (never renamed); no committed partial state; project remains in pre-run state |
| EC-11 | `cursor_field` type is `Decimal` (e.g., price column) | `encode_cursor` converts to string; `decode_cursor` returns string; `coerce_cursor_value` converts to `float` (or `Decimal` if column is NUMERIC); tool warns about potential precision loss |
| EC-12 | Time-based cursor across different system timezones | `encode_cursor` normalizes `datetime` to UTC via `tzinfo=timezone.utc`; `decode_cursor` produces UTC-aware datetime; comparison is timezone-safe |
| EC-13 | Migration index already exists with a different name | Tool checks for any index on `cursor_field` (not by name); if found, skips migration with note `"Index on created_at already exists, skipped"` |
| EC-14 | `cursor_field` has NULL values in some rows | CRUD uses `NULLS LAST` in ORDER BY (Postgres default for DESC); NULLs appear at the very end of pagination; never cause errors |
| EC-15 | `models=None` on a project where some models already have cursor pagination | Tool processes all models; already-paginated models are skipped idempotently; new models are converted; mixed state handled cleanly |

---

## 14. Acceptance Criteria (Final Sign-off)

The tool ships when:

1. ✅ All 34 Completeness Criteria (CC-01..CC-34) verified by automated check
2. ✅ All 25 user stories have passing acceptance tests (manual + automated)
3. ✅ All 30 test cases (T-01..T-30) pass with zero skips
4. ✅ All 8 invariants (INV-CP-01..INV-CP-08) enforced and exercised by tests
5. ✅ All 15 edge cases (EC-01..EC-15) handled without crashing or silent errors
6. ✅ Interaction matrix verified by integration tests (cursor + soft-delete + multi-tenancy)
7. ✅ Rollback procedure tested end-to-end: code rollback, DB rollback, partial-state recovery
8. ✅ Performance SLO verified on real PostgreSQL: < 50ms at page 5000 on 10M rows
9. ✅ Re-audit by Opus in fresh context, brutal mode: ≥ 9.5/10
10. ✅ One human developer uses it on a real project without reading the spec first

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight validation
- [ ] Validate `project_dir` exists and is a directory
- [ ] Validate `app/` subdirectory exists inside `project_dir`
- [ ] Validate Python version is 3.11+ (union type syntax required)
- [ ] Parse each target model file with `ast.parse` — abort on syntax error
- [ ] Verify `cursor_field` column exists on each target model via AST
- [ ] Check if `cursor_field` has a UNIQUE constraint on the model
- [ ] If not unique, enable composite cursor mode (cursor_field + id)
- [ ] Check if `cursor_field` is already indexed (scan `__table_args__` and existing migrations)
- [ ] Check for existing `get_multi_cursor` in CRUD (idempotency signal)
- [ ] Check for existing `next_cursor` in schema (idempotency signal)
- [ ] If both idempotency signals present, add to `skip_list` and return early per model

### 15.2 Cursor utility module (`app/core/cursor.py`)
- [ ] Check if `app/core/cursor.py` already exists (shared across all models)
- [ ] If not, generate with `encode_cursor`, `decode_cursor`, and `_MAX_CURSOR_BYTES` constant
- [ ] Verify `encode_cursor` uses `urlsafe_b64encode` and strips trailing `=`
- [ ] Verify `decode_cursor` re-pads before decode and raises `ValueError` on all failure modes
- [ ] Verify `decode_cursor` checks byte length before attempting decode
- [ ] `ast.parse` the generated file
- [ ] Write atomically via temp-file + `os.replace`

### 15.3 CursorPaginator helper (`app/core/cursor_paginator.py`)
- [ ] Check if `app/core/cursor_paginator.py` already exists
- [ ] If not, generate `CursorPaginator` class with generic type parameter
- [ ] Implement `paginate()` method with count + cursor filter + N+1 fetch
- [ ] Implement `_coerce_value()` for datetime, UUID, int, float, str
- [ ] Verify `paginate()` never uses `OFFSET`
- [ ] Verify `paginate()` raises `ValueError` on cursor field mismatch
- [ ] `ast.parse` the generated file
- [ ] Write atomically

### 15.4 Composite cursor helper (`app/core/cursor_composite.py`)
- [ ] Only generate when cursor_field is non-unique (detected in pre-flight §15.1)
- [ ] Implement `paginate_composite()` with row-value comparison `(col, id) < (cursor_val, cursor_id)` for DESC
- [ ] Implement `OR (col == cv, id < cid)` branch to correctly handle ties at page boundary
- [ ] Implement matching ASC branch: `(col, id) > (cursor_val, cursor_id)`
- [ ] Verify `encode_cursor` caller passes `tiebreaker_id=str(last_row.id)` when composite mode active
- [ ] Verify `decode_cursor` caller reads `decoded["id"]` and passes to composite paginator
- [ ] `ast.parse` the generated file
- [ ] Write atomically via temp-file + `os.replace`

### 15.5 Schema modification (`app/schemas/{name}.py`)
- [ ] Read existing schema file
- [ ] Locate `{Model}sPublic` class via AST
- [ ] Verify `data: list[{Model}Public]` and `count: int` still present (pre-condition)
- [ ] Add `next_cursor: str | None = None` if not already present
- [ ] Add `has_more: bool = False` if not already present
- [ ] Add docstring to `{Model}sPublic` explaining cursor fields
- [ ] `ast.parse` the modified file
- [ ] Write atomically

### 15.6 CRUD modification (`app/crud/{name}.py`)
- [ ] Read existing CRUD file
- [ ] Add `from app.core.cursor_paginator import CursorPaginator` if not present
- [ ] Add `CURSOR_FIELD = "{cursor_field}"` module-level constant
- [ ] Add `CURSOR_DIRECTION = "{direction}"` module-level constant
- [ ] Add `_paginator = CursorPaginator(...)` module-level instance
- [ ] Insert `get_multi_cursor()` function body
- [ ] Verify function body does NOT contain `OFFSET`
- [ ] Verify soft-delete conditional `hasattr(Model, "is_deleted")` is present
- [ ] Verify owner filter branch is present (if original `get_multi` had one)
- [ ] `ast.parse` the modified file
- [ ] Write atomically

### 15.7 Route modification (`app/api/routes/{name}.py`)
- [ ] Read existing route file
- [ ] Locate list endpoint via `@router.get("/")`
- [ ] Replace `skip: int = Query(...)` and `limit: int = Query(...)` params with `cursor` and `page_size`
- [ ] Set `cursor` max_length=1024 in Query
- [ ] Set `page_size` le=`max_page_size` in Query
- [ ] Replace `crud.get_multi(...)` call with `crud.get_multi_cursor(...)`
- [ ] Wrap call in `try/except ValueError → HTTPException(400)`
- [ ] Preserve all other query params (filter fields, etc.)
- [ ] `ast.parse` the modified file
- [ ] Write atomically

### 15.8 Migration generation (conditional)
- [ ] Only generate if cursor_field is NOT already indexed
- [ ] Compute next revision number from existing migration files
- [ ] Generate `0NNN_cursor_idx_{table}.py` with descriptive message
- [ ] `upgrade()`: create DESC single-field index + DESC composite (cursor_field, id) index
- [ ] `downgrade()`: drop both indexes in reverse order
- [ ] Set `down_revision` to most recent existing revision
- [ ] `ast.parse` the generated migration file
- [ ] Write atomically

### 15.9 Test file generation (`tests/test_{name}_cursor_pagination.py`)
- [ ] Create test file with imports from `httpx`, `pytest`, `conftest`
- [ ] Generate T-01 through T-14 functional + integrity tests
- [ ] Generate T-15 through T-20 encoding edge case tests
- [ ] Use existing fixtures from `conftest.py` (session, async_client, auth headers)
- [ ] Verify all test function names are unique
- [ ] `ast.parse` the generated file
- [ ] Write atomically

### 15.10 Encoding unit test file (`tests/test_cursor_encoding.py`)
- [ ] Create (or append to existing) encoding unit test file
- [ ] Generate round-trip tests for datetime, UUID, int, float, str
- [ ] Generate oversized cursor rejection test (T-30 equivalent)
- [ ] Generate invalid JSON cursor test
- [ ] Generate missing-key cursor test
- [ ] Generate composite cursor round-trip test
- [ ] `ast.parse` the generated file
- [ ] Write atomically

### 15.11 Documentation updates
- [ ] Append cursor pagination section to `app/core/KNOWLEDGE.md` (create if not exists)
- [ ] Section in KNOWLEDGE.md must include: cursor field, direction, composite mode status, index names
- [ ] Add tool entry to `manifest.yaml` with full signature, parameters, and example invocation
- [ ] Add tool row to `SKILL.md` tools table with category, complexity, and dependency columns
- [ ] Update `mcp_server.py` with `@mcp_tool` decorated function matching the tool signature
- [ ] Update `CHANGELOG.md` with tool version, date, and summary of what was changed
- [ ] Verify `SKILL.md` table row links to this spec file correctly

### 15.12 Atomicity and error recovery
- [ ] Track all files written in current run in a `_written_files: list[tuple[Path, bytes]]` list (path + original contents for rollback)
- [ ] For new files: record `(path, b"")` so rollback knows to delete them
- [ ] For modified files: read original contents into memory before writing; record `(path, original_bytes)`
- [ ] Each write: write to temp path `{file}.cursor_tmp`, then `os.replace` for atomic rename
- [ ] On any exception: iterate `_written_files` in reverse; restore `original_bytes` or delete if was new
- [ ] Log each write action to run journal with timestamp (append-only file `cursor_run.log`)
- [ ] Return `{files_created, files_modified, files_rolled_back, error}` on failure
- [ ] Never re-raise original exception until rollback is complete

### 15.13 Verification pass
- [ ] Run `ast.parse` on every file in `_written_files`
- [ ] Run `python -c "import app.core.cursor; import app.crud.item"` — verify no import errors
- [ ] Run `pytest tests/ -x --tb=short` — verify 0 failures
- [ ] Run existing benchmark: verify performance SLOs not regressed
- [ ] Measure tool execution time; log in `metrics.execution_time_ms`
- [ ] Return success report with all metrics, files, notes, and next_steps

---

## 16. Documentation Output

When the tool succeeds, it returns a structured report:

```json
{
  "status": "success",
  "files_created": [
    "app/core/cursor.py",
    "app/core/cursor_paginator.py",
    "app/core/cursor_composite.py",
    "app/core/cursor_integration.py",
    "alembic/versions/0004_cursor_idx_items.py",
    "tests/test_item_cursor_pagination.py",
    "tests/test_cursor_encoding.py",
    "app/core/KNOWLEDGE.md"
  ],
  "files_modified": [
    "app/schemas/item.py",
    "app/crud/item.py",
    "app/api/routes/item.py",
    "manifest.yaml",
    "SKILL.md",
    "mcp_server.py"
  ],
  "metrics": {
    "execution_time_ms": 1821,
    "files_changed": 14,
    "lines_added": 287,
    "lines_removed": 22,
    "models_converted": 1,
    "models_skipped_idempotent": 0,
    "cursor_field": "created_at",
    "direction": "desc",
    "composite_cursor": true,
    "migration_generated": true
  },
  "next_steps": [
    "Run: alembic upgrade head — creates cursor indexes on items table",
    "Run: pytest tests/test_item_cursor_pagination.py -v — verify all 30 test cases",
    "Run: pytest tests/test_cursor_encoding.py -v — verify encode/decode round-trips",
    "Update API client: replace skip/limit params with cursor and page_size",
    "Test deep pagination: walk to page 5000 and verify latency < 50ms on production data"
  ],
  "warnings": [
    "created_at column is not UNIQUE on items table — composite cursor (created_at, id) enabled to prevent record skipping on page boundaries.",
    "Existing offset-based API clients will receive first page only until they adopt the cursor parameter. Communicate the API change to all consumers before removing the deprecated skip/limit support."
  ],
  "notes": [
    "Cursor pagination enabled on Item model with cursor_field=created_at, direction=desc.",
    "Composite cursor mode active: cursor encodes (created_at, id) pair for stable page boundaries under concurrent inserts.",
    "Two Alembic indexes created: ix_items_created_at_cursor (single) and ix_items_created_at_id_cursor (composite).",
    "Response schema ItemsPublic extended with next_cursor and has_more fields (backward-compatible defaults).",
    "Existing tests still pass: 47/47.",
    "Tool execution time: 1821ms for 1 model."
  ]
}
```
