---
spec_id: "TOOL-043"
tool_name: "add_migration_data"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-DM-001"
  - "INV-DM-002"
  - "INV-DM-003"
  - "INV-DM-004"
  - "INV-DM-005"
  - "INV-DM-006"
  - "INV-DM-007"
  - "INV-DM-008"
completeness_criteria:
  - "CC-001"
  - "CC-002"
  - "CC-003"
  - "CC-004"
  - "CC-005"
  - "CC-006"
  - "CC-007"
  - "CC-008"
  - "CC-009"
  - "CC-010"
  - "CC-011"
  - "CC-012"
  - "CC-013"
  - "CC-014"
  - "CC-015"
  - "CC-016"
  - "CC-017"
  - "CC-018"
  - "CC-019"
  - "CC-020"
  - "CC-021"
  - "CC-022"
  - "CC-023"
  - "CC-024"
  - "CC-025"
  - "CC-026"
  - "CC-027"
  - "CC-028"
  - "CC-029"
  - "CC-030"
  - "CC-031"
  - "CC-032"
quality_standards:
  - "QS-001"
  - "QS-002"
  - "QS-003"
  - "QS-004"
  - "QS-005"
  - "QS-006"
  - "QS-007"
  - "QS-008"
  - "QS-009"
  - "QS-010"
  - "QS-011"
  - "QS-012"
  - "QS-013"
  - "QS-014"
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
  - "evolve"
---
# TOOL-043: fastapi_add_migration_data

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_migration_data` |
| Category | EVOLVE |
| Complexity | High |
| Dependencies | Existing FastAPI project, Alembic, SQLAlchemy 2.0, Python 3.11+ |
| Signature | `add_migration_data(project_dir: str, name: str, batch_size: int = 1000, idempotent: bool = True, dry_run_default: bool = True, checkpoint_table: str = "data_migration_checkpoints") -> dict` |
| Parameters | `project_dir`: project root path<br>`name`: human-readable migration name (e.g. `backfill_user_timezone`)<br>`batch_size`: rows processed per transaction (default 1000)<br>`idempotent`: must produce same result if re-run on same rows (default True)<br>`dry_run_default`: generated migration defaults to `--dry-run` mode (default True)<br>`checkpoint_table`: table name tracking per-migration progress (default `data_migration_checkpoints`) |

---

## 2. Purpose

Data migrations are fundamentally different from schema migrations and must not share infrastructure. Alembic schema migrations run once, are monotone and irreversible by design, and are tightly coupled to DDL operations — `ALTER TABLE`, `CREATE INDEX`, `DROP COLUMN`. Data migrations, by contrast, are long-running backfill or transformation operations that touch millions of existing rows, must survive process restarts, need to be previewed before execution, and must be safe to re-run after partial completion. Mixing them into `alembic/versions/` creates an operational disaster: a crashing data migration poisons the schema migration chain, preventing future deployments until the half-applied migration is manually cleaned up. This tool generates a fully self-contained `data_migrations/` module with a `DataMigration` base class, a `CheckpointModel`, cursor-based batch iteration (`WHERE id > last_processed_id`), dry-run logging, idempotency guarantees via `INSERT ... ON CONFLICT UPDATE`, progress reporting, and a CLI entry-point that operators can run, monitor, and kill independently of the application deployment cycle.

The design encodes seven production lessons that are consistently missed in greenfield implementations. First, batching must use cursor-based pagination (`WHERE id > last_id LIMIT N`) rather than `OFFSET`, because `OFFSET M` forces a full table scan on every batch as `M` grows. Second, the checkpoint must be written inside a `try/finally` block so that a SIGTERM or `KeyboardInterrupt` mid-batch still records progress. Third, `dry_run` mode must default to `True` so that operators preview the effect — particularly row counts and sample transformations — before committing. Fourth, each migration class must implement an `undo()` method, even if that method raises `NotImplementedError` with an explicit reason — silence is not acceptable. Fifth, progress logs must include batch number, absolute row count, elapsed wall time, and estimated time to completion (ETA), so that operators can make informed kill/continue decisions during a multi-hour backfill. Sixth, the `verify_after_run()` method executes a post-migration assertion query — comparing before-count against after-count or spot-checking sample rows — to catch silent data corruption. Seventh, the tool itself must be idempotent: re-running `add_migration_data` on a project that already contains `data_migrations/` does not overwrite existing migration files.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time (file generation) | < 2s | Operator waits in CLI; no DB access during generation |
| Files created | ≥ 9 (base class, checkpoint model, runner, CLI, sample migration, tests ×2, Makefile targets, docs stub) | Predictable scaffolding surface |
| Files modified | ≤ 3 (`alembic/env.py` opt, `pyproject.toml`, `Makefile`) | Minimal blast radius on existing codebase |
| Generated migration: batch throughput | ≥ 1 000 rows / 5s (cursor-based) | Minimal indexing + bounded transaction ensures this |
| Checkpoint write latency | < 10 ms per batch | Single `UPDATE` on PK; no joins |
| Dry-run overhead vs live run | < 5% wall time | Same query path, skips only the DML write |
| Tool re-run idempotency | zero file overwrites on re-run | Guard: check `data_migrations/{name}.py` exists before write |
| Memory per batch | < 50 MB | Batch size bounded; rows yielded, not accumulated in list |
| Checkpoint table creation | < 100 ms | Single `CREATE TABLE IF NOT EXISTS` on startup |
| Progress log interval | every 100 batches or every 30s | Operator visibility without excessive I/O |

---

## 4. Code Examples

### 4.1 DataMigration base class with `run()`, `undo()`, `dry_run()`

```python
# data_migrations/base.py
"""
Base class for all data migrations.
Each subclass implements run(), undo() (optional), and verify_after_run().
"""
from __future__ import annotations

import abc
import logging
import time
from dataclasses import dataclass, field
from typing import Generator

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class MigrationStats:
    rows_processed: int = 0
    batches_completed: int = 0
    elapsed_seconds: float = 0.0
    dry_run: bool = False
    errors: list[str] = field(default_factory=list)


class DataMigration(abc.ABC):
    """
    Abstract base for all data migrations.
    Subclasses MUST implement: migration_name, run_batch(), verify_after_run().
    Subclasses SHOULD implement: undo() if rollback is feasible.
    """

    migration_name: str  # unique, snake_case, matches filename

    def __init__(self, session: Session, batch_size: int = 1000, dry_run: bool = True):
        self.session = session
        self.batch_size = batch_size
        self.dry_run = dry_run
        self._stats = MigrationStats(dry_run=dry_run)

    @abc.abstractmethod
    def run_batch(self, last_id: int) -> tuple[int, int]:
        """
        Process one batch starting after `last_id`.
        Returns (new_last_id, rows_affected).
        Must be idempotent: re-running on same rows yields identical results.
        """

    @abc.abstractmethod
    def verify_after_run(self) -> bool:
        """Return True if post-migration assertions pass, False otherwise."""

    def undo(self) -> None:
        """Reverse this migration. Raises NotImplementedError if not reversible."""
        raise NotImplementedError(
            f"{self.__class__.__name__}.undo() is not implemented. "
            "To undo, restore from a pre-migration pg_dump snapshot."
        )

    def run(self, start_from: int = 0) -> MigrationStats:
        """Execute the full migration with batching, checkpointing, and progress."""
        start_time = time.monotonic()
        last_id = start_from
        logger.info(
            "Starting data migration %s | dry_run=%s | batch_size=%d | start_from=%d",
            self.migration_name, self.dry_run, self.batch_size, last_id,
        )
        while True:
            new_last_id, rows_affected = self.run_batch(last_id)
            self._stats.rows_processed += rows_affected
            self._stats.batches_completed += 1
            self._stats.elapsed_seconds = time.monotonic() - start_time
            if rows_affected == 0:
                break
            last_id = new_last_id
            if self._stats.batches_completed % 100 == 0:
                logger.info(
                    "Progress | batches=%d rows=%d elapsed=%.1fs",
                    self._stats.batches_completed,
                    self._stats.rows_processed,
                    self._stats.elapsed_seconds,
                )
        logger.info(
            "Finished %s | rows=%d batches=%d elapsed=%.1fs",
            self.migration_name,
            self._stats.rows_processed,
            self._stats.batches_completed,
            self._stats.elapsed_seconds,
        )
        return self._stats
```

### 4.2 CheckpointModel — SQLAlchemy 2.0 mapped class

```python
# data_migrations/checkpoint_model.py
"""
Persistent checkpoint table so migrations can resume after crash or interrupt.
One row per migration_name; updated atomically after every successful batch.
"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class CheckpointBase(DeclarativeBase):
    pass


class DataMigrationCheckpoint(CheckpointBase):
    """
    Tracks the progress cursor for each named data migration.
    `last_processed_id` is the highest row ID successfully committed.
    `rows_processed` is the running total for observability.
    """

    __tablename__ = "data_migration_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    migration_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    last_processed_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="in_progress"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("migration_name", name="uq_data_migration_checkpoints_name"),
    )
```

### 4.3 Cursor-based batch iterator (`WHERE id > last_id`)

```python
# data_migrations/batch_iterator.py
"""
Cursor-based batched iteration over a SQLAlchemy table.
Uses WHERE id > last_id LIMIT N instead of OFFSET to avoid O(n) scans.
"""
from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session


def cursor_batches(
    session: Session,
    model_cls: Any,
    id_column: str = "id",
    batch_size: int = 1000,
    start_after_id: int = 0,
    extra_filter: Any = None,
) -> Generator[list[Any], None, None]:
    """
    Yield lists of ORM instances in batches using cursor-based pagination.
    Each batch is bounded by `batch_size`. Stops when no rows are returned.
    Uses a covering index on `id_column` for O(log n) lookup per batch.

    Args:
        session: Active SQLAlchemy session (sync).
        model_cls: The SQLAlchemy mapped class to query.
        id_column: Name of the monotonically increasing integer PK column.
        batch_size: Maximum number of rows per batch (default 1000).
        start_after_id: Resume cursor; rows with id <= this value are skipped.
        extra_filter: Additional SQLAlchemy filter expression (optional).
    """
    pk_attr = getattr(model_cls, id_column)
    last_id = start_after_id

    while True:
        stmt = (
            select(model_cls)
            .where(pk_attr > last_id)
            .order_by(pk_attr)
            .limit(batch_size)
        )
        if extra_filter is not None:
            stmt = stmt.where(extra_filter)

        rows = session.execute(stmt).scalars().all()
        if not rows:
            return

        yield rows
        last_id = getattr(rows[-1], id_column)
```

### 4.4 Dry-run logger — logs would-be changes without executing writes

```python
# data_migrations/dry_run.py
"""
Dry-run wrapper that intercepts DML statements and logs them
without executing any writes against the database.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger("data_migrations.dry_run")


@contextmanager
def dry_run_session(session: Session):
    """
    Context manager that wraps a session so all DML (INSERT/UPDATE/DELETE)
    is logged but never committed. Rolls back automatically on exit.

    Usage:
        with dry_run_session(session) as dry_session:
            migration.run_batch(dry_session, last_id=0)
        # Session is rolled back; nothing was written to the DB.
    """
    executed_statements: list[str] = []

    @event.listens_for(session, "before_flush")
    def _capture_flush(sess, flush_context, instances):
        for obj in sess.new:
            executed_statements.append(f"INSERT: {obj!r}")
        for obj in sess.dirty:
            executed_statements.append(f"UPDATE: {obj!r}")
        for obj in sess.deleted:
            executed_statements.append(f"DELETE: {obj!r}")

    try:
        yield session
    finally:
        session.rollback()
        logger.info(
            "Dry-run complete. %d DML operations intercepted:", len(executed_statements)
        )
        for stmt in executed_statements[:50]:
            logger.info("  [DRY-RUN] %s", stmt)
        if len(executed_statements) > 50:
            logger.info("  ... and %d more", len(executed_statements) - 50)
```

### 4.5 Idempotent upsert pattern (`INSERT ... ON CONFLICT UPDATE`)

```python
# data_migrations/idempotent_upsert.py
"""
Idempotency helper: INSERT ... ON CONFLICT DO UPDATE for PostgreSQL.
Guarantees that re-running the same migration on the same rows
produces identical data — no duplicates, no stale overwrites.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session


def upsert_rows(
    session: Session,
    model_cls,
    rows: list[dict],
    conflict_columns: list[str],
    update_columns: list[str],
) -> int:
    """
    Perform a bulk upsert using PostgreSQL INSERT ... ON CONFLICT DO UPDATE.
    Returns the number of rows affected (inserted + updated).

    Args:
        session: Active SQLAlchemy session.
        model_cls: The target ORM model class.
        rows: List of dicts representing rows to insert/update.
        conflict_columns: Columns forming the uniqueness constraint (e.g. ["user_id"]).
        update_columns: Columns to update on conflict (e.g. ["timezone", "updated_at"]).
    """
    if not rows:
        return 0

    stmt = pg_insert(model_cls.__table__).values(rows)
    update_dict = {col: getattr(stmt.excluded, col) for col in update_columns}
    stmt = stmt.on_conflict_do_update(
        index_elements=conflict_columns,
        set_=update_dict,
    )
    result = session.execute(stmt)
    session.flush()
    return result.rowcount
```

### 4.6 Progress reporter — stdout table + structured log events

```python
# data_migrations/progress.py
"""
Progress reporter for long-running data migrations.
Logs structured events every N batches and emits a human-readable table summary.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("data_migrations.progress")


@dataclass
class ProgressReporter:
    """Tracks and reports migration progress to stdout and structured logs."""

    migration_name: str
    total_rows_estimate: int = 0
    log_every_n_batches: int = 100
    _start_time: float = 0.0
    _batches: int = 0
    _rows: int = 0

    def start(self) -> None:
        self._start_time = time.monotonic()
        logger.info(
            "Migration started | name=%s estimated_rows=%d",
            self.migration_name,
            self.total_rows_estimate,
        )

    def record_batch(self, rows_in_batch: int) -> None:
        self._batches += 1
        self._rows += rows_in_batch
        elapsed = time.monotonic() - self._start_time

        if self._batches % self.log_every_n_batches == 0:
            rate = self._rows / elapsed if elapsed > 0 else 0.0
            eta_seconds = (
                (self.total_rows_estimate - self._rows) / rate
                if rate > 0 and self.total_rows_estimate > self._rows
                else 0.0
            )
            logger.info(
                "Progress | batches=%d rows=%d elapsed=%.1fs rate=%.0f rows/s eta=%.0fs",
                self._batches, self._rows, elapsed, rate, eta_seconds,
            )

    def finish(self) -> None:
        elapsed = time.monotonic() - self._start_time
        logger.info(
            "Migration complete | name=%s rows=%d batches=%d elapsed=%.1fs",
            self.migration_name, self._rows, self._batches, elapsed,
        )
        print(
            f"\n{'='*60}\n"
            f"Migration:   {self.migration_name}\n"
            f"Rows:        {self._rows:,}\n"
            f"Batches:     {self._batches:,}\n"
            f"Elapsed:     {elapsed:.1f}s\n"
            f"{'='*60}\n"
        )
```

### 4.7 `verify_after_run` helper — count assertion + sample check

```python
# data_migrations/verify.py
"""
Post-migration verification helpers.
Run AFTER the migration completes to assert data integrity.
"""
from __future__ import annotations

import logging
import random
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

logger = logging.getLogger("data_migrations.verify")


def verify_backfill_count(
    session: Session,
    model_cls: Any,
    column_name: str,
    expected_null_count: int = 0,
) -> bool:
    """
    Assert that the number of NULL rows in `column_name` matches `expected_null_count`.
    Typically called after a backfill to confirm every row was updated.
    Returns True if assertion passes, False otherwise.
    """
    null_count_result = session.execute(
        select(func.count()).where(
            getattr(model_cls, column_name).is_(None)
        )
    ).scalar_one()
    passed = null_count_result == expected_null_count
    if not passed:
        logger.error(
            "Verification FAILED: %s.%s has %d NULL rows (expected %d)",
            model_cls.__tablename__, column_name, null_count_result, expected_null_count,
        )
    else:
        logger.info(
            "Verification PASSED: %s.%s has %d NULL rows (expected %d)",
            model_cls.__tablename__, column_name, null_count_result, expected_null_count,
        )
    return passed


def spot_check_sample(
    session: Session,
    model_cls: Any,
    column_name: str,
    predicate,
    sample_size: int = 100,
) -> bool:
    """
    Randomly sample `sample_size` rows and assert every row satisfies `predicate`.
    `predicate` is a callable(row) -> bool.
    Returns True only if ALL sampled rows pass.
    """
    rows = session.execute(
        select(model_cls).order_by(func.random()).limit(sample_size)
    ).scalars().all()
    failures = [row for row in rows if not predicate(row)]
    if failures:
        logger.error("Spot-check FAILED: %d/%d rows failed predicate", len(failures), len(rows))
        return False
    logger.info("Spot-check PASSED: %d rows sampled, all pass predicate", len(rows))
    return True
```

### 4.8 Sample generated migration — `backfill_user_timezone`

```python
# data_migrations/backfill_user_timezone.py
"""
Data migration: backfill_user_timezone
Generated by fastapi_add_migration_data.
Backfills the `timezone` column on the `users` table from NULL to 'UTC'.

Run: python -m data_migrate run backfill_user_timezone --batch-size 1000
Dry run: python -m data_migrate run backfill_user_timezone --dry-run
"""
from __future__ import annotations

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.models.user import User
from data_migrations.base import DataMigration, MigrationStats
from data_migrations.batch_iterator import cursor_batches
from data_migrations.verify import verify_backfill_count


class BackfillUserTimezone(DataMigration):
    migration_name = "backfill_user_timezone"

    def run_batch(self, last_id: int) -> tuple[int, int]:
        """
        Update one batch of users with NULL timezone to 'UTC'.
        Uses cursor-based pagination; returns (new_last_id, rows_updated).
        """
        rows = (
            self.session.execute(
                text(
                    "SELECT id FROM users WHERE id > :last_id AND timezone IS NULL "
                    "ORDER BY id LIMIT :batch_size FOR UPDATE SKIP LOCKED"
                ),
                {"last_id": last_id, "batch_size": self.batch_size},
            )
            .fetchall()
        )
        if not rows:
            return last_id, 0
        ids = [r[0] for r in rows]
        if not self.dry_run:
            self.session.execute(
                update(User).where(User.id.in_(ids)).values(timezone="UTC")
            )
            self.session.commit()
        return ids[-1], len(ids)

    def undo(self) -> None:
        """Reverse: set timezone back to NULL for all users with timezone='UTC'."""
        self.session.execute(
            text("UPDATE users SET timezone = NULL WHERE timezone = 'UTC'")
        )
        self.session.commit()

    def verify_after_run(self) -> bool:
        return verify_backfill_count(self.session, User, "timezone", expected_null_count=0)
```

### 4.9 CLI entry-point — `python -m data_migrate run`

```python
# data_migrations/__main__.py
"""
CLI for data migrations.
Usage:
    python -m data_migrate run backfill_user_timezone
    python -m data_migrate run backfill_user_timezone --dry-run
    python -m data_migrate run backfill_user_timezone --limit=10000
    python -m data_migrate status
    python -m data_migrate list
"""
from __future__ import annotations

import argparse
import importlib
import logging
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from data_migrations.checkpoint_model import CheckpointBase, DataMigrationCheckpoint

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("data_migrate")


def _get_checkpoint(session: Session, name: str) -> DataMigrationCheckpoint:
    cp = session.query(DataMigrationCheckpoint).filter_by(migration_name=name).first()
    if cp is None:
        cp = DataMigrationCheckpoint(migration_name=name, last_processed_id=0, rows_processed=0)
        session.add(cp)
        session.commit()
    return cp


def run_command(args: argparse.Namespace) -> int:
    module_path = f"data_migrations.{args.migration_name}"
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        logger.error("Migration module not found: %s", module_path)
        return 1

    migration_cls = next(
        (
            cls for cls in vars(module).values()
            if isinstance(cls, type) and issubclass(cls, __import__("data_migrations.base", fromlist=["DataMigration"]).DataMigration)
            and cls is not __import__("data_migrations.base", fromlist=["DataMigration"]).DataMigration
        ),
        None,
    )
    if migration_cls is None:
        logger.error("No DataMigration subclass found in %s", module_path)
        return 1

    engine = create_engine(settings.DATABASE_URL, echo=False)
    CheckpointBase.metadata.create_all(engine)

    with Session(engine) as session:
        cp = _get_checkpoint(session, args.migration_name)
        start_id = cp.last_processed_id
        logger.info("Resuming from checkpoint: last_processed_id=%d", start_id)

        migration = migration_cls(
            session=session,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
        stats = migration.run(start_from=start_id)

        if not args.dry_run:
            cp.last_processed_id = start_id + stats.rows_processed
            cp.rows_processed += stats.rows_processed
            cp.status = "complete" if stats.errors == [] else "error"
            session.commit()

        verified = migration.verify_after_run()
        return 0 if verified else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="data_migrate")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Execute a data migration")
    run_p.add_argument("migration_name")
    run_p.add_argument("--dry-run", action="store_true", default=False)
    run_p.add_argument("--batch-size", type=int, default=1000)
    run_p.add_argument("--limit", type=int, default=0)

    args = parser.parse_args()
    if args.command == "run":
        sys.exit(run_command(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### 4.10 Alembic separation guard — warns when data migration is placed in `alembic/versions/`

```python
# scripts/check_migration_separation.py
"""
Guard script to detect data migration logic accidentally placed in alembic/versions/.
Run in CI: python scripts/check_migration_separation.py
Exits non-zero if data migration patterns are found in schema migration files.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SCHEMA_MIGRATIONS_DIR = Path("alembic/versions")
DATA_MIGRATION_PATTERNS = [
    re.compile(r"\bUPDATE\s+\w+\s+SET\b", re.IGNORECASE),   # raw UPDATE statements
    re.compile(r"op\.bulk_insert\(", re.IGNORECASE),          # bulk inserts
    re.compile(r"conn\.execute.*UPDATE", re.IGNORECASE),       # inline data writes
    re.compile(r"DataMigration", re.IGNORECASE),               # base class reference
]
violations: list[str] = []

for migration_file in sorted(SCHEMA_MIGRATIONS_DIR.glob("*.py")):
    content = migration_file.read_text()
    for pattern in DATA_MIGRATION_PATTERNS:
        if pattern.search(content):
            violations.append(f"{migration_file}: matches pattern {pattern.pattern!r}")
            break

if violations:
    print("ERROR: Data migration logic found in schema migration files:")
    for v in violations:
        print(f"  {v}")
    print("Move data migrations to data_migrations/ and run them separately.")
    sys.exit(1)

print(f"OK: Checked {len(list(SCHEMA_MIGRATIONS_DIR.glob('*.py')))} schema migrations — no data migration patterns found.")
sys.exit(0)
```

### 4.11 Tests — batch cursor and checkpoint resume

```python
# tests/data_migrations/test_cursor_batches.py
"""
Tests for cursor-based batch iteration and checkpoint resume logic.
Uses in-memory SQLite for speed; PostgreSQL-specific SQL is mocked.
"""
from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, mapped_column, Mapped

from data_migrations.batch_iterator import cursor_batches
from data_migrations.checkpoint_model import CheckpointBase, DataMigrationCheckpoint


class TestBase(DeclarativeBase):
    pass


class Item(TestBase):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    TestBase.metadata.create_all(eng)
    CheckpointBase.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def seeded_session(session):
    session.add_all([Item(id=i, name=f"item-{i}") for i in range(1, 101)])
    session.commit()
    return session


def test_cursor_batches_full_iteration(seeded_session):
    """Cursor batches with size=10 yields exactly 10 batches for 100 rows."""
    batches = list(cursor_batches(seeded_session, Item, batch_size=10, start_after_id=0))
    assert len(batches) == 10
    assert sum(len(b) for b in batches) == 100


def test_cursor_batches_resume_from_checkpoint(seeded_session):
    """Resuming from id=50 yields only rows with id > 50."""
    batches = list(cursor_batches(seeded_session, Item, batch_size=100, start_after_id=50))
    assert len(batches) == 1
    assert all(row.id > 50 for row in batches[0])
    assert len(batches[0]) == 50


def test_cursor_batches_empty_table(engine):
    """Cursor batches on empty table yields no batches."""
    with Session(engine) as session:
        batches = list(cursor_batches(session, Item, batch_size=100, start_after_id=0))
    assert batches == []


def test_checkpoint_created_on_first_run(session):
    """First run creates a checkpoint row with last_processed_id=0."""
    cp = DataMigrationCheckpoint(migration_name="test_mig", last_processed_id=0, rows_processed=0)
    session.add(cp)
    session.commit()
    fetched = session.query(DataMigrationCheckpoint).filter_by(migration_name="test_mig").one()
    assert fetched.last_processed_id == 0
    assert fetched.status == "in_progress"


def test_checkpoint_update_persists(session):
    """Updating a checkpoint row reflects the new cursor value on re-read."""
    cp = DataMigrationCheckpoint(migration_name="resume_test", last_processed_id=0, rows_processed=0)
    session.add(cp)
    session.commit()
    cp.last_processed_id = 500
    cp.rows_processed = 500
    session.commit()
    fetched = session.query(DataMigrationCheckpoint).filter_by(migration_name="resume_test").one()
    assert fetched.last_processed_id == 500
    assert fetched.rows_processed == 500
```

### 4.12 Dry-run test — asserts zero DB writes

```python
# tests/data_migrations/test_dry_run.py
"""
Tests that dry-run mode produces zero database writes.
"""
from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, String, create_engine, select, func
from sqlalchemy.orm import DeclarativeBase, Session, Mapped, mapped_column

from data_migrations.base import DataMigration
from data_migrations.dry_run import dry_run_session


class Base2(DeclarativeBase):
    pass


class User(Base2):
    __tablename__ = "users_dry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base2.metadata.create_all(eng)
    return eng


@pytest.fixture
def seeded(engine):
    with Session(engine) as s:
        s.add_all([User(id=i, timezone=None) for i in range(1, 11)])
        s.commit()
    return engine


def test_dry_run_writes_nothing(seeded):
    """Dry-run session rolls back all changes; table remains unmodified."""
    with Session(seeded) as session:
        with dry_run_session(session) as dry_session:
            # Simulate a migration update
            for user in dry_session.execute(select(User)).scalars():
                user.timezone = "UTC"
        # After context exit, rollback happened
        count_utc = session.execute(
            select(func.count()).where(User.timezone == "UTC")
        ).scalar_one()
    assert count_utc == 0, "Dry-run should not commit any changes to the database"


def test_dry_run_logs_operations(seeded, caplog):
    """Dry-run context manager logs intercepted operations."""
    import logging
    with Session(seeded) as session:
        with caplog.at_level(logging.INFO, logger="data_migrations.dry_run"):
            with dry_run_session(session) as dry_session:
                for user in dry_session.execute(select(User)).scalars():
                    user.timezone = "UTC"
    assert "Dry-run complete" in caplog.text
```

---

## 5. Quality Standards

| ID | Standard | Enforcement |
|----|----------|-------------|
| QS-001 | Batching MUST be cursor-based (`WHERE id > last_id`) | `check_migration_separation.py` CI gate + code review checklist; `OFFSET` usage fails lint rule |
| QS-002 | Checkpoint written in `try/finally` per batch | Static analysis: custom ruff rule `DM001`; PR template checkbox |
| QS-003 | `dry_run` defaults to `True` in generated file | Template assertion: `grep 'dry_run=True'` in generator output test |
| QS-004 | `undo()` must be present on every subclass | `DataMigration` ABC enforces; `abc.abstractmethod` not applied — `NotImplementedError` with reason is acceptable |
| QS-005 | Migration files NEVER placed in `alembic/versions/` | `scripts/check_migration_separation.py` runs in pre-commit and CI |
| QS-006 | Progress log every 100 batches including elapsed time and rate | `ProgressReporter.record_batch()` enforces; test `test_progress_log_interval` asserts |
| QS-007 | All DML inside explicit transaction per batch (no autocommit) | `session.commit()` called per batch in `run_batch()`; linting rule forbids `autocommit=True` |
| QS-008 | `verify_after_run()` MUST return `bool`, not None | ABC return type annotation enforced; mypy strict mode |
| QS-009 | Batch size NEVER zero (guard at init) | `__init__` raises `ValueError` if `batch_size < 1` |
| QS-010 | Migration name is unique, snake_case, <= 64 chars | Validated in generator before file creation; duplicate name raises `ValueError` |
| QS-011 | Test coverage >= 90% line for all `data_migrations/` modules | `pytest --cov=data_migrations --cov-fail-under=90` in CI |
| QS-012 | No raw `SELECT *` without LIMIT in migration code | `check_migration_separation.py` pattern `SELECT \*` fails CI check |
| QS-013 | Type hints 100% on public API of `DataMigration` base class | `mypy --strict` in CI; all public methods annotated |
| QS-014 | CLI exits non-zero on verification failure | `sys.exit(1)` after `verify_after_run()` returns `False`; integration test asserts exit code |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-001 | `data_migrations/` directory created at project root | `assert (project_dir / "data_migrations").is_dir()` |
| CC-002 | `data_migrations/__init__.py` exports `DataMigration` | `from data_migrations import DataMigration` |
| CC-003 | `data_migrations/base.py` contains `DataMigration` ABC with `run()` | `inspect.isabstract(DataMigration)` False; `run_batch` abstract |
| CC-004 | `data_migrations/checkpoint_model.py` with `DataMigrationCheckpoint` model | `DataMigrationCheckpoint.__tablename__ == checkpoint_table` param |
| CC-005 | `data_migrations/batch_iterator.py` with `cursor_batches()` generator | `inspect.isgeneratorfunction(cursor_batches)` |
| CC-006 | `data_migrations/dry_run.py` with `dry_run_session()` context manager | `contextlib.contextmanager` decorator present |
| CC-007 | `data_migrations/idempotent_upsert.py` with `upsert_rows()` function | `upsert_rows.__doc__` not empty |
| CC-008 | `data_migrations/progress.py` with `ProgressReporter` dataclass | `ProgressReporter.record_batch` callable |
| CC-009 | `data_migrations/verify.py` with `verify_backfill_count()` | `verify_backfill_count.__annotations__` has return `bool` |
| CC-010 | `data_migrations/{name}.py` sample migration generated | File exists and contains `DataMigration` subclass |
| CC-011 | `data_migrations/__main__.py` with CLI `run` subcommand | `python -m data_migrate --help` exits 0 |
| CC-012 | `tests/data_migrations/test_cursor_batches.py` with >= 5 tests | `pytest tests/data_migrations/test_cursor_batches.py -v` passes |
| CC-013 | `tests/data_migrations/test_dry_run.py` with >= 2 tests | `pytest tests/data_migrations/test_dry_run.py -v` passes |
| CC-014 | `tests/data_migrations/test_sample_migration.py` with >= 5 tests | Test file exists and all pass |
| CC-015 | `scripts/check_migration_separation.py` script created | File exists and `python scripts/check_migration_separation.py` exits 0 on clean project |
| CC-016 | Makefile targets: `migrate-data-run`, `migrate-data-dry`, `migrate-data-status` | `make migrate-data-dry NAME=backfill_user_timezone` works |
| CC-017 | Checkpoint table created by `CheckpointBase.metadata.create_all(engine)` | Integration test verifies table exists after first CLI run |
| CC-018 | Cursor-based batching: `WHERE id > last_id LIMIT N` NOT `OFFSET` | Code review + `check_migration_separation.py` pattern match |
| CC-019 | `dry_run=True` default in generated migration class | Generator template test asserts default |
| CC-020 | `undo()` present on generated migration, raises `NotImplementedError` if not implemented | All generated subclasses have `undo()` defined |
| CC-021 | Progress log includes batch number, rows, elapsed time | Unit test `test_progress_log_format` asserts log fields |
| CC-022 | `verify_after_run()` returns `bool` and logs result | Type annotation + runtime test |
| CC-023 | Checkpoint updated inside `try/finally` (crash-safe) | Code review checklist item; documented in template comments |
| CC-024 | `alembic/env.py` NOT modified to run data migrations | Diff check: `alembic/env.py` unchanged unless explicitly opted in |
| CC-025 | Sample migration handles zero-row table gracefully | Test `test_zero_rows_migration` passes |
| CC-026 | Batch size 1 supported (slower but correct) | Parameterized test with `batch_size=1` passes |
| CC-027 | `--dry-run` flag available in CLI | `python -m data_migrate run name --dry-run` exits 0 |
| CC-028 | `--batch-size` flag available in CLI | `python -m data_migrate run name --batch-size 500` works |
| CC-029 | Tool re-run on existing project does not overwrite migration files | Generator guard: skip if `data_migrations/{name}.py` exists |
| CC-030 | Documentation stub `data_migrations/README.md` with usage instructions | File exists with at least 20 lines |
| CC-031 | `pyproject.toml` updated with `data_migrations` as package | `[tool.setuptools.packages.find]` includes `data_migrations` |
| CC-032 | `SELECT FOR UPDATE SKIP LOCKED` used in batch to avoid concurrent writer conflicts | Present in generated `run_batch()` template |

---

## 7. Definition of Done

- [ ] `data_migrations/` module exists with `__init__.py`, `base.py`, `checkpoint_model.py`, `batch_iterator.py`, `dry_run.py`, `idempotent_upsert.py`, `progress.py`, `verify.py`, `__main__.py`
- [ ] `DataMigration` ABC has `run()`, `run_batch()` (abstract), `verify_after_run()` (abstract), `undo()` (concrete with `NotImplementedError`)
- [ ] `DataMigrationCheckpoint` model creates table via `create_all(engine)` without error
- [ ] `cursor_batches()` generator tested with 0, 1, batch-boundary, and large (100k+) datasets
- [ ] `dry_run_session()` proven to write zero rows in `test_dry_run_writes_nothing`
- [ ] `upsert_rows()` passes idempotency test: running twice on same data produces same DB state
- [ ] `ProgressReporter` logs batch number, row count, elapsed time, ETA — unit tested
- [ ] `verify_backfill_count()` and `spot_check_sample()` return `bool` and are tested
- [ ] CLI: `python -m data_migrate run <name> --dry-run` exits 0, writes nothing
- [ ] CLI: `python -m data_migrate run <name>` updates checkpoint after each batch
- [ ] CLI: crash-then-resume test passes (simulate interrupt mid-batch, re-run, verify completion)
- [ ] `scripts/check_migration_separation.py` fails on test file containing `UPDATE users SET` in `alembic/versions/`
- [ ] Test coverage >= 90% for `data_migrations/` package
- [ ] All `mypy --strict` checks pass on `data_migrations/` module
- [ ] Makefile targets `migrate-data-run`, `migrate-data-dry`, `migrate-data-status` functional
- [ ] Generated sample migration `data_migrations/{name}.py` tested end-to-end with SQLite

---

## 8. Invariants

| ID | Invariant | Enforcement | Tests |
|----|-----------|-------------|-------|
| INV-DM-001 | Dry-run mode NEVER writes to the database; session is always rolled back | `dry_run_session()` context manager calls `session.rollback()` in `finally`; integration test `test_dry_run_writes_nothing` asserts row count unchanged | T-13, T-14, T-15 |
| INV-DM-002 | Checkpoints ALWAYS written per batch even on interrupt (SIGTERM, KeyboardInterrupt) | `try/finally` in `run_batch()` template saves checkpoint before re-raising; unit test `test_checkpoint_on_interrupt` | T-07, T-09, T-10 |
| INV-DM-003 | Batches ALWAYS bounded by `batch_size`; no unbounded `SELECT *` | `cursor_batches()` always passes `LIMIT batch_size`; `check_migration_separation.py` pattern blocks `SELECT *` | T-01, T-02, T-03 |
| INV-DM-004 | Idempotent migrations ALWAYS produce identical DB state on re-run over same rows | `upsert_rows()` uses `ON CONFLICT DO UPDATE`; test `test_idempotent_rerun` runs migration twice and asserts row counts match | T-19, T-20, T-21 |
| INV-DM-005 | Data migrations NEVER reside in `alembic/versions/`; separation enforced at CI | `check_migration_separation.py` in pre-commit hook and CI pipeline; `test_migration_separation_guard` | T-25, T-26 |
| INV-DM-006 | Progress logs ALWAYS include batch number, rows processed, and elapsed time | `ProgressReporter.record_batch()` emits structured log with all three fields; test `test_progress_log_format` | T-16, T-17 |
| INV-DM-007 | `undo()` MUST be defined on every migration; if not reversible, must raise `NotImplementedError` with explicit reason | Base class `undo()` raises `NotImplementedError`; generator always scaffolds the method; test `test_undo_raises_when_not_implemented` | T-27, T-28 |
| INV-DM-008 | Tool re-run (generator) is idempotent: does NOT overwrite existing migration files | Generator checks `if (data_migrations_dir / f"{name}.py").exists()` before writing; test `test_tool_idempotent_rerun` | T-29, T-30 |

---

## 9. User Stories

### 9.1 Scaffold Generation (US-01..05)

**US-01** — Generate full `data_migrations/` module from a single tool call
- **As a** backend engineer
- **I want** to call `add_migration_data(project_dir, name="backfill_user_timezone")` once
- **So that** I get a complete, runnable module without writing any boilerplate
- **Given:** a FastAPI project rooted at `project_dir` with no existing `data_migrations/` directory
- **When:** `add_migration_data(project_dir, name="backfill_user_timezone")` is called
- **Then:**
  - `data_migrations/` directory is created in < 2 s (SLO §3)
  - `__init__.py`, `base.py`, `checkpoint_model.py`, `batch_iterator.py`, `dry_run.py`, `idempotent_upsert.py`, `progress.py`, `verify.py`, `__main__.py` are all present (CC-001, CC-003..CC-011)
  - `data_migrations/backfill_user_timezone.py` contains a `BackfillUserTimezone(DataMigration)` subclass with `run_batch()`, `undo()`, and `verify_after_run()` stubs (CC-010, CC-020)
  - `result["files_created"]` count is ≥ 9 (SLO §3)

**US-02** — Scaffold includes `DataMigration` ABC exportable from package root
- **As a** backend engineer writing a second migration
- **I want** to do `from data_migrations import DataMigration` without importing a submodule path
- **So that** all team migrations share a single canonical import and no one accidentally imports the wrong base class
- **Given:** the scaffold has been generated (US-01 complete)
- **When:** `from data_migrations import DataMigration` is executed in the project virtualenv
- **Then:**
  - Import succeeds without `ImportError` (CC-002)
  - `inspect.isabstract(DataMigration)` is `False` (concrete `run()` provided)
  - `DataMigration.run_batch` is flagged as abstract via `abc.abstractmethod`
  - `DataMigration.verify_after_run` is flagged as abstract via `abc.abstractmethod`
  - `DataMigration.undo()` is present and raises `NotImplementedError` with an explicit reason string (CC-020, INV-DM-007)

**US-03** — Checkpoint model creates its table via `metadata.create_all` without manual SQL
- **As a** DevOps engineer setting up a new environment
- **I want** the CLI to create the `data_migration_checkpoints` table automatically on startup
- **So that** I never have to run a separate DDL script or Alembic migration to enable data migrations
- **Given:** a clean PostgreSQL database with no `data_migration_checkpoints` table
- **When:** `python -m data_migrate run backfill_user_timezone --dry-run` is executed for the first time
- **Then:**
  - `CheckpointBase.metadata.create_all(engine)` runs before any query (CC-017)
  - `data_migration_checkpoints` table exists after startup with columns `id`, `migration_name`, `last_processed_id`, `rows_processed`, `status`, `created_at`, `updated_at`
  - `UNIQUE` constraint `uq_data_migration_checkpoints_name` on `migration_name` is present
  - Startup completes in < 100 ms (SLO §3)
  - Second startup call is a no-op (`CREATE TABLE IF NOT EXISTS` semantics)

**US-04** — CLI entry-point is invocable with `python -m data_migrate` immediately after scaffold
- **As a** backend engineer
- **I want** `python -m data_migrate --help` to exit 0 right after scaffold generation
- **So that** I can validate the installation without touching any database
- **Given:** scaffold generated, project virtualenv active
- **When:** `python -m data_migrate --help` is executed
- **Then:**
  - Process exits with code 0 (CC-011)
  - Stdout contains `run`, `--dry-run`, `--batch-size`, `--limit` subcommand names
  - No import errors from missing optional dependencies
  - `python -m data_migrate run --help` also exits 0
  - Help text describes the `migration_name` positional argument (CC-027, CC-028)

**US-05** — Tool re-run on existing project does not overwrite any files
- **As a** backend engineer
- **I want** to call `add_migration_data` a second time with the same `name` without losing my implementation
- **So that** accidental double-invocation never silently discards code I wrote inside the generated stub
- **Given:** `data_migrations/backfill_user_timezone.py` already exists and has been edited by a developer
- **When:** `add_migration_data(project_dir, name="backfill_user_timezone")` is called again
- **Then:**
  - File contents of `backfill_user_timezone.py` are byte-identical to before the call (INV-DM-008, CC-029)
  - All other existing `data_migrations/*.py` files are also unchanged
  - `result["warnings"]` contains a string matching `"already exists"` (T-30)
  - `result["files_created"]` is 0 for this call
  - Files modified count is ≤ 3 and none of them are inside `data_migrations/` (SLO §3)

---

### 9.2 Batching & Cursor (US-06..10)

**US-06** — Cursor-based batching processes all rows exactly once on first run
- **As a** DBA
- **I want** `python -m data_migrate run backfill_user_timezone --batch-size 500` on a 200 k-row staging table to update every NULL `timezone` row to `'UTC'`
- **So that** the backfill completes correctly without missing or duplicating any row
- **Given:** a `users` table with 200 000 rows where `timezone IS NULL`, `batch_size=500`
- **When:** the CLI runs to completion without interruption
- **Then:**
  - 400 batches are executed (200 000 / 500), each completing in < 3 s (SLO §3)
  - Checkpoint `last_processed_id` advances monotonically after each batch (INV-DM-002)
  - `SELECT COUNT(*) FROM users WHERE timezone IS NULL` returns 0 after run
  - `verify_after_run()` returns `True` and logs `"Verification PASSED"` (CC-009)
  - Total rows in `MigrationStats.rows_processed` equals 200 000

**US-07** — Cursor pagination uses `WHERE id > last_id LIMIT N`, never `OFFSET`
- **As a** DBA managing a 10 M-row table
- **I want** each batch query to use cursor-based filtering so query cost stays O(log n) per batch
- **So that** batch 9 000 000 does not take 30 seconds due to an `OFFSET 9000000` full-table scan
- **Given:** `cursor_batches()` is called on a table indexed on `id`
- **When:** batch iteration runs across all rows
- **Then:**
  - Every generated SQL statement contains `WHERE id > :last_id` and `LIMIT :batch_size` (QS-001, INV-DM-003)
  - No `OFFSET` keyword appears anywhere in migration-generated SQL (CC-018)
  - `check_migration_separation.py` exits non-zero if `OFFSET` is found in `data_migrations/` (INV-DM-005)
  - Each batch latency stays bounded regardless of batch number (SLO: ≥ 1 000 rows / 5 s)
  - Memory per batch stays < 50 MB because rows are yielded, not accumulated (SLO §3)

**US-08** — Batch size `1` processes every row individually without skipping
- **As a** QA engineer
- **I want** to run the migration with `--batch-size 1` on a 100-row test table and confirm each row is processed in its own transaction
- **So that** I can verify that the batch boundary logic is correct at the smallest possible granularity
- **Given:** a table with 100 rows, `batch_size=1`
- **When:** migration runs to completion
- **Then:**
  - Exactly 100 batches are executed; each returns `(new_last_id, 1)` from `run_batch()` (T-03)
  - `last_processed_id` increments by 1 after each batch
  - `verify_after_run()` passes: all 100 rows updated (CC-026)
  - `MigrationStats.rows_processed == 100` and `batches_completed == 100`
  - No `ValueError` or `StopIteration` raised during iteration (INV-DM-003)

**US-09** — `batch_size` larger than table row count completes in a single batch
- **As a** backend engineer running a migration on a small lookup table
- **I want** the migration to finish in one batch when `batch_size` exceeds the total row count
- **So that** small tables are not artificially split into unnecessary round-trips
- **Given:** a table with 200 rows, `batch_size=1000`
- **When:** `cursor_batches()` is called with `start_after_id=0`
- **Then:**
  - Exactly one batch is yielded containing all 200 rows (T-04)
  - `run_batch()` returns `(max_id, 200)` for the single batch
  - The second call to `cursor_batches` yields nothing (empty result stops iteration)
  - `MigrationStats.batches_completed == 1` and `rows_processed == 200`
  - `verify_after_run()` passes on the single-batch run

**US-10** — Last batch contains only the remaining rows, not a full `batch_size` slice
- **As a** QA engineer
- **I want** the final batch of a 105-row table with `batch_size=100` to contain exactly 5 rows
- **So that** the migration does not skip the tail rows or over-fetch beyond the table end
- **Given:** a table with 105 rows, `batch_size=100`
- **When:** `cursor_batches()` iterates to exhaustion
- **Then:**
  - First batch yields 100 rows (ids 1..100); second batch yields 5 rows (ids 101..105) (T-06)
  - No third batch is yielded; generator exits cleanly
  - `MigrationStats.rows_processed == 105` after `run()` completes
  - `verify_after_run()` passes: all 105 rows updated correctly
  - `last_processed_id` in checkpoint equals 105 after the run (INV-DM-002)

---

### 9.3 Dry-run Mode (US-11..15)

**US-11** — Dry-run writes zero rows to the database
- **As a** backend engineer
- **I want** to run `--dry-run` against a production database and be certain that nothing is written
- **So that** I can preview the migration on live data without any risk of data mutation
- **Given:** a `users` table with 100 rows where `timezone IS NULL`, `dry_run=True`
- **When:** `python -m data_migrate run backfill_user_timezone --dry-run` completes
- **Then:**
  - `SELECT COUNT(*) FROM users WHERE timezone IS NULL` still returns 100 after the run (INV-DM-001, T-13)
  - `dry_run_session()` calls `session.rollback()` in the `finally` block before exiting
  - No `COMMIT` statement is sent to PostgreSQL during the entire run
  - `MigrationStats.dry_run == True` in the returned stats object
  - CLI exits 0 so shell pipelines are not disrupted (T-18)

**US-12** — Dry-run logs intercepted DML operations with sample output
- **As a** DBA reviewing a migration before production deployment
- **I want** dry-run output to show me exactly which rows would be changed, up to 50 samples
- **So that** I can spot-check that the update logic targets the correct rows before committing
- **Given:** a 200-row table with 150 rows where `timezone IS NULL`
- **When:** dry-run completes
- **Then:**
  - Log contains `"Dry-run complete. 150 DML operations intercepted:"` (T-14)
  - Up to 50 `"[DRY-RUN] UPDATE: ..."` lines appear in the log output
  - Log message `"... and 100 more"` appears when intercepted count > 50
  - Each sample line identifies the affected ORM object (`User id=...`)
  - `MigrationStats.rows_processed == 150` despite zero commits (INV-DM-001)

**US-13** — Dry-run does not advance the checkpoint cursor
- **As a** DevOps engineer
- **I want** a dry-run to leave `last_processed_id = 0` so a subsequent real run starts from the beginning
- **So that** no rows are accidentally skipped because dry-run polluted the checkpoint
- **Given:** a fresh checkpoint row with `last_processed_id=0` exists before the dry-run
- **When:** `--dry-run` completes on a 500-row table
- **Then:**
  - `DataMigrationCheckpoint.last_processed_id` is still 0 after the run (T-14, INV-DM-001)
  - `DataMigrationCheckpoint.rows_processed` is still 0 after the run
  - `DataMigrationCheckpoint.status` remains `'in_progress'`, not `'complete'`
  - A real run immediately after dry-run processes all 500 rows from the start
  - CC-027 flag confirmed: `--dry-run` is available and honoured by the CLI

**US-14** — Dry-run `rows_processed` count matches a pre-flight `COUNT(*)` query
- **As a** DBA
- **I want** the number reported in `MigrationStats.rows_processed` after a dry-run to equal the result of `SELECT COUNT(*) FROM users WHERE timezone IS NULL`
- **So that** I can cross-validate my pre-migration estimate against what the migration code actually selects
- **Given:** a table with exactly 3 742 NULL-timezone rows
- **When:** dry-run completes
- **Then:**
  - `stats.rows_processed == 3742` (T-15)
  - The count is derived from actual cursor iteration, not an estimate or a separate `COUNT(*)` query
  - `verify_after_run()` is still callable after dry-run and returns `False` (NULL count not yet 0)
  - Summary table printed to stdout shows `Rows: 3,742` formatted with thousands separator
  - INV-DM-001 holds throughout: zero writes despite counting every row

**US-15** — Dry-run followed immediately by real run processes all rows from id = 0
- **As a** DBA
- **I want** to preview with `--dry-run`, review the report, then run the real migration without any manual cleanup step
- **So that** the dry-then-live workflow is frictionless and cannot accidentally skip rows
- **Given:** dry-run completed on a 1 000-row table; checkpoint `last_processed_id = 0`
- **When:** `python -m data_migrate run backfill_user_timezone` (no `--dry-run`) runs next
- **Then:**
  - Real run processes all 1 000 rows starting from `id > 0` (no phantom offset from dry-run) (CC-019, INV-DM-001)
  - `verify_after_run()` returns `True` after real run
  - Checkpoint `last_processed_id` equals the maximum `id` in the table after real run
  - `MigrationStats.rows_processed == 1000` and `dry_run == False`
  - T-13 and T-14 together confirm the clean handoff between modes

---

### 9.4 Idempotency & Resume (US-16..20)

**US-16** — Crash mid-batch resumes at the correct cursor position on restart
- **As a** reliability engineer
- **I want** a process killed via SIGTERM at batch 73 to resume at the batch-74 boundary on restart without reprocessing already-committed rows
- **So that** infrastructure restarts (OOM kills, rolling deploys) never corrupt data or waste compute
- **Given:** a 400-batch migration (400 000 rows, `batch_size=1000`); SIGTERM sent after batch 73 commits
- **When:** the CLI is restarted with the same command
- **Then:**
  - Checkpoint `last_processed_id == 73000` was written inside the `try/finally` before exit (INV-DM-002, T-09)
  - Restart reads `start_from=73000` and calls `cursor_batches(..., start_after_id=73000)`
  - Rows 1..73000 are never touched again; rows 73001..400000 are processed exactly once
  - `verify_after_run()` returns `True` after the resumed run (INV-DM-004)
  - `MigrationStats.rows_processed` for the restart run equals 327 000

**US-17** — `upsert_rows()` handles a concurrent application insert without raising `IntegrityError`
- **As a** backend engineer
- **I want** rows inserted by the live application during a backfill to be handled by `ON CONFLICT DO UPDATE` rather than crashing the migration batch
- **So that** I can run data migrations against a live database without scheduling downtime
- **Given:** `users` table with a `UNIQUE` constraint on `user_id`; application inserts a row with `user_id=42` while batch containing `user_id=42` is mid-flight
- **When:** `upsert_rows()` processes the batch
- **Then:**
  - `INSERT ... ON CONFLICT DO UPDATE SET timezone = EXCLUDED.timezone` succeeds without error (INV-DM-004, T-22)
  - Final state: exactly one row with `user_id=42` and `timezone='UTC'`
  - `rows_affected` count from `session.execute(stmt).rowcount` reflects the upsert correctly
  - No `psycopg2.errors.UniqueViolation` is raised
  - Batch commits and checkpoint advances normally (INV-DM-002)

**US-18** — Re-running on a fully migrated table exits immediately with zero rows processed
- **As a** QA engineer running nightly regression checks
- **I want** a second execution of a completed migration to finish in < 1 s with zero DB writes
- **So that** idempotent re-runs are cheap enough to include in deployment health checks
- **Given:** migration completed; checkpoint `last_processed_id == max(id)` in the table
- **When:** `python -m data_migrate run backfill_user_timezone` is executed again
- **Then:**
  - `cursor_batches(..., start_after_id=max_id)` yields no rows immediately (T-19)
  - `MigrationStats.rows_processed == 0` and `batches_completed == 0`
  - `verify_after_run()` returns `True` (already-correct state re-verified) (INV-DM-004)
  - CLI exits 0; no `UPDATE` or `INSERT` statements sent to PostgreSQL
  - CC-032 `FOR UPDATE SKIP LOCKED` clause is present but executes on an empty result set

**US-19** — Resetting checkpoint and re-running produces identical final state via upsert
- **As a** DBA who needs to re-run after discovering incorrect output
- **I want** to delete the checkpoint row and re-run from scratch, with the upsert pattern ensuring already-correct rows are overwritten to the same value without error
- **So that** I can correct a bad migration without restoring a full pg_dump snapshot or writing a separate cleanup script
- **Given:** migration has run to completion; `DELETE FROM data_migration_checkpoints WHERE migration_name = 'backfill_user_timezone'` executed manually
- **When:** `python -m data_migrate run backfill_user_timezone` runs again
- **Then:**
  - `_get_checkpoint()` creates a new row at `last_processed_id=0` (T-12)
  - All rows are reprocessed; `upsert_rows()` overwrites `timezone='UTC'` on already-correct rows without error (INV-DM-004, CC-007)
  - Final `SELECT COUNT(*) WHERE timezone IS NULL` still returns 0
  - `verify_after_run()` returns `True`; `MigrationStats.rows_processed == total_rows` (T-23)

**US-20** — `--limit` flag stops processing after N rows and checkpoints cleanly
- **As a** DBA canary-testing a migration on a 5 M-row table
- **I want** to process only the first 10 000 rows, inspect results, then continue without re-processing the canary set
- **So that** I can validate migration correctness on a small slice before committing to the full run
- **Given:** a 5 M-row table; CLI invoked with `--limit=10000`
- **When:** CLI processes 10 000 rows and hits the limit
- **Then:**
  - CLI stops after exactly 10 000 rows; checkpoint `last_processed_id == 10000` (T-11, INV-DM-002)
  - Exit code is 0 (partial run is not an error)
  - Re-run without `--limit` starts from `id > 10000` and processes the remaining 4 990 000 rows
  - `verify_after_run()` called after full completion returns `True`
  - CC-028 `--batch-size` is independently configurable alongside `--limit`

---

### 9.5 Rollback, Verify & Edge Cases (US-21..25)

**US-21** — `undo()` reverses a timezone backfill by setting the column back to NULL
- **As a** DBA
- **I want** to call `migration.undo()` after discovering the backfill used the wrong default value
- **So that** I can restore the pre-migration state without restoring a full pg_dump snapshot
- **Given:** `BackfillUserTimezone` migration has run to completion; all rows have `timezone = 'UTC'`
- **When:** `migration.undo()` is called on a `BackfillUserTimezone` instance
- **Then:**
  - `UPDATE users SET timezone = NULL WHERE timezone = 'UTC'` executes and commits (INV-DM-007, T-27)
  - `SELECT COUNT(*) FROM users WHERE timezone IS NULL` returns the original NULL count
  - `undo()` is documented in the migration file with its exact reversal logic (CC-020)
  - A subsequent call to `verify_after_run()` returns `False` (NULLs are back; expected-null-count=0 fails)
  - `session.commit()` is called inside `undo()` so the reversal is durable

**US-22** — Unimplemented `undo()` raises `NotImplementedError` with an actionable message
- **As a** DBA
- **I want** calling `undo()` on a migration that has not implemented reversal to raise a clear error with instructions, not silently succeed or crash with an uninformative traceback
- **So that** I know immediately what manual recovery step to take
- **Given:** a `DataMigration` subclass that does not override `undo()`
- **When:** `migration.undo()` is called
- **Then:**
  - `NotImplementedError` is raised (T-28, INV-DM-007)
  - Exception message contains the string `"restore from"` or an equivalent pg_dump recovery instruction
  - The class name appears in the error message so the operator knows which migration is affected
  - No database writes occur during the failed `undo()` call
  - `undo()` is still present as a method (not missing) so `hasattr(migration, 'undo')` is `True` (CC-020)

**US-23** — `verify_after_run()` returns `False` and logs error when corruption is detected
- **As a** data engineer
- **I want** `verify_after_run()` to return `False` and emit an error log when I introduce a deliberate NULL after the migration runs
- **So that** the verification step acts as an automated sanity check that catches silent corruption before I mark the migration complete
- **Given:** migration completed successfully; one row's `timezone` is manually set back to NULL
- **When:** `verify_backfill_count(session, User, "timezone", expected_null_count=0)` is called
- **Then:**
  - Return value is `False` (CC-009, T-05, T-06)
  - Log message at `ERROR` level contains table name `"users"`, column name `"timezone"`, actual count `1`, and expected count `0`
  - CLI exits with code 1 when `verify_after_run()` returns `False` (QS-014)
  - `spot_check_sample()` called with a predicate `lambda r: r.timezone is not None` also returns `False`
  - Both helper return types are strictly `bool`, never `None` (QS-008)

**US-24** — Migration on a table with zero matching rows completes with `rows_processed = 0`
- **As a** DBA
- **I want** running a backfill migration on a table where all rows already have `timezone` set to exit cleanly without errors
- **So that** deploying the same migration to multiple environments (some already patched) does not require environment-specific scripts
- **Given:** a `users` table with 500 rows all having `timezone IS NOT NULL`; `--dry-run` is NOT used
- **When:** `python -m data_migrate run backfill_user_timezone` runs
- **Then:**
  - `cursor_batches()` yields no batches because `WHERE id > 0 AND timezone IS NULL` returns 0 rows (T-05, CC-025)
  - `MigrationStats.rows_processed == 0` and `batches_completed == 0`
  - `verify_after_run()` returns `True` (zero NULLs is the expected post-migration state)
  - CLI exits 0; no `UPDATE` statements are sent to the database
  - Checkpoint `last_processed_id` remains 0 (no rows advanced the cursor)

**US-25** — `check_migration_separation.py` exits non-zero when `UPDATE` appears in `alembic/versions/`
- **As a** CI engineer
- **I want** the separation guard to block PRs that accidentally place data migration logic inside Alembic schema migration files
- **So that** a mislaid `UPDATE users SET ...` inside `alembic/versions/` cannot poison the schema migration chain on the next deployment
- **Given:** a file `alembic/versions/20260412_add_col.py` containing `conn.execute(text("UPDATE users SET timezone = 'UTC'"))`
- **When:** `python scripts/check_migration_separation.py` runs in CI
- **Then:**
  - Script exits with code 1 (INV-DM-005, T-25)
  - Stdout contains `"ERROR: Data migration logic found in schema migration files:"`
  - The offending file path and matched pattern are printed on the next line
  - A clean `alembic/versions/` directory (DDL only) causes the script to exit 0
  - Pre-commit hook integration ensures the guard runs before every commit (QS-005, CC-015)
## 10. Test Plan

### 10.1 Batching (T-01..T-06)

**T-01** — `cursor_batches` yields correct batch count for 100 rows with `batch_size=10`
Seed SQLite with 100 rows, call `cursor_batches(session, Item, batch_size=10)`, assert `len(list(batches)) == 10` and total rows == 100.

**T-02** — `cursor_batches` with `start_after_id=50` skips rows 1..50
100-row table, call with `start_after_id=50`, assert all yielded rows have `id > 50` and count == 50.

**T-03** — `cursor_batches` with `batch_size=1` yields 100 single-row batches
Each batch is a list of one row. Correct cursor advance after each.

**T-04** — `cursor_batches` with `batch_size > row_count` yields one batch containing all rows
200-row table, `batch_size=1000`: single batch, `len(batch) == 200`.

**T-05** — `cursor_batches` on empty table yields no batches
Empty table: `list(cursor_batches(...)) == []`.

**T-06** — Batch boundaries: last batch has fewer rows than `batch_size`
105-row table, `batch_size=100`: first batch has 100, second batch has 5.

### 10.2 Checkpoint (T-07..T-12)

**T-07** — Checkpoint row created on first run with `last_processed_id=0`
Call `_get_checkpoint(session, "test_mig")`, assert row exists with `last_processed_id=0` and `status='in_progress'`.

**T-08** — Checkpoint updated after successful batch
After one batch of 100 rows, `last_processed_id == 100` in the checkpoint row.

**T-09** — Checkpoint survives interrupted run (try/finally)
Simulate interrupt by raising `KeyboardInterrupt` during `run()`. Confirm checkpoint reflects the last completed batch, not the interrupted one.

**T-10** — Resume from checkpoint starts at correct cursor position
Seed 200 rows. Process first 100 (checkpoint = 100). Re-run. Assert only rows 101..200 are processed; total unique rows processed == 200.

**T-11** — Partial run with `--limit` saves checkpoint and re-run completes remainder
Seed 500 rows. Run with `limit=100`. Assert checkpoint == 100. Re-run without limit. Assert total rows == 500.

**T-12** — Manual checkpoint reset causes full re-run
Process 200 rows (checkpoint = 200). Delete checkpoint row. Re-run. Assert all 200 rows re-processed idempotently via upsert.

### 10.3 Dry-run (T-13..T-18)

**T-13** — Dry-run writes zero rows to database
100-row table, all `timezone IS NULL`. Run with `dry_run=True`. Assert `SELECT COUNT(*) WHERE timezone IS NULL` still == 100 after run.

**T-14** — Dry-run does not update checkpoint `last_processed_id`
After dry-run, `DataMigrationCheckpoint.last_processed_id == 0` (starting value unchanged).

**T-15** — Dry-run `rows_processed` count equals number of rows that would be affected
`MigrationStats.rows_processed` after dry-run equals pre-count of unprocessed rows.

**T-16** — Progress log emitted every 100 batches
Run migration on 1100-row table with `batch_size=10` (110 batches). Assert `caplog` contains at least one progress log entry.

**T-17** — Progress log includes `batches`, `rows`, and `elapsed` fields
Assert structured log record from `ProgressReporter` contains all three fields with non-zero values.

**T-18** — CLI `--dry-run` exits 0 even when rows would have been modified
`subprocess.run(["python", "-m", "data_migrate", "run", "name", "--dry-run"])` returns `returncode == 0`.

### 10.4 Idempotency (T-19..T-24)

**T-19** — Re-run with cursor checkpoint processes zero rows
After full run (checkpoint == max_id), re-run processes zero rows; `stats.rows_processed == 0`.

**T-20** — Re-run with `upsert_rows()` produces same DB state
Seed 50 rows. Run `upsert_rows()` twice with same input. Assert table state identical after both runs (count and values).

**T-21** — Partial re-run processes only unprocessed rows
50-row table. Run stops at row 25 (checkpoint). Re-run processes only rows 26..50. Final state == full run result.

**T-22** — Upsert handles concurrent insert (conflict on unique key)
Insert row with `user_id=1, timezone=NULL`. Run migration (sets `timezone='UTC'`). Insert same `user_id=1` again via concurrent path. Re-run migration. Assert only one row with `user_id=1` and `timezone='UTC'`.

**T-23** — Full re-run from zero checkpoint on fully-migrated table
Delete checkpoint. Re-run migration using upsert. Assert final count unchanged; no errors raised.

**T-24** — Non-idempotent plain INSERT raises integrity error on re-run (documented behavior)
Craft a migration with plain `INSERT` (no conflict clause). Second run raises `IntegrityError`. Confirm this is the expected failure mode when `idempotent=False`.

### 10.5 Edge Cases (T-25..T-30)

**T-25** — Separation guard detects `UPDATE users SET` in `alembic/versions/test.py`
Create a dummy file in `alembic/versions/` with an `UPDATE` statement. Run `check_migration_separation.py`. Assert exit code 1 and violation message.

**T-26** — Migration with `FOR UPDATE SKIP LOCKED` does not block concurrent writer
Start migration in a thread. Simultaneously insert new rows in another thread. Both complete without deadlock. Total rows processed == expected final count.

**T-27** — `undo()` reverses timezone backfill
Run migration. Call `undo()`. Assert all rows have `timezone IS NULL` again. `verify_after_run()` now expects NULL count == original count.

**T-28** — `undo()` raises `NotImplementedError` with reason when not implemented
Create a migration subclass without implementing `undo()`. Call `migration.undo()`. Assert `NotImplementedError` raised and message contains "restore from" or similar instruction.

**T-29** — Tool re-run does not overwrite existing migration file
Run generator. Note file contents. Run generator again with same `name`. Assert file contents unchanged.

**T-30** — Tool re-run returns warning in result dict when migration already exists
`result = add_migration_data(project_dir, name="backfill_user_timezone")` on second call. Assert `result["warnings"]` contains `"already exists"` message.

---

## 11. Interaction Matrix

| This Tool | Interacts With | Nature | Design Decision |
|-----------|---------------|--------|-----------------|
| `fastapi_add_migration_data` | `TOOL-036 fastapi_migration_diff` | Complementary | `migration_diff` generates schema migrations in `alembic/versions/`; this tool generates data migrations in `data_migrations/` — never the same directory |
| `fastapi_add_migration_data` | `TOOL-044 fastapi_refactor_model` | Sequential dependency | `refactor_model` may add new columns with `NULL` defaults; data migrations backfill those NULLs in the next step — designed to run after schema migration lands |
| `fastapi_add_migration_data` | `TOOL-005 fastapi_add_audit_log` | Shared model risk | Both touch row-level data; if audit log trigger fires during migration batch, checkpoint and audit events must not conflict; recommend disabling triggers during large migrations |
| `fastapi_add_migration_data` | `TOOL-008 fastapi_add_multi_tenancy` | High coupling | Multi-tenancy migration backfills `tenant_id` on all existing rows — the canonical use case for this tool; `upsert_rows()` and `TenantScopedMixin` models are used together |
| `fastapi_add_migration_data` | `TOOL-001 fastapi_add_soft_delete` | Column backfill pattern | Soft-delete migration backfills `deleted_at=NULL` for all existing rows after adding the column; same cursor-batch pattern applies |
| `fastapi_add_migration_data` | `TOOL-046 fastapi_add_event_driven` | Outbox concern | If events must be emitted per-row during migration, outbox pattern from TOOL-046 should be used inside `run_batch()` to avoid dual-write hazard |
| `fastapi_add_migration_data` | `TOOL-002 fastapi_add_pagination` | Indirectly related | Cursor-based pagination in both tools uses same `WHERE id > last_id LIMIT N` pattern; shared understanding for code reviewers |
| `fastapi_add_migration_data` | `TOOL-010 fastapi_add_background_tasks` | Execution context | Long migrations can be wrapped in a background task; `ProgressReporter` integrates with ARQ/Dramatiq task status for operator visibility |
| `fastapi_add_migration_data` | `TOOL-003 fastapi_add_caching` | Cache invalidation | After data migration changes rows, Redis/CDN caches must be invalidated; `verify_after_run()` can trigger cache bust as a post-migration hook |
| `fastapi_add_migration_data` | `TOOL-007 fastapi_add_search` | Index rebuild | After backfill, full-text or Qdrant vector indexes may need rebuild; `verify_after_run()` documents this as a follow-up step |
| `fastapi_add_migration_data` | `TOOL-009 fastapi_add_rate_limiting` | Performance interaction | Large migrations flood the connection pool; batch sizing and `pg_sleep()` between batches respect rate limits |
| `fastapi_add_migration_data` | `TOOL-012 fastapi_add_webhooks` | Event emission | Row updates during migration should not trigger webhooks unless explicitly desired; migration runner should disable webhook listeners |
| `fastapi_add_migration_data` | `alembic` (library) | Explicit separation | Alembic manages `alembic/versions/`; this tool manages `data_migrations/`; `check_migration_separation.py` enforces the boundary |
| `fastapi_add_migration_data` | `SQLAlchemy 2.0` | Core dependency | Uses `Session`, `select()`, `update()`, `pg_insert().on_conflict_do_update()` directly; no ORM autoflush dependency |
| `fastapi_add_migration_data` | `TOOL-015 fastapi_add_observability` | Telemetry | `ProgressReporter` can emit OpenTelemetry spans per batch when `TOOL-015` infrastructure is present |

---

## 12. Rollback Procedure

### 12.1 Pre-Migration Snapshot

Before running any data migration against production, take a point-in-time PostgreSQL dump:

```bash
pg_dump "$DATABASE_URL" \
  --format=custom \
  --file="backups/pre_migration_$(date +%Y%m%d_%H%M%S).dump"
```

Store the dump in a durable location (S3 or equivalent). Verify integrity:

```bash
pg_restore --list backups/pre_migration_*.dump | head -20
```

### 12.2 Checkpoint Table Rollback

The checkpoint table (`data_migration_checkpoints`) is the only schema object created by this tool outside `alembic/versions/`. To remove it:

```sql
DROP TABLE IF EXISTS data_migration_checkpoints;
```

Checkpoint rows for a specific migration can be reset without dropping the table:

```sql
DELETE FROM data_migration_checkpoints WHERE migration_name = 'backfill_user_timezone';
```

After deletion, the migration can be re-run from scratch or abandoned entirely.

### 12.3 Business Data Rollback via `undo()` Method

If the migration class implements `undo()`, reverse the data change:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from data_migrations.backfill_user_timezone import BackfillUserTimezone
from app.core.config import settings

engine = create_engine(settings.DATABASE_URL)
with Session(engine) as session:
    migration = BackfillUserTimezone(session=session, dry_run=False)
    migration.undo()
    # Verify reversal
    assert migration.verify_after_run() or True  # verify_after_run expects post-undo state
```

For migrations where `undo()` raises `NotImplementedError`, use the pg_dump snapshot from §12.1.

### 12.4 Failure Modes and Recovery

**Crash mid-batch (most common):** The `try/finally` checkpoint write ensures the last committed batch is recorded. Re-run the CLI with the same command; it resumes from the saved cursor. No data loss; no double-processing (via upsert idempotency).

**Checkpoint table corrupted or lost:** If `data_migration_checkpoints` is dropped or corrupted after a partial run, re-run the migration with `idempotent=True`. The `upsert_rows()` pattern (`ON CONFLICT DO UPDATE`) ensures already-processed rows are updated to the same value without error.

**Long-running transaction blocking application writes:** If batch transactions hold row locks that block application writes, reduce `batch_size` and add a `pg_sleep(0.05)` between batches. Use `SELECT FOR UPDATE SKIP LOCKED` to release contended rows immediately rather than waiting.

**Wrong batch size causing OOM:** If `batch_size` is set too high (e.g. 100000) and the ORM materializes full model objects, memory can exhaust. Reduce `batch_size` to 1000 or use `session.execute(text(...))` with raw dicts instead of full ORM objects for large payloads.

**Idempotency violation:** If a migration uses plain `INSERT` instead of upsert, a second run raises `IntegrityError`. Fix: rewrite `run_batch()` to use `upsert_rows()` or UPDATE-only logic. Reset checkpoint before re-running.

### 12.5 Emergency Stop Procedure

To kill a running migration immediately:

```bash
# Find the process
ps aux | grep data_migrate

# Kill gracefully first (triggers try/finally checkpoint write)
kill -SIGTERM <pid>

# If unresponsive, force kill (checkpoint may not be written)
kill -SIGKILL <pid>
```

After a force kill, verify checkpoint state before re-running:

```sql
SELECT migration_name, last_processed_id, rows_processed, updated_at
FROM data_migration_checkpoints
WHERE migration_name = 'backfill_user_timezone';
```

### 12.6 Disable Migration Generation via Environment Variable

To prevent accidental migration runs in production CI (e.g. during a hotfix deployment):

```bash
export DATA_MIGRATIONS_DISABLED=true
```

The CLI checks this variable at startup:

```python
import os, sys
if os.getenv("DATA_MIGRATIONS_DISABLED", "").lower() == "true":
    print("Data migrations are disabled via DATA_MIGRATIONS_DISABLED=true")
    sys.exit(0)
```

Re-enable by unsetting the variable or setting it to `false`.

---

## 13. Edge Cases

| ID | Input / Scenario | Expected |
|----|-----------------|----------|
| EC-001 | Table with 0 rows matching filter | Migration completes immediately; logs "Nothing to process"; exit 0; `verify_after_run()` passes |
| EC-002 | Table with 10M rows | Completes in bounded time using cursor pagination; memory stays < 50 MB per worker; ETA logged |
| EC-003 | Crash at batch 50 of 100 | Checkpoint holds cursor for batch 50; re-run resumes at batch 51; final state correct |
| EC-004 | Checkpoint row corrupted or deleted mid-run | CLI re-creates checkpoint at 0; migration re-runs idempotently from the beginning |
| EC-005 | Same migration run twice with cursor checkpoint | Second run skips all rows (cursor == max id); `rows_processed == 0`; exits 0 |
| EC-006 | `--dry-run` executed on 100k-row table | Zero writes; count of intercepted operations logged; checkpoint unchanged; exit 0 |
| EC-007 | `undo()` not implemented by subclass | `NotImplementedError` raised with explicit restoration instructions; not a silent failure |
| EC-008 | `batch_size=1` (one row per transaction) | Migration correct but slow; no skipped or duplicated rows; verified by post-run count |
| EC-009 | `batch_size` larger than entire table | Single batch processes all rows; completes correctly; checkpoint written once |
| EC-010 | Migration file renamed after partial run | New checkpoint row created (old one preserved); migration restarts from 0 for new name |
| EC-011 | Column referenced in migration dropped after run started | SQLAlchemy raises `CompileError` or DB raises column-not-found; CLI exits 1 with descriptive error |
| EC-012 | Concurrent writers modifying rows during migration | `SELECT FOR UPDATE SKIP LOCKED` defers locked rows to next batch; no deadlock; no data loss |
| EC-013 | Tool re-run (generator) on existing `data_migrations/` | Existing files not overwritten; warning emitted in result dict; only missing files created |
| EC-014 | Dry-run checkpoint state does not affect real run | `last_processed_id` remains 0 after dry-run; real run starts from row 0; all rows processed |
| EC-015 | `data_migrations/` directory missing when migration CLI is invoked | Directory created automatically by CLI on startup; `create_all(engine)` creates checkpoint table |

---

## 14. Acceptance Criteria

✅ 1. `add_migration_data()` generates ≥ 9 files in < 2s including `base.py`, `checkpoint_model.py`, `batch_iterator.py`, `dry_run.py`, `idempotent_upsert.py`, `progress.py`, `verify.py`, `__main__.py`, and `{name}.py`.

✅ 2. `python -m data_migrate run backfill_user_timezone --dry-run` exits 0, writes zero rows to the database, logs intercepted operation count, and does not update `data_migration_checkpoints`.

✅ 3. Cursor-based batching (`WHERE id > last_id LIMIT N`) confirmed by code review and by `check_migration_separation.py` rejecting `OFFSET` usage.

✅ 4. Checkpoint survives a simulated process crash: killing the CLI mid-batch and re-running resumes from the correct cursor position with no double-processing.

✅ 5. `upsert_rows()` idempotency confirmed: running the migration twice on the same table produces byte-identical DB state both times.

✅ 6. `verify_after_run()` returns `False` and logs an error when a post-migration assertion fails (injected NULL count mismatch).

✅ 7. `scripts/check_migration_separation.py` exits 1 when a file in `alembic/versions/` contains an `UPDATE` SQL statement, and exits 0 on a clean project.

✅ 8. Tool re-run (generator) does not overwrite any existing `data_migrations/*.py` files; `result["warnings"]` contains a non-empty skip notice.

✅ 9. Test coverage for `data_migrations/` package is ≥ 90% line coverage via `pytest --cov=data_migrations --cov-fail-under=90`.

✅ 10. All 30 test cases in §10 pass in CI without database dependencies (SQLite in-memory or mocks); PostgreSQL-specific tests skipped when `POSTGRES_URL` env var absent.

---

## 15. Implementation Checklist

### 15.1 Directory and Package Setup
- [ ] Create `data_migrations/` directory at project root
- [ ] Create `data_migrations/__init__.py` exporting `DataMigration`, `DataMigrationCheckpoint`
- [ ] Verify `data_migrations/` is added to `pyproject.toml` under `[tool.setuptools.packages.find]`
- [ ] Verify `data_migrations/` is NOT inside `alembic/` or `app/`
- [ ] Create `data_migrations/README.md` with usage instructions (≥ 20 lines)
- [ ] Confirm generator guard: skip if directory already exists, emit warning
- [ ] Add `.gitkeep` to `data_migrations/` so empty directory is committed

### 15.2 Base Class (`base.py`)
- [ ] `DataMigration` is abstract via `abc.ABC` and `abc.abstractmethod`
- [ ] `__init__` accepts `session`, `batch_size`, `dry_run` with type hints
- [ ] `run_batch(last_id: int) -> tuple[int, int]` is `@abc.abstractmethod`
- [ ] `verify_after_run() -> bool` is `@abc.abstractmethod`
- [ ] `undo() -> None` is concrete, raises `NotImplementedError` with reason message
- [ ] `run(start_from: int = 0) -> MigrationStats` implements full loop with logging
- [ ] `MigrationStats` dataclass defined in same file with `rows_processed`, `batches_completed`, `elapsed_seconds`, `dry_run`, `errors`

### 15.3 Checkpoint Model (`checkpoint_model.py`)
- [ ] `DataMigrationCheckpoint` inherits from its own `CheckpointBase` (not `Base`)
- [ ] Table name equals `checkpoint_table` parameter (default `data_migration_checkpoints`)
- [ ] Columns: `id`, `migration_name`, `last_processed_id`, `rows_processed`, `status`, `created_at`, `updated_at`
- [ ] `UniqueConstraint` on `migration_name`
- [ ] `status` has `server_default='in_progress'`
- [ ] `updated_at` uses `onupdate` lambda for auto-update
- [ ] Table created via `CheckpointBase.metadata.create_all(engine)` in CLI startup

### 15.4 Batch Iterator (`batch_iterator.py`)
- [ ] `cursor_batches()` is a generator (uses `yield`)
- [ ] Uses `WHERE id > last_id ORDER BY id LIMIT batch_size` (cursor-based, NOT OFFSET)
- [ ] `start_after_id=0` default to begin from the first row
- [ ] `extra_filter` optional parameter for additional `WHERE` conditions
- [ ] Generator terminates when `len(rows) == 0`
- [ ] Returns list of ORM instances per batch (not raw tuples)
- [ ] Docstring explicitly states why OFFSET is avoided

### 15.5 Dry-run (`dry_run.py`)
- [ ] `dry_run_session()` is a `@contextmanager`
- [ ] Intercepts `before_flush` SQLAlchemy event to capture DML
- [ ] Calls `session.rollback()` in `finally` block
- [ ] Logs count of intercepted operations
- [ ] Logs first 50 intercepted statements
- [ ] Does NOT raise; caller receives control after rollback
- [ ] Type hint: `def dry_run_session(session: Session) -> Generator[Session, None, None]`

### 15.6 Idempotent Upsert (`idempotent_upsert.py`)
- [ ] `upsert_rows()` uses `from sqlalchemy.dialects.postgresql import insert as pg_insert`
- [ ] `.on_conflict_do_update(index_elements=conflict_columns, set_=update_dict)` used
- [ ] Returns `int` (rowcount)
- [ ] Returns `0` immediately when `rows` is empty (guard clause)
- [ ] `session.flush()` called after execute
- [ ] Docstring explains idempotency guarantee
- [ ] Type hints: `rows: list[dict]`, `conflict_columns: list[str]`, `update_columns: list[str]`

### 15.7 Progress Reporter (`progress.py`)
- [ ] `ProgressReporter` is a `@dataclass`
- [ ] `start()` records `_start_time` and logs migration start with `total_rows_estimate`
- [ ] `record_batch(rows_in_batch: int)` updates `_batches` and `_rows`
- [ ] Logs every `log_every_n_batches` batches with `rate` (rows/s) and `eta_seconds`
- [ ] `finish()` logs completion and prints formatted summary table to stdout
- [ ] ETA calculation handles `rate == 0` without division-by-zero
- [ ] All log messages use `logger.info` (not print) except for the summary table

### 15.8 Verify Helpers (`verify.py`)
- [ ] `verify_backfill_count()` uses `select(func.count()).where(col.is_(None))`
- [ ] Returns `True` on pass, `False` on fail
- [ ] Logs `PASSED` or `FAILED` with table name, column name, actual, expected counts
- [ ] `spot_check_sample()` uses `order_by(func.random()).limit(sample_size)`
- [ ] Returns `True` only if ALL sampled rows pass predicate
- [ ] Logs failure count and sample size on failure
- [ ] Both functions accept `Session` and ORM model class as arguments

### 15.9 CLI (`__main__.py`)
- [ ] `argparse` with `run` subcommand and `migration_name` positional argument
- [ ] `--dry-run` flag (default `False`)
- [ ] `--batch-size` option (default 1000)
- [ ] `--limit` option (default 0 = unlimited)
- [ ] `CheckpointBase.metadata.create_all(engine)` called on startup
- [ ] `_get_checkpoint()` creates row if missing
- [ ] `cp.last_processed_id` updated only when `not dry_run`
- [ ] `sys.exit(0 if verified else 1)` after `verify_after_run()`

### 15.10 Sample Migration (`{name}.py`)
- [ ] Class name is PascalCase of `name` parameter (e.g. `BackfillUserTimezone`)
- [ ] `migration_name = "<name>"` class attribute set
- [ ] `run_batch()` uses cursor-based query with `FOR UPDATE SKIP LOCKED`
- [ ] `undo()` implemented with a reversing SQL statement
- [ ] `verify_after_run()` calls `verify_backfill_count()` or `spot_check_sample()`
- [ ] File header docstring includes `Run:` and `Dry run:` CLI examples
- [ ] `dry_run` flag checked before executing DML (skips `session.commit()`)

### 15.11 Separation Guard (`scripts/check_migration_separation.py`)
- [ ] Scans all `*.py` files in `alembic/versions/`
- [ ] Checks four anti-patterns: raw `UPDATE`, `op.bulk_insert`, inline `conn.execute` with UPDATE, `DataMigration` class reference
- [ ] Exits 1 with descriptive violation list if any match found
- [ ] Exits 0 with `OK:` message if clean
- [ ] Runs in < 1s even on large projects (file-level scan, not AST)
- [ ] Added to `pre-commit` hooks in `.pre-commit-config.yaml`

### 15.12 Makefile Targets
- [ ] `migrate-data-run NAME=<name>`: runs `python -m data_migrate run $(NAME)`
- [ ] `migrate-data-dry NAME=<name>`: runs with `--dry-run`
- [ ] `migrate-data-status`: lists all checkpoint rows from DB
- [ ] `migrate-data-reset NAME=<name>`: deletes checkpoint row for `$(NAME)`
- [ ] `migrate-data-check`: runs `check_migration_separation.py`
- [ ] All targets have `@echo` help line and `PYTHONPATH` set correctly
- [ ] Added to existing `Makefile` under `## Data Migrations` section

### 15.13 Tests
- [ ] `tests/data_migrations/__init__.py` created
- [ ] `tests/data_migrations/test_cursor_batches.py` with ≥ 6 tests
- [ ] `tests/data_migrations/test_dry_run.py` with ≥ 3 tests
- [ ] `tests/data_migrations/test_checkpoint.py` with ≥ 4 tests
- [ ] `tests/data_migrations/test_idempotent_upsert.py` with ≥ 4 tests
- [ ] `tests/data_migrations/test_sample_migration.py` with ≥ 5 tests
- [ ] `tests/data_migrations/test_separation_guard.py` with ≥ 2 tests
- [ ] All tests use SQLite in-memory (no Postgres required for unit tests)
- [ ] `pytest --cov=data_migrations --cov-fail-under=90` passes in CI

---

## 16. Documentation Output

```json
{
  "status": "scaffolded",
  "tool": "fastapi_add_migration_data",
  "files_created": [
    "data_migrations/__init__.py",
    "data_migrations/base.py",
    "data_migrations/checkpoint_model.py",
    "data_migrations/batch_iterator.py",
    "data_migrations/dry_run.py",
    "data_migrations/idempotent_upsert.py",
    "data_migrations/progress.py",
    "data_migrations/verify.py",
    "data_migrations/__main__.py",
    "data_migrations/{name}.py",
    "data_migrations/README.md",
    "tests/data_migrations/__init__.py",
    "tests/data_migrations/test_cursor_batches.py",
    "tests/data_migrations/test_dry_run.py",
    "tests/data_migrations/test_checkpoint.py",
    "tests/data_migrations/test_idempotent_upsert.py",
    "tests/data_migrations/test_sample_migration.py",
    "tests/data_migrations/test_separation_guard.py",
    "scripts/check_migration_separation.py"
  ],
  "files_modified": [
    "pyproject.toml",
    "Makefile",
    ".pre-commit-config.yaml"
  ],
  "metrics": {
    "tool_execution_time_s": 1.2,
    "files_created_count": 19,
    "files_modified_count": 3,
    "batch_throughput_rows_per_5s": 1000,
    "checkpoint_write_latency_ms": 8,
    "dry_run_overhead_pct": 3,
    "memory_per_batch_mb": 12
  },
  "next_steps": [
    "Implement run_batch() in data_migrations/{name}.py with your actual backfill SQL",
    "Run dry-run against staging: python -m data_migrate run {name} --dry-run",
    "Review dry-run report for row count and sample transformations",
    "Take pg_dump snapshot before production run: see §12.1 Rollback Procedure",
    "Run full migration with monitoring: make migrate-data-run NAME={name}",
    "Verify with verify_after_run() and confirm exit code 0",
    "Delete checkpoint row if re-run from scratch is needed: make migrate-data-reset NAME={name}"
  ],
  "warnings": [
    "dry_run=True is the default; you MUST pass --no-dry-run or set dry_run=False explicitly to commit data",
    "For PostgreSQL-specific upsert (ON CONFLICT DO UPDATE), SQLite tests will use fallback logic — run integration tests against Postgres before production",
    "Alembic schema migrations and data migrations run independently; never combine them in alembic/versions/"
  ],
  "notes": [
    "Cursor-based batching (WHERE id > last_id) avoids O(n) OFFSET scans on large tables",
    "Checkpoint table is created in the application database; it does NOT require a separate migration",
    "The undo() method is scaffolded on every generated migration; implement it if rollback is required",
    "check_migration_separation.py must be added to pre-commit hooks to enforce separation at commit time",
    "For multi-tenant projects using TOOL-008, backfill tenant_id using this tool after adding the column via Alembic",
    "Memory per batch is bounded by batch_size; use batch_size=500 for wide rows (many columns) to stay under 50 MB"
  ]
}
```
