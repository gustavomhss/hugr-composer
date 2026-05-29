"""TOOL-019: add_batch_endpoint — add POST /bulk with HTTP 207 Multi-Status to FastAPI.

Generates a shared ``BatchCore`` module (models + engine), per-model
``/items/bulk`` route files, and wires them into ``app/main.py``.  Each bulk
endpoint validates the full payload via Pydantic before any write, returns HTTP
207 Multi-Status with per-item ``{index, status_code, data|error}`` objects, and
supports both ``all_or_nothing`` and ``best_effort`` transaction modes.

Idempotency: a second run detects the ``BatchCore`` fingerprint and returns
``status="no_op"`` without touching any file.

Warnings:
    - Batch endpoint processing is SEQUENTIAL by default.
      Parallel mode is opt-in via BatchRequest.strategy="parallel".

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.api_design.add_batch_endpoint import add_batch_endpoint

    result = add_batch_endpoint(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["...app/core/batch_core.py", ...]
    print(result.next_steps)    # ["curl -X POST /items/bulk ...", ...]
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

_DEFAULT_MAX_BATCH: int = 50
_DEFAULT_TIMEOUT_MS: int = 5000

MCP_TOOL = {
    "name": "fastapi_api_add_batch_endpoint",
    "description": "Add a generic batch request endpoint that fans out to multiple sub-requests.",
    "tags": ["extend", "api_design"],
    "entry": "add_batch_endpoint",
}

_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


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
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=_PREREQ_NOTES,
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"

    # Idempotency guard
    batch_core = app_dir / "core" / "batch_core.py"
    if batch_core.exists() and "BatchCore" in batch_core.read_text():
        return ToolResult(
            status="no_op",
            notes=["BatchCore already present — batch endpoints already enabled, skipped."],
            execution_time_ms=_ms(start),
        )

    model_pairs = _discover_models(app_dir)
    if not model_pairs:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models found in app/models/. Generate models first.",
            execution_time_ms=_ms(start),
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
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []
    timeout_s = _DEFAULT_TIMEOUT_MS / 1000.0

    # Step 1: shared batch_core
    render_to(_HERE, "batch_core.py.tmpl", dest=batch_core, substitutions={})
    files_created.append(str(batch_core))

    # Step 2: idempotency store
    idempotency_file = app_dir / "core" / "idempotency.py"
    if not idempotency_file.exists():
        render_to(_HERE, "idempotency.py.tmpl", dest=idempotency_file, substitutions={})
        files_created.append(str(idempotency_file))
    else:
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
        render_to(
            _HERE,
            "bulk_route.py.tmpl",
            dest=route_file,
            substitutions={
                "model_name": pascal,
                "lower": stem,
                "max_batch": str(_DEFAULT_MAX_BATCH),
                "timeout_s": str(timeout_s),
            },
        )
        files_created.append(str(route_file))

    # Step 4: register bulk routers in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_router(routes_init, model_pairs)
        files_modified.append(str(routes_init))

    # Step 5: emit test
    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Batch endpoints added for: {', '.join(pascal_names)}.",
            "POST /{model}s/bulk — HTTP 207 Multi-Status.",
            f"Max batch size: {_DEFAULT_MAX_BATCH}. Rejects larger payloads with 422.",
            "Supports all_or_nothing and best_effort transaction modes.",
            "Per-item idempotency key via X-Idempotency-Key header.",
            "WARNING: sequential processing by default; parallel is opt-in.",
        ],
        next_steps=[
            "POST /items/bulk with JSON body: "
            '{"items": [...], "mode": "best_effort", "strategy": "sequential"}',
            "Check response HTTP 207 for per-item status_code / error fields.",
        ],
        execution_time_ms=_ms(start),
    )


def _discover_models(app_dir: Path) -> list[tuple[str, str]]:
    """Return ``(snake_stem, PascalName)`` pairs for models with schema Create+Public."""
    models_dir = app_dir / "models"
    schemas_dir = app_dir / "schemas"
    skip = {"base", "user", "mixins", "__init__", "tenant"}
    pairs: list[tuple[str, str]] = []
    if not models_dir.exists():
        return pairs
    for f in sorted(models_dir.glob("*.py")):
        if f.stem in skip:
            continue
        stem = f.stem
        pascal = "".join(part.capitalize() for part in stem.split("_"))
        schema_file = schemas_dir / f"{stem}.py"
        if schema_file.exists():
            schema_src = schema_file.read_text()
            if f"class {pascal}Create" in schema_src and f"class {pascal}Public" in schema_src:
                pairs.append((stem, pascal))
    return pairs


def _merge_idempotency_store(dest: Path) -> None:
    """Append IdempotencyStore + get_idempotency_store to existing idempotency.py."""
    src = dest.read_text()
    if "get_idempotency_store" in src:
        return
    addition = (
        "\n\n# ---------------------------------------------------------------------------\n"
        "# IdempotencyStore — added by add_batch_endpoint tool\n"
        "# ---------------------------------------------------------------------------\n"
        "import threading as _threading\n"
        "from typing import Any as _Any\n"
        "\n\n"
        "class IdempotencyStore:\n"
        '    """Thread-safe in-memory idempotency store for batch requests."""\n\n'
        "    def __init__(self) -> None:\n"
        "        self._store: dict[str, _Any] = {}\n"
        "        self._lock = _threading.Lock()\n\n"
        "    def get(self, key: str) -> _Any | None:\n"
        '        """Return cached result for *key*, or None."""\n'
        "        with self._lock:\n"
        "            return self._store.get(key)\n\n"
        "    def put(self, key: str, result: _Any) -> None:\n"
        '        """Store *result* under *key*."""\n'
        "        with self._lock:\n"
        "            self._store[key] = result\n\n"
        "    def seen(self, key: str) -> bool:\n"
        '        """Return True if *key* was already processed."""\n'
        "        with self._lock:\n"
        "            return key in self._store\n\n\n"
        "_batch_store: IdempotencyStore = IdempotencyStore()\n\n\n"
        "def get_idempotency_store() -> IdempotencyStore:\n"
        '    """Return the process-wide IdempotencyStore singleton."""\n'
        "    return _batch_store\n"
    )
    dest.write_text(src + addition)


def _patch_router(router_file: Path, model_pairs: list[tuple[str, str]]) -> None:
    """Register bulk routers in ``app/routes/__init__.py`` idempotently."""
    src = router_file.read_text()
    lines = src.splitlines()

    for stem, _ in model_pairs:
        import_line = f"from app.api.routes.bulk.{stem}_bulk import router as _{stem}_bulk_router"
        include_line = (
            f"api_router.include_router(_{stem}_bulk_router, prefix='/{stem}s', tags=['bulk'])"
        )
        if import_line in "\n".join(lines):
            continue

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


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_add_batch_endpoint_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_batch_endpoint_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_batch_endpoint_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
