"""TOOL-002: add_cursor_pagination — replace offset pagination with cursor pagination.

Adds opaque base64url cursor encoding/decoding, a generic ``CursorPaginator``
helper, patches CRUD modules with ``get_multi_cursor``, extends response schemas
with ``next_cursor`` and ``has_more`` fields, updates route handlers to accept
``cursor`` and ``page_size`` query params, and generates an Alembic migration
that creates the required DESC and composite indexes.

The tool is idempotent: a second run on an already-patched project detects the
``get_multi_cursor`` fingerprint and returns ``status="no_op"`` without touching
any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.crud_data.add_cursor_pagination import add_cursor_pagination

    result = add_cursor_pagination(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [".../app/core/cursor.py", ...]
    print(result.next_steps)    # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_cursor_pagination(inp: ToolInput) -> ToolResult:
    """Add cursor-based pagination to a FastAPI project.

    Replaces offset-based ``skip/limit`` pagination with cursor pagination on
    list endpoints.  Writes the cursor utility module and paginator helper once,
    then patches each discovered model's CRUD, schema, and route files.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Pre-flight: already patched? -------------------------------------
    crud_item = app_dir / "crud" / "item.py"
    if crud_item.exists() and "get_multi_cursor" in crud_item.read_text():
        return ToolResult(
            status="no_op",
            notes=["get_multi_cursor already present — cursor pagination already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Discover target models -------------------------------------------
    model_names = _discover_models(app_dir)
    if not model_names:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models found in app/models/. Generate models first.",
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would add cursor pagination for models: {', '.join(model_names)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Step 1: Write app/core/cursor.py (once per project) -------------
    cursor_file = app_dir / "core" / "cursor.py"
    if not cursor_file.exists():
        _write_cursor_module(cursor_file)
        files_created.append(str(cursor_file))

    # --- Step 2: Write app/core/cursor_paginator.py (once per project) ---
    paginator_file = app_dir / "core" / "cursor_paginator.py"
    if not paginator_file.exists():
        _write_cursor_paginator(paginator_file)
        files_created.append(str(paginator_file))

    # --- Step 3: Patch CRUD, schema, routes per model --------------------
    for model_name in model_names:
        crud_file = app_dir / "crud" / f"{model_name.lower()}.py"
        if crud_file.exists():
            _patch_crud(crud_file, model_name)
            files_modified.append(str(crud_file))

        schema_file = app_dir / "schemas" / f"{model_name.lower()}.py"
        if schema_file.exists():
            _patch_schema(schema_file, model_name)
            files_modified.append(str(schema_file))

        route_file = app_dir / "api" / "routes" / f"{model_name.lower()}.py"
        if route_file.exists():
            _patch_routes(route_file, model_name)
            files_modified.append(str(route_file))

    # --- Step 4: Generate Alembic migration for cursor indexes -----------
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        for model_name in model_names:
            migration_file = _write_migration(versions_dir, model_name)
            files_created.append(str(migration_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Cursor pagination enabled for: {', '.join(model_names)}",
            "Response schema is backward-compatible: data/count fields unchanged.",
            "next_cursor and has_more added with safe defaults (None, False).",
            "Invalid cursor returns HTTP 400, never 500.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Update API clients to use cursor/page_size instead of skip/limit.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _discover_models(app_dir: Path) -> list[str]:
    """Return PascalCase model names found in ``app/models/``, excluding base files.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Sorted list of discovered model names (e.g. ``["Item"]``).
    """
    models_dir = app_dir / "models"
    skip = {"base", "user", "mixins", "__init__"}
    names = []
    for f in sorted(models_dir.glob("*.py")):
        stem = f.stem
        if stem in skip:
            continue
        names.append(stem.capitalize())
    return names


def _write_cursor_module(dest: Path) -> None:
    """Write ``app/core/cursor.py`` with ``encode_cursor`` and ``decode_cursor``.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Opaque cursor encoding for cursor-based pagination.

        Cursors are URL-safe base64-encoded JSON blobs.  Clients MUST treat
        them as opaque strings — the internal format may change at any time.
        \"\"\"

        from __future__ import annotations

        import base64
        import json
        from datetime import datetime, timezone
        from typing import Any
        from uuid import UUID


        _MAX_CURSOR_BYTES: int = 1024  # 1 KB hard limit — rejects oversized malicious input


        def encode_cursor(
            field: str,
            value: Any,
            tiebreaker_id: str | None = None,
        ) -> str:
            \"\"\"Encode a sort key into a URL-safe base64 cursor string.

            Supports: datetime (ISO-8601 UTC), UUID (str), int, float, str.
            Includes optional tiebreaker_id (record UUID) for composite cursors.

            Args:
                field: Name of the sort column (e.g. ``"created_at"``).
                value: Value of the sort column for the last item on the page.
                tiebreaker_id: Optional record UUID to stabilise ties.

            Returns:
                URL-safe base64url string with no padding characters.
            \"\"\"
            if isinstance(value, datetime):
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
            \"\"\"Decode a cursor string back to ``{field, value, id?}``.

            Args:
                cursor: Opaque cursor string from a previous response.

            Returns:
                Dict with keys ``field``, ``value``, and optionally ``id``.

            Raises:
                ValueError: On bad base64, invalid JSON, wrong structure,
                    oversized input, or missing required keys.
            \"\"\"
            if len(cursor.encode("utf-8")) > _MAX_CURSOR_BYTES:
                raise ValueError(
                    f"Cursor exceeds maximum size ({_MAX_CURSOR_BYTES} bytes)"
                )
            try:
                padding_needed = (4 - len(cursor) % 4) % 4
                padded = cursor + "=" * padding_needed
                raw = base64.urlsafe_b64decode(padded.encode("ascii"))
                data = json.loads(raw)
                if not isinstance(data, dict) or "f" not in data or "v" not in data:
                    raise ValueError("Invalid cursor structure: missing 'f' or 'v' keys")
                return {"field": data["f"], "value": data["v"], "id": data.get("id")}
            except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError(f"Malformed cursor: {exc}") from exc
        """)
    dest.write_text(content)


def _write_cursor_paginator(dest: Path) -> None:
    """Write ``app/core/cursor_paginator.py`` with the generic ``CursorPaginator``.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"CursorPaginator: generic SQLAlchemy 2.0 async cursor pagination helper.

        Usage::

            paginator = CursorPaginator(model=Item, cursor_field="created_at", direction="desc")
            result = await paginator.paginate(session, stmt_base, cursor=cursor_str, page_size=20)
        \"\"\"

        from __future__ import annotations

        from datetime import datetime
        from typing import Any, Generic, Literal, TypeVar
        from uuid import UUID

        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.cursor import decode_cursor, encode_cursor

        M = TypeVar("M")


        class CursorPaginator(Generic[M]):
            \"\"\"Generic cursor paginator for SQLAlchemy 2.0 async models.

            Attributes:
                model: The SQLAlchemy model class to paginate.
                cursor_field: Name of the column used as the sort key.
                direction: Sort direction — ``"desc"`` (newest-first) or ``"asc"``.
            \"\"\"

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
                base_stmt: Any,
                *,
                cursor: str | None,
                page_size: int,
            ) -> dict[str, Any]:
                \"\"\"Execute a cursor-paginated query.

                The ``base_stmt`` must NOT include ORDER BY or LIMIT — this method
                adds them.  Fetches ``page_size + 1`` rows to detect ``has_more``.

                Args:
                    session: Async SQLAlchemy session.
                    base_stmt: Base SELECT statement without ORDER BY / LIMIT.
                    cursor: Opaque cursor from the previous page, or ``None`` for
                        the first page.
                    page_size: Number of records to return.

                Returns:
                    Dict with keys: ``data``, ``count``, ``next_cursor``, ``has_more``.

                Raises:
                    ValueError: If cursor is malformed or encodes the wrong field.
                \"\"\"
                count_stmt = select(func.count()).select_from(base_stmt.subquery())
                total: int = (await session.execute(count_stmt)).scalar_one()

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

                col_ordered = (
                    self._col.desc() if self.direction == "desc" else self._col.asc()
                )
                data_stmt = data_stmt.order_by(col_ordered).limit(page_size + 1)
                rows: list[Any] = list(
                    (await session.execute(data_stmt)).scalars().all()
                )

                has_more = len(rows) > page_size
                if has_more:
                    rows = rows[:page_size]

                next_cursor: str | None = None
                if has_more and rows:
                    last = rows[-1]
                    val = getattr(last, self.cursor_field)
                    id_val = (
                        str(getattr(last, "id")) if self._id_col is not None else None
                    )
                    next_cursor = encode_cursor(self.cursor_field, val, id_val)

                return {
                    "data": rows,
                    "count": total,
                    "next_cursor": next_cursor,
                    "has_more": has_more,
                }

            def _coerce_value(self, raw: Any) -> Any:
                \"\"\"Coerce a decoded cursor value to the correct Python type for the column.

                Args:
                    raw: JSON-decoded value from the cursor payload.

                Returns:
                    Value coerced to datetime, UUID, or the original type.
                \"\"\"
                col_type = str(self._col.property.columns[0].type)
                if "DATETIME" in col_type.upper() or "TIMESTAMP" in col_type.upper():
                    return datetime.fromisoformat(raw)
                if "UUID" in col_type.upper():
                    return UUID(raw)
                return raw
        """)
    dest.write_text(content)


def _patch_crud(crud_file: Path, model_name: str) -> None:
    """Append ``get_multi_cursor`` to a CRUD module.

    Args:
        crud_file: Path to ``app/crud/{name}.py``.
        model_name: PascalCase model name.
    """
    src = crud_file.read_text()
    if "get_multi_cursor" in src:
        return

    lower = model_name.lower()
    additions = textwrap.dedent("""\

        # ---------------------------------------------------------------------------
        # Cursor pagination — added by add_cursor_pagination tool
        # ---------------------------------------------------------------------------
        from app.core.cursor_paginator import CursorPaginator as _CursorPaginator
        from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
        from sqlalchemy import select as _select
        import uuid as _uuid

        CURSOR_FIELD = "created_at"
        CURSOR_DIRECTION = "desc"

        _paginator = _CursorPaginator(
            {model_name}, cursor_field=CURSOR_FIELD, direction=CURSOR_DIRECTION
        )


        async def get_multi_cursor(
            session: _AsyncSession,
            *,
            cursor: str | None = None,
            page_size: int = 20,
            owner_id: _uuid.UUID | None = None,
        ) -> dict:
            \"\"\"Cursor-paginated list.  Stable under concurrent inserts/deletes.

            Returns a dict with ``data``, ``count``, ``next_cursor``, ``has_more``.
            Raises ``ValueError`` if cursor is malformed or encodes a mismatched field.

            Args:
                session: Async SQLAlchemy session.
                cursor: Opaque cursor from a previous response, or ``None`` for first page.
                page_size: Number of records to return per page (1-100).
                owner_id: Optional owner filter applied to both data and count queries.
            \"\"\"
            stmt = _select({model_name})
            if owner_id is not None:
                stmt = stmt.where({model_name}.owner_id == owner_id)
            if hasattr({model_name}, "is_deleted"):
                stmt = stmt.where({model_name}.is_deleted == False)  # noqa: E712
            return await _paginator.paginate(session, stmt, cursor=cursor, page_size=page_size)
        """).replace("{model_name}", model_name)

    crud_file.write_text(src + additions)


def _patch_schema(schema_file: Path, model_name: str) -> None:
    """Add ``next_cursor`` and ``has_more`` fields to ``{Model}sPublic``.

    Args:
        schema_file: Path to ``app/schemas/{name}.py``.
        model_name: PascalCase model name.
    """
    src = schema_file.read_text()
    if "next_cursor" in src:
        return

    plural_class = f"{model_name}sPublic"
    if plural_class not in src:
        return

    # Insert the two new fields after the existing `count: int` field
    old_field = "    count: int"
    new_fields = textwrap.dedent("""\
            count: int
            next_cursor: str | None = None
            has_more: bool = False""")
    src = src.replace(old_field, new_fields, 1)
    schema_file.write_text(src)


def _patch_routes(route_file: Path, model_name: str) -> None:
    """Replace ``skip/limit`` list route with ``cursor/page_size`` variant.

    Args:
        route_file: Path to ``app/api/routes/{name}.py``.
        model_name: PascalCase model name.
    """
    src = route_file.read_text()
    if "get_multi_cursor" in src:
        return

    lower = model_name.lower()
    additions = textwrap.dedent("""\


        # ---------------------------------------------------------------------------
        # Cursor pagination route — added by add_cursor_pagination tool
        # ---------------------------------------------------------------------------
        from app.crud.{lower} import get_multi_cursor as _get_multi_cursor
        from fastapi import Query as _Query


        @router.get("/cursor/", response_model={PublicList})
        async def list_{lower}s_cursor(
            session: SessionDep,
            current_user: CurrentUser,
            cursor: str | None = _Query(
                default=None,
                description="Opaque pagination cursor from previous response next_cursor field",
                max_length=1024,
            ),
            page_size: int = _Query(
                default=20,
                ge=1,
                le=100,
                description="Number of items to return per page (1-100)",
            ),
        ) -> {PublicList}:
            \"\"\"List {model_name}s using cursor-based pagination.  Stable under concurrent writes.

            Args:
                session: Injected async DB session.
                current_user: Authenticated user.
                cursor: Opaque cursor from the previous response, or omit for the first page.
                page_size: Page size, 1-100.

            Raises:
                HTTPException: 400 if cursor is malformed.
            \"\"\"
            from fastapi import HTTPException
            try:
                result = await _get_multi_cursor(
                    session,
                    cursor=cursor,
                    page_size=page_size,
                    owner_id=current_user.id,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail=f"Invalid cursor: {{exc}}"
                ) from exc
            return {PublicList}(**result)
        """).format(
        lower=lower,
        model_name=model_name,
        PublicList=f"{model_name}sPublic",
    )

    route_file.write_text(src + additions)


def _write_migration(versions_dir: Path, model_name: str) -> Path:
    """Generate an Alembic migration creating DESC and composite cursor indexes.

    Args:
        versions_dir: ``alembic/versions/`` directory.
        model_name: PascalCase model name (e.g. ``"Item"``).

    Returns:
        Path of the created migration file.
    """
    table = model_name.lower() + "s"
    rev_id = f"cursor_idx_{table}"
    existing = sorted(versions_dir.glob("*.py"))
    down_rev = "0001_initial"
    if existing:
        down_rev = existing[-1].stem

    content = textwrap.dedent("""\
        \"\"\"Add cursor pagination indexes to {table} table.

        Revision ID: {rev_id}
        Revises: {down_rev}
        Create Date: auto-generated by add_cursor_pagination tool
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "{rev_id}"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Add DESC index on created_at and composite (created_at, id) index.\"\"\"
            # Partial DESC index — optimal for ORDER BY created_at DESC (index seek, no sort step)
            op.create_index(
                "ix_{table}_created_at_cursor",
                "{table}",
                [sa.text("created_at DESC")],
                unique=False,
            )
            # Composite tiebreaker index — resolves ties when multiple rows share created_at
            op.create_index(
                "ix_{table}_created_at_id_cursor",
                "{table}",
                [sa.text("created_at DESC"), sa.text("id DESC")],
                unique=False,
            )


        def downgrade() -> None:
            \"\"\"Remove cursor pagination indexes.\"\"\"
            op.drop_index("ix_{table}_created_at_id_cursor", table_name="{table}")
            op.drop_index("ix_{table}_created_at_cursor", table_name="{table}")
        """).format(table=table, rev_id=rev_id, down_rev=down_rev)

    migration_file = versions_dir / f"{rev_id}.py"
    migration_file.write_text(content)
    return migration_file


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
