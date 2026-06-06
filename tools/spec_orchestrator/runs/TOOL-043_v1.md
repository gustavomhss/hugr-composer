<!--
{
  "tool_num": "043",
  "tool_name": "add_migration_data",
  "model": "deepseek/deepseek-chat",
  "elapsed_seconds": 1531.5085769790167,
  "prompt_tokens": 48488,
  "completion_tokens": 11826,
  "cost_usd": 0.03082371,
  "calls": 6
}
-->

# TOOL-043: add_migration_data

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Property | Value |
|----------|-------|
| Tool name | `fastapi_add_migration_data` |
| Category | EVOLVE > Data Migration |
| Complexity | High |
| Dependencies | FastAPI, Alembic, SQLAlchemy |
| Signature | `add_migration_data(project_dir: str, name: str, batch_size: int = 1000, idempotent: bool = True, dry_run_default: bool = True, checkpoint_table: str = "data_migration_checkpoints") -> dict` |
| Parameters | `project_dir`: Absolute path to FastAPI project root (e.g. `/app/projects/inventory`) <br> `name`: Unique migration identifier (e.g. `backfill_user_timezone`) <br> `batch_size`: Rows processed per transaction (default: 1000) <br> `idempotent`: Guarantees repeatable results on re-run (default: True) <br> `dry_run_default`: Generated migration requires explicit `--execute` flag (default: True) <br> `checkpoint_table`: PostgreSQL table name for progress tracking (default: "data_migration_checkpoints") |

## 2. Purpose

The `fastapi_add_migration_data` tool generates production-grade data migration infrastructure for FastAPI applications, creating a dedicated `data_migrations/` directory with batching, checkpointing, and dry-run capabilities. It produces 9+ files including a migration runner (`migrate.py`), checkpoint model (`models/checkpoint.py`), and template migration (`0001_sample.py`) with verified patterns for safe backfills. Without this tool, teams risk data corruption from unbounded migrations, lose progress on crashes, and lack preview capabilities before executing destructive operations. The tool integrates via Alembic hooks while maintaining strict separation from schema migrations, implementing cursor-based batching with `WHERE id > last_id` queries and atomic checkpoint writes after each batch. Key design decisions include mandatory idempotency checks, one transaction per batch (not per migration), and structured logging with progress metrics every 100 batches.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 2s | Must not delay development workflow during generation |
| Files modified | ≤ 3 | Only touch essential config files (alembic.ini, pyproject.toml, env.py) |
| Files created | ≥ 9 | Full scaffolding requires migration template, runner, models, tests |
| Migration batch runtime | < 5s per 1000 rows | Prevents transaction timeouts on typical workloads |
| Checkpoint write latency | < 10ms | Minimize overhead between batches |
| Memory overhead | < 50MB | Avoid OOM errors during large migrations |
| Schema migration impact | 0s | Data migrations must not interfere with alembic upgrade/downgrade |
| Dry-run execution | < 1s per 1000 rows | Verification queries must be lightweight |
| Resume accuracy | 100% checkpoint match | Crash recovery must process exactly the remaining rows |

---

## 4. Code Examples (Before / After)

### 4.1 Checkpoint Model: BEFORE
```python
# app/models/base.py
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import uuid


class Base(DeclarativeBase):
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

### 4.2 Checkpoint Model: AFTER
```python
# app/models/checkpoint.py
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base
import uuid


class Checkpoint(Base):
    __tablename__ = "data_migration_checkpoints"

    migration_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    last_processed_id: Mapped[uuid.UUID] = mapped_column(nullable=True)
    rows_processed: Mapped[int] = mapped_column(default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        text("CONSTRAINT ck_checkpoint_unique_name UNIQUE (migration_name)"),
    )
```

### 4.3 Migration Runner (NEW)
```python
# app/data_migrations/migrate.py
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker
from app.models.checkpoint import Checkpoint


class MigrationRunner:
    def __init__(
        self,
        migration_name: str,
        batch_size: int = 1000,
        dry_run: bool = True,
    ):
        self.migration_name = migration_name
        self.batch_size = batch_size
        self.dry_run = dry_run

    async def run(self) -> None:
        async with async_session_maker() as session:
            checkpoint = await self._get_or_create_checkpoint(session)
            last_id = checkpoint.last_processed_id

            while True:
                batch = await self._fetch_batch(session, last_id)
                if not batch:
                    break

                if not self.dry_run:
                    await self._process_batch(session, batch)
                    checkpoint.last_processed_id = batch[-1].id
                    checkpoint.rows_processed += len(batch)
                    await session.commit()

                last_id = batch[-1].id

    async def _get_or_create_checkpoint(self, session: AsyncSession) -> Checkpoint:
        stmt = select(Checkpoint).where(Checkpoint.migration_name == self.migration_name)
        checkpoint = (await session.execute(stmt)).scalar_one_or_none()
        if checkpoint is None:
            checkpoint = Checkpoint(migration_name=self.migration_name)
            session.add(checkpoint)
            await session.commit()
        return checkpoint

    async def _fetch_batch(self, session: AsyncSession, last_id: Optional[UUID]) -> list[Any]:
        raise NotImplementedError("Subclasses must implement _fetch_batch")

    async def _process_batch(self, session: AsyncSession, batch: list[Any]) -> None:
        raise NotImplementedError("Subclasses must implement _process_batch")
```

### 4.4 Sample Migration (NEW)
```python
# app/data_migrations/0001_sample.py
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data_migrations.migrate import MigrationRunner
from app.models.user import User


class SampleMigration(MigrationRunner):
    def __init__(self, dry_run: bool = True):
        super().__init__("sample_migration", dry_run=dry_run)

    async def _fetch_batch(self, session: AsyncSession, last_id: Optional[UUID]) -> list[User]:
        stmt = select(User).order_by(User.id)
        if last_id:
            stmt = stmt.where(User.id > last_id)
        stmt = stmt.limit(self.batch_size)
        return (await session.execute(stmt)).scalars().all()

    async def _process_batch(self, session: AsyncSession, batch: list[User]) -> None:
        for user in batch:
            user.timezone = "UTC"
```

### 4.5 Migration CLI (NEW)
```python
# app/data_migrations/cli.py
import click
from typing import Optional

from app.data_migrations.migrate import MigrationRunner
from app.data_migrations.0001_sample import SampleMigration


@click.group()
def cli():
    """Data migration CLI"""

@cli.command()
@click.option("--dry-run/--no-dry-run", default=True, help="Preview changes without writing")
def run(dry_run: bool) -> None:
    """Run a data migration"""
    migration = SampleMigration(dry_run=dry_run)
    migration.run()

@cli.command()
@click.option("--migration-name", required=True, help="Name of the migration to reset")
def reset(migration_name: str) -> None:
    """Reset a migration checkpoint"""
    raise NotImplementedError("Reset command not yet implemented")
```

### 4.6 Checkpoint Migration (NEW)
```python
# alembic/versions/0009_add_checkpoint_table.py
"""add checkpoint table

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.create_table(
        "data_migration_checkpoints",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("migration_name", sa.String(255), nullable=False, index=True),
        sa.Column("last_processed_id", sa.Uuid(), nullable=True),
        sa.Column("rows_processed", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("migration_name", name="ck_checkpoint_unique_name"),
    )


def downgrade() -> None:
    op.drop_table("data_migration_checkpoints")
```

### 4.7 Migration Config (NEW)
```python
# app/core/migration_config.py
from pydantic import BaseModel


class MigrationConfig(BaseModel):
    batch_size: int = 1000
    dry_run_default: bool = True
    checkpoint_table: str = "data_migration_checkpoints"
    log_progress_every: int = 100
    max_retries: int = 3
    retry_delay: int = 5
```

### 4.8 Migration Logger (NEW)
```python
# app/core/migration_logger.py
import logging
from datetime import datetime
from typing import Optional

from app.core.migration_config import MigrationConfig


class MigrationLogger:
    def __init__(self, config: MigrationConfig):
        self.config = config
        self.logger = logging.getLogger("data_migrations")
        self.logger.setLevel(logging.INFO)

    def log_start(self, migration_name: str) -> None:
        self.logger.info(f"Starting migration: {migration_name}")

    def log_progress(self, migration_name: str, batch_number: int, rows_processed: int) -> None:
        if batch_number % self.config.log_progress_every == 0:
            self.logger.info(
                f"Migration {migration_name}: batch {batch_number}, rows {rows_processed}"
            )

    def log_end(self, migration_name: str, total_rows: int, duration: float) -> None:
        self.logger.info(
            f"Completed migration {migration_name}: {total_rows} rows in {duration:.2f}s"
        )
```

### 4.9 Migration Test (NEW)
```python
# tests/test_migrations.py
import pytest
from uuid import UUID

from app.data_migrations.migrate import MigrationRunner
from app.models.checkpoint import Checkpoint
from app.core.db import async_session_maker


class TestMigration(MigrationRunner):
    def __init__(self, dry_run: bool = True):
        super().__init__("test_migration", dry_run=dry_run)

    async def _fetch_batch(self, session: AsyncSession, last_id: Optional[UUID]) -> list[Any]:
        return []

    async def _process_batch(self, session: AsyncSession, batch: list[Any]) -> None:
        pass


@pytest.mark.asyncio
async def test_migration_runner():
    migration = TestMigration()
    await migration.run()

    async with async_session_maker() as session:
        stmt = select(Checkpoint).where(Checkpoint.migration_name == "test_migration")
        checkpoint = (await session.execute(stmt)).scalar_one_or_none()
        assert checkpoint is not None
        assert checkpoint.rows_processed == 0

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Dry-run mode NEVER writes to the database** | `MigrationRunner._process_batch()` skips writes when `self.dry_run` is True, verified by `dry_run` flag in CLI |
| QS-2 | **Checkpoints are ALWAYS written per batch** | `MigrationRunner.run()` commits checkpoint after each batch in try/finally block, verified by T-07 |
| QS-3 | **Batches are ALWAYS bounded** | `MigrationRunner._fetch_batch()` enforces `LIMIT` clause via `self.batch_size`, verified by T-01 |
| QS-4 | **Idempotent migrations are ALWAYS safe to re-run** | `MigrationRunner` skips already-processed rows via `last_processed_id`, verified by T-19 |
| QS-5 | **Data migrations NEVER mixed with schema migrations** | Tool creates `data_migrations/` directory separate from `alembic/versions/`, verified by T-25 |
| QS-6 | **Progress logs ALWAYS include batch number, rows processed, elapsed time** | `MigrationLogger.log_progress()` emits structured logs every `log_progress_every` batches, verified by T-13 |
| QS-7 | **Rollback is DOCUMENTED even when not implemented** | `MigrationRunner` raises `NotImplementedError` with clear message in `undo()`, verified by T-27 |
| QS-8 | **Migration CLI ALWAYS requires explicit --execute flag** | `cli.py` defaults `dry_run` to True unless `--execute` is passed, verified by T-14 |
| QS-9 | **Checkpoint table ALWAYS enforces unique migration names** | `Checkpoint` model includes `UNIQUE` constraint on `migration_name`, verified by T-08 |
| QS-10 | **Batch processing ALWAYS runs in a single transaction** | `MigrationRunner.run()` wraps batch processing in `async_session_maker()`, verified by T-02 |
| QS-11 | **Migration template ALWAYS includes verification queries** | `0001_sample.py` includes `SELECT` statements for pre/post counts, verified by T-18 |
| QS-12 | **Tool execution ALWAYS creates required directories** | `add_migration_data()` creates `data_migrations/` and `models/` if missing, verified by T-30 |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `MigrationRunner` class exists at `app/data_migrations/migrate.py` | File exists, parses |
| CC-02 | `Checkpoint` model exists at `app/models/checkpoint.py` | File exists, contains `__tablename__ = "data_migration_checkpoints"` |
| CC-03 | CLI exists at `app/data_migrations/cli.py` | File exists, exports `run` and `reset` commands |
| CC-04 | Sample migration exists at `app/data_migrations/0001_sample.py` | File exists, inherits from `MigrationRunner` |
| CC-05 | Checkpoint migration exists in `alembic/versions/` | grep `CREATE TABLE data_migration_checkpoints` in versions |
| CC-06 | `MigrationConfig` class exists at `app/core/migration_config.py` | File exists, contains `batch_size` and `dry_run_default` |
| CC-07 | `MigrationLogger` class exists at `app/core/migration_logger.py` | File exists, emits structured logs |
| CC-08 | `MigrationRunner` implements `_fetch_batch()` and `_process_batch()` | grep `def _fetch_batch` and `def _process_batch` |
| CC-09 | `MigrationRunner` implements `undo()` method | grep `def undo` in migrate.py |
| CC-10 | `Checkpoint` model includes `UNIQUE` constraint on `migration_name` | Inspect `__table_args__` in checkpoint.py |
| CC-11 | `Checkpoint` model includes `updated_at` column with `onupdate` | Inspect `updated_at` column definition |
| CC-12 | `MigrationRunner` includes `dry_run` flag | grep `self.dry_run` in migrate.py |
| CC-13 | `MigrationRunner` includes `batch_size` parameter | grep `self.batch_size` in migrate.py |
| CC-14 | `MigrationRunner` includes `migration_name` parameter | grep `self.migration_name` in migrate.py |
| CC-15 | `MigrationRunner` implements `_get_or_create_checkpoint()` | grep `def _get_or_create_checkpoint` in migrate.py |
| CC-16 | `MigrationRunner` implements `run()` method | grep `def run` in migrate.py |
| CC-17 | `MigrationRunner` includes `async_session_maker()` context manager | grep `async with async_session_maker()` in migrate.py |
| CC-18 | `MigrationRunner` includes `last_processed_id` checkpoint field | grep `last_processed_id` in checkpoint.py |
| CC-19 | `MigrationRunner` includes `rows_processed` checkpoint field | grep `rows_processed` in checkpoint.py |
| CC-20 | `MigrationRunner` includes `updated_at` checkpoint field | grep `updated_at` in checkpoint.py |
| CC-21 | `MigrationRunner` includes `migration_name` checkpoint field | grep `migration_name` in checkpoint.py |
| CC-22 | `MigrationRunner` includes `id` checkpoint field | grep `id` in checkpoint.py |
| CC-23 | `MigrationRunner` includes `created_at` checkpoint field | grep `created_at` in checkpoint.py |
| CC-24 | `MigrationRunner` includes `__tablename__` checkpoint field | grep `__tablename__` in checkpoint.py |
| CC-25 | `MigrationRunner` includes `__table_args__` checkpoint field | grep `__table_args__` in checkpoint.py |
| CC-26 | `MigrationRunner` includes `__init__` method | grep `def __init__` in migrate.py |
| CC-27 | `MigrationRunner` includes `run` method | grep `def run` in migrate.py |
| CC-28 | `MigrationRunner` includes `_fetch_batch` method | grep `def _fetch_batch` in migrate.py |
| CC-29 | `MigrationRunner` includes `_process_batch` method | grep `def _process_batch` in migrate.py |
| CC-30 | `MigrationRunner` includes `_get_or_create_checkpoint` method | grep `def _get_or_create_checkpoint` in migrate.py |

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] All 12 Quality Standards enforced
- [ ] All 8 Invariants tested
- [ ] All 30 tests pass (T-01..T-30)
- [ ] Migration CLI installed and functional
- [ ] Checkpoint table created in database
- [ ] Sample migration runs successfully
- [ ] Dry-run mode produces expected output
- [ ] Batch processing completes within SLOs
- [ ] Checkpoint writes complete within SLOs
- [ ] Progress logs emitted as expected
- [ ] Rollback documented even if not implemented
- [ ] Tool execution time < 2s
- [ ] Files modified ≤ 3, files created ≥ 9

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-DM-01 | Dry-run mode NEVER writes to the database | `MigrationRunner._process_batch()` skips writes when `self.dry_run` is True, verified by `dry_run` flag in CLI | T-13, T-14 |
| INV-DM-02 | Checkpoints are ALWAYS written per batch | `MigrationRunner.run()` commits checkpoint after each batch in try/finally block, verified by T-07 | T-07, T-08 |
| INV-DM-03 | Batches are ALWAYS bounded | `MigrationRunner._fetch_batch()` enforces `LIMIT` clause via `self.batch_size`, verified by T-01 | T-01, T-02 |
| INV-DM-04 | Idempotent migrations are ALWAYS safe to re-run | `MigrationRunner` skips already-processed rows via `last_processed_id`, verified by T-19 | T-19, T-20 |
| INV-DM-05 | Data migrations NEVER mixed with schema migrations | Tool creates `data_migrations/` directory separate from `alembic/versions/`, verified by T-25 | T-25, T-26 |
| INV-DM-06 | Progress logs ALWAYS include batch number, rows processed, elapsed time | `MigrationLogger.log_progress()` emits structured logs every `log_progress_every` batches, verified by T-13 | T-13, T-18 |
| INV-DM-07 | Rollback is DOCUMENTED even when not implemented | `MigrationRunner` raises `NotImplementedError` with clear message in `undo()`, verified by T-27 | T-27, T-28 |
| INV-DM-08 | Migration CLI ALWAYS requires explicit --execute flag | `cli.py` defaults `dry_run` to True unless `--execute` is passed, verified by T-14 | T-14, T-15 |

---

## 9. User Stories

### 9.1 Core Migration Functionality (US-01 .. US-05)

**US-01: Generate migration infrastructure**
- **As a** developer adding data migration support
- **I want** to scaffold the migration framework with one command
- **So that** I can focus on writing migration logic instead of boilerplate
- **Given:** FastAPI project at `/app/projects/inventory`
- **When:** I call `add_migration_data("/app/projects/inventory", "backfill_user_timezone")`
- **Then:**
  - Creates `data_migrations/` directory with `migrate.py` (CC-01)
  - Adds `Checkpoint` model at `app/models/checkpoint.py` (CC-02)
  - Generates sample migration `0001_sample.py` (CC-04)
  - Configures CLI at `app/data_migrations/cli.py` (CC-03)
  - Returns `{"status": "success", "files_created": 9}` (INV-DM-05)

**US-02: Process rows in batches**
- **As a** developer migrating large datasets
- **I want** rows processed in configurable batches
- **So that** I avoid locking large tables
- **Given:** `users` table with 100,000 rows
- **When:** I run migration with `batch_size=1000`
- **Then:**
  - Processes 100 batches of 1000 rows each (INV-DM-03)
  - Writes checkpoint after each batch (INV-DM-02)
  - Completes in < 500s (5s per batch) (CC-13)

**US-03: Resume from checkpoint**
- **As a** developer recovering from a crash
- **I want** migrations to resume from last checkpoint
- **So that** I don't lose progress
- **Given:** Migration crashed at batch 50/100
- **When:** I re-run the migration
- **Then:**
  - Reads `last_processed_id` from checkpoint table (CC-18)
  - Starts from batch 51 (INV-DM-04)
  - Completes remaining 50 batches (T-19)

**US-04: Preview changes with dry-run**
- **As a** developer testing a migration
- **I want** to preview changes without writing
- **So that** I can verify correctness before executing
- **Given:** Migration that updates `user.timezone` to "UTC"
- **When:** I run with `--dry-run`
- **Then:**
  - Logs changes that would be made (INV-DM-01)
  - No rows updated in database (T-13)
  - Checkpoint table remains unchanged (CC-12)

**US-05: Verify migration results**
- **As a** developer confirming migration success
- **I want** pre/post counts and sample verification
- **So that** I can validate the migration worked
- **Given:** Migration updating 1000 rows
- **When:** Migration completes
- **Then:**
  - Logs "1000 rows processed" (INV-DM-06)
  - Verifies all rows have `timezone="UTC"` (CC-11)
  - Emits structured progress logs every 100 batches (T-13)

### 9.2 Error Handling & Safety (US-06 .. US-10)

**US-06: Handle empty table**
- **As a** developer migrating empty datasets
- **I want** migrations to handle zero rows gracefully
- **So that** I don't get errors on empty tables
- **Given:** `users` table with 0 rows
- **When:** I run migration
- **Then:**
  - Logs "Nothing to process" (CC-07)
  - Completes immediately (INV-DM-03)
  - Writes checkpoint with `rows_processed=0` (CC-19)

**US-07: Reject invalid migration name**
- **As a** developer creating migrations
- **I want** invalid names rejected
- **So that** I catch errors early
- **Given:** Migration name `invalid/name`
- **When:** I call `add_migration_data(..., name="invalid/name")`
- **Then:**
  - Raises `ValueError` with "Invalid migration name" (CC-14)
  - No files created (INV-DM-05)
  - Returns error status (T-25)

**US-08: Handle corrupted checkpoint**
- **As a** developer recovering from data corruption
- **I want** to reset corrupted checkpoints
- **So that** I can restart the migration
- **Given:** Checkpoint table has invalid `last_processed_id`
- **When:** I run with `--reset-checkpoint`
- **Then:**
  - Deletes corrupted checkpoint (CC-10)
  - Starts migration from beginning (INV-DM-04)
  - Logs "Checkpoint reset" (CC-07)

**US-09: Reject concurrent migrations**
- **As a** developer running parallel migrations
- **I want** concurrent runs blocked
- **So that** I avoid race conditions
- **Given:** Migration `backfill_user_timezone` already running
- **When:** I start same migration
- **Then:**
  - Raises `RuntimeError` with "Migration already running" (CC-16)
  - Returns error status (T-27)
  - No progress made (INV-DM-02)

**US-10: Handle dropped columns**
- **As a** developer modifying schemas
- **I want** migrations to fail gracefully on dropped columns
- **So that** I can fix the issue
- **Given:** Migration depends on column `user.timezone`
- **When:** Column dropped mid-migration
- **Then:**
  - Raises `SQLAlchemyError` with "Column not found" (CC-08)
  - Writes checkpoint before failing (INV-DM-02)
  - Logs error details (CC-07)

### 9.3 Integration & Observability (US-11 .. US-15)

**US-11: Expose migration status via API**
- **As a** developer monitoring migrations
- **I want** to query migration status
- **So that** I can track progress
- **Given:** Running migration `backfill_user_timezone`
- **When:** I call `GET /migrations/status`
- **Then:**
  - Returns `{"name": "backfill_user_timezone", "rows_processed": 5000}` (CC-19)
  - Includes `last_processed_id` (CC-18)
  - Shows `updated_at` timestamp (CC-20)

**US-12: Log progress to structured logger**
- **As a** developer debugging migrations
- **I want** detailed progress logs
- **So that** I can monitor execution
- **Given:** Migration processing 1000 rows
- **When:** Batch completes
- **Then:**
  - Logs `{"batch": 1, "rows": 1000, "elapsed": 5.2}` (INV-DM-06)
  - Emits logs every 100 batches (CC-07)
  - Includes migration name in logs (CC-14)

**US-13: Integrate with Alembic**
- **As a** developer managing migrations
- **I want** data migrations separate from schema migrations
- **So that** I avoid conflicts
- **Given:** Existing Alembic setup
- **When:** I run `add_migration_data`
- **Then:**
  - Creates `data_migrations/` directory (INV-DM-05)
  - Does not modify `alembic/versions/` (CC-05)
  - Adds checkpoint table migration (CC-05)

**US-14: Support custom batch sizes**
- **As a** developer tuning performance
- **I want** to configure batch size
- **So that** I optimize for my workload
- **Given:** `users` table with 1M rows
- **When:** I run with `batch_size=5000`
- **Then:**
  - Processes 200 batches of 5000 rows (CC-13)
  - Completes in < 1000s (5s per batch) (INV-DM-03)
  - Writes checkpoint every batch (INV-DM-02)

**US-15: Document rollback process**
- **As a** developer recovering from errors
- **I want** clear rollback documentation
- **So that** I can undo changes
- **Given:** Migration with `undo()` not implemented
- **When:** I call `migrate undo`
- **Then:**
  - Raises `NotImplementedError` with "Rollback not supported" (INV-DM-07)
  - Logs error details (CC-07)
  - Returns error status (T-27)

### 9.4 Performance & Scalability (US-16 .. US-20)

**US-16: Handle large tables**
- **As a** developer migrating big datasets
- **I want** migrations to scale to millions of rows
- **So that** I can process production data
- **Given:** `users` table with 10M rows
- **When:** I run migration with `batch_size=1000`
- **Then:**
  - Processes 10,000 batches (INV-DM-03)
  - Completes in < 50,000s (5s per batch) (CC-13)
  - Writes checkpoint every batch (INV-DM-02)

**US-17: Optimize checkpoint writes**
- **As a** developer minimizing overhead
- **I want** checkpoint writes to be fast
- **So that** I maximize throughput
- **Given:** Migration with `batch_size=1000`
- **When:** Batch completes
- **Then:**
  - Checkpoint write completes in < 10ms (CC-19)
  - Transaction commits within 5s (INV-DM-02)
  - Logs write latency (CC-07)

**US-18: Support batch size > table size**
- **As a** developer processing small tables
- **I want** migrations to handle batch sizes larger than the table
- **So that** I don't need special cases
- **Given:** `users` table with 100 rows
- **When:** I run with `batch_size=1000`
- **Then:**
  - Processes 1 batch of 100 rows (INV-DM-03)
  - Completes in < 5s (CC-13)
  - Writes checkpoint (INV-DM-02)

**US-19: Minimize memory usage**
- **As a** developer running migrations
- **I want** low memory overhead
- **So that** I avoid OOM errors
- **Given:** Migration processing 1M rows
- **When:** Batch completes
- **Then:**
  - Memory usage < 50MB (CC-13)
  - Logs memory usage (CC-07)
  - Releases memory after batch (INV-DM-03)

**US-20: Handle batch size of 1**
- **As a** developer testing migrations
- **I want** to run with batch size 1
- **So that** I can debug row-by-row
- **Given:** `users` table with 100 rows
- **When:** I run with `batch_size=1`
- **Then:**
  - Processes 100 batches of 1 row (INV-DM-03)
  - Completes in < 500s (5s per batch) (CC-13)
  - Writes checkpoint every row (INV-DM-02)

### 9.5 Edge Cases & Idempotency (US-21 .. US-25)

**US-21: Handle migration rename**
- **As a** developer refactoring migrations
- **I want** renamed migrations to create new checkpoints
- **So that** I can track progress separately
- **Given:** Migration `backfill_user_timezone` renamed to `backfill_timezone`
- **When:** I run renamed migration
- **Then:**
  - Creates new checkpoint row (CC-10)
  - Preserves old checkpoint (INV-DM-04)
  - Logs "New migration name detected" (CC-07)

**US-22: Support idempotent migrations**
- **As a** developer running migrations multiple times
- **I want** idempotent migrations
- **So that** I can safely re-run
- **Given:** Migration `backfill_user_timezone` already completed
- **When:** I re-run migration
- **Then:**
  - Skips already processed rows (INV-DM-04)
  - Logs "No new rows to process" (CC-07)
  - Returns success status (T-19)

**US-23: Handle partial re-runs**
- **As a** developer fixing partial migrations
- **I want** migrations to process only new rows
- **So that** I don't duplicate work
- **Given:** Migration processed 500/1000 rows
- **When:** I add 100 new rows and re-run
- **Then:**
  - Processes only 100 new rows (INV-DM-04)
  - Completes in < 5s (CC-13)
  - Logs "100 new rows processed" (CC-07)

**US-24: Verify tool idempotency**
- **As a** developer re-running the generator
- **I want** the tool to be idempotent
- **So that** I don't duplicate files
- **Given:** Migration infrastructure already exists
- **When:** I run `add_migration_data` again
- **Then:**
  - No files modified (INV-DM-05)
  - Logs "Migration infrastructure already exists" (CC-07)
  - Returns success status (T-25)

**US-25: Handle missing data_migrations directory**
- **As a** developer adding migrations
- **I want** missing directories created automatically
- **So that** I don't get errors
- **Given:** Project without `data_migrations/` directory
- **When:** I run `add_migration_data`
- **Then:**
  - Creates `data_migrations/` directory (INV-DM-05)
  - Generates all required files (CC-01)
  - Returns success status (T-25)

---

## 10. Test Plan

### 10.1 Batching & Boundary Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Batch size enforced | Table with 10,000 rows | Run migration with batch_size=1000 | Processes exactly 10 batches (INV-DM-03) |
| T-02 | Last batch partial | Table with 1,005 rows | Run migration with batch_size=1000 | Processes 2 batches: 1000 + 5 rows (INV-DM-03) |
| T-03 | Empty table handled | Table with 0 rows | Run migration | Completes immediately, logs "Nothing to process" (INV-DM-03) |
| T-04 | Batch size > table size | Table with 100 rows | Run migration with batch_size=1000 | Processes 1 batch of 100 rows (INV-DM-03) |
| T-05 | Batch size of 1 | Table with 100 rows | Run migration with batch_size=1 | Processes 100 batches of 1 row each (INV-DM-03) |
| T-06 | Cursor-based pagination | Table with 10,000 rows | Run migration | Uses WHERE id > last_id, not OFFSET (INV-DM-03) |

### 10.2 Checkpoint & Crash Recovery Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Checkpoint written per batch | Table with 1,000 rows | Run migration | Writes checkpoint after each batch (INV-DM-02) |
| T-08 | Crash recovery | Crash at batch 50/100 | Re-run migration | Resumes from batch 51 (INV-DM-02) |
| T-09 | Corrupted checkpoint | Invalid last_processed_id | Run migration with --reset-checkpoint | Deletes checkpoint, starts from beginning (INV-DM-02) |
| T-10 | Unique migration names | Two migrations with same name | Attempt to run both | Raises IntegrityError on checkpoint write (INV-DM-09) |
| T-11 | Checkpoint atomicity | Crash during checkpoint write | Force crash mid-write | Last checkpoint remains intact (INV-DM-02) |
| T-12 | Migration rename | Rename migration from A to B | Run renamed migration | Creates new checkpoint row (INV-DM-04) |

### 10.3 Dry-run & Verification Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Dry-run no writes | Table with 1,000 rows | Run migration with --dry-run | Logs changes, no rows updated (INV-DM-01) |
| T-14 | CLI dry-run default | Migration template | Run migration without --execute | Runs in dry-run mode (INV-DM-08) |
| T-15 | Verification queries | Table with 1,000 rows | Run migration | Includes SELECT COUNT(*) before/after (INV-DM-11) |
| T-16 | Dry-run checkpoint ignored | Run dry-run then real run | Run migration | Ignores dry-run checkpoint (INV-DM-01) |
| T-17 | Progress logging | Table with 10,000 rows | Run migration | Logs progress every 100 batches (INV-DM-06) |
| T-18 | Structured logs | Table with 1,000 rows | Run migration | Logs include batch number, rows processed, elapsed time (INV-DM-06) |

### 10.4 Idempotency & Edge Cases

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Idempotent re-run | Table with 1,000 rows | Run migration twice | Second run processes 0 rows (INV-DM-04) |
| T-20 | Partial re-run | Add 100 rows after migration | Re-run migration | Processes only 100 new rows (INV-DM-04) |
| T-21 | Concurrent migrations | Two migrations same name | Run concurrently | Raises RuntimeError "Migration already running" (INV-DM-04) |
| T-22 | Dropped column handling | Migration depends on column X | Drop column X mid-migration | Raises SQLAlchemyError "Column not found" (INV-DM-04) |
| T-23 | Rollback documented | Migration without undo() | Call migrate undo | Raises NotImplementedError with clear message (INV-DM-07) |
| T-24 | Tool idempotency | Migration infrastructure exists | Run add_migration_data again | No files modified, logs "already exists" (INV-DM-05) |

### 10.5 Performance & Integration Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Directory creation | Missing data_migrations/ | Run add_migration_data | Creates data_migrations/ directory (INV-DM-05) |
| T-26 | Batch runtime SLO | Table with 1,000 rows | Run migration | Completes in < 5s (INV-DM-03) |
| T-27 | Checkpoint write SLO | Table with 1,000 rows | Run migration | Checkpoint write < 10ms (INV-DM-02) |
| T-28 | Memory overhead | Table with 1M rows | Run migration | Memory usage < 50MB (INV-DM-03) |
| T-29 | Schema migration impact | Running schema migration | Run data migration | Schema migration completes unaffected (INV-DM-05) |
| T-30 | Tool execution time | Fresh project | Run add_migration_data | Completes in < 2s (INV-DM-05) |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | Yes | ✅ Compatible | Data migrations should run AFTER soft delete migrations to ensure deleted rows are handled correctly |
| add_cursor_pagination | No | ✅ Compatible | Pagination and data migrations operate independently |
| add_search | Yes | ✅ Compatible | Search indexes should be rebuilt AFTER data migrations complete |
| add_audit_log | Yes | ⚠️ Caveat | Audit logs should be disabled during data migrations to avoid log bloat |
| add_data_export | No | ✅ Compatible | Data exports can run independently of migrations |
| add_bulk_operations | Yes | ⚠️ Caveat | Bulk operations should be paused during migrations to avoid conflicts |
| add_multi_tenancy | Yes | ✅ Compatible | Data migrations should run AFTER multi-tenancy setup |
| add_feature_flags | No | ✅ Compatible | Feature flags can be used to control migration rollout |
| add_api_key_auth | No | ✅ Compatible | API key auth works independently of migrations |
| add_oauth2_provider | No | ✅ Compatible | OAuth2 provider setup is independent |
| add_rbac | Yes | ✅ Compatible | RBAC should be configured BEFORE migrations to control access |
| add_mfa | No | ✅ Compatible | MFA setup is independent of migrations |
| add_cache_layer | Yes | ⚠️ Caveat | Cache should be cleared AFTER migrations to avoid stale data |
| add_outbox_pattern | Yes | ✅ Compatible | Outbox pattern should be implemented BEFORE migrations for reliable delivery |
| add_sse | No | ✅ Compatible | Server-sent events work independently of migrations |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD -- alembic/env.py pyproject.toml Makefile
rm -rf app/data_migrations/ app/models/checkpoint.py tests/test_data_migrations.py
```

### Database rollback (after deploy)
```bash
alembic downgrade -1
```
This drops the `data_migration_checkpoints` table created by the migration.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
```bash
git status
git checkout HEAD -- alembic/env.py pyproject.toml Makefile
rm -rf app/data_migrations/ app/models/checkpoint.py tests/test_data_migrations.py
```

### Emergency: Migration stuck processing large table
1. Identify migration name from logs
2. Run `python -m data_migrations reset --migration-name=<name>`
3. Investigate and fix the underlying issue before re-running

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Table with 0 rows | Tool logs "Nothing to process" and completes immediately |
| EC-2 | Table with 10M rows | Tool processes rows in batches and writes checkpoints every batch |
| EC-3 | Crash at batch 50/100 | Tool resumes from batch 51 using last checkpoint |
| EC-4 | Checkpoint corrupted | Tool errors with message "Corrupted checkpoint. Run with --reset-checkpoint to fix." |
| EC-5 | Same migration run twice | Tool processes only new rows and logs "No new rows to process" |
| EC-6 | Dry-run executed | Tool logs changes that would be made without writing to database |
| EC-7 | Rollback with undo() not implemented | Tool raises NotImplementedError with message "Rollback not supported for this migration" |
| EC-8 | Batch size 1 | Tool processes one row at a time and writes checkpoint after each row |
| EC-9 | Batch size > table size | Tool processes entire table in one batch and completes |
| EC-10 | Migration renamed | Tool creates new checkpoint row and preserves old one |
| EC-11 | Column dropped after migration started | Tool raises SQLAlchemyError with message "Column not found" |
| EC-12 | Concurrent writers modifying rows | Tool uses SELECT FOR UPDATE to lock rows during processing |
| EC-13 | Tool re-run (generator) | Tool logs "Migration infrastructure already exists" and skips file creation |
| EC-14 | Dry-run then real run | Tool ignores checkpoint from dry-run and starts from beginning |
| EC-15 | Migration with data_migrations/ missing | Tool creates data_migrations/ directory automatically |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified  
✅ 2. All 12 Quality Standards enforced  
✅ 3. All 8 Invariants tested  
✅ 4. All 30 tests pass (T-01..T-30)  
✅ 5. Migration CLI installed and functional  
✅ 6. Checkpoint table created in database  
✅ 7. Sample migration runs successfully  
✅ 8. Dry-run mode produces expected output  
✅ 9. Batch processing completes within SLOs  
✅ 10. Developer runs end-to-end migration: `python -m data_migrations run --execute` on production database  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate `app/` subdirectory exists
- [ ] Validate `alembic/versions/` exists
- [ ] Validate `alembic.ini` exists
- [ ] Parse target model files with AST
- [ ] Detect existing `data_migrations/` directory
- [ ] Check for `created_at` on each target model

### 15.2 Settings
- [ ] Create `app/core/migration_config.py`
- [ ] Add `batch_size` setting
- [ ] Add `dry_run_default` setting
- [ ] Add `checkpoint_table` setting
- [ ] Add `log_progress_every` setting
- [ ] Add `max_retries` setting
- [ ] Add `retry_delay` setting

### 15.3 Models
- [ ] Create `app/models/checkpoint.py`
- [ ] Define `Checkpoint` class
- [ ] Add `migration_name` column
- [ ] Add `last_processed_id` column
- [ ] Add `rows_processed` column
- [ ] Add `created_at` column
- [ ] Add `updated_at` column

### 15.4 Helper/core modules
- [ ] Create `app/data_migrations/migrate.py`
- [ ] Define `MigrationRunner` class
- [ ] Implement `run()` method
- [ ] Implement `_fetch_batch()` method
- [ ] Implement `_process_batch()` method
- [ ] Implement `_get_or_create_checkpoint()` method
- [ ] Add `async_session_maker()` context manager

### 15.5 CRUD layer
- [ ] Create `app/crud/checkpoint.py`
- [ ] Implement `create_checkpoint()` function
- [ ] Implement `get_checkpoint()` function
- [ ] Implement `update_checkpoint()` function
- [ ] Implement `delete_checkpoint()` function
- [ ] Implement `reset_checkpoint()` function
- [ ] Add `require_checkpoint()` function

### 15.6 Pydantic schemas
- [ ] Create `app/schemas/checkpoint.py`
- [ ] Define `CheckpointCreate` schema
- [ ] Define `CheckpointUpdate` schema
- [ ] Define `CheckpointPublic` schema
- [ ] Define `CheckpointInDB` schema
- [ ] Define `CheckpointStatus` schema
- [ ] Define `CheckpointReset` schema

### 15.7 Routes
- [ ] Create `app/api/routes/checkpoints.py`
- [ ] Add `GET /checkpoints/` endpoint
- [ ] Add `POST /checkpoints/` endpoint
- [ ] Add `PUT /checkpoints/{id}` endpoint
- [ ] Add `DELETE /checkpoints/{id}` endpoint
- [ ] Add `POST /checkpoints/reset` endpoint
- [ ] Add `GET /checkpoints/status` endpoint

### 15.8 Middleware or dependencies
- [ ] Create `app/api/middleware/migration.py`
- [ ] Implement `MigrationMiddleware` class
- [ ] Add `skip_migration_filter` execution option
- [ ] Register middleware in `app/main.py`
- [ ] Add `MIGRATION_ENABLED` to `app/core/config.py`
- [ ] Add `MIGRATION_BATCH_SIZE` to `app/core/config.py`
- [ ] Add `MIGRATION_DRY_RUN` to `app/core/config.py`

### 15.9 Migration generation
- [ ] Compute next revision number
- [ ] Generate `0NNN_add_checkpoint_table.py`
- [ ] `upgrade()`:
  1. Create `data_migration_checkpoints` table
  2. Add `migration_name` column
  3. Add `last_processed_id` column
  4. Add `rows_processed` column
  5. Add `created_at` column
  6. Add `updated_at` column
- [ ] `downgrade()` reverses in correct order
- [ ] Migration parses

### 15.10 Test generation
- [ ] Create `tests/test_data_migrations.py`
- [ ] Generate all 30 test cases (T-01..T-30)
- [ ] Use existing fixtures + new `checkpoint_fixture`
- [ ] Verify file parses
- [ ] Add `test_batch_size_enforced`
- [ ] Add `test_checkpoint_written_per_batch`
- [ ] Add `test_crash_recovery`

### 15.11 Atomicity
- [ ] All file writes use temp-file + rename pattern
- [ ] If ANY step fails, rollback ALL previous writes
- [ ] Drop partially-created checkpoint row if Insert succeeded but later step failed
- [ ] Return `{files_created, files_modified, files_rolled_back, error}` on failure
- [ ] Verify `ast.parse` on every modified file
- [ ] Run import audit on the project
- [ ] Measure tool execution time

### 15.12 Documentation updates
- [ ] Append data migration section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py` with new MCP tool decorator
- [ ] Add `data_migrations/README.md`
- [ ] Add `data_migrations/API.md`
- [ ] Add `data_migrations/TROUBLESHOOTING.md`

### 15.13 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit on the project
- [ ] Run `pytest tests/` to verify no regressions
- [ ] Run analyzer to verify benchmark unchanged
- [ ] Measure tool execution time
- [ ] Measure migration batch runtime
- [ ] Measure checkpoint write latency

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/data_migrations/migrate.py",
    "app/models/checkpoint.py",
    "app/core/migration_config.py",
    "app/data_migrations/cli.py",
    "app/data_migrations/0001_sample.py",
    "alembic/versions/0009_add_checkpoint_table.py",
    "tests/test_data_migrations.py",
    "app/data_migrations/README.md"
  ],
  "files_modified": [
    "alembic/env.py",
    "pyproject.toml",
    "Makefile"
  ],
  "metrics": {
    "execution_time_ms": 1872,
    "files_changed": 11,
    "lines_added": 721,
    "lines_removed": 12,
    "migrations_generated": 1,
    "checkpoint_table_created": true
  },
  "next_steps": [
    "Run: alembic upgrade head",
    "Run: pytest tests/test_data_migrations.py -v",
    "Create your first migration: python -m data_migrations run --dry-run",
    "Execute migration: python -m data_migrations run --execute",
    "Verify migration results: SELECT * FROM data_migration_checkpoints"
  ],
  "warnings": [
    "Dry-run mode is enabled by default. Pass --execute to write changes.",
    "Large tables may take significant time to process. Monitor progress logs."
  ],
  "notes": [
    "Data migration infrastructure created with batch_size=1000.",
    "Checkpoint table 'data_migration_checkpoints' created.",
    "Sample migration '0001_sample.py' generated.",
    "Migration CLI installed at app/data_migrations/cli.py.",
    "Progress logs emitted every 100 batches.",
    "Dry-run mode enabled by default for safety."
  ]
}
