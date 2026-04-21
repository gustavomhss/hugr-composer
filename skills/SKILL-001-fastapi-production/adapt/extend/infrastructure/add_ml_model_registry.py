"""TOOL-070: add_ml_model_registry — add a production-grade ML model registry to a
FastAPI project.

Generates a pure DB registry for machine-learning model artefacts.  No ML
framework (torch, sklearn, transformers, etc.) is imported at any level — the
registry is framework-agnostic and tracks only metadata.

Files created:

* ``app/models/ml_model.py``      — ``MLModel`` SQLAlchemy model
* ``app/schemas/ml_model.py``     — Pydantic schemas (Create/Read/Promote/Compare)
* ``app/crud/ml_model.py``        — async CRUD helpers
* ``app/ml/registry_service.py``  — ``RegistryService`` (register, promote,
                                     rollback, get_active, ab_split)
* ``app/api/routes/ml_registry.py``  — REST endpoints
* ``alembic/versions/add_ml_model_registry.py``  — Alembic migration

Files modified:

* ``app/core/config.py``          — two new config fields (no new deps)
* ``app/models/__init__.py``      — MLModel registration
* ``app/routes/__init__.py``      — ml_registry router

The tool does NOT add any new entry to ``requirements.txt``; the registry is
implemented with standard FastAPI / SQLAlchemy 2.0 primitives already in the
project.

Idempotency fingerprint: ``"class MLModel"`` in ``app/models/ml_model.py``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_ml_model_registry import add_ml_model_registry

    result = add_ml_model_registry(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # [.../app/models/ml_model.py, ...]
    print(result.next_steps)     # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_resiliency_add_ml_model_registry",
    "description": (
        "Add a production-grade ML model registry with versioned artefacts, "
        "promote/rollback lifecycle, A/B split, and a compare endpoint. "
        "Pure DB registry — no ML framework imports."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_ml_model_registry",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_ml_model_registry(inp: ToolInput) -> ToolResult:
    """Add a production-grade ML model registry to a FastAPI project.

    Creates ``MLModel`` model/schema/CRUD, ``RegistryService``, HTTP routes,
    and an Alembic migration.  Patches ``app/core/config.py``,
    ``app/models/__init__.py``, and ``app/routes/__init__.py``.  Does NOT
    add any new Python package to ``requirements.txt`` — the implementation
    uses only FastAPI / SQLAlchemy 2.0 primitives already present.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(
            status="error",
            error=err,
            execution_time_ms=_elapsed_ms(start),
        )

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Idempotency guard -----------------------------------------------
    model_file = app_dir / "models" / "ml_model.py"
    if model_file.exists() and "class MLModel" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "class MLModel already present in app/models/ml_model.py — "
                "ML model registry is already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard (BEFORE any write) --------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/models/ml_model.py,",
                "         app/schemas/ml_model.py, app/crud/ml_model.py,",
                "         app/ml/registry_service.py,",
                "         app/api/routes/ml_registry.py,",
                "         and an Alembic migration for the ml_models table.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — MLModel SQLAlchemy model
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text(_ML_MODEL_TEMPLATE)
    files_created.append(str(model_file))

    # Step 2 — Register in app/models/__init__.py
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("ml_model", "MLModel")])
        files_modified.append(str(models_init))

    # Step 3 — Pydantic schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "ml_model.py"
    schema_file.write_text(_ML_MODEL_SCHEMAS_TEMPLATE)
    files_created.append(str(schema_file))

    # Step 4 — CRUD helpers
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    crud_file = crud_dir / "ml_model.py"
    crud_file.write_text(_ML_MODEL_CRUD_TEMPLATE)
    files_created.append(str(crud_file))

    # Step 5 — RegistryService
    ml_dir = app_dir / "ml"
    ml_dir.mkdir(parents=True, exist_ok=True)
    ml_init = ml_dir / "__init__.py"
    if not ml_init.exists():
        ml_init.write_text('"""ML subpackage."""\n')
        files_created.append(str(ml_init))
    registry_svc = ml_dir / "registry_service.py"
    registry_svc.write_text(_REGISTRY_SERVICE_TEMPLATE)
    files_created.append(str(registry_svc))

    # Step 6 — HTTP routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    route_file = routes_dir / "ml_registry.py"
    route_file.write_text(_ML_REGISTRY_ROUTES_TEMPLATE)
    files_created.append(str(route_file))

    # Step 7 — Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        mig_file = _write_ml_migration(versions_dir)
        files_created.append(str(mig_file))

    # Step 8 — Patch config.py
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 9 — Register router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 10 — ast.parse validation (INV-03, QS-07)
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "ML model registry added: MLModel (registered/staging/production/"
            "archived/rolled_back), schemas, CRUD, RegistryService, REST routes.",
            "Endpoints: POST /ml/models, GET /ml/models, "
            "GET /ml/models/{name}/versions, POST /ml/models/{name}/promote, "
            "POST /ml/models/{name}/rollback, POST /ml/models/{name}/ab-test.",
            "Framework-agnostic: no torch/sklearn/etc. imports anywhere.",
            "A/B split uses add_feature_toggles_api if installed; stubs otherwise.",
        ],
        next_steps=[
            "alembic upgrade head",
            "POST /ml/models to register a model artefact.",
            "POST /ml/models/{name}/promote to move a version to production.",
            "GET /ml/models/{name}/versions to list all registered versions.",
            "POST /ml/models/{name}/ab-test to configure percentage rollout "
            "(requires add_feature_toggles_api for persistence).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _write_ml_migration(versions_dir: Path) -> Path:
    """Generate ``alembic/versions/add_ml_model_registry.py``.

    Chains onto the current Alembic HEAD via ``find_migration_head`` to
    avoid multi-root forks when other adapt tools have already run.

    Args:
        versions_dir: Path to ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = _ML_MIGRATION_TEMPLATE.replace("DOWN_REV", down_rev)
    mig_file = versions_dir / "add_ml_model_registry.py"
    mig_file.write_text(content)
    return mig_file


def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently.

    Args:
        models_init: Path to ``app/models/__init__.py``.
        class_imports: List of ``(module, class)`` tuples to register.
    """
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker in content:
            continue
        new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Inject ML registry settings into the ``Settings`` class body.

    Args:
        config_file: Path to the existing ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "ML_REGISTRY_DEFAULT_FRAMEWORK" in src:
        return

    block = (
        "\n"
        "    # --- ML model registry — added by add_ml_model_registry tool ---\n"
        '    ML_REGISTRY_DEFAULT_FRAMEWORK: str = "sklearn"\n'
        '    ML_REGISTRY_ARTIFACT_BASE_PATH: str = "/tmp/ml_artifacts"\n'
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(
                settings_line,
                block.lstrip("\n") + "\n\n" + settings_line,
            )
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the ML registry router in ``app/routes/__init__.py``.

    Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    import_line = (
        "from app.api.routes.ml_registry import router as ml_registry_router"
    )
    include_line = "api_router.include_router(ml_registry_router)"
    _register_router(routes_init, import_line=import_line, include_line=include_line)


def _register_router(
    routes_init: Path,
    *,
    import_line: str,
    include_line: str,
) -> None:
    """Idempotently add an import + ``api_router.include_router`` call.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
        import_line: Import statement to insert (no trailing newline).
        include_line: ``api_router.include_router(...)`` call.
    """
    src = routes_init.read_text()
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

    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_ML_MODEL_TEMPLATE = textwrap.dedent("""\
    \"\"\"SQLAlchemy model for ML model registry artefacts.

    Each row represents one version of a named ML model.  The registry is
    framework-agnostic — it stores only metadata (artifact_path, framework
    name, metrics JSON) and manages lifecycle state transitions.

    Status transitions::

        registered → staging → production
                              ↗
            rolled_back ←────  (rollback restores previous production version)
            archived    ←────  (previous production is archived on promote)
    \"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime

    from sqlalchemy import DateTime, Index, JSON, String, Uuid, func
    from sqlalchemy.orm import Mapped, mapped_column

    from app.models.base import Base


    class MLModel(Base):
        \"\"\"A versioned ML model artefact entry in the registry.

        Attributes:
            id: Internal UUID primary key.
            name: Logical model name (e.g. ``"fraud_detector"``).
            version: Semantic version string (e.g. ``"1.2.3"``).
            artifact_path: Filesystem or object-storage path to the artefact.
            framework: Framework name string (e.g. ``"sklearn"``, ``"pytorch"``).
            metrics_json: Free-form JSON with accuracy, f1, latency, etc.
            status: Lifecycle status — one of ``registered``, ``staging``,
                ``production``, ``archived``, ``rolled_back``.
            promoted_at: UTC timestamp when this version entered production.
            created_at: UTC timestamp when the row was inserted.
        \"\"\"

        __tablename__ = "ml_models"

        id: Mapped[uuid.UUID] = mapped_column(
            Uuid, primary_key=True, default=uuid.uuid4
        )
        name: Mapped[str] = mapped_column(
            String(128), nullable=False, index=True
        )
        version: Mapped[str] = mapped_column(
            String(64), nullable=False
        )
        artifact_path: Mapped[str] = mapped_column(
            String(512), nullable=False, default=""
        )
        framework: Mapped[str] = mapped_column(
            String(64), nullable=False, default="unknown"
        )
        metrics_json: Mapped[dict | None] = mapped_column(
            JSON, nullable=True
        )
        status: Mapped[str] = mapped_column(
            String(32), nullable=False, default="registered", index=True
        )
        promoted_at: Mapped[datetime | None] = mapped_column(
            DateTime(timezone=True), nullable=True
        )
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )

        __table_args__ = (
            Index("ix_ml_models_name_version", "name", "version", unique=True),
        )
""")


_ML_MODEL_SCHEMAS_TEMPLATE = textwrap.dedent("""\
    \"\"\"Pydantic schemas for ML model registry.

    Schemas deliberately omit internal fields (``id``, ``created_at``) from
    create payloads and use ``MLModelRead`` for all API responses so the
    client always gets a stable, versioned view of the data.
    \"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime
    from typing import Any

    from pydantic import BaseModel, ConfigDict, Field


    class MLModelCreate(BaseModel):
        \"\"\"Payload for registering a new model version.\"\"\"

        name: str = Field(..., max_length=128, description="Logical model name")
        version: str = Field(..., max_length=64, description="Semantic version string")
        artifact_path: str = Field(default="", max_length=512)
        framework: str = Field(default="sklearn", max_length=64)
        metrics_json: dict[str, Any] | None = Field(
            default=None, description="accuracy, f1, latency, etc."
        )


    class MLModelRead(BaseModel):
        \"\"\"Full model view returned by all read endpoints.\"\"\"

        model_config = ConfigDict(from_attributes=True)

        id: uuid.UUID
        name: str
        version: str
        artifact_path: str
        framework: str
        metrics_json: dict[str, Any] | None
        status: str
        promoted_at: datetime | None
        created_at: datetime


    class MLModelPromote(BaseModel):
        \"\"\"Payload for promoting a version to production.\"\"\"

        version: str = Field(..., description="Version to promote to production")


    class MLModelCompare(BaseModel):
        \"\"\"Side-by-side metrics comparison of two versions.\"\"\"

        model_config = ConfigDict(from_attributes=True)

        name: str
        version_a: str
        version_b: str
        metrics_a: dict[str, Any] | None
        metrics_b: dict[str, Any] | None
        winner: str | None = Field(
            default=None, description="Version with higher primary metric, or None if tied"
        )
""")


_ML_MODEL_CRUD_TEMPLATE = textwrap.dedent("""\
    \"\"\"Async CRUD helpers for the ML model registry.

    All helpers receive an ``AsyncSession`` and return typed results.  No
    ML framework is imported; this module is pure SQLAlchemy + Python.
    \"\"\"
    from __future__ import annotations

    import logging
    from datetime import datetime, timezone

    from sqlalchemy import select, update
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.ml_model import MLModel
    from app.schemas.ml_model import MLModelCreate

    logger = logging.getLogger(__name__)


    async def register(session: AsyncSession, payload: MLModelCreate) -> MLModel:
        \"\"\"Insert a new model version with status=registered.

        Args:
            session: Active async database session.
            payload: Validated create payload.

        Returns:
            The newly created ``MLModel`` row.
        \"\"\"
        row = MLModel(
            name=payload.name,
            version=payload.version,
            artifact_path=payload.artifact_path,
            framework=payload.framework,
            metrics_json=payload.metrics_json,
            status="registered",
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        logger.info("Registered model %s v%s", payload.name, payload.version)
        return row


    async def get_by_version(
        session: AsyncSession, name: str, version: str
    ) -> MLModel | None:
        \"\"\"Fetch a specific model version by name + version.

        Args:
            session: Active async database session.
            name: Logical model name.
            version: Semantic version string.

        Returns:
            ``MLModel`` row or ``None`` if not found.
        \"\"\"
        result = await session.execute(
            select(MLModel).where(
                MLModel.name == name,
                MLModel.version == version,
            )
        )
        return result.scalars().first()


    async def get_active(session: AsyncSession, name: str) -> MLModel | None:
        \"\"\"Return the current production version for a named model.

        Args:
            session: Active async database session.
            name: Logical model name.

        Returns:
            The production ``MLModel`` row, or ``None`` if none promoted yet.
        \"\"\"
        result = await session.execute(
            select(MLModel).where(
                MLModel.name == name,
                MLModel.status == "production",
            )
        )
        return result.scalars().first()


    async def list_versions(
        session: AsyncSession, name: str, limit: int = 50
    ) -> list[MLModel]:
        \"\"\"List all versions of a named model, newest first.

        Args:
            session: Active async database session.
            name: Logical model name.
            limit: Maximum number of rows to return (default 50).

        Returns:
            List of ``MLModel`` rows ordered by ``created_at`` descending.
        \"\"\"
        result = await session.execute(
            select(MLModel)
            .where(MLModel.name == name)
            .order_by(MLModel.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


    async def list_all(session: AsyncSession, limit: int = 100) -> list[MLModel]:
        \"\"\"List all model entries across all names, newest first.

        Args:
            session: Active async database session.
            limit: Maximum number of rows to return (default 100).

        Returns:
            List of all ``MLModel`` rows ordered by ``created_at`` descending.
        \"\"\"
        result = await session.execute(
            select(MLModel).order_by(MLModel.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


    async def promote(
        session: AsyncSession, name: str, version: str
    ) -> MLModel | None:
        \"\"\"Promote *version* to production; archive the previous production row.

        1. Set the current production row (if any) to ``archived``.
        2. Set the target version to ``production`` and stamp ``promoted_at``.

        Args:
            session: Active async database session.
            name: Logical model name.
            version: Version to promote.

        Returns:
            The promoted ``MLModel`` row, or ``None`` if *version* not found.
        \"\"\"
        target = await get_by_version(session, name, version)
        if target is None:
            return None
        await session.execute(
            update(MLModel)
            .where(MLModel.name == name, MLModel.status == "production")
            .values(status="archived")
        )
        target.status = "production"
        target.promoted_at = datetime.now(timezone.utc)
        await session.flush()
        await session.refresh(target)
        logger.info("Promoted model %s to production (v%s)", name, version)
        return target


    async def rollback(session: AsyncSession, name: str) -> MLModel | None:
        \"\"\"Roll back the current production version; restore the previous one.

        Sets the current production row to ``rolled_back``, then sets the
        most-recently archived row back to ``production``.

        Args:
            session: Active async database session.
            name: Logical model name.

        Returns:
            The restored ``MLModel`` row, or ``None`` if rollback is not possible.
        \"\"\"
        current = await get_active(session, name)
        if current is None:
            return None
        current.status = "rolled_back"
        result = await session.execute(
            select(MLModel)
            .where(MLModel.name == name, MLModel.status == "archived")
            .order_by(MLModel.promoted_at.desc())
            .limit(1)
        )
        previous = result.scalars().first()
        if previous is None:
            return None
        previous.status = "production"
        previous.promoted_at = datetime.now(timezone.utc)
        await session.flush()
        await session.refresh(previous)
        logger.info("Rolled back model %s to v%s", name, previous.version)
        return previous


    async def compare_metrics(
        session: AsyncSession, name: str, version_a: str, version_b: str
    ) -> tuple[MLModel | None, MLModel | None]:
        \"\"\"Fetch two versions for side-by-side metrics comparison.

        Args:
            session: Active async database session.
            name: Logical model name.
            version_a: First version to compare.
            version_b: Second version to compare.

        Returns:
            Tuple of ``(row_a, row_b)``; either may be ``None`` if not found.
        \"\"\"
        row_a = await get_by_version(session, name, version_a)
        row_b = await get_by_version(session, name, version_b)
        return row_a, row_b
""")


_REGISTRY_SERVICE_TEMPLATE = textwrap.dedent("""\
    \"\"\"RegistryService — high-level ML model registry operations.

    Wraps the CRUD layer with business logic: promote, rollback, A/B split.
    If ``add_feature_toggles_api`` is installed the A/B split persists the
    rollout percentage to the ``feature_toggles`` table; otherwise a stub
    response is returned.

    No ML framework (torch, sklearn, etc.) is imported.
    \"\"\"
    from __future__ import annotations

    import logging
    from typing import Any

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.crud import ml_model as crud
    from app.models.ml_model import MLModel
    from app.schemas.ml_model import MLModelCompare, MLModelCreate

    logger = logging.getLogger(__name__)


    class RegistryService:
        \"\"\"Facade for ML model registry operations.

        Attributes:
            session: SQLAlchemy async session (injected via FastAPI dependency).
        \"\"\"

        def __init__(self, session: AsyncSession) -> None:
            \"\"\"Initialise with an active async session.

            Args:
                session: Active ``AsyncSession`` instance.
            \"\"\"
            self.session = session

        async def register_model(self, payload: MLModelCreate) -> MLModel:
            \"\"\"Register a new model version.

            Args:
                payload: Validated create payload.

            Returns:
                The newly inserted ``MLModel`` row.
            \"\"\"
            return await crud.register(self.session, payload)

        async def promote_to_production(
            self, name: str, version: str
        ) -> MLModel | None:
            \"\"\"Promote *version* to production status.

            Args:
                name: Logical model name.
                version: Semantic version to promote.

            Returns:
                Promoted ``MLModel`` row, or ``None`` if version not found.
            \"\"\"
            return await crud.promote(self.session, name, version)

        async def rollback_to_previous(self, name: str) -> MLModel | None:
            \"\"\"Roll back current production version to the previous one.

            Args:
                name: Logical model name.

            Returns:
                Restored ``MLModel`` row, or ``None`` if rollback impossible.
            \"\"\"
            return await crud.rollback(self.session, name)

        async def get_active_model(self, name: str) -> MLModel | None:
            \"\"\"Return the current production version.

            Args:
                name: Logical model name.

            Returns:
                ``MLModel`` row with status=production, or ``None``.
            \"\"\"
            return await crud.get_active(self.session, name)

        async def ab_split(
            self, name: str, version_a: str, version_b: str, percentage: int
        ) -> dict[str, Any]:
            \"\"\"Configure an A/B percentage rollout between two versions.

            If ``add_feature_toggles_api`` is installed (detected by the
            presence of ``app.crud.feature_toggle``), the rollout is
            persisted to the ``feature_toggles`` table.  Otherwise a stub
            acknowledgement is returned.

            Args:
                name: Logical model name.
                version_a: Version sent to ``(100 - percentage)``% of traffic.
                version_b: Version sent to ``percentage``% of traffic.
                percentage: Integer 0-100 for version_b share.

            Returns:
                Dict with ``name``, ``version_a``, ``version_b``,
                ``percentage``, and ``backend`` keys.
            \"\"\"
            backend = "stub"
            try:
                import importlib
                ft_crud = importlib.import_module("app.crud.feature_toggle")
                flag_name = f"ml_ab_{name}"
                await ft_crud.upsert_toggle(
                    self.session,
                    name=flag_name,
                    rollout_percentage=percentage,
                )
                backend = "feature_toggles"
            except (ImportError, AttributeError):
                logger.debug("feature_toggles not installed; using stub A/B response")

            return {
                "name": name,
                "version_a": version_a,
                "version_b": version_b,
                "percentage": percentage,
                "backend": backend,
            }

        async def build_compare(
            self, name: str, version_a: str, version_b: str
        ) -> MLModelCompare:
            \"\"\"Build a side-by-side metrics comparison object.

            Args:
                name: Logical model name.
                version_a: First version.
                version_b: Second version.

            Returns:
                ``MLModelCompare`` with metrics from both versions.
            \"\"\"
            row_a, row_b = await crud.compare_metrics(
                self.session, name, version_a, version_b
            )
            metrics_a = row_a.metrics_json if row_a else None
            metrics_b = row_b.metrics_json if row_b else None
            winner = _pick_winner(version_a, metrics_a, version_b, metrics_b)
            return MLModelCompare(
                name=name,
                version_a=version_a,
                version_b=version_b,
                metrics_a=metrics_a,
                metrics_b=metrics_b,
                winner=winner,
            )


    def _pick_winner(
        v_a: str,
        m_a: dict[str, Any] | None,
        v_b: str,
        m_b: dict[str, Any] | None,
    ) -> str | None:
        \"\"\"Return the version with higher ``accuracy`` metric, or ``None``.

        Args:
            v_a: Label for first version.
            m_a: Metrics dict for first version.
            v_b: Label for second version.
            m_b: Metrics dict for second version.

        Returns:
            Version label of the winner, or ``None`` if undecidable.
        \"\"\"
        if m_a is None or m_b is None:
            return None
        acc_a = m_a.get("accuracy")
        acc_b = m_b.get("accuracy")
        if acc_a is None or acc_b is None:
            return None
        if acc_a > acc_b:
            return v_a
        if acc_b > acc_a:
            return v_b
        return None
""")


_ML_REGISTRY_ROUTES_TEMPLATE = textwrap.dedent("""\
    \"\"\"HTTP routes for the ML model registry.

    Prefix: ``/ml/models``

    Endpoints:
    * ``POST   /ml/models``               — register a new version
    * ``GET    /ml/models``               — list all entries
    * ``GET    /ml/models/{name}/versions`` — list versions of one model
    * ``POST   /ml/models/{name}/promote`` — promote a version to production
    * ``POST   /ml/models/{name}/rollback`` — rollback production version
    * ``POST   /ml/models/{name}/ab-test`` — configure A/B percentage rollout
    * ``GET    /ml/models/{name}/compare`` — compare metrics of two versions
    \"\"\"
    from __future__ import annotations

    import logging
    from typing import Annotated

    from fastapi import APIRouter, Depends, HTTPException, Query
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.crud import ml_model as crud
    from app.ml.registry_service import RegistryService
    from app.schemas.ml_model import (
        MLModelCompare,
        MLModelCreate,
        MLModelPromote,
        MLModelRead,
    )

    logger = logging.getLogger(__name__)

    router = APIRouter(prefix="/ml/models", tags=["ml-registry"])


    async def _get_session() -> AsyncSession:  # pragma: no cover
        \"\"\"FastAPI dependency: yield an async DB session.

        Replaced at test time by the patched db/session fixture.
        \"\"\"
        from app.core.session import get_session
        async for session in get_session():
            yield session


    SessionDep = Annotated[AsyncSession, Depends(_get_session)]


    @router.post("", response_model=MLModelRead, status_code=201)
    async def register_model(
        payload: MLModelCreate,
        session: SessionDep,
    ) -> MLModelRead:
        \"\"\"Register a new ML model version.

        Args:
            payload: Model creation payload.
            session: Injected async DB session.

        Returns:
            The newly created model entry.
        \"\"\"
        svc = RegistryService(session)
        row = await svc.register_model(payload)
        await session.commit()
        return MLModelRead.model_validate(row)


    @router.get("", response_model=list[MLModelRead])
    async def list_models(
        session: SessionDep,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[MLModelRead]:
        \"\"\"List all registered model entries.

        Args:
            session: Injected async DB session.
            limit: Maximum number of entries to return (1-500).

        Returns:
            List of model entries ordered by creation date descending.
        \"\"\"
        rows = await crud.list_all(session, limit=limit)
        return [MLModelRead.model_validate(r) for r in rows]


    @router.get("/{name}/versions", response_model=list[MLModelRead])
    async def list_versions(
        name: str,
        session: SessionDep,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[MLModelRead]:
        \"\"\"List all versions of a named model.

        Args:
            name: Logical model name.
            session: Injected async DB session.
            limit: Maximum number of entries to return (1-200).

        Returns:
            Versions ordered by creation date descending.
        \"\"\"
        rows = await crud.list_versions(session, name=name, limit=limit)
        return [MLModelRead.model_validate(r) for r in rows]


    @router.post("/{name}/promote", response_model=MLModelRead)
    async def promote_model(
        name: str,
        payload: MLModelPromote,
        session: SessionDep,
    ) -> MLModelRead:
        \"\"\"Promote a model version to production status.

        Archives the previously active production version automatically.

        Args:
            name: Logical model name.
            payload: Promote payload containing the target version.
            session: Injected async DB session.

        Returns:
            The promoted model entry.

        Raises:
            HTTPException 404: Version not found.
        \"\"\"
        svc = RegistryService(session)
        row = await svc.promote_to_production(name, payload.version)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"detail": f"Version {payload.version!r} not found for model {name!r}"},
            )
        await session.commit()
        return MLModelRead.model_validate(row)


    @router.post("/{name}/rollback", response_model=MLModelRead)
    async def rollback_model(
        name: str,
        session: SessionDep,
    ) -> MLModelRead:
        \"\"\"Roll back the current production version to the previous one.

        Args:
            name: Logical model name.
            session: Injected async DB session.

        Returns:
            The restored model entry.

        Raises:
            HTTPException 409: No rollback target found.
        \"\"\"
        svc = RegistryService(session)
        row = await svc.rollback_to_previous(name)
        if row is None:
            raise HTTPException(
                status_code=409,
                detail={"detail": f"Cannot rollback model {name!r}: no previous production version"},
            )
        await session.commit()
        return MLModelRead.model_validate(row)


    @router.post("/{name}/ab-test")
    async def ab_test(
        name: str,
        session: SessionDep,
        version_a: str = Query(...),
        version_b: str = Query(...),
        percentage: int = Query(default=50, ge=0, le=100),
    ) -> dict:
        \"\"\"Configure an A/B percentage rollout between two versions.

        Uses the feature-toggle backend when installed; returns a stub
        response otherwise.

        Args:
            name: Logical model name.
            session: Injected async DB session.
            version_a: Version A (reference / control).
            version_b: Version B (candidate / treatment).
            percentage: Percentage of traffic routed to version_b (0-100).

        Returns:
            Rollout configuration dict.
        \"\"\"
        svc = RegistryService(session)
        result = await svc.ab_split(name, version_a, version_b, percentage)
        await session.commit()
        return result


    @router.get("/{name}/compare", response_model=MLModelCompare)
    async def compare_versions(
        name: str,
        session: SessionDep,
        version_a: str = Query(...),
        version_b: str = Query(...),
    ) -> MLModelCompare:
        \"\"\"Compare metrics of two model versions side-by-side.

        Args:
            name: Logical model name.
            session: Injected async DB session.
            version_a: First version to compare.
            version_b: Second version to compare.

        Returns:
            ``MLModelCompare`` object with metrics from both versions.
        \"\"\"
        svc = RegistryService(session)
        return await svc.build_compare(name, version_a, version_b)
""")


_ML_MIGRATION_TEMPLATE = textwrap.dedent("""\
    \"\"\"Alembic migration — create ml_models table.

    Revision: add_ml_model_registry
    \"\"\"
    from __future__ import annotations

    import sqlalchemy as sa
    from alembic import op

    revision: str = "add_ml_model_registry"
    down_revision: str = "DOWN_REV"
    branch_labels = None
    depends_on = None


    def upgrade() -> None:
        \"\"\"Create the ml_models table.\"\"\"
        op.create_table(
            "ml_models",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("version", sa.String(64), nullable=False),
            sa.Column("artifact_path", sa.String(512), nullable=False, server_default=""),
            sa.Column("framework", sa.String(64), nullable=False, server_default="unknown"),
            sa.Column("metrics_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="registered"),
            sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index("ix_ml_models_name", "ml_models", ["name"])
        op.create_index("ix_ml_models_status", "ml_models", ["status"])
        op.create_index(
            "ix_ml_models_name_version",
            "ml_models",
            ["name", "version"],
            unique=True,
        )


    def downgrade() -> None:
        \"\"\"Drop the ml_models table.\"\"\"
        op.drop_index("ix_ml_models_name_version", table_name="ml_models")
        op.drop_index("ix_ml_models_status", table_name="ml_models")
        op.drop_index("ix_ml_models_name", table_name="ml_models")
        op.drop_table("ml_models")
""")
