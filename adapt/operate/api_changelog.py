"""TOOL-038: api_changelog — OpenAPI diff changelog generator.

Diffs two OpenAPI JSON snapshots (from git refs or files on disk),
classifies changes as BREAKING / ADDED / CHANGED / REMOVED / DEPRECATED,
groups them by tag, suggests a semver bump, and writes a Keep a Changelog
formatted CHANGELOG.md section.

Example::

    from adapt.contracts import ToolInput
    from adapt.operate.api_changelog import api_changelog

    result = api_changelog(
        ToolInput(project_dir="/path/to/project"),
        from_ref="v1.0.0",
        to_ref="HEAD",
    )
    print(result.status)
    print(result.files_modified)
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from adapt.contracts import ToolInput, ToolResult


# ---------------------------------------------------------------------------
# Change categories
# ---------------------------------------------------------------------------

_BREAKING = "BREAKING"
_ADDED = "ADDED"
_CHANGED = "CHANGED"
_REMOVED = "REMOVED"
_DEPRECATED = "DEPRECATED"


MCP_TOOL = {
    "name": "fastapi_api_changelog",
    "description": "Generate a human-readable API changelog by diffing OpenAPI specs across git history.",
    "tags": ["operate"],
    "entry": "api_changelog",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def api_changelog(
    inp: ToolInput,
    from_ref: str = "v1.0.0",
    to_ref: str = "HEAD",
    output_file: str = "CHANGELOG.md",
    fmt: str = "keepachangelog",
    include_breaking_prefix: bool = True,
) -> ToolResult:
    """Generate an API changelog from two OpenAPI snapshots.

    Loads ``openapi.json`` from both git refs (or falls back to local files),
    diffs them structurally, classifies each change, and writes a Keep a
    Changelog section to *output_file*.

    Args:
        inp: ``ToolInput`` with ``project_dir``.
        from_ref: Git ref for the baseline snapshot.
        to_ref: Git ref for the current snapshot.
        output_file: Path relative to project_dir where the changelog is
            written (default ``"CHANGELOG.md"``).
        fmt: Report format — ``"keepachangelog"`` or ``"plain"``.
        include_breaking_prefix: Prepend ``BREAKING:`` to breaking entries.

    Returns:
        ``ToolResult`` with ``files_modified`` listing the changelog file.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    if not project.exists():
        return ToolResult(
            status="error",
            error=f"project_dir does not exist: {project}",
            execution_time_ms=_ms(start),
        )

    old_spec = _load_spec(project, from_ref)
    new_spec = _load_spec(project, to_ref)

    if old_spec is None:
        return ToolResult(
            status="error",
            error=f"Cannot load OpenAPI spec for ref '{from_ref}'.",
            execution_time_ms=_ms(start),
        )
    if new_spec is None:
        return ToolResult(
            status="error",
            error=f"Cannot load OpenAPI spec for ref '{to_ref}'.",
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would diff and write changelog. No files written."],
            execution_time_ms=_ms(start),
        )

    changes = _diff_specs(old_spec, new_spec)
    semver = _suggest_semver(changes)
    section = _render_section(changes, from_ref, to_ref, semver, fmt, include_breaking_prefix)

    changelog_path = project / output_file
    _prepend_section(changelog_path, section)

    return ToolResult(
        status="success",
        files_modified=[str(changelog_path)],
        notes=[
            f"Semver suggestion: {semver}",
            f"Changes: BREAKING={sum(1 for c in changes if c['category'] == _BREAKING)}, "
            f"ADDED={sum(1 for c in changes if c['category'] == _ADDED)}, "
            f"CHANGED={sum(1 for c in changes if c['category'] == _CHANGED)}, "
            f"REMOVED={sum(1 for c in changes if c['category'] == _REMOVED)}",
        ],
        next_steps=[
            f"Review {output_file} before tagging the release.",
            f"Bump version to next {semver} version.",
        ],
        execution_time_ms=_ms(start),
    )


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------

def _load_spec(project: Path, ref: str) -> dict | None:
    """Load openapi.json from a git ref or local file.

    Args:
        project: Project root.
        ref: Git ref (``HEAD``, ``v1.0.0``, etc.) or ``"local"`` for disk.

    Returns:
        Parsed OpenAPI dict, or ``None`` on failure.
    """
    # Try git show first
    try:
        raw = subprocess.check_output(
            ["git", "show", f"{ref}:openapi.json"],
            cwd=str(project),
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).decode()
        return json.loads(raw)
    except Exception:
        pass

    # Fallback: local file for HEAD/local
    local = project / "openapi.json"
    if ref in ("HEAD", "local") and local.exists():
        try:
            return json.loads(local.read_text())
        except Exception:
            pass

    # Fallback: .openapi/ directory
    snapshots = sorted((project / ".openapi").glob("*.json")) if (project / ".openapi").exists() else []
    if snapshots:
        try:
            return json.loads(snapshots[-1].read_text())
        except Exception:
            pass

    return None


# ---------------------------------------------------------------------------
# Diff engine
# ---------------------------------------------------------------------------

def _diff_specs(old: dict, new: dict) -> list[dict]:
    """Compute structural diff between two OpenAPI specs.

    Args:
        old: Old OpenAPI specification dict.
        new: New OpenAPI specification dict.

    Returns:
        List of change dicts with ``category``, ``path``, ``method``,
        ``tag``, and ``description``.
    """
    changes: list[dict] = []
    old_paths: dict = old.get("paths", {})
    new_paths: dict = new.get("paths", {})

    # Removed routes
    for path, old_methods in old_paths.items():
        if path not in new_paths:
            for method in old_methods:
                op = old_methods[method]
                changes.append(_change(
                    _BREAKING, path, method,
                    _get_tag(op), f"Route `{method.upper()} {path}` removed.",
                ))
            continue
        # Changed / removed methods
        new_methods = new_paths[path]
        for method, old_op in old_methods.items():
            if method not in new_methods:
                changes.append(_change(
                    _BREAKING, path, method,
                    _get_tag(old_op), f"Method `{method.upper()} {path}` removed.",
                ))
                continue
            new_op = new_methods[method]
            _compare_ops(old_op, new_op, path, method, changes)

    # Added routes
    for path, new_methods in new_paths.items():
        if path not in old_paths:
            for method, new_op in new_methods.items():
                changes.append(_change(
                    _ADDED, path, method,
                    _get_tag(new_op), f"New route `{method.upper()} {path}` added.",
                ))
            continue
        for method, new_op in new_methods.items():
            if method not in old_paths.get(path, {}):
                changes.append(_change(
                    _ADDED, path, method,
                    _get_tag(new_op), f"New method `{method.upper()} {path}` added.",
                ))

    # Schema changes
    old_schemas = old.get("components", {}).get("schemas", {})
    new_schemas = new.get("components", {}).get("schemas", {})
    for name, old_schema in old_schemas.items():
        if name not in new_schemas:
            changes.append(_change(_REMOVED, "", "", "schemas", f"Schema `{name}` removed."))
        elif old_schema != new_schemas[name]:
            changes.append(_change(_CHANGED, "", "", "schemas", f"Schema `{name}` changed."))
    for name in new_schemas:
        if name not in old_schemas:
            changes.append(_change(_ADDED, "", "", "schemas", f"Schema `{name}` added."))

    return changes


def _compare_ops(old_op: dict, new_op: dict, path: str, method: str, changes: list) -> None:
    """Compare two operations and append changes.

    Args:
        old_op: Old operation dict.
        new_op: New operation dict.
        path: Route path.
        method: HTTP method.
        changes: Accumulator list.
    """
    tag = _get_tag(new_op)
    # Parameter removals are BREAKING
    old_params = {p.get("name"): p for p in old_op.get("parameters", [])}
    new_params = {p.get("name"): p for p in new_op.get("parameters", [])}
    for name in old_params:
        if name not in new_params:
            changes.append(_change(
                _BREAKING, path, method, tag,
                f"Required parameter `{name}` removed from `{method.upper()} {path}`.",
            ))
    for name in new_params:
        if name not in old_params:
            changes.append(_change(
                _CHANGED, path, method, tag,
                f"New parameter `{name}` added to `{method.upper()} {path}`.",
            ))

    # Summary/description changes
    if old_op.get("summary") != new_op.get("summary"):
        changes.append(_change(
            _CHANGED, path, method, tag,
            f"Summary changed on `{method.upper()} {path}`.",
        ))


def _change(category: str, path: str, method: str, tag: str, desc: str) -> dict:
    """Build a change entry dict.

    Args:
        category: Change category (BREAKING, ADDED, etc.).
        path: Route path.
        method: HTTP method.
        tag: OpenAPI tag.
        desc: Human-readable description.

    Returns:
        Change entry dict.
    """
    return {
        "category": category,
        "path": path,
        "method": method,
        "tag": tag or "general",
        "description": desc,
    }


def _get_tag(op: dict) -> str:
    """Return first tag from an operation dict, or 'general'.

    Args:
        op: OpenAPI operation dict.

    Returns:
        Tag string.
    """
    tags = op.get("tags", [])
    return tags[0] if tags else "general"


# ---------------------------------------------------------------------------
# Semver suggestion
# ---------------------------------------------------------------------------

def _suggest_semver(changes: list[dict]) -> str:
    """Suggest semver bump level from classified changes.

    Args:
        changes: List of change dicts.

    Returns:
        ``"major"``, ``"minor"``, or ``"patch"``.
    """
    categories = {c["category"] for c in changes}
    if _BREAKING in categories or _REMOVED in categories:
        return "major"
    if _ADDED in categories or _CHANGED in categories:
        return "minor"
    return "patch"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_section(
    changes: list[dict],
    from_ref: str,
    to_ref: str,
    semver: str,
    fmt: str,
    include_breaking_prefix: bool,
) -> str:
    """Render a changelog section for the given changes.

    Args:
        changes: List of change dicts.
        from_ref: Base git ref.
        to_ref: Head git ref.
        semver: Suggested semver bump.
        fmt: ``"keepachangelog"`` or ``"plain"``.
        include_breaking_prefix: Whether to prefix breaking changes.

    Returns:
        Formatted changelog section string.
    """
    lines = [
        f"## [Unreleased] — {from_ref}..{to_ref} (suggested: {semver} bump)",
        "",
    ]
    # Group by tag
    by_tag: dict[str, list[dict]] = {}
    for c in changes:
        by_tag.setdefault(c["tag"], []).append(c)

    order = [_BREAKING, _REMOVED, _ADDED, _CHANGED, _DEPRECATED]
    for tag, tag_changes in sorted(by_tag.items()):
        lines.append(f"### {tag.title()}")
        for cat in order:
            cat_changes = [c for c in tag_changes if c["category"] == cat]
            if not cat_changes:
                continue
            lines.append(f"#### {cat}")
            for c in cat_changes:
                prefix = "BREAKING: " if c["category"] == _BREAKING and include_breaking_prefix else ""
                lines.append(f"- {prefix}{c['description']}")
        lines.append("")

    return "\n".join(lines)


def _prepend_section(changelog_path: Path, section: str) -> None:
    """Prepend *section* to *changelog_path*, creating it if absent.

    Args:
        changelog_path: Absolute path to the changelog file.
        section: Section text to prepend.
    """
    existing = changelog_path.read_text() if changelog_path.exists() else ""
    changelog_path.write_text(section + "\n---\n\n" + existing)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _ms(start: float) -> int:
    """Elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
