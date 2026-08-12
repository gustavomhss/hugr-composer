"""TOOL-029: security_scan — Bandit + semgrep + pip-audit orchestrator for FastAPI.

Generates a ``scripts/security_scan.py`` orchestrator that runs three
complementary static-analysis engines in parallel, merges their SARIF 2.1.0
output, applies a ``.security-exclude.yaml`` suppression file (with mandatory
reason + reviewer + expiry fields), and produces a Markdown summary.  A GitHub
Actions workflow uploads the SARIF to the Security tab and reports findings
that meet the configured severity threshold.

The tool is idempotent: a second run detects the ``scripts/security_scan.py``
fingerprint and returns ``status="no_op"``.

Honesty (WP-14 §11): bandit runs with the *project-provided* config
(``.security/bandit.yaml``) which sets ``skips: []`` and excludes test dirs —
this is bandit's default ruleset, not a curated OWASP-aligned profile.
Semgrep uses five FastAPI-specific rules; that is not "OWASP Top 10 covered".
``warnings`` is worded as "bandit default ruleset + 5 semgrep rules" — it
does not claim "OWASP top 10 covered".
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent


MCP_TOOL = {
    "name": "fastapi_resiliency_analyze_security_scan",
    "description": "Run security-focused static analysis on the FastAPI project.",
    "tags": ["verify", "security"],
    "entry": "security_scan",
}


def security_scan(inp: ToolInput) -> ToolResult:
    """Generate a security scanning infrastructure for a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would generate security scan infrastructure."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )


    orchestrator = project / "scripts" / "security_scan.py"
    if orchestrator.exists() and "SecurityScanOrchestrator" in orchestrator.read_text():
        return ToolResult(
            status="no_op",
            notes=["scripts/security_scan.py already present — security scan already configured."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []


    (project / "scripts").mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "orchestrator.py.tmpl", dest=orchestrator, substitutions={})
    files_created.append(str(orchestrator))

    security_dir = project / ".security"
    security_dir.mkdir(parents=True, exist_ok=True)
    semgrep_rules = security_dir / "semgrep-rules.yaml"
    render_to(_HERE, "semgrep_rules.yaml.tmpl", dest=semgrep_rules, substitutions={})
    files_created.append(str(semgrep_rules))

    bandit_cfg = security_dir / "bandit.yaml"
    render_to(_HERE, "bandit_config.yaml.tmpl", dest=bandit_cfg, substitutions={})
    files_created.append(str(bandit_cfg))

    exclude_file = project / ".security-exclude.yaml"
    if not exclude_file.exists():
        render_to(_HERE, "exclusion_schema.yaml.tmpl", dest=exclude_file, substitutions={})
        files_created.append(str(exclude_file))

    sarif_util = security_dir / "sarif_merge.py"
    render_to(_HERE, "sarif_merge.py.tmpl", dest=sarif_util, substitutions={})
    files_created.append(str(sarif_util))

    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_file = ci_dir / "security.yml"
    if not ci_file.exists():
        render_to(_HERE, "ci_workflow.yml.tmpl", dest=ci_file, substitutions={})
        files_created.append(str(ci_file))

    makefile = project / "Makefile"
    _patch_makefile(makefile)

    # Phase-5 emitted test (P1 #15)
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted_test = project / "tests" / "test_security_scan_emitted.py"
    if not emitted_test.exists():
        render_to(_HERE, "test_emitted.py.tmpl", dest=emitted_test, substitutions={})
        files_created.append(str(emitted_test))

    return ToolResult(
        status="success",
        files_created=files_created,
        notes=[
            "Three scanners: bandit (Python AST), semgrep (FastAPI patterns), pip-audit (CVEs).",
            "SARIF 2.1.0 output — uploads to GitHub Security tab automatically.",
            ".security-exclude.yaml requires reason + reviewer + expiry for every suppression.",
        ],
        warnings=[
            "Advisory check: bandit runs with default ruleset (no curated OWASP profile); "
            "semgrep uses 5 FastAPI-specific rules. Coverage of OWASP Top 10 is NOT "
            "claimed. The emitted CI workflow runs the scan and exits non-zero on "
            "findings at --fail-on threshold, but does NOT register a required status — "
            "configure branch protection separately to actually block PRs."
        ],
        next_steps=[
            "pip install bandit semgrep pip-audit",
            "python scripts/security_scan.py --fail-on high",
            "Commit .security-exclude.yaml with any reviewed false positives.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_makefile(makefile: Path) -> None:
    """Add security target to Makefile if it exists."""
    if not makefile.exists():
        return
    src = makefile.read_text()
    if "security-scan" in src:
        return
    addition = "\nsecurity-scan:  ## Run bandit + semgrep + pip-audit\n\tpython scripts/security_scan.py --fail-on high\n"
    makefile.write_text(src + addition)


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
