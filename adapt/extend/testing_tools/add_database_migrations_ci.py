"""TOOL-091: add_database_migrations_ci — Alembic CI runner + rollback safety + schema diff.

Generates ``app/migrations/__init__.py``, ``app/migrations/ci_runner.py`` with
``MigrationCIRunner`` (check_pending, verify_rollback, schema_diff),
``app/migrations/safety_checker.py`` with ``SafetyChecker`` (detects destructive
operations like DROP TABLE/COLUMN and flags for review), and
``scripts/check_migrations.py`` CLI (pending check, rollback dry-run, diff report).

Config fields added to ``app/core/config.py``: MIGRATION_CI_FAIL_ON_DESTRUCTIVE,
MIGRATION_CI_REQUIRE_ROLLBACK.

No new dependencies — alembic is already required. Uses subprocess to invoke
``alembic`` CLI commands in CI pipeline.

The tool is idempotent: a second run detects ``MigrationCIRunner`` in
``app/migrations/ci_runner.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.testing_tools.add_database_migrations_ci import add_database_migrations_ci

    result = add_database_migrations_ci(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/migrations/ci_runner.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_testing_add_database_migrations_ci",
    "description": "Add Alembic CI runner with rollback safety and schema diff to FastAPI.",
    "tags": ["extend", "testing_tools"],
    "entry": "add_database_migrations_ci",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_database_migrations_ci(inp: ToolInput) -> ToolResult:
    """Add Alembic CI migrations tooling to a FastAPI project.

    Writes ``app/migrations/__init__.py``, ``app/migrations/ci_runner.py``,
    ``app/migrations/safety_checker.py``, and ``scripts/check_migrations.py``.
    Patches ``app/core/config.py`` with migration CI config fields.
    Ensures the ``alembic/versions/`` directory exists for CI runner operation.

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
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
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

    # --- Idempotency guard ---------------------------------------------------
    ci_runner_file = app_dir / "migrations" / "ci_runner.py"
    if ci_runner_file.exists() and "MigrationCIRunner" in ci_runner_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["MigrationCIRunner already present — migration CI already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would create migrations/__init__.py, ci_runner.py, "
                   "safety_checker.py, scripts/check_migrations.py, patch config.py."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: Create app/migrations/ package ------------------------------
    migrations_dir = app_dir / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    migrations_init = migrations_dir / "__init__.py"
    if not migrations_init.exists():
        _write_migrations_init(migrations_init)
        files_created.append(str(migrations_init))

    # --- Step 2: Write app/migrations/ci_runner.py ---------------------------
    _write_ci_runner(ci_runner_file)
    files_created.append(str(ci_runner_file))

    # --- Step 3: Write app/migrations/safety_checker.py ----------------------
    safety_file = migrations_dir / "safety_checker.py"
    _write_safety_checker(safety_file)
    files_created.append(str(safety_file))

    # --- Step 4: Write scripts/check_migrations.py CLI -----------------------
    scripts_dir = project / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    check_script = scripts_dir / "check_migrations.py"
    _write_check_script(check_script)
    files_created.append(str(check_script))

    # --- Step 5: Patch config.py with migration CI settings ------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- ast.parse validation loop ------------------------------------------
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
            "Migration CI tooling added: pending check, rollback safety, schema diff.",
            "MigrationCIRunner.check_pending() detects unapplied migrations.",
            "MigrationCIRunner.verify_rollback() dry-runs downgrade -1 safely.",
            "SafetyChecker.detect_destructive() flags DROP TABLE/COLUMN operations.",
            "scripts/check_migrations.py: CLI runner for CI pipelines.",
        ],
        next_steps=[
            "Add to CI pipeline: python scripts/check_migrations.py --pending",
            "Add rollback check: python scripts/check_migrations.py --rollback",
            "Add schema diff: python scripts/check_migrations.py --diff",
            "Set MIGRATION_CI_FAIL_ON_DESTRUCTIVE=true in CI environment.",
            "alembic must be installed and DATABASE_URL set before running checks.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_migrations_init(dest: Path) -> None:
    """Write ``app/migrations/__init__.py``.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Migrations package — Alembic CI runner and safety checker.\"\"\"

        from app.migrations.ci_runner import MigrationCIRunner
        from app.migrations.safety_checker import SafetyChecker

        __all__ = ["MigrationCIRunner", "SafetyChecker"]
    """))


def _write_ci_runner(dest: Path) -> None:
    """Write ``app/migrations/ci_runner.py`` with MigrationCIRunner.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Alembic CI runner — checks pending migrations, verifies rollback safety.

        Wraps ``alembic`` CLI commands via subprocess for use in CI pipelines.
        No external dependencies beyond alembic (already required).

        Usage::

            from app.migrations.ci_runner import MigrationCIRunner
            runner = MigrationCIRunner(project_dir="/path/to/project")
            result = runner.check_pending()
            if result["pending_count"] > 0:
                print(f"WARNING: {result['pending_count']} unapplied migrations")
        \"\"\"

        from __future__ import annotations

        import logging
        import subprocess
        from pathlib import Path
        from typing import Any

        logger = logging.getLogger(__name__)


        class MigrationCIRunner:
            \"\"\"Alembic CI runner for migration checks in CI pipelines.

            Args:
                project_dir: Root of the FastAPI project (contains alembic.ini).
            \"\"\"

            def __init__(self, project_dir: str | Path) -> None:
                \"\"\"Initialise with the project root containing alembic.ini.

                Args:
                    project_dir: Path to FastAPI project root.
                \"\"\"
                self._project_dir = Path(project_dir)

            def check_pending(self) -> dict[str, Any]:
                \"\"\"Check for unapplied migrations (alembic current vs heads).

                Returns:
                    Dict with keys: ``pending_count`` (int), ``current`` (str),
                    ``heads`` (list[str]), ``is_up_to_date`` (bool).
                \"\"\"
                current = self._run_alembic(["current"])
                heads = self._run_alembic(["heads"])
                current_rev = _parse_revision(current.get("stdout", ""))
                head_revs = _parse_heads(heads.get("stdout", ""))
                is_up_to_date = current_rev in head_revs if head_revs else True
                pending = 0 if is_up_to_date else len(head_revs)
                logger.info(
                    "Migration check: current=%s heads=%s pending=%d",
                    current_rev, head_revs, pending,
                )
                return {
                    "pending_count": pending,
                    "current": current_rev,
                    "heads": head_revs,
                    "is_up_to_date": is_up_to_date,
                }

            def verify_rollback(self) -> dict[str, Any]:
                \"\"\"Dry-run a downgrade by one step to verify rollback is safe.

                Does NOT apply the downgrade — runs alembic with ``--sql`` flag
                to generate SQL without executing it, then checks for errors.

                Returns:
                    Dict with keys: ``rollback_safe`` (bool), ``sql`` (str),
                    ``error`` (str | None).
                \"\"\"
                result = self._run_alembic(["downgrade", "-1", "--sql"])
                has_error = result.get("returncode", 0) != 0
                sql_output = result.get("stdout", "")
                return {
                    "rollback_safe": not has_error,
                    "sql": sql_output,
                    "error": result.get("stderr") if has_error else None,
                }

            def schema_diff(self) -> dict[str, Any]:
                \"\"\"Generate a schema diff report between current DB and models.

                Runs ``alembic check`` (available in alembic >= 1.9) to detect
                schema drift between the ORM models and the database.

                Returns:
                    Dict with keys: ``in_sync`` (bool), ``output`` (str),
                    ``error`` (str | None).
                \"\"\"
                result = self._run_alembic(["check"])
                in_sync = result.get("returncode", 0) == 0
                return {
                    "in_sync": in_sync,
                    "output": result.get("stdout", ""),
                    "error": result.get("stderr") if not in_sync else None,
                }

            def _run_alembic(self, args: list[str]) -> dict[str, Any]:
                \"\"\"Run an alembic subcommand in the project directory.

                Args:
                    args: Alembic sub-command arguments (e.g. [\"current\"]).

                Returns:
                    Dict with ``returncode``, ``stdout``, ``stderr``.
                \"\"\"
                try:
                    proc = subprocess.run(
                        ["alembic", *args],
                        cwd=str(self._project_dir),
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    return {
                        "returncode": proc.returncode,
                        "stdout": proc.stdout,
                        "stderr": proc.stderr,
                    }
                except FileNotFoundError:
                    logger.warning("alembic CLI not found — is it installed?")
                    return {"returncode": 1, "stdout": "", "stderr": "alembic not found"}
                except subprocess.TimeoutExpired:
                    logger.warning("alembic command timed out: %s", args)
                    return {"returncode": 1, "stdout": "", "stderr": "timeout"}


        def _parse_revision(output: str) -> str:
            \"\"\"Extract current revision from alembic current output.

            Args:
                output: Stdout from ``alembic current``.

            Returns:
                Revision string or empty string if not found.
            \"\"\"
            for line in output.splitlines():
                line = line.strip()
                if line and not line.startswith("INFO"):
                    return line.split()[0] if line.split() else ""
            return ""


        def _parse_heads(output: str) -> list[str]:
            \"\"\"Extract head revisions from alembic heads output.

            Args:
                output: Stdout from ``alembic heads``.

            Returns:
                List of head revision strings.
            \"\"\"
            heads = []
            for line in output.splitlines():
                line = line.strip()
                if line and not line.startswith("INFO"):
                    parts = line.split()
                    if parts:
                        heads.append(parts[0])
            return heads
    """))


def _write_safety_checker(dest: Path) -> None:
    """Write ``app/migrations/safety_checker.py`` with SafetyChecker.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Migration safety checker — detects destructive operations in Alembic files.

        Parses migration files to find operations that may cause data loss:
        DROP TABLE, DROP COLUMN, TRUNCATE. These are flagged for human review
        before CI proceeds.

        Usage::

            from app.migrations.safety_checker import SafetyChecker
            checker = SafetyChecker(versions_dir="/path/to/alembic/versions")
            report = checker.detect_destructive()
            if report["destructive_found"]:
                print("WARNING: destructive migrations found!")
                for item in report["findings"]:
                    print(item)
        \"\"\"

        from __future__ import annotations

        import logging
        import re
        from pathlib import Path
        from typing import Any

        logger = logging.getLogger(__name__)

        # Patterns that indicate destructive operations
        _DESTRUCTIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
            ("DROP TABLE", re.compile(r"drop_table|op\\.drop_table", re.IGNORECASE)),
            ("DROP COLUMN", re.compile(r"drop_column|op\\.drop_column", re.IGNORECASE)),
            ("TRUNCATE", re.compile(r"truncate|op\\.execute.*TRUNCATE", re.IGNORECASE)),
            ("DROP CONSTRAINT", re.compile(r"drop_constraint|op\\.drop_constraint", re.IGNORECASE)),
            ("DROP INDEX", re.compile(r"drop_index|op\\.drop_index", re.IGNORECASE)),
        ]


        class SafetyChecker:
            \"\"\"Detects destructive operations in Alembic migration files.

            Args:
                versions_dir: Path to the ``alembic/versions/`` directory.
            \"\"\"

            def __init__(self, versions_dir: str | Path) -> None:
                \"\"\"Initialise with the alembic versions directory.

                Args:
                    versions_dir: Path to Alembic versions directory.
                \"\"\"
                self._versions_dir = Path(versions_dir)

            def detect_destructive(self) -> dict[str, Any]:
                \"\"\"Scan all migration files for destructive operations.

                Returns:
                    Dict with keys: ``destructive_found`` (bool),
                    ``findings`` (list[dict]), ``files_scanned`` (int).
                    Each finding dict has ``file``, ``operation``, ``line``.
                \"\"\"
                findings: list[dict[str, Any]] = []
                files_scanned = 0

                if not self._versions_dir.is_dir():
                    logger.warning(
                        "Versions dir not found: %s", self._versions_dir
                    )
                    return {
                        "destructive_found": False,
                        "findings": [],
                        "files_scanned": 0,
                    }

                for migration_file in sorted(self._versions_dir.glob("*.py")):
                    if migration_file.name.startswith("__"):
                        continue
                    findings.extend(self._scan_file(migration_file))
                    files_scanned += 1

                if findings:
                    logger.warning(
                        "Destructive migrations detected: %d findings in %d files",
                        len(findings), files_scanned,
                    )
                return {
                    "destructive_found": bool(findings),
                    "findings": findings,
                    "files_scanned": files_scanned,
                }

            def _scan_file(self, migration_file: Path) -> list[dict[str, Any]]:
                \"\"\"Scan a single migration file for destructive patterns.

                Args:
                    migration_file: Path to a single ``.py`` migration file.

                Returns:
                    List of finding dicts for this file (may be empty).
                \"\"\"
                findings: list[dict[str, Any]] = []
                try:
                    content = migration_file.read_text(encoding="utf-8")
                except OSError as exc:
                    logger.warning("Could not read %s: %s", migration_file, exc)
                    return findings
                for op_name, pattern in _DESTRUCTIVE_PATTERNS:
                    for lineno, line in enumerate(content.splitlines(), start=1):
                        if pattern.search(line):
                            findings.append({
                                "file": str(migration_file),
                                "operation": op_name,
                                "line": lineno,
                                "content": line.strip(),
                            })
                return findings
    """))


def _write_check_script(dest: Path) -> None:
    """Write ``scripts/check_migrations.py`` CLI runner.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"CLI script for migration CI checks — pending, rollback, diff, safety.

        Usage::

            # Check for pending migrations
            python scripts/check_migrations.py --pending

            # Verify rollback safety (dry-run downgrade -1)
            python scripts/check_migrations.py --rollback

            # Check schema drift between models and DB
            python scripts/check_migrations.py --diff

            # Scan for destructive operations
            python scripts/check_migrations.py --safety

            # Run all checks (default)
            python scripts/check_migrations.py
        \"\"\"

        from __future__ import annotations

        import argparse
        import json
        import logging
        import sys
        from pathlib import Path

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        logger = logging.getLogger(__name__)

        _PROJECT_DIR = Path(__file__).parent.parent


        def _get_runner() -> object:
            \"\"\"Import and return a MigrationCIRunner for the project.

            Returns:
                MigrationCIRunner instance pointed at the project root.
            \"\"\"
            sys.path.insert(0, str(_PROJECT_DIR))
            from app.migrations.ci_runner import MigrationCIRunner
            return MigrationCIRunner(_PROJECT_DIR)


        def _get_checker() -> object:
            \"\"\"Import and return a SafetyChecker for the alembic versions directory.

            Returns:
                SafetyChecker instance pointed at alembic/versions/.
            \"\"\"
            sys.path.insert(0, str(_PROJECT_DIR))
            from app.migrations.safety_checker import SafetyChecker
            versions_dir = _PROJECT_DIR / "alembic" / "versions"
            return SafetyChecker(versions_dir)


        def cmd_pending(runner: object) -> int:
            \"\"\"Run the pending migrations check and exit with code 1 if any found.

            Args:
                runner: MigrationCIRunner instance.

            Returns:
                Exit code: 0 (up-to-date), 1 (pending migrations found).
            \"\"\"
            result = runner.check_pending()
            print(json.dumps(result, indent=2))
            if not result["is_up_to_date"]:
                logger.error("FAIL: %d pending migration(s)", result["pending_count"])
                return 1
            logger.info("PASS: database is up to date")
            return 0


        def cmd_rollback(runner: object) -> int:
            \"\"\"Run the rollback dry-run and exit with code 1 if unsafe.

            Args:
                runner: MigrationCIRunner instance.

            Returns:
                Exit code: 0 (rollback safe), 1 (unsafe).
            \"\"\"
            result = runner.verify_rollback()
            if not result["rollback_safe"]:
                logger.error("FAIL: rollback check failed: %s", result.get("error"))
                return 1
            logger.info("PASS: rollback dry-run succeeded")
            return 0


        def cmd_diff(runner: object) -> int:
            \"\"\"Run the schema diff check and exit with code 1 if out of sync.

            Args:
                runner: MigrationCIRunner instance.

            Returns:
                Exit code: 0 (in sync), 1 (drift detected).
            \"\"\"
            result = runner.schema_diff()
            print(result.get("output", ""))
            if not result["in_sync"]:
                logger.error("FAIL: schema drift detected: %s", result.get("error"))
                return 1
            logger.info("PASS: schema is in sync")
            return 0


        def cmd_safety(checker: object) -> int:
            \"\"\"Scan migration files for destructive operations.

            Args:
                checker: SafetyChecker instance.

            Returns:
                Exit code: 0 (no destructive ops), 1 (destructive found).
            \"\"\"
            result = checker.detect_destructive()
            print(json.dumps(result, indent=2))
            if result["destructive_found"]:
                logger.error("FAIL: destructive operations found — review before merging")
                return 1
            logger.info(
                "PASS: no destructive operations in %d migration files",
                result["files_scanned"],
            )
            return 0


        def main() -> None:
            \"\"\"Parse CLI arguments and run selected migration checks.\"\"\"
            parser = argparse.ArgumentParser(
                description="Migration CI checks: pending, rollback, diff, safety"
            )
            parser.add_argument("--pending", action="store_true",
                                help="Check for unapplied migrations")
            parser.add_argument("--rollback", action="store_true",
                                help="Verify rollback safety (dry-run)")
            parser.add_argument("--diff", action="store_true",
                                help="Detect schema drift")
            parser.add_argument("--safety", action="store_true",
                                help="Scan for destructive operations")
            args = parser.parse_args()

            run_all = not (args.pending or args.rollback or args.diff or args.safety)
            runner = _get_runner()
            checker = _get_checker()
            exit_code = 0

            if args.pending or run_all:
                exit_code |= cmd_pending(runner)
            if args.rollback or run_all:
                exit_code |= cmd_rollback(runner)
            if args.diff or run_all:
                exit_code |= cmd_diff(runner)
            if args.safety or run_all:
                exit_code |= cmd_safety(checker)

            sys.exit(exit_code)


        if __name__ == "__main__":
            main()
    """))


def _patch_config(config_file: Path) -> None:
    """Inject migration CI config fields into ``app/core/config.py`` Settings body.

    Fields are inserted with 4-space indent so they sit inside ``class Settings``.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("MIGRATION_CI_FAIL_ON_DESTRUCTIVE", "MIGRATION_CI_FAIL_ON_DESTRUCTIVE: bool = True"),
            ("MIGRATION_CI_REQUIRE_ROLLBACK", "MIGRATION_CI_REQUIRE_ROLLBACK: bool = True"),
        ],
    )


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
