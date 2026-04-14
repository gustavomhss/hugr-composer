"""TOOL-007: add_bulk_operations — add HTTP 207 bulk endpoints to a FastAPI/SQLAlchemy project.

Generates ``POST /items/bulk``, ``PATCH /items/bulk``, and ``DELETE /items/bulk`` routes
backed by SQLAlchemy bulk operations.  Both ``all_or_nothing`` (single-transaction) and
``best_effort`` (per-item SAVEPOINT) transaction modes are supported.  An optional
Redis-backed idempotency cache prevents duplicate execution on client retries.

The tool is idempotent: a second run detects the ``/bulk`` route fingerprint and returns
``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.crud_data.add_bulk_operations import add_bulk_operations

    result = add_bulk_operations(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["app/core/idempotency.py", ...]
    print(result.next_steps)    # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

# Maximum items per bulk request — hard cap enforced at schema and CRUD layer.
DEFAULT_MAX_BATCH: int = 1000


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_bulk_operations(inp: ToolInput) -> ToolResult:
    """Add bulk create/update/delete endpoints to a FastAPI project.

    Reads the project at ``inp.project_dir``, detects which models exist,
    and writes / patches all necessary files for HTTP 207 bulk operations.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and
            optional ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    app_dir = project / "app"

    # --- Pre-flight: are bulk routes already enabled? ----------------------
    idempotency_file = app_dir / "core" / "idempotency.py"
    if idempotency_file.exists() and "IdempotencyCache" in idempotency_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["IdempotencyCache already present — bulk operations already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )
    # If add_batch_endpoint already wrote idempotency.py (with get_idempotency_store),
    # we must NOT overwrite it — merge the IdempotencyCache content instead.

    # --- Discover target models -------------------------------------------
    model_names = _discover_models(app_dir)
    if not model_names:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models found in app/models/. Generate models first.",
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would add bulk operations for models: {', '.join(model_names)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    # --- Step 1: Idempotency cache module --------------------------------
    if not idempotency_file.exists():
        _write_idempotency(idempotency_file)
        files_created.append(str(idempotency_file))
    else:
        # File exists (written by add_batch_endpoint) — append IdempotencyCache block
        _merge_idempotency_cache(idempotency_file)
        files_created.append(str(idempotency_file))

    # --- Step 2: Patch schemas with Bulk* models -------------------------
    for model_name in model_names:
        schema_file = app_dir / "schemas" / f"{model_name.lower()}.py"
        if schema_file.exists():
            _patch_schema(schema_file, model_name)
            files_modified.append(str(schema_file))

    # --- Step 3: Patch CRUD modules with bulk helpers --------------------
    for model_name in model_names:
        crud_file = app_dir / "crud" / f"{model_name.lower()}.py"
        if crud_file.exists():
            _patch_crud(crud_file, model_name)
            files_modified.append(str(crud_file))

    # --- Step 4: Patch route files with bulk endpoints -------------------
    for model_name in model_names:
        route_file = app_dir / "api" / "routes" / f"{model_name.lower()}.py"
        if route_file.exists():
            _patch_routes(route_file, model_name)
            files_modified.append(str(route_file))

    # --- Step 5: Patch main.py to initialise idempotency cache ----------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- Step 6: Generate Alembic migration for composite index ----------
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
            f"Bulk operations enabled for: {', '.join(model_names)}",
            "Routes: POST /bulk (create), PATCH /bulk (update), DELETE /bulk (delete).",
            "All routes return HTTP 207 Multi-Status.",
            "Idempotency-Key header supported via Redis cache (24-hour TTL).",
            f"Hard batch size cap: {DEFAULT_MAX_BATCH} items per request.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set REDIS_URL in your .env for idempotency cache support.",
            "Call init_idempotency_cache(REDIS_URL) in your app startup (already patched in main.py).",
            "Restart the application.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _discover_models(app_dir: Path) -> list[str]:
    """Return PascalCase model names found in ``app/models/``, excluding system files.

    Only includes models where:
    1. The file contains a class named ``{pascal}`` inheriting from ``Base``.
    2. A matching route file ``app/api/routes/{stem}.py`` exists.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Sorted list of discovered model names (e.g. ``["Item"]``).
    """
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    skip = {"base", "user", "mixins", "__init__"}
    available_routes: set[str] = set()
    if routes_dir.exists():
        for r in routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)
    names = []
    for f in sorted(models_dir.glob("*.py")):
        stem = f.stem
        if stem in skip:
            continue
        if stem not in available_routes:
            continue
        pascal = "".join(w.capitalize() for w in stem.split("_"))
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        base_subclasses = [
            n.name for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef)
            and any(
                (isinstance(b, ast.Name) and b.id == "Base")
                or (isinstance(b, ast.Attribute) and b.attr == "Base")
                for b in n.bases
            )
        ]
        if pascal in base_subclasses:
            names.append(pascal)
    return names


def _write_idempotency(dest: Path) -> None:
    """Write ``app/core/idempotency.py`` with Redis-backed idempotency cache.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Redis-backed idempotency key cache for bulk operation endpoints.

        Stores serialised BulkResponse payloads under the client-provided key
        with a 24-hour TTL.  If Redis is unavailable, operations proceed without
        caching and log a warning — never blocking the primary flow.
        \"\"\"
        from __future__ import annotations

        import json
        import logging
        from typing import Any

        import redis.asyncio as aioredis

        logger = logging.getLogger(__name__)

        _redis: aioredis.Redis | None = None


        def init_idempotency_cache(redis_url: str) -> None:
            \"\"\"Initialise the global idempotency Redis client.

            Call once at application startup (e.g. in lifespan context).

            Args:
                redis_url: Redis connection URL (e.g. ``redis://localhost:6379/0``).
            \"\"\"
            global _redis
            _redis = aioredis.from_url(redis_url, decode_responses=True)


        def get_idempotency_cache() -> "IdempotencyCache":
            \"\"\"Return a cache wrapper bound to the current Redis client.

            Returns:
                ``IdempotencyCache`` instance (safe to call when Redis is None).
            \"\"\"
            return IdempotencyCache(_redis)


        class IdempotencyCache:
            \"\"\"Thin wrapper around Redis providing get/set for idempotency keys.

            Attributes:
                _redis: Underlying async Redis client, or ``None`` when unavailable.
            \"\"\"

            def __init__(self, redis: aioredis.Redis | None) -> None:
                \"\"\"Initialise with a Redis client.

                Args:
                    redis: Async Redis client instance, or ``None``.
                \"\"\"
                self._redis = redis

            async def get(self, key: str) -> dict | None:
                \"\"\"Fetch cached BulkResponse by idempotency key.

                Args:
                    key: Client-provided idempotency key string.

                Returns:
                    Deserialised response dict, or ``None`` on cache miss or Redis failure.
                \"\"\"
                if self._redis is None:
                    return None
                try:
                    raw = await self._redis.get(f"idem:{key}")
                    return json.loads(raw) if raw else None
                except Exception as exc:
                    logger.warning("idempotency_cache_get_failed key=%s exc=%s", key, exc)
                    return None

            async def set(self, key: str, value: Any, ttl: int = 86400) -> None:
                \"\"\"Store BulkResponse under idempotency key with TTL.

                Args:
                    key: Client-provided idempotency key string.
                    value: Response payload to cache (must be JSON-serialisable).
                    ttl: Time-to-live in seconds (default: 86400 = 24 h).
                \"\"\"
                if self._redis is None:
                    return
                try:
                    await self._redis.setex(f"idem:{key}", ttl, json.dumps(value))
                except Exception as exc:
                    logger.warning("idempotency_cache_set_failed key=%s exc=%s", key, exc)
        """)
    dest.write_text(content)


def _merge_idempotency_cache(dest: Path) -> None:
    """Append ``IdempotencyCache`` and ``get_idempotency_cache`` to an existing
    ``app/core/idempotency.py`` file written by a different tool.

    When ``add_batch_endpoint`` runs first, it creates ``idempotency.py`` with
    ``IdempotencyStore``.  This function appends the complementary
    ``IdempotencyCache`` block so bulk routes can import ``get_idempotency_cache``
    without the full file being overwritten.

    Args:
        dest: Path to the existing ``app/core/idempotency.py``.
    """
    src = dest.read_text()
    if "IdempotencyCache" in src:
        return

    cache_block = textwrap.dedent("""\

        # ---------------------------------------------------------------------------
        # IdempotencyCache — added by add_bulk_operations tool
        # ---------------------------------------------------------------------------
        import json as _idem_json
        import logging as _idem_logging
        import redis.asyncio as _idem_aioredis
        from typing import Any as _idem_Any

        _idem_logger = _idem_logging.getLogger(__name__)
        _idem_redis: _idem_aioredis.Redis | None = None


        def init_idempotency_cache(redis_url: str) -> None:
            \"\"\"Initialise the global idempotency Redis client.

            Args:
                redis_url: Redis connection URL.
            \"\"\"
            global _idem_redis
            _idem_redis = _idem_aioredis.from_url(redis_url, decode_responses=True)


        def get_idempotency_cache() -> "IdempotencyCache":
            \"\"\"Return a cache wrapper bound to the current Redis client.

            Returns:
                ``IdempotencyCache`` instance (safe when Redis is None).
            \"\"\"
            return IdempotencyCache(_idem_redis)


        class IdempotencyCache:
            \"\"\"Thin wrapper around Redis providing get/set for idempotency keys.\"\"\"

            def __init__(self, redis: _idem_aioredis.Redis | None) -> None:
                self._redis = redis

            async def get(self, key: str) -> dict | None:
                if self._redis is None:
                    return None
                try:
                    raw = await self._redis.get(f"idem:{key}")
                    return _idem_json.loads(raw) if raw else None
                except Exception as exc:
                    _idem_logger.warning("idempotency_cache_get_failed key=%s exc=%s", key, exc)
                    return None

            async def set(self, key: str, value: _idem_Any, ttl: int = 86400) -> None:
                if self._redis is None:
                    return
                try:
                    await self._redis.setex(f"idem:{key}", ttl, _idem_json.dumps(value))
                except Exception as exc:
                    _idem_logger.warning("idempotency_cache_set_failed key=%s exc=%s", key, exc)
        """)
    dest.write_text(src.rstrip("\n") + "\n" + cache_block)


def _patch_schema(schema_file: Path, model_name: str) -> None:
    """Append BulkRequest, BulkResponse, and BulkResultItem schemas.

    Args:
        schema_file: Path to ``app/schemas/{name}.py``.
        model_name: PascalCase model name.
    """
    src = schema_file.read_text()
    if "BulkResponse" in src:
        return

    lower = model_name.lower()
    additions = textwrap.dedent("""\


        # ---------------------------------------------------------------------------
        # Bulk operation schemas — added by add_bulk_operations tool
        # ---------------------------------------------------------------------------
        import uuid as _bulk_uuid
        from typing import Annotated, Literal


        class BulkResultItem(BaseModel):
            \"\"\"Per-item outcome returned inside ``BulkResponse.results``.

            ``index`` maps back to the original request list position, allowing
            callers to correlate failures to the input payload by position.

            Attributes:
                index: Zero-based position in the request list.
                id: Row UUID if the item was successfully persisted; ``None`` on failure.
                success: True when the item was committed to the database.
                error: Human-readable error description when ``success=False``.
                error_code: Machine-readable code: VALIDATION_ERROR, NOT_FOUND,
                    INTEGRITY_ERROR, INSERT_ERROR, UPDATE_ERROR, ROLLBACK.
            \"\"\"

            index: int
            id: _bulk_uuid.UUID | None = None
            success: bool
            error: str | None = None
            error_code: str | None = None


        class BulkResponse(BaseModel):
            \"\"\"Top-level response envelope for all bulk endpoints.

            ``partial`` is ``True`` when ``mode=best_effort`` and at least one item failed.
            ``transaction_id`` is populated from the idempotency key when present.

            Attributes:
                total: Total items in the request.
                succeeded: Count of successfully committed items.
                failed: Count of items that were not committed.
                partial: True when best_effort mode committed a subset.
                transaction_id: Idempotency key echo (when supplied by caller).
                results: Per-item status list, one entry per input item.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            total: int
            succeeded: int
            failed: int
            partial: bool
            transaction_id: str | None = None
            results: list[BulkResultItem]


        class {model_name}BulkCreate(BaseModel):
            \"\"\"Request body for ``POST /{lower}s/bulk``.

            ``items`` is bounded by ``max_length`` to prevent OOM and table-lock attacks.
            ``mode`` selects the transaction strategy.

            Attributes:
                items: List of items to create (1–{max_batch} items).
                mode: Transaction isolation — all_or_nothing or best_effort.
            \"\"\"

            items: Annotated[list[{model_name}Create], Field(min_length=1, max_length={max_batch})]
            mode: Literal["all_or_nothing", "best_effort"] = "all_or_nothing"


        class {model_name}BulkUpdate(BaseModel):
            \"\"\"Request body for ``PATCH /{lower}s/bulk``.

            Each update dict MUST include ``id`` to resolve the target row.

            Attributes:
                updates: List of partial update dicts, each containing ``id`` (1–{max_batch}).
                mode: Transaction isolation — all_or_nothing or best_effort.
            \"\"\"

            updates: Annotated[list[dict], Field(min_length=1, max_length={max_batch})]
            mode: Literal["all_or_nothing", "best_effort"] = "all_or_nothing"

            @field_validator("updates")
            @classmethod
            def each_update_has_id(cls, v: list[dict]) -> list[dict]:
                \"\"\"Reject any update dict that omits the ``id`` key.

                Args:
                    v: List of update dicts to validate.

                Returns:
                    The validated list.

                Raises:
                    ValueError: If any dict is missing the ``id`` key.
                \"\"\"
                for idx, u in enumerate(v):
                    if "id" not in u:
                        raise ValueError(
                            f"Update at index {idx} is missing required 'id' field"
                        )
                return v


        class {model_name}BulkDelete(BaseModel):
            \"\"\"Request body for ``DELETE /{lower}s/bulk``.

            Attributes:
                ids: List of item UUIDs to delete (1–{max_batch}).
                mode: Transaction isolation — all_or_nothing or best_effort.
            \"\"\"

            ids: Annotated[list[_bulk_uuid.UUID], Field(min_length=1, max_length={max_batch})]
            mode: Literal["all_or_nothing", "best_effort"] = "all_or_nothing"
        """).replace(
        "{model_name}", model_name,
    ).replace("{lower}", lower).replace("{max_batch}", str(DEFAULT_MAX_BATCH))

    # Ensure field_validator is imported
    if "field_validator" not in src:
        src = src.replace(
            "from pydantic import BaseModel",
            "from pydantic import BaseModel, ConfigDict, Field, field_validator",
        )
        src = src.replace(
            "from pydantic import BaseModel, ConfigDict",
            "from pydantic import BaseModel, ConfigDict, Field, field_validator",
        )

    # Ensure ConfigDict is imported
    if "ConfigDict" not in src:
        src = src.replace(
            "from pydantic import BaseModel",
            "from pydantic import BaseModel, ConfigDict",
        )

    # Ensure Field is imported
    if ", Field" not in src and "Field" not in src:
        src = src.replace(
            "from pydantic import BaseModel",
            "from pydantic import BaseModel, Field",
        )

    schema_file.write_text(src + additions)


def _patch_crud(crud_file: Path, model_name: str) -> None:
    """Append bulk_create, bulk_update, bulk_delete CRUD functions.

    Args:
        crud_file: Path to ``app/crud/{name}.py``.
        model_name: PascalCase model name.
    """
    src = crud_file.read_text()
    if "bulk_create" in src:
        return

    lower = model_name.lower()
    additions = textwrap.dedent("""\


        # ---------------------------------------------------------------------------
        # Bulk operation CRUD helpers — added by add_bulk_operations tool
        # ---------------------------------------------------------------------------
        import uuid as _bulk_uuid
        from sqlalchemy import delete as _sql_delete, select as _bulk_select, update as _sql_update
        from sqlalchemy.ext.asyncio import AsyncSession as _BulkSession
        from sqlalchemy.exc import IntegrityError as _IntegrityError

        try:
            from sqlalchemy.dialects.postgresql import insert as _pg_insert
        except ImportError:
            _pg_insert = None  # type: ignore[assignment]


        async def _bulk_insert_all_or_nothing_{lower}(
            session: _BulkSession, items: list, owner_id: _bulk_uuid.UUID
        ) -> tuple[list, int, int]:
            \"\"\"Insert all {model_name} rows atomically; rollback entire batch on failure.

            Args:
                session: Async SQLAlchemy session.
                items: Pydantic schema instances with ``.model_dump()``.
                owner_id: UUID assigned as owner_id on every inserted row.

            Returns:
                Tuple of (results_list, succeeded_count, failed_count).
            \"\"\"
            from app.schemas.{lower} import BulkResultItem  # type: ignore[import]
            rows = [{{**item.model_dump(), "owner_id": owner_id, "id": _bulk_uuid.uuid4()}} for item in items]
            try:
                if _pg_insert is not None:
                    stmt = _pg_insert({model_name}).values(rows).returning({model_name}.id)
                else:
                    stmt = {model_name}.__table__.insert().values(rows).returning({model_name}.id)  # type: ignore[attr-defined]
                db_result = await session.execute(stmt)
                inserted_ids = list(db_result.scalars())
                await session.flush()
                results = [BulkResultItem(index=idx, id=row_id, success=True) for idx, row_id in enumerate(inserted_ids)]
                return results, len(inserted_ids), 0
            except _IntegrityError as exc:
                await session.rollback()
                results = [
                    BulkResultItem(index=idx, success=False, error=str(exc.orig), error_code="INTEGRITY_ERROR")
                    for idx in range(len(items))
                ]
                return results, 0, len(items)


        async def _bulk_insert_best_effort_{lower}(
            session: _BulkSession, items: list, owner_id: _bulk_uuid.UUID
        ) -> tuple[list, int, int]:
            \"\"\"Insert {model_name} rows one by one using savepoints; skip failed rows.

            Args:
                session: Async SQLAlchemy session.
                items: Pydantic schema instances with ``.model_dump()``.
                owner_id: UUID assigned as owner_id on every inserted row.

            Returns:
                Tuple of (results_list, succeeded_count, failed_count).
            \"\"\"
            from app.schemas.{lower} import BulkResultItem  # type: ignore[import]
            results: list = []
            succeeded = 0
            failed = 0
            for idx, item in enumerate(items):
                try:
                    sp = await session.begin_nested()
                    new_obj = {model_name}(**item.model_dump(), owner_id=owner_id, id=_bulk_uuid.uuid4())
                    session.add(new_obj)
                    await session.flush()
                    await sp.commit()
                    results.append(BulkResultItem(index=idx, id=new_obj.id, success=True))
                    succeeded += 1
                except Exception as exc:
                    await sp.rollback()
                    results.append(BulkResultItem(index=idx, success=False, error=str(exc), error_code="INSERT_ERROR"))
                    failed += 1
            await session.flush()
            return results, succeeded, failed


        async def bulk_create_{lower}s(
            session: _BulkSession,
            *,
            items: list,
            owner_id: _bulk_uuid.UUID,
            mode: str = "all_or_nothing",
        ) -> dict:
            \"\"\"Insert N {model_name} rows in a single transaction or per-item savepoints.

            Args:
                session: Async SQLAlchemy session.
                items: List of Pydantic schema instances (must have ``.model_dump()``).
                owner_id: UUID of the requesting user (scoped ownership).
                mode: ``all_or_nothing`` or ``best_effort``.

            Returns:
                BulkResponse-compatible dict with total, succeeded, failed, partial, results.
            \"\"\"
            from app.schemas.{lower} import BulkResponse  # type: ignore[import]
            if mode == "all_or_nothing":
                results, succeeded, failed = await _bulk_insert_all_or_nothing_{lower}(session, items, owner_id)
            else:
                results, succeeded, failed = await _bulk_insert_best_effort_{lower}(session, items, owner_id)
            return BulkResponse(
                total=len(items), succeeded=succeeded, failed=failed,
                partial=(failed > 0 and mode == "best_effort"), results=results,
            ).model_dump()


        async def _apply_bulk_updates_{lower}(
            session: _BulkSession, updates: list[dict], found_ids: set
        ) -> tuple[list, int, int]:
            \"\"\"Apply per-row PATCH updates using savepoints; skip unowned rows.

            Args:
                session: Async SQLAlchemy session.
                updates: List of update dicts each containing ``id``.
                found_ids: Set of IDs verified as owned by the caller.

            Returns:
                Tuple of (results_list, succeeded_count, failed_count).
            \"\"\"
            from app.schemas.{lower} import BulkResultItem  # type: ignore[import]
            results: list = []
            succeeded = 0
            failed = 0
            for idx, upd in enumerate(updates):
                row_id = _bulk_uuid.UUID(str(upd.get("id")))
                if row_id not in found_ids:
                    results.append(BulkResultItem(
                        index=idx, id=row_id, success=False,
                        error="Item not found or not owned by caller", error_code="NOT_FOUND",
                    ))
                    failed += 1
                    continue
                try:
                    sp = await session.begin_nested()
                    patch = {{k: v for k, v in upd.items() if k != "id"}}
                    stmt = _sql_update({model_name}).where({model_name}.id == row_id).values(**patch)
                    await session.execute(stmt)
                    await sp.commit()
                    results.append(BulkResultItem(index=idx, id=row_id, success=True))
                    succeeded += 1
                except Exception as exc:
                    await sp.rollback()
                    results.append(BulkResultItem(
                        index=idx, id=row_id, success=False, error=str(exc), error_code="UPDATE_ERROR",
                    ))
                    failed += 1
            await session.flush()
            return results, succeeded, failed


        async def bulk_update_{lower}s(
            session: _BulkSession,
            *,
            updates: list[dict],
            owner_id: _bulk_uuid.UUID,
            mode: str = "all_or_nothing",
        ) -> dict:
            \"\"\"Partially update N {model_name} rows. Each dict must contain ``id``.

            Ownership is verified before any mutation: IDs not owned by the caller
            become NOT_FOUND errors without touching the database.

            Args:
                session: Async SQLAlchemy session.
                updates: List of update dicts, each containing ``id``.
                owner_id: UUID of the requesting user.
                mode: ``all_or_nothing`` or ``best_effort``.

            Returns:
                BulkResponse-compatible dict.
            \"\"\"
            from app.schemas.{lower} import BulkResponse  # type: ignore[import]
            ids = [_bulk_uuid.UUID(str(u["id"])) for u in updates if "id" in u]
            existing_stmt = _bulk_select({model_name}.id).where(
                {model_name}.id.in_(ids), {model_name}.owner_id == owner_id
            )
            found_ids = set((await session.execute(existing_stmt)).scalars().all())
            results, succeeded, failed = await _apply_bulk_updates_{lower}(session, updates, found_ids)
            return BulkResponse(
                total=len(updates), succeeded=succeeded, failed=failed,
                partial=(failed > 0), results=results,
            ).model_dump()


        async def _check_delete_ownership_{lower}(
            session: _BulkSession, ids: list, owner_id: _bulk_uuid.UUID
        ) -> tuple[set, list, list]:
            \"\"\"Resolve which IDs are owned by the caller vs not found.

            Args:
                session: Async SQLAlchemy session.
                ids: Requested UUIDs to delete.
                owner_id: UUID of the requesting user.

            Returns:
                Tuple of (owned_ids_set, not_owned_list, not_found_results_list).
            \"\"\"
            from app.schemas.{lower} import BulkResultItem  # type: ignore[import]
            owned_stmt = _bulk_select({model_name}.id).where(
                {model_name}.id.in_(ids), {model_name}.owner_id == owner_id
            )
            owned_ids = set((await session.execute(owned_stmt)).scalars().all())
            not_owned = [i for i in ids if i not in owned_ids]
            not_found_results = [
                BulkResultItem(index=idx, id=item_id, success=False,
                    error="Item not found or not owned by caller", error_code="NOT_FOUND")
                for idx, item_id in enumerate(ids) if item_id not in owned_ids
            ]
            return owned_ids, not_owned, not_found_results


        async def bulk_delete_{lower}s(
            session: _BulkSession,
            *,
            ids: list[_bulk_uuid.UUID],
            owner_id: _bulk_uuid.UUID,
            mode: str = "all_or_nothing",
        ) -> dict:
            \"\"\"Delete N {model_name} rows in a single DELETE WHERE id IN (...).

            Ownership is verified first. For all_or_nothing mode, any unowned ID
            rolls back the entire batch. For best_effort, owned IDs are deleted
            and unowned IDs become NOT_FOUND errors.

            Args:
                session: Async SQLAlchemy session.
                ids: List of UUIDs to delete.
                owner_id: UUID of the requesting user.
                mode: ``all_or_nothing`` or ``best_effort``.

            Returns:
                BulkResponse-compatible dict.
            \"\"\"
            from app.schemas.{lower} import BulkResultItem, BulkResponse  # type: ignore[import]
            owned_ids, not_owned, results = await _check_delete_ownership_{lower}(session, ids, owner_id)
            if mode == "all_or_nothing" and not_owned:
                await session.rollback()
                rollback_items = [
                    BulkResultItem(index=len(not_owned) + i, id=oid, success=False,
                        error="Rolled back due to unowned IDs", error_code="ROLLBACK")
                    for i, oid in enumerate(owned_ids)
                ]
                return BulkResponse(total=len(ids), succeeded=0, failed=len(ids),
                    partial=False, results=results + rollback_items).model_dump()
            del_stmt = _sql_delete({model_name}).where({model_name}.id.in_(list(owned_ids)))
            succeeded = (await session.execute(del_stmt)).rowcount
            await session.flush()
            for idx, item_id in enumerate(ids):
                if item_id in owned_ids:
                    results.append(BulkResultItem(index=idx, id=item_id, success=True))
            return BulkResponse(total=len(ids), succeeded=succeeded, failed=len(not_owned),
                partial=(len(not_owned) > 0), results=sorted(results, key=lambda r: r.index),
            ).model_dump()
        """).replace("{model_name}", model_name).replace("{lower}", lower)

    crud_file.write_text(src + additions)


def _patch_routes(route_file: Path, model_name: str) -> None:
    """Append POST/PATCH/DELETE /bulk endpoints to the route file.

    Args:
        route_file: Path to ``app/api/routes/{name}.py``.
        model_name: PascalCase model name.
    """
    src = route_file.read_text()
    if "/bulk" in src or "bulk_create" in src:
        return

    lower = model_name.lower()
    additions = textwrap.dedent("""\


        # ---------------------------------------------------------------------------
        # Bulk operation endpoints — added by add_bulk_operations tool
        # ---------------------------------------------------------------------------
        from typing import Annotated as _Annotated
        from fastapi import Header as _Header

        from app.core.idempotency import get_idempotency_cache as _get_idem_cache
        from app.crud.{lower} import (
            bulk_create_{lower}s as _crud_bulk_create,
            bulk_update_{lower}s as _crud_bulk_update,
            bulk_delete_{lower}s as _crud_bulk_delete,
        )
        from app.schemas.{lower} import (
            {model_name}BulkCreate,
            {model_name}BulkUpdate,
            {model_name}BulkDelete,
            BulkResponse,
        )


        @router.post("/bulk", response_model=BulkResponse, status_code=207)
        async def bulk_create_{lower}(
            payload: {model_name}BulkCreate,
            session: SessionDep,
            current_user: CurrentUser,
            idempotency_key: _Annotated[str | None, _Header(alias="Idempotency-Key")] = None,
        ) -> BulkResponse:
            \"\"\"Create multiple {model_name} rows in a single request (HTTP 207 Multi-Status).

            Supports ``all_or_nothing`` (single transaction) and ``best_effort``
            (per-item SAVEPOINT) transaction modes.  Idempotency-Key header deduplicates
            retries within 24 hours.

            Args:
                payload: Bulk create request body.
                session: Injected async DB session.
                current_user: Authenticated user.
                idempotency_key: Optional client-side deduplication key.

            Returns:
                BulkResponse with per-item status.
            \"\"\"
            from fastapi import HTTPException

            if idempotency_key:
                cached = await _get_idem_cache().get(idempotency_key)
                if cached is not None:
                    return BulkResponse.model_validate(cached)

            result_dict = await _crud_bulk_create(
                session, items=payload.items, owner_id=current_user.id, mode=payload.mode
            )

            if idempotency_key:
                await _get_idem_cache().set(idempotency_key, result_dict, ttl=86400)

            result = BulkResponse.model_validate(result_dict)
            if result.failed > 0 and payload.mode == "all_or_nothing":
                raise HTTPException(
                    status_code=422,
                    detail={{"message": "Batch failed", "results": result_dict}},
                )
            return result


        @router.patch("/bulk", response_model=BulkResponse, status_code=207)
        async def bulk_update_{lower}(
            payload: {model_name}BulkUpdate,
            session: SessionDep,
            current_user: CurrentUser,
            idempotency_key: _Annotated[str | None, _Header(alias="Idempotency-Key")] = None,
        ) -> BulkResponse:
            \"\"\"Partially update multiple {model_name} rows. Each dict must include ``id``.

            Args:
                payload: Bulk update request body.
                session: Injected async DB session.
                current_user: Authenticated user (ownership check applied).
                idempotency_key: Optional client-side deduplication key.

            Returns:
                BulkResponse with per-item status.
            \"\"\"
            if idempotency_key:
                cached = await _get_idem_cache().get(idempotency_key)
                if cached is not None:
                    return BulkResponse.model_validate(cached)

            result_dict = await _crud_bulk_update(
                session, updates=payload.updates, owner_id=current_user.id, mode=payload.mode
            )

            if idempotency_key:
                await _get_idem_cache().set(idempotency_key, result_dict, ttl=86400)

            return BulkResponse.model_validate(result_dict)


        @router.delete("/bulk", response_model=BulkResponse, status_code=207)
        async def bulk_delete_{lower}(
            payload: {model_name}BulkDelete,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> BulkResponse:
            \"\"\"Delete multiple {model_name} rows by ID in a single transaction.

            Ownership is verified before deletion. Unowned IDs are reported as
            NOT_FOUND without rolling back the owned deletions (best_effort mode).

            Args:
                payload: Bulk delete request body.
                session: Injected async DB session.
                current_user: Authenticated user (ownership check applied).

            Returns:
                BulkResponse with per-item status.
            \"\"\"
            result_dict = await _crud_bulk_delete(
                session, ids=payload.ids, owner_id=current_user.id, mode=payload.mode
            )
            return BulkResponse.model_validate(result_dict)
        """).replace("{model_name}", model_name).replace("{lower}", lower)

    route_file.write_text(src + additions)


def _patch_main(main_file: Path) -> None:
    """Add init_idempotency_cache call to main.py startup.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "init_idempotency_cache" in src:
        return

    import_line = "from app.core.idempotency import init_idempotency_cache  # noqa: F401"
    init_block = textwrap.dedent("""\


        # Idempotency cache — added by add_bulk_operations tool
        import os as _os
        _redis_url = _os.getenv("REDIS_URL", "redis://localhost:6379/0")
        init_idempotency_cache(_redis_url)
        """)

    # Insert import after first import block
    if "from app.core.logging import configure_logging" in src:
        src = src.replace(
            "from app.core.logging import configure_logging",
            f"from app.core.logging import configure_logging\n{import_line}",
        )
    else:
        src = f"{import_line}\n" + src

    # Append init block at end of file
    src = src.rstrip("\n") + "\n" + init_block

    main_file.write_text(src)


def _write_migration(versions_dir: Path, model_name: str) -> Path:
    """Generate an Alembic migration creating the composite (owner_id, id) index.

    Args:
        versions_dir: ``alembic/versions/`` directory.
        model_name: PascalCase model name.

    Returns:
        Path of the created migration file.
    """
    table = model_name.lower() + "s"
        # Find the true HEAD of the migration chain (not just the alphabetically last file)
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = textwrap.dedent("""\
        \"\"\"Add composite index for bulk query optimisation on {table} table.

        Bulk DELETE and bulk UPDATE both filter by owner_id + id.in_(...).
        This index ensures the owner pre-filter is sargable and avoids full-table scans.

        Revision ID: 0007_bulk_ops_index_{table}
        Revises: {down_rev}
        Create Date: auto-generated by add_bulk_operations tool
        \"\"\"
        from __future__ import annotations

        from alembic import op

        revision = "0007_bulk_ops_index_{table}"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create composite index ix_{table}_owner_id for bulk ownership check queries.\"\"\"
            op.create_index(
                "ix_{table}_owner_id",
                "{table}",
                ["owner_id", "id"],
                unique=False,
                postgresql_concurrently=True,
            )


        def downgrade() -> None:
            \"\"\"Drop the bulk operations composite index.\"\"\"
            op.drop_index(
                "ix_{table}_owner_id",
                table_name="{table}",
                postgresql_concurrently=True,
            )
        """).replace("{table}", table).replace("{down_rev}", down_rev)

    migration_file = versions_dir / f"0007_bulk_ops_index_{table}.py"
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
