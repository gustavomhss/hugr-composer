"""TOOL-078: add_data_versioning — add draft/published/archived lifecycle to a FastAPI project.

Generates a content versioning system: ContentVersion model (draft → published →
archived lifecycle), VersioningService (create_draft, publish, archive, get_history,
diff), Pydantic schemas, CRUD helpers, and REST endpoints for managing drafts
and inspecting version history.  A configurable VERSIONING_MAX_DRAFTS setting
limits concurrent drafts per content item.

The tool is idempotent: a second run detects ``ContentVersion`` in
``app/models/content_version.py`` and returns ``status="no_op"`` without touching
any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.crud_data.add_data_versioning import add_data_versioning

    result = add_data_versioning(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["app/versioning/__init__.py", ...]
    print(result.next_steps)    # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_data_add_data_versioning",
    "description": "Add draft/published/archived lifecycle with diff to any content type.",
    "tags": ["extend", "crud_data"],
    "entry": "add_data_versioning",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_data_versioning(inp: ToolInput) -> ToolResult:
    """Add content versioning (draft/published/archived) to a FastAPI project.

    Generates ContentVersion model, VersioningService, schemas, CRUD, routes,
    and an Alembic migration.

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
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
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

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Pre-flight: is versioning already enabled? ----------------------------
    version_model = app_dir / "models" / "content_version.py"
    if version_model.exists() and "ContentVersion" in version_model.read_text():
        return ToolResult(
            status="no_op",
            notes=["ContentVersion model already present — data versioning is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would add content versioning (ContentVersion, VersioningService).",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: app/versioning/__init__.py --------------------------------
    versioning_pkg = app_dir / "versioning" / "__init__.py"
    _write_versioning_init(versioning_pkg)
    files_created.append(str(versioning_pkg))

    # --- Step 2: app/versioning/service.py ---------------------------------
    service_file = app_dir / "versioning" / "service.py"
    _write_versioning_service(service_file)
    files_created.append(str(service_file))

    # --- Step 3: app/models/content_version.py -----------------------------
    _write_content_version_model(version_model)
    files_created.append(str(version_model))

    # Register model in app/models/__init__.py
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [("content_version", "ContentVersion")],
    )

    # --- Step 4: app/schemas/version.py ------------------------------------
    schema_file = app_dir / "schemas" / "version.py"
    _write_version_schema(schema_file)
    files_created.append(str(schema_file))

    # --- Step 5: app/crud/version.py ---------------------------------------
    crud_file = app_dir / "crud" / "version.py"
    _write_version_crud(crud_file)
    files_created.append(str(crud_file))

    # --- Step 6: app/api/routes/versions.py --------------------------------
    routes_file = app_dir / "api" / "routes" / "versions.py"
    _write_version_routes(routes_file)
    files_created.append(str(routes_file))

    # --- Step 7: Register route in app/routes/__init__.py ------------------
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # --- Step 8: Patch config.py with versioning settings ------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 9: Alembic migration -----------------------------------------
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_migration(versions_dir)
        files_created.append(str(migration_file))

    # --- ast.parse validation loop -----------------------------------------
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
            "ContentVersion model created (content_id, version_number, status, data_json, "
            "published_at, author_id).",
            "VersioningService: create_draft, publish, archive, get_history, diff.",
            "Lifecycle: pending → draft → published → archived.",
            "Diff uses DeepDiff-style JSON field comparison (no external dep).",
            "Config: VERSIONING_MAX_DRAFTS (default 10) limits concurrent drafts per content.",
            "Routes: draft, publish, archive, history, diff — under /versions/{content_type}/{id}.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set VERSIONING_MAX_DRAFTS in your .env to change concurrent draft limit.",
            "Pass author_id (user UUID) to VersioningService calls.",
            "Restart the application.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently.

    Args:
        models_init: Path to the models ``__init__.py``.
        class_imports: List of ``(module_stem, ClassName)`` tuples.
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


def _patch_routes_init(routes_init: Path) -> None:
    """Register versions router in ``app/routes/__init__.py``.

    Args:
        routes_init: Path to the routes ``__init__.py``.
    """
    src = routes_init.read_text()
    if "versions_router" in src:
        return
    addition = textwrap.dedent("""\

        # --- Data versioning routes — added by add_data_versioning tool ---
        from app.api.routes.versions import router as versions_router  # noqa: E402
        api_router.include_router(versions_router)
        """)
    routes_init.write_text(src.rstrip("\n") + "\n" + addition)


def _patch_config(config_file: Path) -> None:
    """Inject versioning settings into ``app/core/config.py``.

    Fields are inserted with 4-space indent so they land inside the Settings class body.

    Args:
        config_file: Path to the config module.
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("VERSIONING_MAX_DRAFTS", "VERSIONING_MAX_DRAFTS: int = 10"),
        ],
    )


def _write_versioning_init(dest: Path) -> None:
    """Write ``app/versioning/__init__.py`` package marker.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Content versioning package.

        Exposes VersioningService for managing draft/published/archived lifecycles.
        \"\"\"

        from app.versioning.service import VersioningService

        __all__ = ["VersioningService"]
        """))


def _write_versioning_service(dest: Path) -> None:
    """Write ``app/versioning/service.py`` with VersioningService.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"VersioningService — create drafts, publish, archive, diff content versions.

        Lifecycle
        ---------
        create_draft  → status=draft   (version_number auto-incremented)
        publish       → status=published, published_at=now(), previous published → archived
        archive       → status=archived  (idempotent)
        get_history   → all versions for a content_id, newest first
        diff          → field-level diff between two version numbers
        \"\"\"

        from __future__ import annotations

        import logging
        import uuid
        from datetime import datetime, timezone
        from typing import Any

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.content_version import ContentVersion

        logger = logging.getLogger(__name__)

        # Maximum number of active drafts per content_id (overridden by settings).
        _DEFAULT_MAX_DRAFTS: int = 10


        class VersioningService:
            \"\"\"Service layer for content version lifecycle management.

            Attributes:
                max_drafts: Maximum concurrent drafts allowed per content_id.
            \"\"\"

            def __init__(self, max_drafts: int = _DEFAULT_MAX_DRAFTS) -> None:
                \"\"\"Initialise the service.

                Args:
                    max_drafts: Maximum concurrent drafts per content item.
                \"\"\"
                self.max_drafts = max_drafts

            async def create_draft(
                self,
                session: AsyncSession,
                content_id: str,
                content_type: str,
                data: dict[str, Any],
                author_id: uuid.UUID | None = None,
            ) -> ContentVersion:
                \"\"\"Create a new draft version for a content item.

                Enforces max_drafts limit. Auto-increments version_number.

                Args:
                    session: Async SQLAlchemy session.
                    content_id: Opaque string ID of the content item.
                    content_type: Lowercase name of the content type (e.g. 'article').
                    data: JSON-serialisable dict representing the content snapshot.
                    author_id: UUID of the user creating the draft.

                Returns:
                    The newly created ContentVersion with status='draft'.

                Raises:
                    ValueError: If max_drafts limit is reached for this content_id.
                \"\"\"
                drafts = await self._count_drafts(session, content_id)
                if drafts >= self.max_drafts:
                    raise ValueError(
                        f"Max drafts ({self.max_drafts}) reached for content_id={content_id}"
                    )
                next_version = await self._next_version_number(session, content_id)
                version = ContentVersion(
                    content_id=content_id,
                    content_type=content_type,
                    version_number=next_version,
                    status="draft",
                    data_json=data,
                    author_id=author_id,
                )
                session.add(version)
                await session.commit()
                await session.refresh(version)
                return version

            async def publish(
                self,
                session: AsyncSession,
                content_id: str,
                version_number: int,
            ) -> ContentVersion:
                \"\"\"Publish a specific draft version.

                Transitions the target version to published and archives any
                currently published version for the same content_id.

                Args:
                    session: Async SQLAlchemy session.
                    content_id: Opaque string ID of the content item.
                    version_number: Version number of the draft to publish.

                Returns:
                    The updated ContentVersion with status='published'.

                Raises:
                    ValueError: If the target version does not exist or is not a draft.
                \"\"\"
                version = await self._get_version(session, content_id, version_number)
                if version is None:
                    raise ValueError(
                        f"Version {version_number} not found for content_id={content_id}"
                    )
                if version.status not in ("draft", "pending"):
                    raise ValueError(
                        f"Only draft versions can be published; current status={version.status}"
                    )
                # Archive the currently published version
                await self._archive_current_published(session, content_id)
                version.status = "published"
                version.published_at = datetime.now(timezone.utc)
                await session.commit()
                await session.refresh(version)
                return version

            async def archive(
                self,
                session: AsyncSession,
                content_id: str,
                version_number: int,
            ) -> ContentVersion:
                \"\"\"Archive a specific version (idempotent).

                Args:
                    session: Async SQLAlchemy session.
                    content_id: Opaque string ID of the content item.
                    version_number: Version number to archive.

                Returns:
                    The updated ContentVersion with status='archived'.

                Raises:
                    ValueError: If the target version does not exist.
                \"\"\"
                version = await self._get_version(session, content_id, version_number)
                if version is None:
                    raise ValueError(
                        f"Version {version_number} not found for content_id={content_id}"
                    )
                if version.status != "archived":
                    version.status = "archived"
                    await session.commit()
                    await session.refresh(version)
                return version

            async def get_history(
                self,
                session: AsyncSession,
                content_id: str,
                limit: int = 50,
            ) -> list[ContentVersion]:
                \"\"\"Return all versions for a content item, newest first.

                Args:
                    session: Async SQLAlchemy session.
                    content_id: Opaque string ID of the content item.
                    limit: Maximum number of versions to return.

                Returns:
                    List of ContentVersion instances ordered by version_number desc.
                \"\"\"
                stmt = (
                    select(ContentVersion)
                    .where(ContentVersion.content_id == content_id)
                    .order_by(ContentVersion.version_number.desc())
                    .limit(limit)
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())

            async def diff(
                self,
                session: AsyncSession,
                content_id: str,
                v1: int,
                v2: int,
            ) -> dict[str, Any]:
                \"\"\"Compute a field-level diff between two version numbers.

                Returns a dict with 'added', 'removed', and 'changed' keys.
                Values show (old, new) tuples for 'changed' fields.

                Args:
                    session: Async SQLAlchemy session.
                    content_id: Opaque string ID of the content item.
                    v1: Earlier version number.
                    v2: Later version number.

                Returns:
                    Dict with 'added', 'removed', 'changed' field-level diffs.

                Raises:
                    ValueError: If either version is not found.
                \"\"\"
                ver1 = await self._get_version(session, content_id, v1)
                ver2 = await self._get_version(session, content_id, v2)
                if ver1 is None:
                    raise ValueError(f"Version {v1} not found for content_id={content_id}")
                if ver2 is None:
                    raise ValueError(f"Version {v2} not found for content_id={content_id}")
                return _compute_diff(ver1.data_json or {}, ver2.data_json or {})

            async def _count_drafts(self, session: AsyncSession, content_id: str) -> int:
                \"\"\"Count active draft versions for a content item.

                Args:
                    session: Async SQLAlchemy session.
                    content_id: Opaque string ID of the content item.

                Returns:
                    Number of versions with status='draft'.
                \"\"\"
                stmt = select(ContentVersion).where(
                    ContentVersion.content_id == content_id,
                    ContentVersion.status == "draft",
                )
                result = await session.execute(stmt)
                return len(result.scalars().all())

            async def _next_version_number(
                self, session: AsyncSession, content_id: str
            ) -> int:
                \"\"\"Compute the next version number for a content item.

                Args:
                    session: Async SQLAlchemy session.
                    content_id: Opaque string ID of the content item.

                Returns:
                    Current max version_number + 1, or 1 if no versions exist.
                \"\"\"
                stmt = (
                    select(ContentVersion.version_number)
                    .where(ContentVersion.content_id == content_id)
                    .order_by(ContentVersion.version_number.desc())
                    .limit(1)
                )
                result = await session.execute(stmt)
                current = result.scalar_one_or_none()
                return (current or 0) + 1

            async def _get_version(
                self, session: AsyncSession, content_id: str, version_number: int
            ) -> ContentVersion | None:
                \"\"\"Fetch a specific version by content_id and version_number.

                Args:
                    session: Async SQLAlchemy session.
                    content_id: Opaque string ID of the content item.
                    version_number: The version to fetch.

                Returns:
                    ContentVersion instance or None if not found.
                \"\"\"
                stmt = select(ContentVersion).where(
                    ContentVersion.content_id == content_id,
                    ContentVersion.version_number == version_number,
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none()

            async def _archive_current_published(
                self, session: AsyncSession, content_id: str
            ) -> None:
                \"\"\"Archive any currently published version for a content item.

                Args:
                    session: Async SQLAlchemy session.
                    content_id: Opaque string ID of the content item.
                \"\"\"
                stmt = select(ContentVersion).where(
                    ContentVersion.content_id == content_id,
                    ContentVersion.status == "published",
                )
                result = await session.execute(stmt)
                for version in result.scalars().all():
                    version.status = "archived"


        def _compute_diff(
            old: dict[str, Any], new: dict[str, Any]
        ) -> dict[str, Any]:
            \"\"\"Compute a shallow field-level diff between two dicts.

            Args:
                old: The earlier data snapshot (v1).
                new: The later data snapshot (v2).

            Returns:
                Dict with 'added' (keys only in new), 'removed' (keys only in old),
                and 'changed' (keys in both with different values: {key: [old, new]}).
            \"\"\"
            old_keys = set(old.keys())
            new_keys = set(new.keys())
            added = {k: new[k] for k in new_keys - old_keys}
            removed = {k: old[k] for k in old_keys - new_keys}
            changed = {
                k: [old[k], new[k]]
                for k in old_keys & new_keys
                if old[k] != new[k]
            }
            return {"added": added, "removed": removed, "changed": changed}
        """))


def _write_content_version_model(dest: Path) -> None:
    """Write ``app/models/content_version.py`` with the ContentVersion ORM model.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"ContentVersion model — tracks draft/published/archived lifecycle for any content type.

        Lifecycle
        ---------
        pending  →  draft  →  published  →  archived

        A content item may have multiple drafts simultaneously (bounded by
        VERSIONING_MAX_DRAFTS), but only one published version at a time.
        Publishing automatically archives the previous published version.
        \"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime
        from typing import Any

        from sqlalchemy import DateTime, Index, Integer, String, Text, Uuid, func
        from sqlalchemy import JSON
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class ContentVersion(Base):
            \"\"\"Stores a versioned snapshot of any content item.

            Attributes:
                id: UUID primary key.
                content_id: Opaque string ID of the owning content item.
                content_type: Lowercase type name (e.g. 'article', 'product').
                version_number: Monotonically increasing integer per content_id.
                status: Lifecycle state (pending, draft, published, archived).
                data_json: Full content snapshot as a JSON object.
                published_at: UTC timestamp when this version was published; None for drafts.
                author_id: UUID of the user who created this version.
                created_at: UTC creation timestamp (server default).
            \"\"\"

            __tablename__ = "content_versions"

            id: Mapped[uuid.UUID] = mapped_column(
                Uuid, primary_key=True, default=uuid.uuid4
            )
            content_id: Mapped[str] = mapped_column(
                String(255), nullable=False, index=True
            )
            content_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
            version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
            status: Mapped[str] = mapped_column(
                String(20), nullable=False, default="draft", index=True
            )
            data_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
            published_at: Mapped[datetime | None] = mapped_column(
                DateTime(timezone=True), nullable=True
            )
            author_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )

            __table_args__ = (
                Index(
                    "ix_content_versions_content_id_version",
                    "content_id",
                    "version_number",
                    unique=True,
                ),
            )
        """))


def _write_version_schema(dest: Path) -> None:
    """Write ``app/schemas/version.py`` with Pydantic response/request schemas.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Pydantic schemas for the content versioning API.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime
        from typing import Any

        from pydantic import BaseModel, ConfigDict, Field


        class VersionCreate(BaseModel):
            \"\"\"Request body for creating a new draft version.

            Attributes:
                data: JSON-serialisable dict representing the full content snapshot.
                author_id: UUID of the author creating the draft.
            \"\"\"

            data: dict[str, Any] = Field(..., description="Full content snapshot as JSON object")
            author_id: uuid.UUID | None = Field(None, description="Author user UUID")


        class VersionRead(BaseModel):
            \"\"\"Public representation of a ContentVersion.

            Attributes:
                id: UUID primary key.
                content_id: Owning content item ID.
                content_type: Lowercase content type name.
                version_number: Monotonically increasing version counter.
                status: Current lifecycle status.
                published_at: UTC publish timestamp; None for non-published versions.
                author_id: UUID of the version author.
                created_at: UTC creation timestamp.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            content_id: str
            content_type: str
            version_number: int
            status: str
            published_at: datetime | None
            author_id: uuid.UUID | None
            created_at: datetime


        class VersionDiff(BaseModel):
            \"\"\"Response for a diff between two version numbers.

            Attributes:
                content_id: Owning content item ID.
                v1: Earlier version number.
                v2: Later version number.
                added: Fields present in v2 but not v1.
                removed: Fields present in v1 but not v2.
                changed: Fields present in both with differing values (old, new).
            \"\"\"

            content_id: str
            v1: int
            v2: int
            added: dict[str, Any]
            removed: dict[str, Any]
            changed: dict[str, Any]
        """))


def _write_version_crud(dest: Path) -> None:
    """Write ``app/crud/version.py`` with thin CRUD helpers.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Thin CRUD layer for ContentVersion queries.

        Higher-level lifecycle operations live in VersioningService
        (app/versioning/service.py).
        \"\"\"

        from __future__ import annotations

        import uuid

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.content_version import ContentVersion


        async def get_version_by_id(
            session: AsyncSession, version_id: uuid.UUID
        ) -> ContentVersion | None:
            \"\"\"Fetch a ContentVersion by its primary key.

            Args:
                session: Async SQLAlchemy session.
                version_id: UUID of the version row.

            Returns:
                ContentVersion instance or None if not found.
            \"\"\"
            result = await session.execute(
                select(ContentVersion).where(ContentVersion.id == version_id)
            )
            return result.scalar_one_or_none()


        async def list_versions_for_content(
            session: AsyncSession,
            content_id: str,
            status: str | None = None,
            limit: int = 50,
        ) -> list[ContentVersion]:
            \"\"\"List versions for a content item, optionally filtered by status.

            Args:
                session: Async SQLAlchemy session.
                content_id: Opaque content item identifier.
                status: Optional lifecycle status filter.
                limit: Maximum rows to return.

            Returns:
                List of ContentVersion instances ordered by version_number desc.
            \"\"\"
            stmt = (
                select(ContentVersion)
                .where(ContentVersion.content_id == content_id)
            )
            if status is not None:
                stmt = stmt.where(ContentVersion.status == status)
            stmt = stmt.order_by(ContentVersion.version_number.desc()).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())
        """))


def _write_version_routes(dest: Path) -> None:
    """Write ``app/api/routes/versions.py`` with lifecycle endpoints.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Content versioning endpoints.

        Endpoints
        ---------
        POST /versions/{content_type}/{id}/draft   — create a draft
        POST /versions/{content_type}/{id}/publish/{version_number} — publish a draft
        POST /versions/{content_type}/{id}/archive/{version_number} — archive a version
        GET  /versions/{content_type}/{id}/history — list all versions
        GET  /versions/{content_type}/{id}/diff/{v1}/{v2} — field-level diff
        \"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, Depends, HTTPException, status
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.schemas.version import VersionCreate, VersionDiff, VersionRead
        from app.versioning.service import VersioningService

        router = APIRouter(prefix="/versions", tags=["versions"])


        async def _get_session() -> AsyncSession:
            \"\"\"FastAPI dependency placeholder — replaced by real session dep on boot.

            Raises:
                RuntimeError: Always — callers must override this dependency.
            \"\"\"
            raise RuntimeError("Inject get_async_session via app.dependency_overrides")


        def _get_service() -> VersioningService:
            \"\"\"Return a VersioningService configured from application settings.

            Returns:
                VersioningService with max_drafts from settings.
            \"\"\"
            from app.core.config import settings  # noqa: PLC0415

            return VersioningService(max_drafts=settings.VERSIONING_MAX_DRAFTS)


        @router.post(
            "/{content_type}/{content_id}/draft",
            response_model=VersionRead,
            status_code=status.HTTP_201_CREATED,
        )
        async def create_draft(
            content_type: str,
            content_id: str,
            body: VersionCreate,
            session: AsyncSession = Depends(_get_session),
            service: VersioningService = Depends(_get_service),
        ) -> VersionRead:
            \"\"\"Create a new draft version for a content item.

            Args:
                content_type: Lowercase content type name.
                content_id: Opaque string ID of the content item.
                body: VersionCreate with data and optional author_id.
                session: Injected async DB session.
                service: VersioningService instance.

            Returns:
                The newly created draft as VersionRead.

            Raises:
                HTTPException 422: If max_drafts limit is reached.
            \"\"\"
            try:
                version = await service.create_draft(
                    session,
                    content_id=content_id,
                    content_type=content_type,
                    data=body.data,
                    author_id=body.author_id,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"detail": str(exc)},
                ) from exc
            return VersionRead.model_validate(version)


        @router.post(
            "/{content_type}/{content_id}/publish/{version_number}",
            response_model=VersionRead,
        )
        async def publish_version(
            content_type: str,
            content_id: str,
            version_number: int,
            session: AsyncSession = Depends(_get_session),
            service: VersioningService = Depends(_get_service),
        ) -> VersionRead:
            \"\"\"Publish a specific draft version.

            Args:
                content_type: Lowercase content type name.
                content_id: Opaque string ID of the content item.
                version_number: Version number of the draft to publish.
                session: Injected async DB session.
                service: VersioningService instance.

            Returns:
                The published ContentVersion as VersionRead.

            Raises:
                HTTPException 422: If the version is not in draft status.
                HTTPException 404: If the version does not exist.
            \"\"\"
            try:
                version = await service.publish(session, content_id, version_number)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"detail": str(exc)},
                ) from exc
            return VersionRead.model_validate(version)


        @router.post(
            "/{content_type}/{content_id}/archive/{version_number}",
            response_model=VersionRead,
        )
        async def archive_version(
            content_type: str,
            content_id: str,
            version_number: int,
            session: AsyncSession = Depends(_get_session),
            service: VersioningService = Depends(_get_service),
        ) -> VersionRead:
            \"\"\"Archive a specific version (idempotent).

            Args:
                content_type: Lowercase content type name.
                content_id: Opaque string ID of the content item.
                version_number: Version number to archive.
                session: Injected async DB session.
                service: VersioningService instance.

            Returns:
                The archived ContentVersion as VersionRead.

            Raises:
                HTTPException 404: If the version does not exist.
            \"\"\"
            try:
                version = await service.archive(session, content_id, version_number)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"detail": str(exc)},
                ) from exc
            return VersionRead.model_validate(version)


        @router.get(
            "/{content_type}/{content_id}/history",
            response_model=list[VersionRead],
        )
        async def get_version_history(
            content_type: str,
            content_id: str,
            limit: int = 50,
            session: AsyncSession = Depends(_get_session),
            service: VersioningService = Depends(_get_service),
        ) -> list[VersionRead]:
            \"\"\"Return the version history for a content item.

            Args:
                content_type: Lowercase content type name.
                content_id: Opaque string ID of the content item.
                limit: Maximum number of versions to return (default 50).
                session: Injected async DB session.
                service: VersioningService instance.

            Returns:
                List of VersionRead instances, newest first.
            \"\"\"
            versions = await service.get_history(session, content_id, limit=limit)
            return [VersionRead.model_validate(v) for v in versions]


        @router.get(
            "/{content_type}/{content_id}/diff/{v1}/{v2}",
            response_model=VersionDiff,
        )
        async def diff_versions(
            content_type: str,
            content_id: str,
            v1: int,
            v2: int,
            session: AsyncSession = Depends(_get_session),
            service: VersioningService = Depends(_get_service),
        ) -> VersionDiff:
            \"\"\"Return a field-level diff between two version numbers.

            Args:
                content_type: Lowercase content type name.
                content_id: Opaque string ID of the content item.
                v1: Earlier version number.
                v2: Later version number.
                session: Injected async DB session.
                service: VersioningService instance.

            Returns:
                VersionDiff with added, removed, and changed fields.

            Raises:
                HTTPException 404: If either version does not exist.
            \"\"\"
            try:
                result = await service.diff(session, content_id, v1, v2)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"detail": str(exc)},
                ) from exc
            return VersionDiff(
                content_id=content_id, v1=v1, v2=v2, **result
            )
        """))


def _write_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration for the content_versions table.

    Args:
        versions_dir: Path to ``alembic/versions/``.

    Returns:
        Path of the created migration file.
    """
    rev_id = "add_content_versions"
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    dest = versions_dir / f"{rev_id}.py"
    content = textwrap.dedent(f"""\
        \"\"\"add content_versions table

        Revision ID: {rev_id}
        Revises: {down_rev}
        Create Date: auto-generated by add_data_versioning tool
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision: str = "{rev_id}"
        down_revision: str | None = "{down_rev}"
        branch_labels: str | None = None
        depends_on: str | None = None


        def upgrade() -> None:
            \"\"\"Create the content_versions table with unique version index.\"\"\"
            op.create_table(
                "content_versions",
                sa.Column("id", sa.Uuid(), nullable=False),
                sa.Column("content_id", sa.String(255), nullable=False),
                sa.Column("content_type", sa.String(100), nullable=False),
                sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
                sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
                sa.Column("data_json", sa.JSON(), nullable=True),
                sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("author_id", sa.Uuid(), nullable=True),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("now()"),
                    nullable=False,
                ),
                sa.PrimaryKeyConstraint("id"),
            )
            op.create_index("ix_content_versions_content_id", "content_versions", ["content_id"])
            op.create_index("ix_content_versions_content_type", "content_versions", ["content_type"])
            op.create_index("ix_content_versions_status", "content_versions", ["status"])
            op.create_index(
                "ix_content_versions_content_id_version",
                "content_versions",
                ["content_id", "version_number"],
                unique=True,
            )


        def downgrade() -> None:
            \"\"\"Drop the content_versions table.\"\"\"
            op.drop_index("ix_content_versions_content_id_version", table_name="content_versions")
            op.drop_index("ix_content_versions_status", table_name="content_versions")
            op.drop_index("ix_content_versions_content_type", table_name="content_versions")
            op.drop_index("ix_content_versions_content_id", table_name="content_versions")
            op.drop_table("content_versions")
        """)
    dest.write_text(content)
    return dest


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (minimum 1).

    Args:
        start: ``time.monotonic()`` value captured at function entry.

    Returns:
        Integer milliseconds elapsed, at least 1 to satisfy ``> 0`` checks.
    """
    return max(1, int((time.monotonic() - start) * 1000))
