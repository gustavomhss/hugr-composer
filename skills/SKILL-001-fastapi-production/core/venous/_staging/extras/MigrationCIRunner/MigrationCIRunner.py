from __future__ import annotations
from pathlib import Path
from typing import Any


class MigrationCIRunner:
    """Alembic CI runner for migration checks in CI pipelines.

    Args:
        project_dir: Root of the FastAPI project (contains alembic.ini).
    """

    def __init__(self, project_dir: str | Path) -> None:
        """Initialise with the project root containing alembic.ini.

        Args:
            project_dir: Path to FastAPI project root.
        """
        self._project_dir = Path(project_dir)

    def check_pending(self) -> dict[str, Any]:
        """Check for unapplied migrations (alembic current vs heads).

        Returns:
            Dict with keys: ``pending_count`` (int), ``current`` (str),
            ``heads`` (list[str]), ``is_up_to_date`` (bool).
        """
        current = self._run_alembic(['current'])
        heads = self._run_alembic(['heads'])
        current_rev = _parse_revision(current.get('stdout', ''))
        head_revs = _parse_heads(heads.get('stdout', ''))
        is_up_to_date = current_rev in head_revs if head_revs else True
        pending = 0 if is_up_to_date else len(head_revs)
        logger.info('Migration check: current=%s heads=%s pending=%d', current_rev, head_revs, pending)
        return {'pending_count': pending, 'current': current_rev, 'heads': head_revs, 'is_up_to_date': is_up_to_date}

    def verify_rollback(self) -> dict[str, Any]:
        """Dry-run a downgrade by one step to verify rollback is safe.

        Does NOT apply the downgrade — runs alembic with ``--sql`` flag
        to generate SQL without executing it, then checks for errors.

        Returns:
            Dict with keys: ``rollback_safe`` (bool), ``sql`` (str),
            ``error`` (str | None).
        """
        result = self._run_alembic(['downgrade', '-1', '--sql'])
        has_error = result.get('returncode', 0) != 0
        sql_output = result.get('stdout', '')
        return {'rollback_safe': not has_error, 'sql': sql_output, 'error': result.get('stderr') if has_error else None}

    def schema_diff(self) -> dict[str, Any]:
        """Generate a schema diff report between current DB and models.

        Runs ``alembic check`` (available in alembic >= 1.9) to detect
        schema drift between the ORM models and the database.

        Returns:
            Dict with keys: ``in_sync`` (bool), ``output`` (str),
            ``error`` (str | None).
        """
        result = self._run_alembic(['check'])
        in_sync = result.get('returncode', 0) == 0
        return {'in_sync': in_sync, 'output': result.get('stdout', ''), 'error': result.get('stderr') if not in_sync else None}

    def _run_alembic(self, args: list[str]) -> dict[str, Any]:
        """Run an alembic subcommand in the project directory.

        Args:
            args: Alembic sub-command arguments (e.g. ["current"]).

        Returns:
            Dict with ``returncode``, ``stdout``, ``stderr``.
        """
        try:
            proc = subprocess.run(['alembic', *args], cwd=str(self._project_dir), capture_output=True, text=True, timeout=60)
            return {'returncode': proc.returncode, 'stdout': proc.stdout, 'stderr': proc.stderr}
        except FileNotFoundError:
            logger.warning('alembic CLI not found — is it installed?')
            return {'returncode': 1, 'stdout': '', 'stderr': 'alembic not found'}
        except subprocess.TimeoutExpired:
            logger.warning('alembic command timed out: %s', args)
            return {'returncode': 1, 'stdout': '', 'stderr': 'timeout'}
