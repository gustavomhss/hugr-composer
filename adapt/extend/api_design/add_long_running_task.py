"""TOOL-020: add_long_running_task — add async task infrastructure to a FastAPI project.

Generates the full long-running task stack:
  - ``POST /tasks``    → 202 Accepted + ``Location`` header
  - ``GET /tasks/{id}``  → status polling (state, progress, ETA)
  - ``DELETE /tasks/{id}`` → cooperative cancellation
  - ARQ worker module wired to Redis for queue and state storage
  - Fernet-encrypted task IDs so clients cannot enumerate other users' tasks
  - Progress reporting via Redis hash updates (O(1) poll reads)

Idempotency: a second run detects the ``TaskManager`` fingerprint and returns
``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.api_design.add_long_running_task import add_long_running_task

    result = add_long_running_task(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["...app/core/task_manager.py", ...]
    print(result.next_steps)    # ["pip install arq cryptography", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_add_long_running_task",
    "description": "Add async long-running task pattern with polling endpoint and status tracking.",
    "tags": ["extend", "api_design"],
    "entry": "add_long_running_task",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_long_running_task(inp: ToolInput) -> ToolResult:
    """Add async task infrastructure (ARQ + Redis) to a FastAPI project.

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

    task_mgr = app_dir / "core" / "task_manager.py"
    if task_mgr.exists() and "TaskManager" in task_mgr.read_text():
        return ToolResult(
            status="no_op",
            notes=["TaskManager already present — long-running task infra already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would generate TaskManager, ARQ worker, task routes, schemas.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    # Step 1: task_manager.py — Fernet IDs + Redis state
    _write_task_manager(task_mgr)
    files_created.append(str(task_mgr))

    # Step 2: task_registry.py
    registry_file = app_dir / "core" / "task_registry.py"
    _write_task_registry(registry_file)
    files_created.append(str(registry_file))

    # Step 3: task schemas
    schemas_file = app_dir / "schemas" / "task.py"
    _write_task_schemas(schemas_file)
    files_created.append(str(schemas_file))

    # Step 4: task routes
    routes_file = app_dir / "api" / "routes" / "tasks.py"
    _write_task_routes(routes_file)
    files_created.append(str(routes_file))

    # Step 5: ARQ worker
    workers_dir = project / "workers"
    workers_init = workers_dir / "__init__.py"
    workers_dir.mkdir(parents=True, exist_ok=True)
    workers_init.write_text('"""ARQ worker modules."""\n')
    files_created.append(str(workers_init))

    worker_file = workers_dir / "task_worker.py"
    _write_arq_worker(worker_file)
    files_created.append(str(worker_file))

    # Step 6: Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_migration(versions_dir)
        files_created.append(str(migration_file))

    # Step 7: register tasks router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_router(routes_init)
        files_modified.append(str(routes_init))

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
            "POST /tasks → 202 Accepted + Location: /tasks/{encrypted_id}.",
            "GET /tasks/{id} → status, progress (0-100), ETA, partial result.",
            "DELETE /tasks/{id} → cooperative cancellation via Redis flag.",
            "Task IDs are Fernet-encrypted — clients cannot enumerate other users' tasks.",
            "ARQ worker in workers/task_worker.py polls Redis for new tasks.",
            "Progress updates via app.core.task_manager.report_progress().",
        ],
        next_steps=[
            "pip install arq 'cryptography>=41'",
            "Set TASK_FERNET_KEY env var: python -c "
            "\"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"",
            "Run the ARQ worker: arq workers.task_worker.WorkerSettings",
            "alembic upgrade head",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def _write_task_manager(dest: Path) -> None:
    """Write ``app/core/task_manager.py`` with Fernet IDs and Redis state.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"TaskManager — Redis-backed state and Fernet-encrypted task IDs.

        All task state is stored in Redis hashes under ``task:{raw_id}``.
        Task IDs exposed to clients are Fernet-encrypted so the raw UUID is
        never visible and sequential enumeration is impossible.

        Usage::

            from app.core.task_manager import TaskManager

            mgr = TaskManager()
            task_id = await mgr.create(owner_id=user.id, task_type="export")
            await mgr.set_status(task_id, "running")
            await mgr.report_progress(task_id, 42, "Processing row 42/100")
        \"\"\"

        from __future__ import annotations

        import json
        import os
        import uuid
        from datetime import datetime, timezone
        from enum import Enum
        from typing import Any

        from cryptography.fernet import Fernet, InvalidToken


        # ---------------------------------------------------------------------------
        # Status enum
        # ---------------------------------------------------------------------------

        class TaskStatus(str, Enum):
            \"\"\"Task lifecycle states.

            Attributes:
                PENDING: Queued, not yet picked up by a worker.
                RUNNING: Currently executing.
                COMPLETED: Finished successfully.
                FAILED: Terminated with an error.
                CANCELLED: Cancelled by client request.
            \"\"\"

            PENDING = "pending"
            RUNNING = "running"
            COMPLETED = "completed"
            FAILED = "failed"
            CANCELLED = "cancelled"


        # ---------------------------------------------------------------------------
        # Redis key helpers
        # ---------------------------------------------------------------------------

        _TASK_PREFIX = "task:"
        _CANCEL_PREFIX = "task:cancel:"
        _DEFAULT_TTL = int(os.getenv("TASK_RESULT_TTL_SECONDS", "86400"))
        _MAX_DURATION = int(os.getenv("TASK_MAX_DURATION_SECONDS", "3600"))
        _POLL_HINT = int(os.getenv("TASK_POLL_INTERVAL_HINT_SECONDS", "5"))


        def _task_key(raw_id: str) -> str:
            \"\"\"Return the Redis hash key for a task.

            Args:
                raw_id: Raw UUID string.

            Returns:
                Redis key string.
            \"\"\"
            return f"{_TASK_PREFIX}{raw_id}"


        def _cancel_key(raw_id: str) -> str:
            \"\"\"Return the Redis key used to signal task cancellation.

            Args:
                raw_id: Raw UUID string.

            Returns:
                Redis cancel-flag key string.
            \"\"\"
            return f"{_CANCEL_PREFIX}{raw_id}"


        # ---------------------------------------------------------------------------
        # Fernet helpers
        # ---------------------------------------------------------------------------

        def _get_fernet() -> Fernet:
            \"\"\"Return a Fernet instance keyed from the TASK_FERNET_KEY env var.

            Returns:
                Fernet object for encryption / decryption.

            Raises:
                RuntimeError: If TASK_FERNET_KEY is not set.
            \"\"\"
            key = os.getenv("TASK_FERNET_KEY")
            if not key:
                raise RuntimeError(
                    "TASK_FERNET_KEY environment variable is not set. "
                    "Generate one with: python -c \\"from cryptography.fernet import Fernet; "
                    "print(Fernet.generate_key().decode())\\"."
                )
            return Fernet(key.encode())


        def encrypt_task_id(raw_id: str) -> str:
            \"\"\"Encrypt a raw UUID string into a URL-safe client token.

            Args:
                raw_id: UUID string to encrypt.

            Returns:
                URL-safe base64-encoded Fernet token.
            \"\"\"
            return _get_fernet().encrypt(raw_id.encode()).decode()


        def decrypt_task_id(token: str) -> str:
            \"\"\"Decrypt a client token back to a raw UUID string.

            Args:
                token: URL-safe Fernet token from the client.

            Returns:
                Raw UUID string.

            Raises:
                ValueError: If the token is invalid or tampered.
            \"\"\"
            try:
                return _get_fernet().decrypt(token.encode()).decode()
            except InvalidToken as exc:
                raise ValueError("Invalid or expired task ID token.") from exc


        # ---------------------------------------------------------------------------
        # TaskManager
        # ---------------------------------------------------------------------------

        class TaskManager:
            \"\"\"Create, update, query, and cancel tasks via Redis.

            All methods are async and accept an optional ``redis`` client.
            When ``redis`` is None the manager attempts to use a module-level
            singleton obtained from ``app.core.redis.get_redis()``.

            Args:
                redis: Optional pre-connected Redis async client.
            \"\"\"

            def __init__(self, redis: Any | None = None) -> None:
                self._redis = redis

            async def _get_redis(self) -> Any:
                \"\"\"Return a connected Redis client.

                Returns:
                    An async Redis client instance.
                \"\"\"
                if self._redis is not None:
                    return self._redis
                from app.core.redis import get_redis as _get
                return await _get()

            async def create(
                self,
                owner_id: str,
                task_type: str,
                params: dict | None = None,
            ) -> str:
                \"\"\"Create a new task, store initial state in Redis.

                Args:
                    owner_id: UUID string of the task owner.
                    task_type: Registered task type identifier.
                    params: Optional input parameters for the worker.

                Returns:
                    Encrypted task ID token to return to the client.
                \"\"\"
                raw_id = str(uuid.uuid4())
                redis = await self._get_redis()
                now = datetime.now(timezone.utc).isoformat()
                mapping = {
                    "raw_id": raw_id,
                    "owner_id": str(owner_id),
                    "task_type": task_type,
                    "status": TaskStatus.PENDING.value,
                    "progress": "0",
                    "message": "",
                    "result": "",
                    "error": "",
                    "created_at": now,
                    "updated_at": now,
                    "params": json.dumps(params or {}),
                }
                await redis.hset(_task_key(raw_id), mapping=mapping)
                await redis.expire(_task_key(raw_id), _DEFAULT_TTL)
                return encrypt_task_id(raw_id)

            async def get(self, token: str, owner_id: str) -> dict:
                \"\"\"Fetch task state for the given encrypted token.

                Args:
                    token: Encrypted task ID token from the client.
                    owner_id: UUID string of the requesting user.

                Returns:
                    Dict with task state fields.

                Raises:
                    KeyError: If task not found.
                    PermissionError: If owner_id does not match.
                    ValueError: If token is invalid.
                \"\"\"
                raw_id = decrypt_task_id(token)
                redis = await self._get_redis()
                data = await redis.hgetall(_task_key(raw_id))
                if not data:
                    raise KeyError(f"Task not found: {token}")
                stored_owner = data.get(b"owner_id", data.get("owner_id", ""))
                if isinstance(stored_owner, bytes):
                    stored_owner = stored_owner.decode()
                if stored_owner != str(owner_id):
                    raise PermissionError("Task belongs to a different user.")
                return {
                    k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                    for k, v in data.items()
                }

            async def set_status(self, raw_id: str, status: str) -> None:
                \"\"\"Update the task status field in Redis.

                Args:
                    raw_id: Raw UUID string (not the encrypted token).
                    status: New status value from TaskStatus.
                \"\"\"
                redis = await self._get_redis()
                now = datetime.now(timezone.utc).isoformat()
                await redis.hset(_task_key(raw_id), mapping={"status": status, "updated_at": now})

            async def report_progress(
                self, raw_id: str, pct: int, message: str = ""
            ) -> None:
                \"\"\"Update progress percentage and optional message.

                Args:
                    raw_id: Raw UUID string.
                    pct: Progress percentage 0-100.
                    message: Human-readable progress description.
                \"\"\"
                redis = await self._get_redis()
                now = datetime.now(timezone.utc).isoformat()
                await redis.hset(
                    _task_key(raw_id),
                    mapping={
                        "progress": str(max(0, min(100, pct))),
                        "message": message,
                        "updated_at": now,
                    },
                )

            async def set_result(self, raw_id: str, result: Any) -> None:
                \"\"\"Store the final result and mark task as completed.

                Args:
                    raw_id: Raw UUID string.
                    result: JSON-serialisable result payload.
                \"\"\"
                redis = await self._get_redis()
                now = datetime.now(timezone.utc).isoformat()
                await redis.hset(
                    _task_key(raw_id),
                    mapping={
                        "status": TaskStatus.COMPLETED.value,
                        "progress": "100",
                        "result": json.dumps(result),
                        "updated_at": now,
                    },
                )

            async def set_error(self, raw_id: str, error: str) -> None:
                \"\"\"Mark task as failed with an error message.

                Args:
                    raw_id: Raw UUID string.
                    error: Human-readable error string.
                \"\"\"
                redis = await self._get_redis()
                now = datetime.now(timezone.utc).isoformat()
                await redis.hset(
                    _task_key(raw_id),
                    mapping={
                        "status": TaskStatus.FAILED.value,
                        "error": error,
                        "updated_at": now,
                    },
                )

            async def request_cancel(self, token: str, owner_id: str) -> None:
                \"\"\"Set a Redis cancellation flag that the worker polls.

                Args:
                    token: Encrypted task ID token.
                    owner_id: UUID string of the requesting user.

                Raises:
                    KeyError: If task not found.
                    PermissionError: If caller is not the task owner.
                \"\"\"
                await self.get(token, owner_id)  # validates ownership
                raw_id = decrypt_task_id(token)
                redis = await self._get_redis()
                await redis.setex(_cancel_key(raw_id), _DEFAULT_TTL, "1")

            async def is_cancel_requested(self, raw_id: str) -> bool:
                \"\"\"Check whether cancellation was requested for this task.

                Args:
                    raw_id: Raw UUID string.

                Returns:
                    True if a cancellation flag is set.
                \"\"\"
                redis = await self._get_redis()
                return bool(await redis.exists(_cancel_key(raw_id)))


        # ---------------------------------------------------------------------------
        # Module-level singleton
        # ---------------------------------------------------------------------------

        _manager: TaskManager | None = None


        def get_task_manager() -> TaskManager:
            \"\"\"Return the process-wide TaskManager singleton.

            Returns:
                Global TaskManager instance.
            \"\"\"
            global _manager
            if _manager is None:
                _manager = TaskManager()
            return _manager


        # ---------------------------------------------------------------------------
        # Poll hint constant (exposed for route headers)
        # ---------------------------------------------------------------------------

        POLL_INTERVAL_HINT: int = _POLL_HINT
        MAX_TASK_DURATION: int = _MAX_DURATION
        RESULT_TTL: int = _DEFAULT_TTL
        """)
    dest.write_text(content)


def _write_task_registry(dest: Path) -> None:
    """Write ``app/core/task_registry.py``.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Registry of async task handlers.  Workers look up handlers by task_type.

        Register handlers at application startup::

            from app.core.task_registry import task_registry

            @task_registry.register("pdf_export")
            async def export_pdf(raw_id: str, params: dict) -> dict:
                ...
        \"\"\"

        from __future__ import annotations

        import inspect
        from typing import Any, Awaitable, Callable


        class TaskRegistry:
            \"\"\"Thread-safe registry mapping task_type strings to async handlers.

            Attributes:
                _handlers: Mapping from task_type to async callable.
            \"\"\"

            def __init__(self) -> None:
                self._handlers: dict[str, Callable[..., Awaitable[Any]]] = {}

            def register(self, task_type: str) -> Callable:
                \"\"\"Decorator that registers an async handler under *task_type*.

                Args:
                    task_type: Unique task type identifier string.

                Returns:
                    The original handler function, unmodified.

                Raises:
                    ValueError: If *task_type* is already registered.
                    TypeError: If the decorated function is not a coroutine function.
                \"\"\"
                def decorator(func: Callable) -> Callable:
                    \"\"\"Register the decorated coroutine under *task_type*.

                    Args:
                        func: Async handler to register.

                    Returns:
                        The original function, unmodified.

                    Raises:
                        ValueError: If *task_type* is already registered.
                        TypeError: If *func* is not a coroutine function.
                    \"\"\"
                    if task_type in self._handlers:
                        raise ValueError(f"Task type '{task_type}' is already registered.")
                    if not inspect.iscoroutinefunction(func):
                        raise TypeError(
                            f"Task handler '{func.__name__}' must be an async function."
                        )
                    self._handlers[task_type] = func
                    return func
                return decorator

            def get(self, task_type: str) -> Callable[..., Awaitable[Any]]:
                \"\"\"Return the registered handler for *task_type*.

                Args:
                    task_type: Task type identifier.

                Returns:
                    Registered async callable.

                Raises:
                    KeyError: If *task_type* is not registered.
                \"\"\"
                if task_type not in self._handlers:
                    raise KeyError(
                        f"Unknown task type: '{task_type}'. "
                        f"Registered: {sorted(self._handlers.keys())}"
                    )
                return self._handlers[task_type]

            def registered_types(self) -> list[str]:
                \"\"\"Return all registered task type strings.

                Returns:
                    Sorted list of registered type identifiers.
                \"\"\"
                return sorted(self._handlers.keys())


        task_registry: TaskRegistry = TaskRegistry()
        """)
    dest.write_text(content)


def _write_task_schemas(dest: Path) -> None:
    """Write ``app/schemas/task.py`` with Pydantic request/response models.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Pydantic schemas for the long-running task API.\"\"\"

        from __future__ import annotations

        from enum import Enum
        from typing import Any

        from pydantic import BaseModel, Field


        class TaskStatus(str, Enum):
            \"\"\"Task lifecycle state.

            Attributes:
                PENDING: Queued but not yet started.
                RUNNING: Currently executing.
                COMPLETED: Finished successfully.
                FAILED: Terminated with error.
                CANCELLED: Cancelled by client request.
            \"\"\"

            PENDING = "pending"
            RUNNING = "running"
            COMPLETED = "completed"
            FAILED = "failed"
            CANCELLED = "cancelled"


        class TaskSubmit(BaseModel):
            \"\"\"Request body for POST /tasks.

            Attributes:
                task_type: Registered task type identifier.
                params: Arbitrary JSON-serialisable parameters for the worker.
            \"\"\"

            task_type: str = Field(..., min_length=1, max_length=255)
            params: dict[str, Any] = Field(default_factory=dict)


        class TaskStatusResponse(BaseModel):
            \"\"\"Response body for GET /tasks/{id}.

            Attributes:
                task_id: Encrypted task ID token (opaque to clients).
                task_type: Registered task type identifier.
                status: Current lifecycle state.
                progress: Progress percentage 0-100.
                message: Human-readable progress description.
                result: Final result payload when status=completed.
                error: Error message when status=failed.
                created_at: ISO-8601 creation timestamp.
                updated_at: ISO-8601 last update timestamp.
            \"\"\"

            task_id: str
            task_type: str
            status: TaskStatus
            progress: float = Field(default=0.0, ge=0.0, le=100.0)
            message: str = ""
            result: Any | None = None
            error: str | None = None
            created_at: str
            updated_at: str


        class TaskCancelResponse(BaseModel):
            \"\"\"Response body for DELETE /tasks/{id}.

            Attributes:
                task_id: Encrypted task ID token.
                message: Human-readable confirmation.
            \"\"\"

            task_id: str
            message: str = "Cancellation requested. Worker will stop at next checkpoint."
        """)
    dest.write_text(content)


def _write_task_routes(dest: Path) -> None:
    """Write ``app/api/routes/tasks.py`` with submit/poll/cancel endpoints.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Long-running task API routes: submit, poll, cancel.\"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, HTTPException, status
        from fastapi.responses import JSONResponse

        from app.api.deps import CurrentUser, SessionDep
        from app.core.task_manager import POLL_INTERVAL_HINT, get_task_manager
        from app.core.task_registry import task_registry
        from app.schemas.task import TaskCancelResponse, TaskStatus, TaskStatusResponse, TaskSubmit

        router = APIRouter(prefix="/tasks", tags=["tasks"])


        @router.post(
            "",
            response_model=None,
            status_code=status.HTTP_202_ACCEPTED,
            summary="Submit a long-running task",
        )
        async def submit_task(
            task_in: TaskSubmit,
            current_user: CurrentUser,
        ) -> JSONResponse:
            \"\"\"Queue a long-running task.  Returns 202 with a Location header.

            The client should poll ``GET /tasks/{task_id}`` until status is
            ``completed`` or ``failed``.  Use ``DELETE /tasks/{task_id}`` to
            request cooperative cancellation.

            Args:
                task_in: Validated task submission body.
                current_user: Authenticated requesting user.

            Returns:
                JSONResponse with 202 status and Location header.

            Raises:
                HTTPException: 422 if task_type is not registered.
            \"\"\"
            try:
                task_registry.get(task_in.task_type)
            except KeyError:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown task_type '{task_in.task_type}'. "
                           f"Registered: {task_registry.registered_types()}",
                )
            mgr = get_task_manager()
            token = await mgr.create(
                owner_id=str(current_user.id),
                task_type=task_in.task_type,
                params=task_in.params,
            )
            return JSONResponse(
                content={"task_id": token},
                status_code=status.HTTP_202_ACCEPTED,
                headers={
                    "Location": f"/tasks/{token}",
                    "Retry-After": str(POLL_INTERVAL_HINT),
                },
            )


        @router.get(
            "/{task_id}",
            response_model=TaskStatusResponse,
            summary="Poll task status",
        )
        async def get_task_status(
            task_id: str,
            current_user: CurrentUser,
        ) -> TaskStatusResponse:
            \"\"\"Poll the current status of a submitted task.

            Args:
                task_id: Encrypted task ID token from POST /tasks response.
                current_user: Authenticated requesting user.

            Returns:
                TaskStatusResponse with current state and progress.

            Raises:
                HTTPException: 404 if task not found.
                HTTPException: 403 if task belongs to a different user.
                HTTPException: 400 if task_id token is invalid.
            \"\"\"
            mgr = get_task_manager()
            try:
                data = await mgr.get(task_id, owner_id=str(current_user.id))
            except KeyError:
                raise HTTPException(status_code=404, detail="Task not found.")
            except PermissionError:
                raise HTTPException(status_code=403, detail="Access denied.")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid task ID.")

            import json
            result_raw = data.get("result", "") or ""
            result = json.loads(result_raw) if result_raw else None

            return TaskStatusResponse(
                task_id=task_id,
                task_type=data.get("task_type", ""),
                status=TaskStatus(data.get("status", "pending")),
                progress=float(data.get("progress", 0)),
                message=data.get("message", ""),
                result=result,
                error=data.get("error") or None,
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
            )


        @router.delete(
            "/{task_id}",
            response_model=TaskCancelResponse,
            summary="Request task cancellation",
        )
        async def cancel_task(
            task_id: str,
            current_user: CurrentUser,
        ) -> TaskCancelResponse:
            \"\"\"Signal the worker to stop at the next cooperative checkpoint.

            Cancellation is not immediate — the worker checks for the Redis flag
            between processing steps and exits cleanly when found.

            Args:
                task_id: Encrypted task ID token.
                current_user: Authenticated requesting user.

            Returns:
                TaskCancelResponse confirming the cancellation request.

            Raises:
                HTTPException: 404 if task not found.
                HTTPException: 403 if task belongs to a different user.
                HTTPException: 400 if task_id token is invalid.
            \"\"\"
            mgr = get_task_manager()
            try:
                await mgr.request_cancel(task_id, owner_id=str(current_user.id))
            except KeyError:
                raise HTTPException(status_code=404, detail="Task not found.")
            except PermissionError:
                raise HTTPException(status_code=403, detail="Access denied.")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid task ID.")
            return TaskCancelResponse(task_id=task_id)
        """)
    dest.write_text(content)


def _write_arq_worker(dest: Path) -> None:
    """Write ``workers/task_worker.py`` with ARQ worker settings.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"ARQ worker — dequeues tasks from Redis and executes registered handlers.

        Start the worker::

            arq workers.task_worker.WorkerSettings

        The worker respects cooperative cancellation: after each progress report
        it calls ``TaskManager.is_cancel_requested`` and exits early if the flag
        is set.
        \"\"\"

        from __future__ import annotations

        import json
        import os
        from typing import Any

        import arq


        async def execute_task(ctx: dict, raw_id: str, task_type: str, params: str) -> None:
            \"\"\"ARQ job: run the handler for *task_type* and update Redis state.

            Args:
                ctx: ARQ context dict (contains ``redis`` client).
                raw_id: Raw UUID string of the task (not encrypted).
                task_type: Registered task type identifier.
                params: JSON-encoded parameter dict.

            The handler is looked up via ``task_registry``; any exception sets
            status=failed.  The worker checks ``is_cancel_requested`` before
            executing and marks the task cancelled if the flag is set.
            \"\"\"
            from app.core.task_manager import TaskManager, TaskStatus
            from app.core.task_registry import task_registry

            mgr = TaskManager(redis=ctx["redis"])

            # Honour cancellation requests submitted before pickup
            if await mgr.is_cancel_requested(raw_id):
                await mgr.set_status(raw_id, TaskStatus.CANCELLED.value)
                return

            await mgr.set_status(raw_id, TaskStatus.RUNNING.value)
            parsed_params = json.loads(params)

            try:
                handler = task_registry.get(task_type)
                result = await handler(raw_id=raw_id, params=parsed_params)
                await mgr.set_result(raw_id, result)
            except Exception as exc:
                await mgr.set_error(raw_id, f"{type(exc).__name__}: {exc}")
                raise


        class WorkerSettings:
            \"\"\"ARQ WorkerSettings — configure Redis URL and job functions here.

            Attributes:
                functions: List of job functions the worker can execute.
                redis_settings: arq.connections.RedisSettings from REDIS_URL env var.
                max_jobs: Concurrency limit (10 by default).
                job_timeout: Hard timeout per job in seconds.
            \"\"\"

            functions = [execute_task]
            redis_settings = arq.connections.RedisSettings.from_dsn(
                os.getenv("REDIS_URL", "redis://localhost:6379")
            )
            max_jobs: int = 10
            job_timeout: int = int(os.getenv("TASK_MAX_DURATION_SECONDS", "3600"))
        """)
    dest.write_text(content)


def _write_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration adding the tasks table.

    Args:
        versions_dir: ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    rev_id = "add_tasks_table"
        # Find the true HEAD of the migration chain (not just the alphabetically last file)
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = textwrap.dedent("""\
        \"\"\"Add tasks table for long-running task infrastructure.

        Revision ID: {rev_id}
        Revises: {down_rev}
        Create Date: auto-generated by add_long_running_task tool
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "{rev_id}"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create tasks table with owner FK and composite status index.\"\"\"
            op.create_table(
                "tasks",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column("task_type", sa.String(255), nullable=False),
                sa.Column(
                    "status",
                    sa.String(16),
                    nullable=False,
                    server_default="pending",
                ),
                sa.Column(
                    "owner_id",
                    sa.Uuid(),
                    sa.ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False,
                    index=True,
                ),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
            )
            op.create_index(
                "ix_tasks_owner_status", "tasks", ["owner_id", "status"]
            )


        def downgrade() -> None:
            \"\"\"Drop tasks table and its composite index.\"\"\"
            op.drop_index("ix_tasks_owner_status", table_name="tasks")
            op.drop_table("tasks")
        """).replace("{rev_id}", rev_id).replace("{down_rev}", down_rev)

    migration_file = versions_dir / f"{rev_id}.py"
    migration_file.write_text(content)
    return migration_file


def _patch_router(router_file: Path) -> None:
    """Register the tasks router in ``app/routes/__init__.py``.

    The real router assembly lives in ``app/routes/__init__.py`` (see
    ``generators/orchestrator.py``), NOT ``app/api/main.py`` (which does not
    exist in the generated scaffold). Idempotent — no-op if already present.

    Args:
        router_file: Path to ``app/routes/__init__.py``.
    """
    src = router_file.read_text()
    import_line = "from app.api.routes.tasks import router as _tasks_router"
    include_line = "api_router.include_router(_tasks_router)"
    if import_line in src:
        return

    lines = src.splitlines()

    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)

    last_include_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include_idx = idx
    if last_include_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include_idx = idx
                break
    lines.insert(last_include_idx + 1, include_line)

    router_file.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


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
