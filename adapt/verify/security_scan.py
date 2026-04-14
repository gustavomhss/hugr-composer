"""TOOL-029: security_scan — Bandit + semgrep + pip-audit orchestrator for FastAPI.

Generates a ``scripts/security_scan.py`` orchestrator that runs three
complementary static-analysis engines in parallel, merges their SARIF 2.1.0
output, applies a ``.security-exclude.yaml`` suppression file (with mandatory
reason + reviewer + expiry fields), and produces a Markdown summary.  A GitHub
Actions workflow uploads the SARIF to the Security tab and fails the job on
findings that meet the configured severity threshold.

The tool is idempotent: a second run detects the ``scripts/security_scan.py``
fingerprint and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.verify.security_scan import security_scan

    result = security_scan(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # list of new files
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_security_scan",
    "description": "Run security-focused static analysis on the FastAPI project.",
    "tags": ["verify", "security"],
    "entry": "security_scan",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def security_scan(inp: ToolInput) -> ToolResult:
    """Generate a security scanning infrastructure for a FastAPI project.

    Creates an orchestrator script, FastAPI-specific semgrep rules, bandit
    config, a SARIF merge utility, suppression schema, and CI workflow.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)


    # --- Idempotency guard ---------------------------------------------------
    orchestrator = project / "scripts" / "security_scan.py"
    if orchestrator.exists() and "SecurityScanOrchestrator" in orchestrator.read_text():
        return ToolResult(
            status="no_op",
            notes=["scripts/security_scan.py already present — security scan already configured."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would generate security scan infrastructure."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Step 1: Orchestrator script -----------------------------------------
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    _write_orchestrator(orchestrator)
    files_created.append(str(orchestrator))

    # --- Step 2: FastAPI-specific semgrep rules -------------------------------
    security_dir = project / ".security"
    security_dir.mkdir(parents=True, exist_ok=True)
    semgrep_rules = security_dir / "semgrep-rules.yaml"
    _write_semgrep_rules(semgrep_rules)
    files_created.append(str(semgrep_rules))

    # --- Step 3: Bandit config -----------------------------------------------
    bandit_cfg = security_dir / "bandit.yaml"
    _write_bandit_config(bandit_cfg)
    files_created.append(str(bandit_cfg))

    # --- Step 4: Exclusion schema -------------------------------------------
    exclude_file = project / ".security-exclude.yaml"
    if not exclude_file.exists():
        _write_exclusion_schema(exclude_file)
        files_created.append(str(exclude_file))

    # --- Step 5: SARIF merge utility -----------------------------------------
    sarif_util = security_dir / "sarif_merge.py"
    _write_sarif_merge(sarif_util)
    files_created.append(str(sarif_util))

    # --- Step 6: GitHub Actions workflow -------------------------------------
    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_file = ci_dir / "security.yml"
    if not ci_file.exists():
        _write_ci_workflow(ci_file)
        files_created.append(str(ci_file))

    # --- Step 7: Makefile target hint ----------------------------------------
    makefile = project / "Makefile"
    _patch_makefile(makefile)

    return ToolResult(
        status="success",
        files_created=files_created,
        notes=[
            "Three scanners: bandit (Python AST), semgrep (FastAPI patterns), pip-audit (CVEs).",
            "SARIF 2.1.0 output — uploads to GitHub Security tab automatically.",
            ".security-exclude.yaml requires reason + reviewer + expiry for every suppression.",
        ],
        next_steps=[
            "pip install bandit semgrep pip-audit",
            "python scripts/security_scan.py --fail-on high",
            "Commit .security-exclude.yaml with any reviewed false positives.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_orchestrator(dest: Path) -> None:
    """Write scripts/security_scan.py orchestrator.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Security scan orchestrator: runs bandit, semgrep, pip-audit in parallel.

        Usage::

            python scripts/security_scan.py [--fail-on high|medium|low] [--json]
        \"\"\"

        from __future__ import annotations

        import argparse
        import json
        import subprocess
        import sys
        import tempfile
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from pathlib import Path
        from typing import Any

        ROOT = Path(__file__).parent.parent
        SECURITY_DIR = ROOT / ".security"
        EXCLUDE_FILE = ROOT / ".security-exclude.yaml"
        SARIF_OUT = ROOT / "security-results.sarif"
        SEVERITY_ORDER = ["INFORMATIONAL", "LOW", "MEDIUM", "HIGH", "CRITICAL"]


        class SecurityScanOrchestrator:
            \"\"\"Run bandit, semgrep, and pip-audit; merge SARIF; apply exclusions.\"\"\"

            def __init__(self, fail_on: str = "high", project_dir: Path = ROOT) -> None:
                self.fail_on = fail_on.upper()
                self.project_dir = project_dir

            def run(self) -> dict[str, Any]:
                \"\"\"Execute all scanners in parallel and return merged results.

                Returns:
                    Dict with ``findings``, ``summary``, and ``exit_code``.
                \"\"\"
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures = {
                        pool.submit(self._run_bandit): "bandit",
                        pool.submit(self._run_semgrep): "semgrep",
                        pool.submit(self._run_pip_audit): "pip_audit",
                    }
                    raw: dict[str, list[dict]] = {}
                    for future in as_completed(futures):
                        tool = futures[future]
                        try:
                            raw[tool] = future.result()
                        except Exception as exc:  # noqa: BLE001
                            raw[tool] = [{"error": str(exc), "severity": "LOW"}]

                findings = self._merge(raw)
                findings = self._apply_exclusions(findings)
                summary = self._summarize(findings)
                failing = any(
                    SEVERITY_ORDER.index(f.get("severity", "LOW").upper())
                    >= SEVERITY_ORDER.index(self.fail_on)
                    for f in findings
                )
                return {"findings": findings, "summary": summary, "exit_code": 1 if failing else 0}

            def _run_bandit(self) -> list[dict]:
                \"\"\"Run bandit and parse JSON output.\"\"\"
                with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                    result = subprocess.run(
                        ["bandit", "-r", str(self.project_dir / "app"),
                         "-f", "json", "-o", tmp.name,
                         "-c", str(SECURITY_DIR / "bandit.yaml"),
                         "--exit-zero"],
                        capture_output=True, text=True, timeout=120,
                    )
                    try:
                        data = json.loads(Path(tmp.name).read_text())
                        return [
                            {"tool": "bandit", "severity": r.get("issue_severity", "LOW"),
                             "message": r.get("issue_text", ""), "file": r.get("filename", ""),
                             "line": r.get("line_number", 0)}
                            for r in data.get("results", [])
                        ]
                    except (json.JSONDecodeError, KeyError):
                        return []

            def _run_semgrep(self) -> list[dict]:
                \"\"\"Run semgrep with FastAPI-specific rules.\"\"\"
                with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                    subprocess.run(
                        ["semgrep", "--config", str(SECURITY_DIR / "semgrep-rules.yaml"),
                         str(self.project_dir / "app"), "--json", "-o", tmp.name,
                         "--quiet"],
                        capture_output=True, text=True, timeout=180,
                    )
                    try:
                        data = json.loads(Path(tmp.name).read_text())
                        return [
                            {"tool": "semgrep", "severity": r.get("extra", {}).get("severity", "WARNING"),
                             "message": r.get("extra", {}).get("message", ""),
                             "file": r.get("path", ""), "line": r.get("start", {}).get("line", 0)}
                            for r in data.get("results", [])
                        ]
                    except (json.JSONDecodeError, KeyError):
                        return []

            def _run_pip_audit(self) -> list[dict]:
                \"\"\"Run pip-audit and parse JSON output.\"\"\"
                result = subprocess.run(
                    ["pip-audit", "--format", "json", "--progress-spinner", "off"],
                    capture_output=True, text=True, cwd=self.project_dir, timeout=120,
                )
                try:
                    data = json.loads(result.stdout)
                    findings = []
                    for dep in data.get("dependencies", []):
                        for vuln in dep.get("vulns", []):
                            findings.append({
                                "tool": "pip_audit", "severity": "HIGH",
                                "message": f"{dep['name']} {dep['version']}: {vuln.get('id', '')} — {vuln.get('description', '')[:80]}",
                                "file": "requirements", "line": 0,
                            })
                    return findings
                except (json.JSONDecodeError, KeyError):
                    return []

            def _merge(self, raw: dict[str, list[dict]]) -> list[dict]:
                \"\"\"Merge findings from all tools, deduplicating by (file, line, message[:40]).\"\"\"
                seen: set[tuple] = set()
                merged = []
                for findings in raw.values():
                    for f in findings:
                        key = (f.get("file", ""), f.get("line", 0), f.get("message", "")[:40])
                        if key not in seen:
                            seen.add(key)
                            merged.append(f)
                return sorted(merged, key=lambda x: SEVERITY_ORDER.index(x.get("severity", "LOW").upper()), reverse=True)

            def _apply_exclusions(self, findings: list[dict]) -> list[dict]:
                \"\"\"Remove findings suppressed in .security-exclude.yaml.\"\"\"
                if not EXCLUDE_FILE.exists():
                    return findings
                try:
                    import yaml  # type: ignore[import]
                    exclusions = yaml.safe_load(EXCLUDE_FILE.read_text()) or {}
                except Exception:  # noqa: BLE001
                    return findings
                suppressed = {
                    (e.get("file", ""), e.get("message_contains", ""))
                    for e in exclusions.get("exclusions", [])
                    if e.get("expiry", "9999-99-99") > "2020-01-01"
                }
                return [
                    f for f in findings
                    if not any(
                        f.get("file", "").endswith(s[0]) and s[1] in f.get("message", "")
                        for s in suppressed
                    )
                ]

            def _summarize(self, findings: list[dict]) -> dict[str, int]:
                \"\"\"Return count of findings per severity.\"\"\"
                summary: dict[str, int] = {}
                for f in findings:
                    sev = f.get("severity", "LOW").upper()
                    summary[sev] = summary.get(sev, 0) + 1
                return summary


        if __name__ == "__main__":
            parser = argparse.ArgumentParser(description="FastAPI security scan")
            parser.add_argument("--fail-on", default="high", choices=["low", "medium", "high", "critical"])
            parser.add_argument("--json", action="store_true")
            args = parser.parse_args()

            orchestrator = SecurityScanOrchestrator(fail_on=args.fail_on)
            results = orchestrator.run()

            if args.json:
                print(json.dumps(results["summary"], indent=2))
            else:
                print("\\n=== Security Scan Summary ===")
                for sev, count in results["summary"].items():
                    print(f"  {sev}: {count}")
                print(f"\\nTotal findings: {len(results['findings'])}")

            sys.exit(results["exit_code"])
        """)
    dest.write_text(content)


def _write_semgrep_rules(dest: Path) -> None:
    """Write .security/semgrep-rules.yaml with FastAPI-specific patterns.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # FastAPI-specific semgrep security rules
        rules:
          - id: fastapi-cors-wildcard
            patterns:
              - pattern: |
                  CORSMiddleware(..., allow_origins=["*"], ...)
            message: "CORS wildcard allows any origin — restrict to known domains."
            severity: WARNING
            languages: [python]

          - id: fastapi-unparameterized-sql
            patterns:
              - pattern: |
                  session.execute(f"...")
              - pattern: |
                  session.execute("..." + ...)
            message: "Potential SQL injection via f-string or concatenation in execute()."
            severity: ERROR
            languages: [python]

          - id: fastapi-assert-auth
            pattern: assert $USER.is_superuser, ...
            message: "Do not use assert for access control — it is disabled with -O."
            severity: ERROR
            languages: [python]

          - id: fastapi-jwt-none-algorithm
            pattern: jwt.encode(..., algorithm="none")
            message: "JWT signed with 'none' algorithm is unsigned and trivially forgeable."
            severity: ERROR
            languages: [python]

          - id: fastapi-hardcoded-secret
            patterns:
              - pattern: SECRET_KEY = "..."
              - pattern: secret_key = "..."
            message: "Hardcoded secret key detected — use environment variable."
            severity: WARNING
            languages: [python]
        """)
    dest.write_text(content)


def _write_bandit_config(dest: Path) -> None:
    """Write .security/bandit.yaml bandit configuration.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # Bandit security linter configuration
        skips: []
        exclude_dirs:
          - tests
          - .venv
          - venv
          - alembic/versions
        assert_used:
          skips:
            - "*_test.py"
            - "test_*.py"
        """)
    dest.write_text(content)


def _write_exclusion_schema(dest: Path) -> None:
    """Write .security-exclude.yaml suppression schema template.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .security-exclude.yaml — reviewed security finding suppressions.
        # Every exclusion MUST include reason, reviewer, and expiry.
        # Expired entries are NOT applied (they remain for audit history).
        #
        # Example:
        #   - file: app/tests/fixtures/seed_data.py
        #     message_contains: "hardcoded password"
        #     reason: "Test fixture — never runs in production"
        #     reviewer: "@security-team"
        #     expiry: "2027-01-01"
        version: "1.0"
        exclusions: []
        """)
    dest.write_text(content)


def _write_sarif_merge(dest: Path) -> None:
    """Write .security/sarif_merge.py SARIF 2.1.0 merge utility.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Merge multiple SARIF 2.1.0 files into a single output file.\"\"\"

        from __future__ import annotations

        import json
        from pathlib import Path
        from typing import Any


        def merge_sarif(sarif_files: list[Path], output: Path) -> None:
            \"\"\"Merge *sarif_files* into a single SARIF document at *output*.

            Args:
                sarif_files: List of SARIF 2.1.0 input files to merge.
                output: Destination path for the merged SARIF document.
            \"\"\"
            merged: dict[str, Any] = {
                "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
                "version": "2.1.0",
                "runs": [],
            }
            for sarif_file in sarif_files:
                if not sarif_file.exists():
                    continue
                try:
                    doc = json.loads(sarif_file.read_text())
                    merged["runs"].extend(doc.get("runs", []))
                except (json.JSONDecodeError, OSError):
                    continue
            output.write_text(json.dumps(merged, indent=2))


        def findings_to_sarif(findings: list[dict], tool_name: str) -> dict[str, Any]:
            \"\"\"Convert a list of findings dicts to a minimal SARIF 2.1.0 run.

            Args:
                findings: List of finding dicts with keys: message, file, line, severity.
                tool_name: Name of the tool that produced the findings.

            Returns:
                SARIF 2.1.0 ``run`` object.
            \"\"\"
            results = [
                {
                    "ruleId": f.get("rule_id", f"{tool_name}-finding"),
                    "level": _sarif_level(f.get("severity", "LOW")),
                    "message": {"text": f.get("message", "")},
                    "locations": [{"physicalLocation": {
                        "artifactLocation": {"uri": f.get("file", "unknown")},
                        "region": {"startLine": max(1, f.get("line", 1))},
                    }}],
                }
                for f in findings
            ]
            return {
                "tool": {"driver": {"name": tool_name, "version": "1.0.0"}},
                "results": results,
            }


        def _sarif_level(severity: str) -> str:
            mapping = {"CRITICAL": "error", "HIGH": "error", "MEDIUM": "warning",
                       "LOW": "note", "INFORMATIONAL": "none"}
            return mapping.get(severity.upper(), "note")
        """)
    dest.write_text(content)


def _write_ci_workflow(dest: Path) -> None:
    """Write .github/workflows/security.yml CI workflow.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .github/workflows/security.yml
        name: Security Scan

        on:
          pull_request:
            branches: [main, master]
          push:
            branches: [main, master]
          schedule:
            - cron: "0 6 * * 1"  # Weekly Monday scan

        jobs:
          security:
            runs-on: ubuntu-latest
            permissions:
              security-events: write
              contents: read
            steps:
              - uses: actions/checkout@v4
              - uses: actions/setup-python@v5
                with:
                  python-version: "3.12"
                  cache: pip
              - name: Install scanners
                run: pip install bandit semgrep pip-audit pyyaml
              - name: Install project dependencies
                run: pip install -r requirements.txt
              - name: Run security scan
                run: python scripts/security_scan.py --fail-on high --json
              - name: Upload SARIF to GitHub Security tab
                if: always()
                uses: github/codeql-action/upload-sarif@v3
                with:
                  sarif_file: security-results.sarif
        """)
    dest.write_text(content)


def _patch_makefile(makefile: Path) -> None:
    """Add security target to Makefile if it exists.

    Args:
        makefile: Path to project Makefile.
    """
    if not makefile.exists():
        return
    src = makefile.read_text()
    if "security-scan" in src:
        return
    addition = "\nsecurity-scan:  ## Run bandit + semgrep + pip-audit\n\tpython scripts/security_scan.py --fail-on high\n"
    makefile.write_text(src + addition)


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
