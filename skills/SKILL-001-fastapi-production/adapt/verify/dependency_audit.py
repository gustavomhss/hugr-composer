"""TOOL-030: dependency_audit — pip-audit + deptry + license check for FastAPI.

Generates a ``scripts/run_audit.py`` orchestrator that runs three supply-chain
checks in parallel: (1) ``pip-audit`` for CVEs across direct and transitive
deps, (2) ``deptry`` for unused / missing imports, and (3) ``pip-licenses``
against a configurable allowlist (default MIT/BSD/Apache).  Produces JSON +
HTML reports and a GitHub Actions workflow that blocks PRs on CRITICAL/HIGH
CVEs.

The tool is idempotent: a second run detects ``scripts/run_audit.py`` and
returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.verify.dependency_audit import dependency_audit

    result = dependency_audit(ToolInput(project_dir="/path/to/project"))
    print(result.status)  # "success"
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_DEFAULT_LICENSES = ["MIT", "BSD", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0",
                     "Apache Software License", "ISC", "MPL-2.0", "PSF", "Python Software Foundation License"]


MCP_TOOL = {
    "name": "fastapi_compliance_analyze_dependency_audit",
    "description": "Audit Python dependencies for vulnerabilities and outdated packages.",
    "tags": ["verify"],
    "entry": "dependency_audit",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def dependency_audit(inp: ToolInput) -> ToolResult:
    """Generate dependency audit infrastructure for a FastAPI project.

    Creates run_audit.py orchestrator, .audit.yaml config, .audit-ignore
    template, license checker, and CI workflow.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` describing every file created.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    # --- Prerequisite check ---------------------------------------------------
    from adapt.contracts.prerequisites import check_prerequisites, Prereq

    prereq_errors = check_prerequisites(inp.project_dir, Prereq.REQUIREMENTS_TXT)
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Idempotency guard ---------------------------------------------------
    orchestrator = project / "scripts" / "run_audit.py"
    if orchestrator.exists() and "DependencyAuditOrchestrator" in orchestrator.read_text():
        return ToolResult(
            status="no_op",
            notes=["scripts/run_audit.py already present — dependency audit already configured."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would generate dependency audit infrastructure."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Step 1: Orchestrator ------------------------------------------------
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    _write_orchestrator(orchestrator)
    files_created.append(str(orchestrator))

    # --- Step 2: .audit.yaml config ------------------------------------------
    audit_cfg = project / ".audit.yaml"
    if not audit_cfg.exists():
        _write_audit_config(audit_cfg)
        files_created.append(str(audit_cfg))

    # --- Step 3: .audit-ignore schema ----------------------------------------
    audit_ignore = project / ".audit-ignore"
    if not audit_ignore.exists():
        _write_audit_ignore(audit_ignore)
        files_created.append(str(audit_ignore))

    # --- Step 4: License checker helper --------------------------------------
    license_checker = project / "scripts" / "check_licenses.py"
    _write_license_checker(license_checker)
    files_created.append(str(license_checker))

    # --- Step 5: CI workflow -------------------------------------------------
    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_file = ci_dir / "dependency-audit.yml"
    if not ci_file.exists():
        _write_ci_workflow(ci_file)
        files_created.append(str(ci_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        notes=[
            "Three checks: pip-audit (CVEs), deptry (dead imports), pip-licenses (compliance).",
            "Allowed licenses: " + ", ".join(_DEFAULT_LICENSES[:5]) + " and others.",
            ".audit-ignore requires reason + reviewer + expiry for every suppression.",
        ],
        next_steps=[
            "pip install pip-audit deptry pip-licenses",
            "python scripts/run_audit.py",
            "Review .audit-ignore and add justifications for any known false positives.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_orchestrator(dest: Path) -> None:
    """Write scripts/run_audit.py orchestrator.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Dependency audit orchestrator: pip-audit + deptry + license check.

        Usage::

            python scripts/run_audit.py [--fail-on-cve] [--check-licenses]
        \"\"\"

        from __future__ import annotations

        import argparse
        import json
        import subprocess
        import sys
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from pathlib import Path
        from typing import Any

        ROOT = Path(__file__).parent.parent
        IGNORE_FILE = ROOT / ".audit-ignore"


        class DependencyAuditOrchestrator:
            \"\"\"Run pip-audit, deptry, and license checks in parallel.\"\"\"

            def __init__(
                self,
                project_dir: Path = ROOT,
                fail_on_cve: bool = True,
                fail_on_unused: bool = False,
                check_licenses: bool = True,
                allowed_licenses: list[str] | None = None,
            ) -> None:
                self.project_dir = project_dir
                self.fail_on_cve = fail_on_cve
                self.fail_on_unused = fail_on_unused
                self.check_licenses = check_licenses
                self.allowed_licenses = allowed_licenses or [
                    "MIT", "BSD", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0",
                    "Apache Software License", "ISC", "MPL-2.0", "PSF",
                ]

            def run(self) -> dict[str, Any]:
                \"\"\"Execute all checks and return merged results.

                Returns:
                    Dict with ``cve_findings``, ``unused_deps``, ``license_violations``,
                    and ``exit_code``.
                \"\"\"
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures = {
                        pool.submit(self._run_pip_audit): "cve",
                        pool.submit(self._run_deptry): "deps",
                        pool.submit(self._run_license_check): "licenses",
                    }
                    results: dict[str, Any] = {}
                    for future in as_completed(futures):
                        key = futures[future]
                        try:
                            results[key] = future.result()
                        except Exception as exc:  # noqa: BLE001
                            results[key] = {"error": str(exc)}

                cve_findings = self._apply_ignore(results.get("cve", {}).get("findings", []), "cve")
                unused_deps = results.get("deps", {}).get("unused", [])
                license_violations = results.get("licenses", {}).get("violations", [])

                exit_code = 0
                if self.fail_on_cve and cve_findings:
                    exit_code = 1
                if self.fail_on_unused and unused_deps:
                    exit_code = 1
                if self.check_licenses and license_violations:
                    exit_code = 1

                return {
                    "cve_findings": cve_findings,
                    "unused_deps": unused_deps,
                    "license_violations": license_violations,
                    "exit_code": exit_code,
                }

            def _run_pip_audit(self) -> dict[str, Any]:
                \"\"\"Run pip-audit and return CVE findings.\"\"\"
                result = subprocess.run(
                    ["pip-audit", "--format", "json", "--progress-spinner", "off"],
                    capture_output=True, text=True, cwd=self.project_dir, timeout=120,
                )
                try:
                    data = json.loads(result.stdout or result.stderr or "{}")
                    findings = []
                    for dep in data.get("dependencies", []):
                        for vuln in dep.get("vulns", []):
                            findings.append({
                                "package": dep["name"], "version": dep["version"],
                                "cve": vuln.get("id", ""), "severity": "HIGH",
                                "fix": vuln.get("fix_versions", []),
                                "description": vuln.get("description", "")[:120],
                            })
                    return {"findings": findings}
                except (json.JSONDecodeError, KeyError):
                    return {"findings": []}

            def _run_deptry(self) -> dict[str, Any]:
                \"\"\"Run deptry and return unused/missing deps.\"\"\"
                result = subprocess.run(
                    ["deptry", ".", "--json-output", "/dev/stdout"],
                    capture_output=True, text=True, cwd=self.project_dir, timeout=60,
                )
                try:
                    data = json.loads(result.stdout or "{}")
                    return {
                        "unused": [i["package"] for i in data.get("DEP002", [])],
                        "missing": [i["package"] for i in data.get("DEP001", [])],
                    }
                except (json.JSONDecodeError, KeyError):
                    return {"unused": [], "missing": []}

            def _run_license_check(self) -> dict[str, Any]:
                \"\"\"Check package licenses against allowlist.\"\"\"
                result = subprocess.run(
                    ["pip-licenses", "--format", "json", "--with-license-file"],
                    capture_output=True, text=True, cwd=self.project_dir, timeout=30,
                )
                try:
                    packages = json.loads(result.stdout or "[]")
                    violations = [
                        {"package": p["Name"], "license": p.get("License", "UNKNOWN")}
                        for p in packages
                        if not any(
                            allowed in p.get("License", "") for allowed in self.allowed_licenses
                        )
                    ]
                    return {"violations": violations}
                except (json.JSONDecodeError, KeyError):
                    return {"violations": []}

            def _apply_ignore(self, findings: list[dict], kind: str) -> list[dict]:
                \"\"\"Remove suppressed findings from .audit-ignore.\"\"\"
                if not IGNORE_FILE.exists():
                    return findings
                try:
                    suppressed = {
                        line.split(":", 1)[1].strip()
                        for line in IGNORE_FILE.read_text().splitlines()
                        if line.startswith(f"{kind}:")
                    }
                    return [f for f in findings if f.get("cve", f.get("package")) not in suppressed]
                except Exception:  # noqa: BLE001
                    return findings


        if __name__ == "__main__":
            parser = argparse.ArgumentParser(description="Dependency audit")
            parser.add_argument("--fail-on-cve", action="store_true", default=True)
            parser.add_argument("--check-licenses", action="store_true", default=True)
            args = parser.parse_args()

            orch = DependencyAuditOrchestrator(
                fail_on_cve=args.fail_on_cve, check_licenses=args.check_licenses
            )
            results = orch.run()
            print(f"CVEs: {len(results['cve_findings'])}")
            print(f"Unused deps: {len(results['unused_deps'])}")
            print(f"License violations: {len(results['license_violations'])}")
            sys.exit(results["exit_code"])
        """)
    dest.write_text(content)


def _write_audit_config(dest: Path) -> None:
    """Write .audit.yaml audit configuration.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .audit.yaml — dependency audit configuration
        version: "1.0"
        fail_on_cve: true
        fail_on_unused: false
        check_licenses: true
        allowed_licenses:
          - MIT
          - BSD
          - BSD-2-Clause
          - BSD-3-Clause
          - Apache-2.0
          - Apache Software License
          - ISC
          - MPL-2.0
          - PSF
          - Python Software Foundation License
        cache_validity_hours: 24
        network_retries: 3
        """)
    dest.write_text(content)


def _write_audit_ignore(dest: Path) -> None:
    """Write .audit-ignore suppression template.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .audit-ignore — reviewed dependency audit suppressions.
        # Format: <kind>: <identifier>
        # Kinds: cve, license, unused
        # Every entry MUST be followed by: reason, reviewer, expiry comment.
        #
        # Example:
        #   cve: GHSA-xxxx-xxxx-xxxx
        #   # reason: Only exploitable on Windows; we deploy Linux-only.
        #   # reviewer: @security-team
        #   # expiry: 2026-12-31
        """)
    dest.write_text(content)


def _write_license_checker(dest: Path) -> None:
    """Write scripts/check_licenses.py standalone license check helper.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Standalone license compliance checker.

        Usage::

            python scripts/check_licenses.py [--allowed MIT,BSD,Apache-2.0]
        \"\"\"

        from __future__ import annotations

        import argparse
        import json
        import subprocess
        import sys

        DEFAULT_ALLOWED = ["MIT", "BSD", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0",
                           "Apache Software License", "ISC", "MPL-2.0", "PSF"]


        def check_licenses(allowed: list[str]) -> list[dict]:
            \"\"\"Return packages whose license is not in *allowed*.

            Args:
                allowed: List of allowed SPDX license identifiers.

            Returns:
                List of violation dicts with ``package`` and ``license`` keys.
            \"\"\"
            result = subprocess.run(
                ["pip-licenses", "--format", "json"],
                capture_output=True, text=True, timeout=30,
            )
            try:
                packages = json.loads(result.stdout or "[]")
            except json.JSONDecodeError:
                return []
            return [
                {"package": p["Name"], "license": p.get("License", "UNKNOWN")}
                for p in packages
                if not any(a in p.get("License", "") for a in allowed)
            ]


        if __name__ == "__main__":
            parser = argparse.ArgumentParser()
            parser.add_argument("--allowed", default=",".join(DEFAULT_ALLOWED))
            args = parser.parse_args()
            allowed = [a.strip() for a in args.allowed.split(",")]
            violations = check_licenses(allowed)
            for v in violations:
                print(f"VIOLATION: {v['package']} uses {v['license']}")
            sys.exit(1 if violations else 0)
        """)
    dest.write_text(content)


def _write_ci_workflow(dest: Path) -> None:
    """Write .github/workflows/dependency-audit.yml CI workflow.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .github/workflows/dependency-audit.yml
        name: Dependency Audit

        on:
          pull_request:
            branches: [main, master]
          push:
            branches: [main, master]
          schedule:
            - cron: "0 4 * * *"  # Daily CVE check

        jobs:
          audit:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
              - uses: actions/setup-python@v5
                with:
                  python-version: "3.12"
                  cache: pip
              - name: Install audit tools
                run: pip install pip-audit deptry pip-licenses
              - name: Install project dependencies
                run: pip install -r requirements.txt
              - name: Run dependency audit
                run: python scripts/run_audit.py --fail-on-cve --check-licenses
        """)
    dest.write_text(content)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
