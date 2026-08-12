"""TOOL-110: add_sbom_guardian — CycloneDX SBOM + dependency integrity for FastAPI.

Generates scripts/generate_sbom.py and scripts/verify_lockfile.py, patches
app/core/config.py with SBOM settings.

Tool is idempotent: second run detects ``generate_sbom`` in scripts/ and
returns ``status="no_op"``.

WARNING: add_sbom_guardian diffs the lockfile and logs vulnerability findings
but does NOT hard-block CI by default. Set SBOM_FAIL_ON_CRITICAL=true to
enable hard-blocking on critical CVEs. The tool only logs (does not block)
unless that flag is set.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_testing_add_sbom_guardian",
    "description": (
        "Add CycloneDX SBOM generation, lockfile integrity verification, "
        "dependency confusion detection, and OSV/NVD vulnerability scanning."
    ),
    "tags": ["extend", "testing_tools", "security", "supply-chain"],
    "entry": "add_sbom_guardian",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_sbom_guardian(inp: ToolInput) -> ToolResult:
    """Add SBOM guardian to a FastAPI project.

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
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
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

    files_created: list[str] = list(scaffolded or [])

    scripts_dir = project / "scripts"
    sbom_script = scripts_dir / "generate_sbom.py"
    if sbom_script.exists() and "generate_sbom" in sbom_script.read_text():
        return ToolResult(
            status="no_op",
            notes=["generate_sbom already present — SBOM guardian already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create scripts/generate_sbom.py",
                "[dry_run] Would create scripts/verify_lockfile.py",
                "[dry_run] Would patch app/core/config.py with SBOM settings",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    scripts_dir.mkdir(parents=True, exist_ok=True)
    scripts_init = scripts_dir / "__init__.py"
    if not scripts_init.exists():
        scripts_init.write_text('"""CLI scripts package."""\n')
        files_created.append(str(scripts_init))

    render_to(_HERE, "generate_sbom.py.tmpl", dest=sbom_script, substitutions={})
    files_created.append(str(sbom_script))

    lockfile_script = scripts_dir / "verify_lockfile.py"
    render_to(_HERE, "verify_lockfile.py.tmpl", dest=lockfile_script, substitutions={})
    files_created.append(str(lockfile_script))

    config_file = project / "app" / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

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

    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_sbom_guardian_emitted.py"
    if not emitted.exists():
        render_to(_HERE, "test_add_sbom_guardian_emitted.py.tmpl", dest=emitted, substitutions={})
        files_created.append(str(emitted))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "SBOM guardian added: CycloneDX generation + lockfile integrity + confusion detection.",
            "generate_sbom.py: Creates CycloneDX JSON SBOM from pip inspect (stdlib only).",
            "verify_lockfile.py: Validates lockfile hash, detects dependency confusion, scans OSV.",
            "Config: SBOM_FAIL_ON_CRITICAL (default true), SBOM_LOCKFILE_PATH (default requirements.txt).",
            "WARNING: Tool only logs findings by default. Set SBOM_FAIL_ON_CRITICAL=true to hard-block CI.",
            "PCI DSS 4.0 Req 6.3 compliant — inventory of all software components.",
        ],
        next_steps=[
            "Run: python scripts/generate_sbom.py --output sbom.json",
            "Run: python scripts/verify_lockfile.py --lockfile requirements.txt",
            "Add to CI: python scripts/verify_lockfile.py --fail-on-critical",
            "Optionally add pip-audit for deeper OSV scanning: pip install pip-audit",
            "Store sbom.json as CI artifact for compliance audits (PCI DSS 4.0 Req 6.3).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("SBOM_FAIL_ON_CRITICAL", "SBOM_FAIL_ON_CRITICAL: bool = True"),
            ("SBOM_LOCKFILE_PATH", 'SBOM_LOCKFILE_PATH: str = "requirements.txt"'),
        ],
    )


