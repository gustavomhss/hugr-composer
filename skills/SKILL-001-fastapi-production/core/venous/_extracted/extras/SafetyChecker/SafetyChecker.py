from __future__ import annotations
from pathlib import Path
from typing import Any


class SafetyChecker:
    """Detects destructive operations in Alembic migration files.

    Args:
        versions_dir: Path to the ``alembic/versions/`` directory.
    """

    def __init__(self, versions_dir: str | Path) -> None:
        """Initialise with the alembic versions directory.

        Args:
            versions_dir: Path to Alembic versions directory.
        """
        self._versions_dir = Path(versions_dir)

    def detect_destructive(self) -> dict[str, Any]:
        """Scan all migration files for destructive operations.

        Returns:
            Dict with keys: ``destructive_found`` (bool),
            ``findings`` (list[dict]), ``files_scanned`` (int).
            Each finding dict has ``file``, ``operation``, ``line``.
        """
        findings: list[dict[str, Any]] = []
        files_scanned = 0
        if not self._versions_dir.is_dir():
            logger.warning('Versions dir not found: %s', self._versions_dir)
            return {'destructive_found': False, 'findings': [], 'files_scanned': 0}
        for migration_file in sorted(self._versions_dir.glob('*.py')):
            if migration_file.name.startswith('__'):
                continue
            findings.extend(self._scan_file(migration_file))
            files_scanned += 1
        if findings:
            logger.warning('Destructive migrations detected: %d findings in %d files', len(findings), files_scanned)
        return {'destructive_found': bool(findings), 'findings': findings, 'files_scanned': files_scanned}

    def _scan_file(self, migration_file: Path) -> list[dict[str, Any]]:
        """Scan a single migration file for destructive patterns.

        Args:
            migration_file: Path to a single ``.py`` migration file.

        Returns:
            List of finding dicts for this file (may be empty).
        """
        findings: list[dict[str, Any]] = []
        try:
            content = migration_file.read_text(encoding='utf-8')
        except OSError as exc:
            logger.warning('Could not read %s: %s', migration_file, exc)
            return findings
        for op_name, pattern in _DESTRUCTIVE_PATTERNS:
            for lineno, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    findings.append({'file': str(migration_file), 'operation': op_name, 'line': lineno, 'content': line.strip()})
        return findings
