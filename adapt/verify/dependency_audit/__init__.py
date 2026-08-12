"""TOOL-030: dependency_audit — pip-audit + deptry + license check for FastAPI.

Generates a ``scripts/run_audit.py`` orchestrator that runs three supply-chain
checks in parallel: (1) ``pip-audit`` for CVEs across direct and transitive
deps, (2) ``deptry`` for unused / missing imports, and (3) ``pip-licenses``
against a configurable allowlist (default MIT/BSD/Apache).  Produces JSON +
HTML reports and a GitHub Actions workflow.

The tool is idempotent: a second run detects ``scripts/run_audit.py`` and
returns ``status="no_op"``.

Honesty (WP-14 §11): the emitted CI workflow runs the orchestrator with
``--fail-on-cve --check-licenses``, which produces a non-zero exit on CVEs;
however the workflow does NOT register a required status check, so a failing
exit code alone does NOT block merge unless branch protection is configured
separately. ``warnings`` is worded as "reports CVEs", never "blocks on
CRITICAL CVEs".
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

_DEFAULT_LICENSES = [
    "MIT",
    "BSD",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "Apache-2.0",
    "Apache Software License",
    "ISC",
    "MPL-2.0",
    "PSF",
    "Python Software Foundation License",
]


MCP_TOOL = {
    "name": "fastapi_compliance_analyze_dependency_audit",
    "description": "Audit Python dependencies for vulnerabilities and outdated packages.",
    "tags": ["verify"],
    "entry": "dependency_audit",
}


def dependency_audit(inp: ToolInput) -> ToolResult:
    """Generate dependency audit infrastructure for a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would generate dependency audit infrastructure."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )


    from adapt.contracts.prerequisites import Prereq, check_prerequisites

    prereq_errors = check_prerequisites(inp.project_dir, Prereq.REQUIREMENTS_TXT)
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_elapsed_ms(start),
        )

    orchestrator = project / "scripts" / "run_audit.py"
    if orchestrator.exists() and "DependencyAuditOrchestrator" in orchestrator.read_text():
        return ToolResult(
            status="no_op",
            notes=["scripts/run_audit.py already present — dependency audit already configured."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []


    (project / "scripts").mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "orchestrator.py.tmpl", dest=orchestrator, substitutions={})
    files_created.append(str(orchestrator))

    audit_cfg = project / ".audit.yaml"
    if not audit_cfg.exists():
        render_to(_HERE, "audit_config.yaml.tmpl", dest=audit_cfg, substitutions={})
        files_created.append(str(audit_cfg))

    audit_ignore = project / ".audit-ignore"
    if not audit_ignore.exists():
        render_to(_HERE, "audit_ignore.tmpl", dest=audit_ignore, substitutions={})
        files_created.append(str(audit_ignore))

    license_checker = project / "scripts" / "check_licenses.py"
    render_to(_HERE, "license_checker.py.tmpl", dest=license_checker, substitutions={})
    files_created.append(str(license_checker))

    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_file = ci_dir / "dependency-audit.yml"
    if not ci_file.exists():
        render_to(_HERE, "ci_workflow.yml.tmpl", dest=ci_file, substitutions={})
        files_created.append(str(ci_file))

    # Phase-5 emitted test (P1 #15)
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted_test = project / "tests" / "test_dependency_audit_emitted.py"
    if not emitted_test.exists():
        render_to(_HERE, "test_emitted.py.tmpl", dest=emitted_test, substitutions={})
        files_created.append(str(emitted_test))

    return ToolResult(
        status="success",
        files_created=files_created,
        notes=[
            "Three checks: pip-audit (CVEs), deptry (dead imports), pip-licenses (compliance).",
            "Allowed licenses: " + ", ".join(_DEFAULT_LICENSES[:5]) + " and others.",
            ".audit-ignore requires reason + reviewer + expiry for every suppression.",
        ],
        warnings=[
            "Advisory check: scripts/run_audit.py reports CVEs and license violations and "
            "exits non-zero on findings; the emitted CI workflow surfaces those exits but "
            "does NOT register a required status — branch protection must be configured "
            "separately for merges to actually be blocked."
        ],
        next_steps=[
            "pip install pip-audit deptry pip-licenses",
            "python scripts/run_audit.py",
            "Review .audit-ignore and add justifications for any known false positives.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
