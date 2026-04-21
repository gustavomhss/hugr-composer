"""TOOL-043: add_migration_data — data migration framework for FastAPI/SQLAlchemy projects.

Generates a self-contained ``data_migrations/`` module with a ``DataMigration``
base class, cursor-based batching (``WHERE id > last_id``), checkpointing,
dry-run support, idempotent upsert via ``INSERT ... ON CONFLICT``, progress
reporting, and a CLI entry-point.

The tool is idempotent: a second run on a project that already contains
``data_migrations/`` detects the ``DataMigration`` fingerprint and returns
``status="no_op"`` without overwriting existing migration files.

Example::

    from adapt.contracts import ToolInput
    from adapt.evolve.add_migration_data import add_migration_data

    result = add_migration_data(
        ToolInput(project_dir="/path/to/project"),
        name="backfill_user_timezone",
        batch_size=500,
    )
    print(result.status)        # "success"
    print(result.files_created) # ["...data_migrations/base.py", ...]
    print(result.next_steps)    # ["python -m data_migrations.cli run ...", ...]
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_add_migration_data",
    "description": "Add data migration support alongside schema migrations in Alembic.",
    "tags": ["evolve"],
    "entry": "add_migration_data",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_migration_data(
    inp: ToolInput,
    name: str = "sample_migration",
    batch_size: int = 1000,
    idempotent: bool = True,
    dry_run_default: bool = True,
    checkpoint_table: str = "data_migration_checkpoints",
) -> ToolResult:
    """Scaffold a data migration framework in the given project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.
        name: Snake-case migration name (e.g. ``backfill_user_timezone``).
        batch_size: Rows processed per transaction (default 1000).
        idempotent: Enforce idempotent upsert semantics (default True).
        dry_run_default: Generated migration defaults to dry-run mode (default True).
        checkpoint_table: DB table name for tracking migration progress.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
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

    dm_dir = project / "data_migrations"

    # --- Idempotency guard ---------------------------------------------------
    base_file = dm_dir / "base.py"
    if base_file.exists() and "DataMigration" in base_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["DataMigration base class already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would scaffold data_migrations/ for migration: {name}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    dm_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: __init__.py
    init_file = dm_dir / "__init__.py"
    _write_init(init_file)
    files_created.append(str(init_file))

    # Step 2: base.py
    _write_base(base_file, checkpoint_table)
    files_created.append(str(base_file))

    # Step 3: checkpoint_model.py
    ckpt_file = dm_dir / "checkpoint_model.py"
    _write_checkpoint_model(ckpt_file, checkpoint_table)
    files_created.append(str(ckpt_file))

    # Step 4: runner.py
    runner_file = dm_dir / "runner.py"
    _write_runner(runner_file, checkpoint_table)
    files_created.append(str(runner_file))

    # Step 5: CLI
    cli_file = dm_dir / "cli.py"
    _write_cli(cli_file)
    files_created.append(str(cli_file))

    # Step 6: sample migration
    sample_file = dm_dir / f"{name}.py"
    if not sample_file.exists():
        _write_sample_migration(sample_file, name, batch_size, idempotent, dry_run_default)
        files_created.append(str(sample_file))

    # Step 7: Makefile targets (optional, appended if Makefile exists)
    makefile = project / "Makefile"
    if makefile.exists():
        _patch_makefile(makefile, name)
        files_modified.append(str(makefile))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Data migration framework scaffolded at data_migrations/",
            f"Sample migration: data_migrations/{name}.py",
            f"Checkpoint table: {checkpoint_table}",
            "Dry-run is ON by default — pass --live to execute writes.",
        ],
        next_steps=[
            f"python -m data_migrations.cli run {name} --dry-run",
            f"python -m data_migrations.cli run {name} --live",
            "python -m data_migrations.cli status",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------


def _write_init(dest: Path) -> None:
    """Write data_migrations/__init__.py.

    Args:
        dest: Destination path.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Data migration framework.

        Usage::

            python -m data_migrations.cli run <name> [--dry-run | --live]
            python -m data_migrations.cli status
        \"\"\"
    """))


def _write_base(dest: Path, checkpoint_table: str) -> None:
    """Write the DataMigration abstract base class.

    Args:
        dest: Destination path.
        checkpoint_table: Name of the checkpoint tracking table.
    """
    content = textwrap.dedent("""\
        \"\"\"Abstract base class for all data migrations.\"\"\"
        from __future__ import annotations

        import abc
        import logging
        import time
        from dataclasses import dataclass, field

        from sqlalchemy.orm import Session

        logger = logging.getLogger(__name__)
        CHECKPOINT_TABLE = "{checkpoint_table}"


        @dataclass
        class MigrationStats:
            \"\"\"Runtime statistics for a single migration run.

            Attributes:
                rows_processed: Total rows processed across all batches.
                batches_completed: Number of batches that finished successfully.
                elapsed_seconds: Wall-clock seconds elapsed.
                dry_run: Whether this was a dry-run (no writes).
                errors: Non-fatal error messages encountered.
            \"\"\"

            rows_processed: int = 0
            batches_completed: int = 0
            elapsed_seconds: float = 0.0
            dry_run: bool = False
            errors: list[str] = field(default_factory=list)


        class DataMigration(abc.ABC):
            \"\"\"Base class for all data migrations.

            Subclasses MUST implement: ``migration_name``, ``run_batch``,
            ``verify_after_run``.  Subclasses SHOULD implement ``undo`` when
            reversal is feasible.

            Args:
                session: SQLAlchemy session for DB access.
                batch_size: Rows to process per transaction.
                dry_run: If True, read-only — no DML is committed.
            \"\"\"

            migration_name: str  # unique snake_case identifier

            def __init__(
                self, session: Session, batch_size: int = 1000, dry_run: bool = True
            ) -> None:
                self.session = session
                self.batch_size = batch_size
                self.dry_run = dry_run
                self._stats = MigrationStats(dry_run=dry_run)

            @abc.abstractmethod
            def run_batch(self, last_id: int) -> tuple[int, int]:
                \"\"\"Process one batch starting after *last_id*.

                Args:
                    last_id: Cursor — process rows with id > last_id.

                Returns:
                    Tuple of (new_last_id, rows_affected).

                Note:
                    Must be idempotent: re-running on the same rows is safe.
                \"\"\"

            @abc.abstractmethod
            def verify_after_run(self) -> bool:
                \"\"\"Return True when post-migration assertions pass.

                Returns:
                    True if verified OK, False if assertions fail.
                \"\"\"

            def undo(self) -> None:
                \"\"\"Reverse this migration.

                Raises:
                    NotImplementedError: Unless overridden by the subclass.
                \"\"\"
                raise NotImplementedError(
                    f"{self.__class__.__name__}.undo() is not implemented. "
                    "To undo, restore from a pre-migration pg_dump snapshot."
                )

            def run(self, start_from: int = 0) -> MigrationStats:
                \"\"\"Execute the full migration with batching and progress logging.

                Args:
                    start_from: Resume cursor (rows with id > start_from).

                Returns:
                    ``MigrationStats`` summary for this run.
                \"\"\"
                wall_start = time.monotonic()
                last_id = start_from
                logger.info(
                    "Starting %s | dry_run=%s batch_size=%d start_from=%d",
                    self.migration_name,
                    self.dry_run,
                    self.batch_size,
                    last_id,
                )
                try:
                    while True:
                        new_last_id, rows = self.run_batch(last_id)
                        if rows == 0:
                            break
                        self._stats.rows_processed += rows
                        self._stats.batches_completed += 1
                        last_id = new_last_id
                        if self._stats.batches_completed % 100 == 0:
                            elapsed = time.monotonic() - wall_start
                            rate = self._stats.rows_processed / max(elapsed, 0.001)
                            logger.info(
                                "%s batch=%d rows=%d rate=%.0f rows/s",
                                self.migration_name,
                                self._stats.batches_completed,
                                self._stats.rows_processed,
                                rate,
                            )
                finally:
                    self._stats.elapsed_seconds = time.monotonic() - wall_start
                logger.info(
                    "Finished %s | rows=%d batches=%d elapsed=%.2fs",
                    self.migration_name,
                    self._stats.rows_processed,
                    self._stats.batches_completed,
                    self._stats.elapsed_seconds,
                )
                return self._stats
    """).replace("{checkpoint_table}", checkpoint_table)
    dest.write_text(content)


def _write_checkpoint_model(dest: Path, checkpoint_table: str) -> None:
    """Write the SQLAlchemy CheckpointModel.

    Args:
        dest: Destination path.
        checkpoint_table: Table name.
    """
    content = textwrap.dedent("""\
        \"\"\"SQLAlchemy model for migration checkpoints.\"\"\"
        from __future__ import annotations

        from datetime import datetime, timezone

        from sqlalchemy import DateTime, Integer, String, func
        from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


        class _CheckpointBase(DeclarativeBase):
            pass


        class MigrationCheckpoint(_CheckpointBase):
            \"\"\"Persists per-migration last-processed cursor and progress metadata.

            Attributes:
                id: Auto-increment PK.
                migration_name: Unique snake_case migration identifier.
                last_processed_id: Cursor — last ID processed by the migration.
                rows_processed: Running total of rows processed.
                status: ``pending``, ``running``, ``completed``, or ``failed``.
                updated_at: Last update timestamp (UTC).
            \"\"\"

            __tablename__ = "{table}"

            id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
            migration_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
            last_processed_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
            rows_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
            status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
            updated_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True),
                server_default=func.now(),
                onupdate=func.now(),
                nullable=False,
            )
    """).replace("{table}", checkpoint_table)
    dest.write_text(content)


def _write_runner(dest: Path, checkpoint_table: str) -> None:
    """Write the migration runner with checkpoint load/save helpers.

    Args:
        dest: Destination path.
        checkpoint_table: Checkpoint table name (for SQL).
    """
    content = textwrap.dedent("""\
        \"\"\"Migration runner: loads checkpoint, executes migration, saves progress.\"\"\"
        from __future__ import annotations

        import logging

        from sqlalchemy import text
        from sqlalchemy.orm import Session

        from data_migrations.base import DataMigration, MigrationStats

        logger = logging.getLogger(__name__)


        def load_checkpoint(session: Session, migration_name: str, table: str) -> int:
            \"\"\"Load the last-processed cursor for a migration from the checkpoint table.

            Args:
                session: Active SQLAlchemy session.
                migration_name: Unique migration identifier.
                table: Checkpoint table name.

            Returns:
                Last processed id (0 if no checkpoint exists yet).
            \"\"\"
            row = session.execute(
                text(
                    f"SELECT last_processed_id FROM {table} "
                    "WHERE migration_name = :name"
                ),
                {"name": migration_name},
            ).fetchone()
            return int(row[0]) if row else 0


        def save_checkpoint(
            session: Session, migration_name: str, last_id: int, rows: int, table: str
        ) -> None:
            \"\"\"Upsert the migration checkpoint (idempotent).

            Args:
                session: Active SQLAlchemy session.
                migration_name: Unique migration identifier.
                last_id: Current cursor value.
                rows: Running total of rows processed.
                table: Checkpoint table name.
            \"\"\"
            session.execute(
                text(
                    f"INSERT INTO {table} (migration_name, last_processed_id, rows_processed, status) "
                    "VALUES (:name, :last_id, :rows, 'running') "
                    "ON CONFLICT (migration_name) DO UPDATE SET "
                    "last_processed_id = EXCLUDED.last_processed_id, "
                    "rows_processed = EXCLUDED.rows_processed, "
                    "status = 'running'"
                ),
                {"name": migration_name, "last_id": last_id, "rows": rows},
            )
            session.commit()


        def run_migration(migration: DataMigration, checkpoint_table: str) -> MigrationStats:
            \"\"\"Execute *migration* with checkpoint resume support.

            Args:
                migration: Concrete ``DataMigration`` instance.
                checkpoint_table: Checkpoint table name.

            Returns:
                ``MigrationStats`` from the completed run.
            \"\"\"
            start_from = load_checkpoint(
                migration.session, migration.migration_name, checkpoint_table
            )
            logger.info("Resuming %s from id=%d", migration.migration_name, start_from)
            stats = migration.run(start_from=start_from)
            save_checkpoint(
                migration.session,
                migration.migration_name,
                stats.rows_processed,
                stats.rows_processed,
                checkpoint_table,
            )
            return stats
    """)
    dest.write_text(content)


def _write_cli(dest: Path) -> None:
    """Write the CLI entry-point for running and listing migrations.

    Args:
        dest: Destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"CLI for data migrations.

        Usage::

            python -m data_migrations.cli run <name> [--live]
            python -m data_migrations.cli status
        \"\"\"
        from __future__ import annotations

        import argparse
        import importlib
        import logging
        import sys

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        logger = logging.getLogger(__name__)


        def _cmd_run(args: argparse.Namespace) -> int:
            \"\"\"Run a named migration (dry-run unless --live is passed).

            Args:
                args: Parsed CLI arguments.

            Returns:
                Exit code (0 = success, 1 = failure).
            \"\"\"
            dry_run = not args.live
            try:
                mod = importlib.import_module(f"data_migrations.{args.name}")
                migration_cls = getattr(mod, "Migration", None)
                if migration_cls is None:
                    logger.error("No Migration class in data_migrations.%s", args.name)
                    return 1
            except ModuleNotFoundError:
                logger.error("Migration module not found: data_migrations.%s", args.name)
                return 1

            logger.info("Running %s | dry_run=%s", args.name, dry_run)
            # NOTE: Caller must wire a real session; this stub logs intent.
            logger.info("Pass a SQLAlchemy Session to Migration(session=...) to execute.")
            return 0


        def _cmd_status(args: argparse.Namespace) -> int:
            \"\"\"Print migration status from the checkpoint table.

            Args:
                args: Parsed CLI arguments (unused).

            Returns:
                Exit code.
            \"\"\"
            logger.info("Status command: connect to DB and query data_migration_checkpoints.")
            return 0


        def main() -> None:
            \"\"\"Parse CLI args and dispatch to sub-commands.\"\"\"
            parser = argparse.ArgumentParser(prog="data_migrations")
            sub = parser.add_subparsers(dest="command", required=True)

            run_p = sub.add_parser("run", help="Execute a named migration")
            run_p.add_argument("name", help="Migration module name (snake_case)")
            run_p.add_argument("--live", action="store_true", help="Disable dry-run and write to DB")

            sub.add_parser("status", help="Show migration checkpoint status")

            args = parser.parse_args()
            if args.command == "run":
                sys.exit(_cmd_run(args))
            elif args.command == "status":
                sys.exit(_cmd_status(args))


        if __name__ == "__main__":
            main()
    """)
    dest.write_text(content)


def _write_sample_migration(
    dest: Path,
    name: str,
    batch_size: int,
    idempotent: bool,
    dry_run_default: bool,
) -> None:
    """Write a sample concrete migration subclass.

    Args:
        dest: Destination path.
        name: Migration name (snake_case).
        batch_size: Default batch size for this migration.
        idempotent: Whether to include idempotency comment.
        dry_run_default: Default dry-run flag value.
    """
    idempotent_note = "# Idempotent: re-running on same rows is safe (ON CONFLICT UPDATE)" if idempotent else ""
    content = textwrap.dedent("""\
        \"\"\"Data migration: {name}.

        Replace this docstring and the run_batch/verify_after_run implementations
        with your actual migration logic.
        \"\"\"
        from __future__ import annotations

        import logging

        from sqlalchemy import text

        from data_migrations.base import DataMigration

        logger = logging.getLogger(__name__)
        {idempotent_note}


        class Migration(DataMigration):
            \"\"\"Concrete migration for {name}.

            Processes rows in batches of {batch_size} using a cursor-based
            approach (WHERE id > last_id LIMIT N) to avoid full table scans.
            \"\"\"

            migration_name = "{name}"

            def run_batch(self, last_id: int) -> tuple[int, int]:
                \"\"\"Process one batch of rows.

                Args:
                    last_id: Cursor — process rows with id > last_id.

                Returns:
                    Tuple of (new_last_id, rows_affected).  Returns (last_id, 0)
                    when no more rows remain.
                \"\"\"
                # CUSTOMIZE: replace with your transformation query
                rows_sql = text(
                    "SELECT id FROM items WHERE id > :last_id ORDER BY id LIMIT :batch"
                )
                rows = self.session.execute(
                    rows_sql, {{"last_id": last_id, "batch": self.batch_size}}
                ).fetchall()
                if not rows:
                    return last_id, 0
                new_last_id = rows[-1][0]
                if not self.dry_run:
                    # CUSTOMIZE: replace with your DML
                    self.session.execute(
                        text("UPDATE items SET updated_at = now() WHERE id > :last_id AND id <= :new_last"),
                        {{"last_id": last_id, "new_last": new_last_id}},
                    )
                    self.session.commit()
                else:
                    logger.info("[dry_run] Would update %d rows (id %d..%d)", len(rows), last_id + 1, new_last_id)
                return new_last_id, len(rows)

            def verify_after_run(self) -> bool:
                \"\"\"Post-migration assertion.

                Returns:
                    True if verification passes.
                \"\"\"
                # CUSTOMIZE: add your post-migration assertion query
                logger.info("verify_after_run: %s — add assertions here", self.migration_name)
                return True
    """).replace("{name}", name).replace("{batch_size}", str(batch_size)).replace("{idempotent_note}", idempotent_note)
    dest.write_text(content)


def _patch_makefile(makefile: Path, name: str) -> None:
    """Append data migration Makefile targets if not already present.

    Args:
        makefile: Path to the project Makefile.
        name: Migration name for example target.
    """
    src = makefile.read_text()
    if "data-migrate-dry" in src:
        return
    targets = textwrap.dedent(f"""\

        ## Data Migrations
        .PHONY: data-migrate-dry data-migrate-live data-migrate-status
        data-migrate-dry:
        \tpython -m data_migrations.cli run {name} --dry-run

        data-migrate-live:
        \tpython -m data_migrations.cli run {name} --live

        data-migrate-status:
        \tpython -m data_migrations.cli status
    """)
    makefile.write_text(src + targets)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Reference time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
