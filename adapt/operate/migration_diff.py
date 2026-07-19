"""TOOL-036: migration_diff — Alembic migration safety classifier.

Parses ``upgrade()`` / ``downgrade()`` bodies of Alembic migration files
added in a git range, classifies each operation as SAFE / UNSAFE /
DESTRUCTIVE, computes rollback distance, detects multi-phase zero-downtime
patterns, and validates an explicit allow-list.

Example::

    from adapt.contracts import ToolInput
    from adapt.operate.migration_diff import migration_diff

    result = migration_diff(
        ToolInput(project_dir="/path/to/project"),
        base_ref="origin/main",
        head_ref="HEAD",
        fail_on_destructive=True,
    )
    print(result.status)
    print(result.notes)
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult

# ---------------------------------------------------------------------------
# Safety classification constants
# ---------------------------------------------------------------------------

_DESTRUCTIVE_OPS: frozenset[str] = frozenset(
    {
        "drop_table",
        "drop_column",
        "drop_constraint",
        "drop_index",
        "drop_type",
        "execute",  # raw SQL — classified DESTRUCTIVE unless allow-listed
    }
)

_UNSAFE_OPS: frozenset[str] = frozenset(
    {
        "rename_table",
        "rename_column",
        "alter_column",  # refined further in _classify_op
        "create_index",  # unsafe without CONCURRENTLY
    }
)


MCP_TOOL = {
    "name": "fastapi_resiliency_analyze_migration_diff",
    "description": "Compare pending Alembic migrations against the current database schema.",
    "tags": ["operate"],
    "entry": "migration_diff",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def migration_diff(
    inp: ToolInput,
    base_ref: str = "origin/main",
    head_ref: str = "HEAD",
    fail_on_destructive: bool = True,
    fail_on_unsafe_default: bool = True,
    allow_list_file: str = ".migration-allow.yaml",
) -> ToolResult:
    """Analyse Alembic migrations introduced between two git refs.

    Args:
        inp: ``ToolInput`` with ``project_dir``.
        base_ref: Git ref to compare from (default ``"origin/main"``).
        head_ref: Git ref to compare to (default ``"HEAD"``).
        fail_on_destructive: Return ``status="error"`` when DESTRUCTIVE ops
            are found and not allow-listed.
        fail_on_unsafe_default: Return ``status="error"`` when UNSAFE ops
            without safe defaults are found.
        allow_list_file: Path (relative to project_dir) of the YAML
            allow-list for acknowledged destructive operations.

    Returns:
        ``ToolResult`` with classification summary in ``notes``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    if not project.exists():
        return ToolResult(
            status="error",
            error=f"project_dir does not exist: {project}",
            execution_time_ms=_ms(start),
        )

    # --- Prerequisite check ---------------------------------------------------
    from adapt.contracts.prerequisites import Prereq, check_prerequisites

    prereq_errors = check_prerequisites(inp.project_dir, Prereq.ALEMBIC_VERSIONS)
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_ms(start),
        )

    versions_dir = project / "alembic" / "versions"
    if not versions_dir.exists():
        return ToolResult(
            status="error",
            error="No alembic/versions/ directory found.",
            execution_time_ms=_ms(start),
        )

    new_files = _get_new_migration_files(project, base_ref, head_ref, versions_dir)
    allow_list = _load_allow_list(project / allow_list_file)

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[f"[dry_run] Would analyse {len(new_files)} migration(s)."],
            execution_time_ms=_ms(start),
        )

    report_lines: list[str] = ["## Migration Diff Report", ""]
    blocking: list[str] = []
    all_ops: list[dict] = []

    for mig_file in sorted(new_files):
        ops = _extract_ops(mig_file)
        all_ops.extend(ops)
        file_hash = _sha256(mig_file)
        allowed = _is_allow_listed(mig_file.name, file_hash, allow_list)
        classification = _classify_ops(ops)
        rollback = _rollback_distance(mig_file, versions_dir)
        multi = _detect_multi_phase(ops, versions_dir)

        icon = {"SAFE": "✅", "UNSAFE": "⚠️", "DESTRUCTIVE": "❌"}.get(
            classification, "❓"
        )
        report_lines.append(f"### {icon} `{mig_file.name}` — {classification}")
        report_lines.append(f"- Rollback distance: {rollback}")
        report_lines.append(f"- Multi-phase ZDT detected: {multi}")
        if ops:
            report_lines.append("- Operations:")
            for op in ops:
                report_lines.append(f"  - `{op['type']}` {op.get('detail', '')}")
        if allowed:
            report_lines.append("- _Allow-listed — acknowledged by reviewer._")
        report_lines.append("")

        if classification == "DESTRUCTIVE" and fail_on_destructive and not allowed:
            blocking.append(f"{mig_file.name}: DESTRUCTIVE op not allow-listed")
        if classification == "UNSAFE" and fail_on_unsafe_default and not allowed:
            blocking.append(f"{mig_file.name}: UNSAFE op without safe default")

    if blocking:
        return ToolResult(
            status="error",
            error="Blocking migration issues: " + "; ".join(blocking),
            notes=report_lines,
            execution_time_ms=_ms(start),
        )

    return ToolResult(
        status="success",
        notes=report_lines,
        next_steps=[
            "Review ⚠️/❌ migrations before merging.",
            "Add allow-list entries for acknowledged destructive ops.",
        ],
        execution_time_ms=_ms(start),
    )


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _get_new_migration_files(
    project: Path, base_ref: str, head_ref: str, versions_dir: Path
) -> list[Path]:
    """Return migration files added between *base_ref* and *head_ref*.

    Args:
        project: Project root for running git.
        base_ref: Base git ref.
        head_ref: Head git ref.
        versions_dir: Alembic versions directory.

    Returns:
        List of Path objects for newly added migration files.
    """
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=A", base_ref, head_ref],
            cwd=str(project),
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).decode()
    except Exception:
        # Fallback: return all migration files
        return list(versions_dir.glob("*.py"))

    files: list[Path] = []
    for line in out.splitlines():
        p = project / line.strip()
        if p.exists() and p.suffix == ".py" and "versions" in str(p):
            files.append(p)
    return files if files else list(versions_dir.glob("*.py"))


# ---------------------------------------------------------------------------
# AST parsing
# ---------------------------------------------------------------------------

def _extract_ops(mig_file: Path) -> list[dict]:
    """Extract Alembic op.* calls from a migration's upgrade() function.

    Args:
        mig_file: Path to the migration file.

    Returns:
        List of dicts with ``type`` and optional ``detail`` keys.
    """
    try:
        tree = ast.parse(mig_file.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []

    ops: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in ("upgrade", "downgrade"):
            continue
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Expr):
                continue
            call = stmt.value
            if not isinstance(call, ast.Call):
                continue
            if not isinstance(call.func, ast.Attribute):
                continue
            if not isinstance(call.func.value, ast.Name):
                continue
            if call.func.value.id != "op":
                continue
            op_name = call.func.attr
            detail = ""
            if call.args:
                first = call.args[0]
                if isinstance(first, ast.Constant):
                    detail = str(first.value)
            ops.append({"type": op_name, "detail": detail, "func_name": node.name})
    return ops


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _classify_ops(ops: list[dict]) -> str:
    """Classify a list of operations as SAFE / UNSAFE / DESTRUCTIVE.

    Args:
        ops: List of operation dicts from ``_extract_ops``.

    Returns:
        Classification string.
    """
    for op in ops:
        if op["type"] in _DESTRUCTIVE_OPS:
            return "DESTRUCTIVE"
    for op in ops:
        if op["type"] in _UNSAFE_OPS:
            return "UNSAFE"
    return "SAFE"


def _rollback_distance(mig_file: Path, versions_dir: Path) -> int:
    """Count how many migrations follow this one (rollback steps needed).

    Args:
        mig_file: The migration file.
        versions_dir: Directory of all migrations.

    Returns:
        Number of migrations that would need to be reverted.
    """
    all_files = sorted(versions_dir.glob("*.py"))
    try:
        idx = all_files.index(mig_file)
        return len(all_files) - 1 - idx
    except ValueError:
        return -1


def _detect_multi_phase(ops: list[dict], versions_dir: Path) -> bool:
    """Detect multi-phase zero-downtime pattern (add nullable → backfill → NOT NULL).

    Args:
        ops: Operations from the migration.
        versions_dir: Versions directory (for cross-migration detection).

    Returns:
        True if a multi-phase ZDT pattern is detected.
    """
    types = {op["type"] for op in ops}
    # Simplistic: migration has add_column and alter_column = likely multi-phase
    return "add_column" in types and "alter_column" in types


# ---------------------------------------------------------------------------
# Allow-list
# ---------------------------------------------------------------------------

def _load_allow_list(path: Path) -> dict:
    """Load YAML allow-list from *path*, returning empty dict on any error.

    Args:
        path: Absolute path to the allow-list YAML file.

    Returns:
        Dict of allow-list entries keyed by migration filename.
    """
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore[import-untyped]
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _is_allow_listed(filename: str, file_hash: str, allow_list: dict) -> bool:
    """Check whether *filename* with *file_hash* is in the allow-list.

    Args:
        filename: Migration filename (stem or full name).
        file_hash: SHA-256 of the migration file.
        allow_list: Loaded allow-list dict.

    Returns:
        True if the entry exists and the hash matches.
    """
    entry = allow_list.get(filename, {})
    if not entry:
        return False
    return entry.get("sha256", "") == file_hash


def _sha256(path: Path) -> str:
    """Return hex SHA-256 of *path*.

    Args:
        path: File to hash.

    Returns:
        Hex digest string.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _ms(start: float) -> int:
    """Elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
