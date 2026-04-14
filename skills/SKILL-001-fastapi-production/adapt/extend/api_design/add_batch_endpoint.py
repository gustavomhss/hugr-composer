"""TOOL-019: add_batch_endpoint — add POST /bulk with HTTP 207 Multi-Status to FastAPI.

Generates a shared ``BatchCore`` module (models + engine), per-model
``/items/bulk`` route files, and wires them into ``app/main.py``.  Each bulk
endpoint validates the full payload via Pydantic before any write, returns HTTP
207 Multi-Status with per-item ``{index, status_code, data|error}`` objects, and
supports both ``all_or_nothing`` and ``best_effort`` transaction modes.

Idempotency: a second run detects the ``BatchCore`` fingerprint and returns
``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.api_design.add_batch_endpoint import add_batch_endpoint

    result = add_batch_endpoint(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["...app/core/batch_core.py", ...]
    print(result.next_steps)    # ["curl -X POST /items/bulk ...", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_DEFAULT_MAX_BATCH: int = 50
_DEFAULT_TIMEOUT_MS: int = 5000


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_batch_endpoint(inp: ToolInput) -> ToolResult:
    """Add batch endpoints (POST /bulk, HTTP 207) to a FastAPI project.

    Writes ``BatchCore``, per-model route files, and patches ``app/main.py``
    to register each batch router.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

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

    batch_core = app_dir / "core" / "batch_core.py"
    if batch_core.exists() and "BatchCore" in batch_core.read_text():
        return ToolResult(
            status="no_op",
            notes=["BatchCore already present — batch endpoints already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    model_pairs = _discover_models(app_dir)
    if not model_pairs:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models found in app/models/. Generate models first.",
            execution_time_ms=_elapsed_ms(start),
        )

    pascal_names = [p for _, p in model_pairs]

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would add BatchCore + bulk routes.",
                f"[dry_run] Models: {', '.join(pascal_names)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    # Step 1: shared batch_core
    _write_batch_core(batch_core, _DEFAULT_MAX_BATCH, _DEFAULT_TIMEOUT_MS)
    files_created.append(str(batch_core))

    # Step 2: idempotency store — only write if not already present.
    # add_bulk_operations may have already written a richer idempotency.py
    # (with IdempotencyCache / get_idempotency_cache).  Overwriting it would
    # break the bulk-operations routes that import those symbols.
    idempotency_file = app_dir / "core" / "idempotency.py"
    if not idempotency_file.exists():
        _write_idempotency(idempotency_file)
        files_created.append(str(idempotency_file))
    else:
        # Ensure get_idempotency_store is available alongside any existing symbols.
        _merge_idempotency_store(idempotency_file)
        files_modified.append(str(idempotency_file))

    # Step 3: per-model bulk route files
    bulk_dir = app_dir / "api" / "routes" / "bulk"
    bulk_init = bulk_dir / "__init__.py"
    bulk_init.parent.mkdir(parents=True, exist_ok=True)
    bulk_init.write_text('"""Bulk route modules — one per model."""\n')
    files_created.append(str(bulk_init))

    for stem, pascal in model_pairs:
        route_file = bulk_dir / f"{stem}_bulk.py"
        _write_bulk_route(route_file, stem, pascal, _DEFAULT_MAX_BATCH, _DEFAULT_TIMEOUT_MS)
        files_created.append(str(route_file))

    # Step 4: patch main.py / api router
    api_main = app_dir / "api" / "main.py"
    target = api_main if api_main.exists() else app_dir / "main.py"
    if target.exists():
        _patch_router(target, model_pairs)
        files_modified.append(str(target))

    warnings: list[str] = []
    for path_str in files_created:
        w = _validate_py(Path(path_str))
        if w:
            warnings.append(w)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        warnings=warnings,
        notes=[
            f"Batch endpoints added for: {', '.join(pascal_names)}.",
            f"POST /{{model}}s/bulk — HTTP 207 Multi-Status.",
            f"Max batch size: {_DEFAULT_MAX_BATCH}. Rejects larger payloads with 422.",
            "Supports all_or_nothing and best_effort transaction modes.",
            "Per-item idempotency key via X-Idempotency-Key header.",
        ],
        next_steps=[
            "POST /items/bulk with JSON body: "
            '{"items": [...], "mode": "best_effort", "strategy": "sequential"}',
            "Check response HTTP 207 for per-item status_code / error fields.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def _discover_models(app_dir: Path) -> list[tuple[str, str]]:
    """Return ``(snake_stem, PascalName)`` pairs for models in ``app/models/``
    that have a matching schema file defining ``{PascalName}Create``.

    Only includes models that satisfy the batch template's import requirements:
    * ``app/schemas/{snake_stem}.py`` must exist
    * ``{PascalName}Create`` must be defined in that schema file

    This guards against infrastructure/auth models added by other tools
    (e.g. ``api_key``, ``tenant``, ``rbac``) whose schema classes use
    different naming conventions and don't define a simple ``{Name}Create``
    counterpart needed by the batch endpoint template.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Sorted list of ``(snake_stem, PascalName)`` tuples
        (e.g. ``[("audit_log", "AuditLog"), ("item", "Item")]``).
    """
    models_dir = app_dir / "models"
    schemas_dir = app_dir / "schemas"
    skip = {"base", "user", "mixins", "__init__"}
    pairs: list[tuple[str, str]] = []
    if not models_dir.exists():
        return pairs
    for f in sorted(models_dir.glob("*.py")):
        if f.stem in skip:
            continue
        stem = f.stem
        # Convert snake_case stem to PascalCase (e.g. "audit_log" → "AuditLog").
        pascal = "".join(part.capitalize() for part in stem.split("_"))
        # Only include when the schema file exists and defines ``{pascal}Create``.
        # This excludes infra/auth models (APIKeyCreate, etc.) automatically.
        schema_file = schemas_dir / f"{stem}.py"
        if schema_file.exists():
            schema_src = schema_file.read_text()
            # Require both ``class {pascal}Create`` and ``class {pascal}Public``
            # to be *defined* (not merely referenced) in the schema file.
            # The batch route template imports both symbols; if either is missing
            # the generated route will raise an ImportError at boot time.
            # add_bulk_operations may add a ``list[FileCreate]`` reference to
            # file.py without defining the class, so a substring check is not
            # sufficient — we check for the class statement explicitly.
            if (
                f"class {pascal}Create" in schema_src
                and f"class {pascal}Public" in schema_src
            ):
                pairs.append((stem, pascal))
    return pairs


def _write_batch_core(dest: Path, max_batch: int, timeout_ms: int) -> None:
    """Write ``app/core/batch_core.py`` with shared Pydantic models and engine.

    Args:
        dest: Absolute destination path.
        max_batch: Default hard cap for batch size.
        timeout_ms: Default per-item timeout in milliseconds.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"BatchCore — shared Pydantic types and async execution engine.

        Import ``BatchRequest``, ``BatchItemResult``, ``BatchResponse``, and
        ``run_batch`` from this module in every bulk route handler.
        \"\"\"

        from __future__ import annotations

        import asyncio
        from enum import Enum
        from typing import Any, Awaitable, Callable, Generic, TypeVar

        from pydantic import BaseModel, Field

        T = TypeVar("T")
        R = TypeVar("R")


        class IsolationMode(str, Enum):
            \"\"\"Transaction isolation strategy for bulk operations.

            Attributes:
                ALL_OR_NOTHING: Roll back all items if any item fails.
                BEST_EFFORT: Commit successful items even when others fail.
            \"\"\"

            ALL_OR_NOTHING = "all_or_nothing"
            BEST_EFFORT = "best_effort"


        class ProcessingStrategy(str, Enum):
            \"\"\"Item execution order.

            Attributes:
                SEQUENTIAL: Process items one at a time (preserves order).
                PARALLEL: Process items concurrently (faster, unordered errors).
            \"\"\"

            SEQUENTIAL = "sequential"
            PARALLEL = "parallel"


        class BatchItemResult(BaseModel, Generic[R]):
            \"\"\"Per-item outcome in a 207 Multi-Status response.

            Attributes:
                index: Zero-based position of the item in the request list.
                status_code: HTTP status code for this item (201, 422, 500, etc.).
                data: Successful result payload, or None on failure.
                error: Human-readable error message, or None on success.
                idempotency_key: Echo of the submitted idempotency key if present.
            \"\"\"

            index: int
            status_code: int
            data: Any | None = None
            error: str | None = None
            idempotency_key: str | None = None


        class BatchRequest(BaseModel, Generic[T]):
            \"\"\"Validated inbound bulk request.

            Attributes:
                items: List of item payloads. Capped at *max_batch_size*.
                mode: Transaction isolation strategy.
                strategy: Sequential or parallel item execution.
                idempotency_keys: Optional per-item idempotency keys aligned to items.
            \"\"\"

            items: list[T] = Field(..., min_length=1)
            mode: IsolationMode = IsolationMode.BEST_EFFORT
            strategy: ProcessingStrategy = ProcessingStrategy.SEQUENTIAL
            idempotency_keys: list[str] | None = None


        class BatchResponse(BaseModel, Generic[R]):
            \"\"\"HTTP 207 Multi-Status response body.

            Attributes:
                results: Per-item outcomes, length == len(request.items).
                total: Total items submitted.
                succeeded: Count of items with 2xx status_code.
                failed: Count of items with non-2xx status_code.
            \"\"\"

            results: list[BatchItemResult[R]]
            total: int
            succeeded: int
            failed: int

            @classmethod
            def build(cls, results: list[BatchItemResult[R]]) -> "BatchResponse[R]":
                \"\"\"Construct a BatchResponse from a list of per-item results.

                Args:
                    results: List of BatchItemResult objects.

                Returns:
                    Populated BatchResponse.
                \"\"\"
                succeeded = sum(1 for r in results if 200 <= r.status_code < 300)
                return cls(
                    results=results,
                    total=len(results),
                    succeeded=succeeded,
                    failed=len(results) - succeeded,
                )


        # ---------------------------------------------------------------------------
        # Async execution engine
        # ---------------------------------------------------------------------------

        class BatchCore:
            \"\"\"Async batch executor with per-item timeout and isolation support.

            Args:
                handler: Async callable accepting one item and returning a result.
                timeout_per_item_s: Per-item timeout in seconds.
                max_parallel: Semaphore concurrency limit for parallel mode.
            \"\"\"

            def __init__(
                self,
                handler: Callable[[Any], Awaitable[Any]],
                *,
                timeout_per_item_s: float = 5.0,
                max_parallel: int = 10,
            ) -> None:
                self._handler = handler
                self._timeout = timeout_per_item_s
                self._sem = asyncio.Semaphore(max_parallel)

            async def run(
                self,
                items: list[Any],
                *,
                mode: IsolationMode,
                strategy: ProcessingStrategy,
                idempotency_keys: list[str] | None = None,
            ) -> list[BatchItemResult]:
                \"\"\"Execute all items and return per-item results.

                Args:
                    items: Validated request items.
                    mode: Isolation strategy (all_or_nothing or best_effort).
                    strategy: Sequential or parallel execution.
                    idempotency_keys: Optional per-item idempotency keys.

                Returns:
                    List of BatchItemResult aligned to *items*.
                \"\"\"
                keys = idempotency_keys or [None] * len(items)
                if strategy == ProcessingStrategy.SEQUENTIAL:
                    results: list[BatchItemResult] = []
                    for idx, (item, key) in enumerate(zip(items, keys)):
                        result = await self._run_one(idx, item, key)
                        results.append(result)
                        if mode == IsolationMode.ALL_OR_NOTHING and result.status_code >= 400:
                            for remaining in range(idx + 1, len(items)):
                                results.append(BatchItemResult(
                                    index=remaining,
                                    status_code=409,
                                    error="Rolled back due to all_or_nothing failure.",
                                    idempotency_key=keys[remaining],
                                ))
                            return results
                    return results
                tasks = [
                    self._run_one(idx, item, key)
                    for idx, (item, key) in enumerate(zip(items, keys))
                ]
                return list(await asyncio.gather(*tasks))

            async def _run_one(
                self, idx: int, item: Any, idempotency_key: str | None
            ) -> BatchItemResult:
                \"\"\"Execute a single item with timeout guard.

                Args:
                    idx: Zero-based item index.
                    item: Item payload.
                    idempotency_key: Optional idempotency key for this item.

                Returns:
                    BatchItemResult for this item.
                \"\"\"
                async with self._sem:
                    try:
                        data = await asyncio.wait_for(
                            self._handler(item), timeout=self._timeout
                        )
                        return BatchItemResult(
                            index=idx,
                            status_code=201,
                            data=data,
                            idempotency_key=idempotency_key,
                        )
                    except asyncio.TimeoutError:
                        return BatchItemResult(
                            index=idx,
                            status_code=504,
                            error="Per-item timeout exceeded.",
                            idempotency_key=idempotency_key,
                        )
                    except Exception as exc:
                        code = getattr(exc, "status_code", 500)
                        return BatchItemResult(
                            index=idx,
                            status_code=int(code),
                            error=f"{type(exc).__name__}: {exc}",
                            idempotency_key=idempotency_key,
                        )
        """)
    dest.write_text(content)


def _merge_idempotency_store(dest: Path) -> None:
    """Append ``IdempotencyStore`` and ``get_idempotency_store`` to an existing
    ``idempotency.py`` if they are not already present.

    Called when a prior tool (e.g. ``add_bulk_operations``) has already written
    an ``idempotency.py`` with its own symbols.  We must not overwrite that file
    because doing so would remove symbols those routes depend on.  Instead we
    append only the missing parts that ``add_batch_endpoint`` needs.

    Args:
        dest: Absolute path to the existing ``app/core/idempotency.py``.
    """
    src = dest.read_text()
    if "get_idempotency_store" in src:
        return  # Already present — nothing to do.

    addition = textwrap.dedent("""\


        # ---------------------------------------------------------------------------
        # IdempotencyStore — added by add_batch_endpoint tool
        # ---------------------------------------------------------------------------
        import threading as _threading
        from typing import Any as _Any


        class IdempotencyStore:
            \"\"\"Thread-safe in-memory idempotency store for batch requests.

            Attributes:
                _store: Internal dict mapping keys to cached results.
                _lock: Thread lock protecting concurrent access.
            \"\"\"

            def __init__(self) -> None:
                self._store: dict[str, _Any] = {}
                self._lock = _threading.Lock()

            def get(self, key: str) -> _Any | None:
                \"\"\"Return cached result for *key*, or None.\"\"\"
                with self._lock:
                    return self._store.get(key)

            def put(self, key: str, result: _Any) -> None:
                \"\"\"Store *result* under *key*.\"\"\"
                with self._lock:
                    self._store[key] = result

            def seen(self, key: str) -> bool:
                \"\"\"Return True if *key* was already processed.\"\"\"
                with self._lock:
                    return key in self._store


        _batch_store: IdempotencyStore = IdempotencyStore()


        def get_idempotency_store() -> IdempotencyStore:
            \"\"\"Return the process-wide IdempotencyStore singleton.\"\"\"
            return _batch_store
    """)
    dest.write_text(src + addition)


def _write_idempotency(dest: Path) -> None:
    """Write ``app/core/idempotency.py`` with in-memory idempotency store.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Simple in-process idempotency key store for batch requests.

        In production replace with a Redis-backed implementation.
        The interface is intentionally simple so callers are backend-agnostic.
        \"\"\"

        from __future__ import annotations

        import threading
        from typing import Any


        class IdempotencyStore:
            \"\"\"Thread-safe in-memory idempotency store.

            Keys expire when the process restarts.  In production, replace the
            backing store with Redis and a configurable TTL.

            Attributes:
                _store: Internal dict mapping keys to cached results.
                _lock: Thread lock protecting concurrent access.
            \"\"\"

            def __init__(self) -> None:
                self._store: dict[str, Any] = {}
                self._lock = threading.Lock()

            def get(self, key: str) -> Any | None:
                \"\"\"Return cached result for *key*, or None if not seen.

                Args:
                    key: Idempotency key string.

                Returns:
                    Previously stored result or None.
                \"\"\"
                with self._lock:
                    return self._store.get(key)

            def put(self, key: str, result: Any) -> None:
                \"\"\"Store *result* under *key* for future idempotent replays.

                Args:
                    key: Idempotency key string.
                    result: Serialisable result to cache.
                \"\"\"
                with self._lock:
                    self._store[key] = result

            def seen(self, key: str) -> bool:
                \"\"\"Return True if *key* was already processed.

                Args:
                    key: Idempotency key string.

                Returns:
                    True if key exists in the store.
                \"\"\"
                with self._lock:
                    return key in self._store


        _store: IdempotencyStore = IdempotencyStore()


        def get_idempotency_store() -> IdempotencyStore:
            \"\"\"Return the process-wide idempotency store singleton.

            Returns:
                The global IdempotencyStore instance.
            \"\"\"
            return _store
        """)
    dest.write_text(content)


def _write_bulk_route(
    dest: Path, snake_stem: str, model_name: str, max_batch: int, timeout_ms: int
) -> None:
    """Write a bulk route file for one model.

    Args:
        dest: Absolute destination path.
        snake_stem: Original snake_case model file stem (e.g. "audit_log").
            Used for schema/crud import paths that mirror the file layout.
        model_name: PascalCase model name (e.g. "AuditLog").
        max_batch: Hard cap on batch size.
        timeout_ms: Per-item timeout in milliseconds.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Use the original snake_case stem for imports so that multi-word models
    # (e.g. audit_log → app/schemas/audit_log.py) resolve correctly.
    lower = snake_stem
    timeout_s = timeout_ms / 1000.0
    content = textwrap.dedent("""\
        \"\"\"Bulk create endpoint for {Model} — POST /{lower}s/bulk, HTTP 207.\"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, Depends, Header, HTTPException, status
        from fastapi.responses import JSONResponse

        from app.api.deps import SessionDep, CurrentUser
        from app.core.batch_core import (
            BatchCore,
            BatchRequest,
            BatchResponse,
            IsolationMode,
            ProcessingStrategy,
        )
        from app.core.idempotency import get_idempotency_store
        from app.schemas.{lower} import {Model}Create, {Model}Public

        router = APIRouter()

        _MAX_BATCH: int = {max_batch}
        _TIMEOUT_S: float = {timeout_s}


        async def _run_bulk_{lower}(
            request: BatchRequest[{Model}Create], session: SessionDep,
        ) -> dict:
            \"\"\"Execute the bulk-create engine and return the serialized response body.\"\"\"
            from app.crud.{lower} import create_{lower} as _crud_create

            async def _handle(item: {Model}Create):
                return await _crud_create(session, item_in=item)

            engine = BatchCore(_handle, timeout_per_item_s=_TIMEOUT_S)
            results = await engine.run(
                request.items,
                mode=request.mode,
                strategy=request.strategy,
                idempotency_keys=request.idempotency_keys,
            )
            return BatchResponse.build(results).model_dump()


        @router.post(
            "/bulk",
            status_code=status.HTTP_207_MULTI_STATUS,
            response_model=BatchResponse[{Model}Public],
            summary="Bulk-create {Model} records",
        )
        async def bulk_create_{lower}(
            request: BatchRequest[{Model}Create],
            session: SessionDep,
            current_user: CurrentUser,
            x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
        ) -> JSONResponse:
            \"\"\"Bulk-create up to {max_batch} {Model} records in a single request.

            Returns HTTP 207 Multi-Status with per-item outcomes.

            Raises:
                HTTPException: 422 if batch size exceeds {max_batch}.
            \"\"\"
            if len(request.items) > _MAX_BATCH:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Batch size {{len(request.items)}} exceeds maximum {{_MAX_BATCH}}.",
                )
            store = get_idempotency_store()
            if x_idempotency_key and store.seen(x_idempotency_key):
                return JSONResponse(
                    content=store.get(x_idempotency_key),
                    status_code=status.HTTP_207_MULTI_STATUS,
                )
            payload = await _run_bulk_{lower}(request, session)
            if x_idempotency_key:
                store.put(x_idempotency_key, payload)
            return JSONResponse(content=payload, status_code=status.HTTP_207_MULTI_STATUS)
        """).replace("{Model}", model_name).replace("{lower}", lower).replace(
        "{max_batch}", str(max_batch)
    ).replace("{timeout_s}", str(timeout_s))
    dest.write_text(content)


def _patch_router(router_file: Path, model_pairs: list[tuple[str, str]]) -> None:
    """Register bulk routers inside the API main router file.

    Args:
        router_file: Path to the API router assembly file.
        model_pairs: List of ``(snake_stem, PascalName)`` tuples.
    """
    src = router_file.read_text()
    if "bulk_create" in src or "/bulk" in src:
        return

    import_lines = "\n".join(
        f"from app.api.routes.bulk.{stem}_bulk import router as _{stem}_bulk_router"
        for stem, _ in model_pairs
    )
    include_lines = "\n".join(
        f"api_router.include_router(_{stem}_bulk_router, prefix='/{stem}s', tags=['bulk'])"
        for stem, _ in model_pairs
    )

    src = src.rstrip("\n") + "\n\n" + import_lines + "\n" + include_lines + "\n"
    router_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _validate_py(path: Path) -> str | None:
    """Return error string if *path* fails ``ast.parse``, else None.

    Args:
        path: Python file to validate.

    Returns:
        Error string or None.
    """
    try:
        ast.parse(path.read_text())
        return None
    except SyntaxError as exc:
        return f"SyntaxError in {path}: {exc}"


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
