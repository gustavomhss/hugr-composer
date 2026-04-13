"""
SKILL-001 Database Tool: Generate a production-ready database module for FastAPI.

Creates a complete async SQLAlchemy database layer with:
- Async engine + session factory with correct pool configuration
- Declarative Base with timestamps (created_at, updated_at) and soft delete mixin
- Alembic async migration environment (optional)
- Multi-tenancy foundation with RLS support (optional)
- FastAPI dependency with auto commit/rollback

Generated structure:
    database/
        __init__.py          -- Public exports
        engine.py            -- Engine, session factory, get_session dependency
        models/
            __init__.py      -- Re-export Base + mixins
            base.py          -- DeclarativeBase with TimestampMixin, SoftDeleteMixin
        alembic/             -- (if with_alembic=True)
            alembic.ini
            env.py           -- Async env.py with run_async_migrations
            versions/        -- Empty migration directory
        tenancy.py           -- (if with_multi_tenancy=True) RLS middleware + tenant dep
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity


# ---------------------------------------------------------------------------
# File templates
# ---------------------------------------------------------------------------


def _engine_py(db_url: str, with_multi_tenancy: bool) -> str:
    """Template for database/engine.py -- engine, session factory, dependency."""
    tenant_import = ""
    if with_multi_tenancy:
        tenant_import = "from sqlalchemy import text\n"

    tenant_set = ""
    if with_multi_tenancy:
        tenant_set = '''

# --- Tenant-scoped session (multi-tenancy) ---

async def get_tenant_session(
    tenant_id: str,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session with RLS tenant context.

    Sets ``app.current_tenant`` for Row-Level Security policies.
    Uses ``SET LOCAL`` so the setting is scoped to the transaction
    and does not leak across pooled connections.
    """
    async with async_session_factory() as session:
        try:
            await session.execute(
                text("SET LOCAL app.current_tenant = :tid"),
                {"tid": tenant_id},
            )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
'''

    return f'''"""Database engine, async session factory, and FastAPI dependency.

Architecture:
- One engine per process (created at import time from settings).
- Sessions are short-lived: one per request, auto commit/rollback.
- expire_on_commit=False is MANDATORY for async (prevents MissingGreenlet).

Pool sizing formula:
    total_connections = workers * pods * (pool_size + max_overflow)
    target: total_connections <= pg max_connections - reserved (20)
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
{tenant_import}
# ---------------------------------------------------------------------------
# Engine -- one per process, configured via settings
# ---------------------------------------------------------------------------

# Pool sizing rationale (4 workers, 3 pods, PG max_connections=200):
#   budget = (200 - 20 reserved) / (4 * 3) = 15 per process
#   pool_size=5 (idle) + max_overflow=10 (burst) = 15 total

engine = create_async_engine(
    "{db_url}",
    pool_size=5,
    max_overflow=10,
    pool_recycle=1800,       # Recycle every 30min (LB idle timeout safety)
    pool_pre_ping=True,      # Detect dead connections before checkout
    pool_timeout=30,         # Max wait for connection from pool
    echo=False,              # Set True for SQL logging in development
)


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # CRITICAL: prevents MissingGreenlet in async
)


# ---------------------------------------------------------------------------
# FastAPI dependency -- auto commit/rollback
# ---------------------------------------------------------------------------

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session with auto commit on success, rollback on error.

    Usage in routes::

        from typing import Annotated
        from fastapi import Depends

        SessionDep = Annotated[AsyncSession, Depends(get_session)]

        @app.get("/items")
        async def list_items(session: SessionDep):
            result = await session.execute(select(Item))
            return result.scalars().all()
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------

async def dispose_engine() -> None:
    """Dispose the engine and close all pooled connections.

    Call this in the FastAPI lifespan shutdown phase.
    """
    await engine.dispose()
{tenant_set}'''


def _base_py(with_multi_tenancy: bool) -> str:
    """Template for database/models/base.py -- Base + mixins."""
    tenant_mixin = ""
    if with_multi_tenancy:
        tenant_mixin = '''

class TenantMixin:
    """Mixin that adds tenant_id to models for multi-tenancy.

    Combine with PostgreSQL Row-Level Security for database-enforced
    isolation. The application filters by tenant_id AND the DB
    enforces it via RLS policy (defense in depth).

    SQL for RLS::

        ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
        ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON <table>
            USING (tenant_id = current_setting('app.current_tenant')::text);
    """

    tenant_id: Mapped[str] = mapped_column(
        String(50),
        index=True,
        nullable=False,
    )
'''

    return f'''"""SQLAlchemy declarative base with production mixins.

Provides:
- TimestampMixin: created_at + updated_at (auto-managed)
- SoftDeleteMixin: deleted_at + is_deleted + soft_delete()/restore()
- Base: DeclarativeBase with TimestampMixin baked in
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------

class TimestampMixin:
    """Adds created_at and updated_at to every model.

    - created_at: set once on INSERT (server-side or Python default).
    - updated_at: set on every UPDATE via onupdate.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class SoftDeleteMixin:
    """Adds soft delete capability to a model.

    Usage::

        class User(Base, SoftDeleteMixin):
            __tablename__ = "users"
            ...

        # Soft delete
        user.soft_delete()
        await session.commit()

        # Query active records
        stmt = select(User).where(User.deleted_at.is_(None))

        # Restore
        user.restore()
        await session.commit()

    IMPORTANT: Create a partial index for performance::

        CREATE INDEX idx_<table>_active ON <table> (...) WHERE deleted_at IS NULL;
        CREATE UNIQUE INDEX idx_<table>_email_unique_active ON <table> (email)
            WHERE deleted_at IS NULL;
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        index=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Mark this record as deleted (sets deleted_at to now)."""
        self.deleted_at = datetime.now(timezone.utc)

    def restore(self) -> None:
        """Undelete this record (clears deleted_at)."""
        self.deleted_at = None


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase, TimestampMixin):
    """Declarative base with timestamps baked in.

    All models inheriting from Base automatically get:
    - created_at: UTC timestamp set on INSERT
    - updated_at: UTC timestamp set on every UPDATE

    For soft delete, add SoftDeleteMixin explicitly::

        class User(Base, SoftDeleteMixin):
            __tablename__ = "users"
            ...
    """

    __abstract__ = True
{tenant_mixin}'''


def _models_init_py(with_multi_tenancy: bool) -> str:
    """Template for database/models/__init__.py."""
    exports = ["Base", "TimestampMixin", "SoftDeleteMixin"]
    imports = "Base, TimestampMixin, SoftDeleteMixin"
    if with_multi_tenancy:
        exports.append("TenantMixin")
        imports += ", TenantMixin"

    return f'''"""Database models -- re-export base and mixins."""

from .base import {imports}

__all__ = {exports!r}
'''


def _db_init_py() -> str:
    """Template for database/__init__.py."""
    return '''"""Database module -- async SQLAlchemy for FastAPI."""

from .engine import async_session_factory, dispose_engine, engine, get_session
from .models.base import Base, SoftDeleteMixin, TimestampMixin

__all__ = [
    "Base",
    "SoftDeleteMixin",
    "TimestampMixin",
    "async_session_factory",
    "dispose_engine",
    "engine",
    "get_session",
]
'''


def _alembic_ini(db_url: str) -> str:
    """Template for alembic.ini."""
    return f'''[alembic]
script_location = %(here)s
prepend_sys_path = .

# Connection string -- overridden in env.py from app settings.
# This is a fallback only. NEVER hardcode production credentials here.
sqlalchemy.url = {db_url}

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %%(levelname)-5.5s [%%(name)s] %%(message)s
datefmt = %%H:%%M:%%S
'''


def _alembic_env_py() -> str:
    """Template for alembic/env.py -- async migrations."""
    return '''"""Alembic async migration environment.

Runs migrations using the async engine (asyncpg).
Database URL is loaded from app settings -- never hardcoded in alembic.ini.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# --- IMPORTANT: Import your Base.metadata here ---
# Update this import to match your project structure:
# from app.database.models.base import Base
# target_metadata = Base.metadata
target_metadata = None  # Replace with Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- Override DB URL from app settings (recommended) ---
# Uncomment and adapt:
# from app.config import settings
# config.set_main_option("sqlalchemy.url", settings.database_url)


def do_run_migrations(connection) -> None:
    """Run migrations synchronously within an async connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # No pool for migrations
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for \'alembic upgrade head\'."""
    asyncio.run(run_async_migrations())


run_migrations_online()
'''


def _alembic_script_mako() -> str:
    """Template for alembic/script.py.mako -- migration template."""
    return '''"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''


def _tenancy_py() -> str:
    """Template for database/tenancy.py -- multi-tenancy middleware + deps."""
    return '''"""Multi-tenancy support via PostgreSQL Row-Level Security.

Architecture:
- Each request sets ``app.current_tenant`` via ``SET LOCAL`` (transaction-scoped).
- RLS policies on tenant tables enforce isolation at the database level.
- The application also filters by tenant_id (defense in depth).

Setup SQL (run once per tenant table)::

    ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
    ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON <table>
        USING (tenant_id = current_setting('app.current_tenant')::text);
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .engine import get_tenant_session


def get_tenant_id_from_request(request: Request) -> str:
    """Extract tenant ID from the request.

    Override this function to match your auth strategy:
    - JWT claim: request.state.user["tenant_id"]
    - Header: request.headers["X-Tenant-ID"]
    - Subdomain: request.url.hostname.split(".")[0]
    """
    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tenant_id


async def get_session_with_tenant(
    request: Request,
) -> AsyncSession:
    """Dependency that provides a tenant-scoped database session.

    Usage::

        TenantSession = Annotated[AsyncSession, Depends(get_session_with_tenant)]

        @app.get("/documents")
        async def list_docs(session: TenantSession):
            # RLS automatically filters by tenant
            result = await session.execute(select(Document))
            return result.scalars().all()
    """
    tenant_id = get_tenant_id_from_request(request)
    async for session in get_tenant_session(tenant_id):
        yield session


# Type alias for tenant-scoped session dependency
TenantSession = Annotated[AsyncSession, Depends(get_session_with_tenant)]
'''


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_db_module(
    output_dir: str,
    db_url: str = "postgresql+asyncpg://user:pass@localhost:5432/db",
    with_alembic: bool = True,
    with_multi_tenancy: bool = False,
) -> dict:
    """
    Generate a production-ready database module for a FastAPI project.

    Creates an async SQLAlchemy database layer inside a ``database/``
    subdirectory of *output_dir*. Includes engine configuration with
    proper pool sizing, a declarative Base with timestamp and soft-delete
    mixins, and a FastAPI dependency for auto commit/rollback sessions.

    Optionally generates:
    - Alembic async migration environment (``--with-alembic``)
    - Multi-tenancy foundation with RLS middleware (``--with-multi-tenancy``)

    Args:
        output_dir: Parent directory where the ``database/`` package will
            be created.
        db_url: PostgreSQL async connection string. Must use the
            ``postgresql+asyncpg://`` scheme.
        with_alembic: Generate Alembic async migration directory.
        with_multi_tenancy: Generate multi-tenancy middleware and
            TenantMixin model.

    Returns:
        Dict with ``created_files`` (list of relative paths), ``db_path``
        (absolute path to the created package), and feature flags.

    Raises:
        ValueError: If *db_url* does not use the asyncpg scheme.

    Example::

        result = generate_db_module(
            "/tmp/myproject",
            db_url="postgresql+asyncpg://app:secret@db:5432/myapp",
            with_alembic=True,
            with_multi_tenancy=False,
        )
        print(result["created_files"])
        # ['database/__init__.py', 'database/engine.py',
        #  'database/models/__init__.py', 'database/models/base.py',
        #  'database/alembic/alembic.ini', 'database/alembic/env.py',
        #  'database/alembic/script.py.mako', 'database/alembic/versions/']
    """
    if "asyncpg" not in db_url and "postgresql" in db_url:
        raise ValueError(
            f"Database URL must use asyncpg driver: "
            f"'postgresql+asyncpg://...' (got: {db_url!r}). "
            f"Sync drivers block the event loop in FastAPI."
        )

    db_dir = Path(output_dir) / "database"
    models_dir = db_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    created: list[str] = []

    # --- Core files ---
    files: dict[str, str] = {
        "database/__init__.py": _db_init_py(),
        "database/engine.py": _engine_py(db_url, with_multi_tenancy),
        "database/models/__init__.py": _models_init_py(with_multi_tenancy),
        "database/models/base.py": _base_py(with_multi_tenancy),
    }

    # --- Multi-tenancy ---
    if with_multi_tenancy:
        files["database/tenancy.py"] = _tenancy_py()

    # --- Alembic ---
    if with_alembic:
        alembic_dir = db_dir / "alembic"
        versions_dir = alembic_dir / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        created.append("database/alembic/versions/")

        files["database/alembic/alembic.ini"] = _alembic_ini(db_url)
        files["database/alembic/env.py"] = _alembic_env_py()
        files["database/alembic/script.py.mako"] = _alembic_script_mako()

    # --- Write files ---
    for rel_path, content in files.items():
        filepath = Path(output_dir) / rel_path
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        created.append(rel_path)

    return {
        "created_files": sorted(created),
        "db_path": str(db_dir),
        "with_alembic": with_alembic,
        "with_multi_tenancy": with_multi_tenancy,
    }
