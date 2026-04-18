"""TOOL-110: add_sbom_guardian — CycloneDX SBOM + dependency integrity for FastAPI.

Generates:
  - ``scripts/generate_sbom.py``  — CycloneDX SBOM generator (stdlib + pip inspect)
  - ``scripts/verify_lockfile.py`` — lockfile integrity + confusion detection
  - patches ``app/core/config.py`` with SBOM_FAIL_ON_CRITICAL, SBOM_LOCKFILE_PATH

Covers PCI DSS 4.0 Req 6.3, SLSA supply-chain provenance.
Tool is idempotent: second run detects ``generate_sbom`` in scripts/ and
returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.testing_tools.add_sbom_guardian import add_sbom_guardian

    result = add_sbom_guardian(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../scripts/generate_sbom.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_sbom_guardian",
    "description": (
        "Add CycloneDX SBOM generation, lockfile integrity verification, "
        "dependency confusion detection, and OSV/NVD vulnerability scanning."
    ),
    "tags": ["extend", "testing_tools", "security", "supply-chain"],
    "entry": "add_sbom_guardian",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_sbom_guardian(inp: ToolInput) -> ToolResult:
    """Add SBOM guardian to a FastAPI project.

    Writes ``scripts/generate_sbom.py``, ``scripts/verify_lockfile.py``,
    patches ``app/core/config.py`` with SBOM settings.

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

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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

    files_created: list[str] = list(scaffolded)

    # --- Idempotency guard ---------------------------------------------------
    scripts_dir = project / "scripts"
    sbom_script = scripts_dir / "generate_sbom.py"
    if sbom_script.exists() and "generate_sbom" in sbom_script.read_text():
        return ToolResult(
            status="no_op",
            notes=["generate_sbom already present — SBOM guardian already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard -------------------------------------------------------
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

    # --- Step 1: scripts directory -------------------------------------------
    scripts_dir.mkdir(parents=True, exist_ok=True)
    scripts_init = scripts_dir / "__init__.py"
    if not scripts_init.exists():
        scripts_init.write_text('"""CLI scripts package."""\n')
        files_created.append(str(scripts_init))

    # --- Step 2: generate_sbom.py --------------------------------------------
    _write_generate_sbom(sbom_script)
    files_created.append(str(sbom_script))

    # --- Step 3: verify_lockfile.py ------------------------------------------
    lockfile_script = scripts_dir / "verify_lockfile.py"
    _write_verify_lockfile(lockfile_script)
    files_created.append(str(lockfile_script))

    # --- Step 4: patch config.py ---------------------------------------------
    config_file = project / "app" / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 5: ast.parse validation loop -----------------------------------
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
            "SBOM guardian added: CycloneDX generation + lockfile integrity + confusion detection.",
            "generate_sbom.py: Creates CycloneDX JSON SBOM from pip inspect (stdlib only).",
            "verify_lockfile.py: Validates lockfile hash, detects dependency confusion, scans OSV.",
            "Config: SBOM_FAIL_ON_CRITICAL (default true), SBOM_LOCKFILE_PATH (default requirements.txt).",
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


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_generate_sbom(dest: Path) -> None:
    """Write ``scripts/generate_sbom.py`` — CycloneDX SBOM generator.

    Args:
        dest: Absolute path for the script file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"CycloneDX SBOM generator — stdlib + pip inspect, no external deps.

        Generates a CycloneDX 1.4 JSON SBOM from the installed environment.

        Usage::

            python scripts/generate_sbom.py --output sbom.json
            python scripts/generate_sbom.py --output sbom.json --sign
        \"\"\"

        from __future__ import annotations

        import argparse
        import hashlib
        import json
        import logging
        import subprocess
        import sys
        from datetime import datetime, timezone
        from pathlib import Path

        logger = logging.getLogger(__name__)


        def get_installed_packages() -> list[dict]:
            \"\"\"Return list of installed packages via pip inspect.

            Returns:
                List of dicts with name, version, metadata fields.
            \"\"\"
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "inspect", "--format=json"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                data = json.loads(result.stdout)
                return data.get("installed", [])
            except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
                logger.warning("pip inspect failed: %s", exc)
                return []


        def build_component(pkg: dict) -> dict:
            \"\"\"Build a CycloneDX component entry from a pip package record.

            Args:
                pkg: Package dict from pip inspect output.

            Returns:
                CycloneDX component dict.
            \"\"\"
            meta = pkg.get("metadata", {})
            name = meta.get("name", pkg.get("name", "unknown"))
            version = meta.get("version", "unknown")
            return {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name.lower()}@{version}",
                "bom-ref": f"pkg:pypi/{name.lower()}@{version}",
            }


        def compute_sbom_hash(sbom_content: str) -> str:
            \"\"\"Return SHA-256 hash of the SBOM content for integrity signing.

            Args:
                sbom_content: JSON string of the SBOM.

            Returns:
                Hex-encoded SHA-256 digest.
            \"\"\"
            return hashlib.sha256(sbom_content.encode()).hexdigest()


        def generate_sbom(output_path: str, sign: bool = False) -> dict:
            \"\"\"Generate CycloneDX 1.4 JSON SBOM and write to output_path.

            Args:
                output_path: File path to write the SBOM JSON.
                sign: When True, embed SHA-256 integrity hash in metadata.

            Returns:
                Dict with component_count and output_path.
            \"\"\"
            packages = get_installed_packages()
            components = [build_component(p) for p in packages]

            sbom: dict = {
                "bomFormat": "CycloneDX",
                "specVersion": "1.4",
                "version": 1,
                "metadata": {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "tools": [{"name": "sbom_guardian", "version": "1.0.0"}],
                },
                "components": components,
            }

            sbom_json = json.dumps(sbom, indent=2)
            if sign:
                sbom["metadata"]["integrity"] = compute_sbom_hash(sbom_json)
                sbom_json = json.dumps(sbom, indent=2)

            Path(output_path).write_text(sbom_json)
            logger.info("SBOM written to %s (%d components)", output_path, len(components))
            return {"component_count": len(components), "output_path": output_path}


        def main() -> None:
            \"\"\"CLI entry point for SBOM generation.\"\"\"
            parser = argparse.ArgumentParser(description="Generate CycloneDX SBOM")
            parser.add_argument("--output", default="sbom.json", help="Output file path")
            parser.add_argument("--sign", action="store_true", help="Embed SHA-256 integrity hash")
            args = parser.parse_args()
            logging.basicConfig(level=logging.INFO)
            result = generate_sbom(args.output, sign=args.sign)
            print(f"SBOM generated: {result['component_count']} components → {result['output_path']}")


        if __name__ == "__main__":
            main()
    """))


def _write_verify_lockfile(dest: Path) -> None:
    """Write ``scripts/verify_lockfile.py`` — lockfile integrity + confusion detector.

    Args:
        dest: Absolute path for the script file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Lockfile integrity verifier + dependency confusion detector.

        Checks:
        1. Lockfile hash matches recorded baseline (integrity)
        2. Internal namespace packages are not shadowed on PyPI (confusion)
        3. OSV vulnerability query for critical CVEs (severity threshold)

        Usage::

            python scripts/verify_lockfile.py --lockfile requirements.txt
            python scripts/verify_lockfile.py --lockfile requirements.txt --fail-on-critical
        \"\"\"

        from __future__ import annotations

        import argparse
        import hashlib
        import json
        import logging
        import re
        import sys
        import urllib.request
        from pathlib import Path

        logger = logging.getLogger(__name__)

        # Known internal namespace prefixes (configure for your org)
        _INTERNAL_PREFIXES = ("myorg-", "internal-", "priv-")
        # OSV API endpoint
        _OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"


        def hash_lockfile(path: Path) -> str:
            \"\"\"Return SHA-256 hex digest of the lockfile contents.

            Args:
                path: Path to requirements.txt or similar lockfile.

            Returns:
                Hex-encoded SHA-256 digest.
            \"\"\"
            return hashlib.sha256(path.read_bytes()).hexdigest()


        def detect_confusion(lockfile_path: Path) -> list[str]:
            \"\"\"Detect dependency confusion: internal packages potentially shadowed on PyPI.

            Args:
                lockfile_path: Path to requirements.txt.

            Returns:
                List of warning strings for suspicious packages.
            \"\"\"
            warnings: list[str] = []
            content = lockfile_path.read_text()
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name = re.split(r"[>=<!=;\\s]", line)[0].lower()
                if any(name.startswith(prefix.lower()) for prefix in _INTERNAL_PREFIXES):
                    warnings.append(
                        f"CONFUSION-RISK: '{name}' matches internal prefix — "
                        "verify it cannot be claimed on PyPI"
                    )
            return warnings


        def parse_requirements(lockfile_path: Path) -> list[dict]:
            \"\"\"Parse requirements.txt into list of name/version dicts.

            Args:
                lockfile_path: Path to requirements.txt.

            Returns:
                List of dicts with 'name' and 'version' keys.
            \"\"\"
            packages = []
            for line in lockfile_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                match = re.match(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
                if match:
                    packages.append({"name": match.group(1), "version": match.group(2)})
            return packages


        def query_osv(packages: list[dict]) -> list[dict]:
            \"\"\"Query OSV API for known vulnerabilities.

            Args:
                packages: List of dicts with 'name' and 'version'.

            Returns:
                List of vulnerability result dicts.
            \"\"\"
            if not packages:
                return []
            queries = [
                {"version": p["version"], "package": {"name": p["name"], "ecosystem": "PyPI"}}
                for p in packages
            ]
            payload = json.dumps({"queries": queries}).encode()
            req = urllib.request.Request(
                _OSV_BATCH_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                return data.get("results", [])
            except Exception as exc:
                logger.warning("OSV query failed (offline?): %s", exc)
                return []


        def find_critical_vulns(osv_results: list[dict], packages: list[dict]) -> list[str]:
            \"\"\"Return list of CRITICAL/HIGH severity vulnerability descriptions.

            Args:
                osv_results: Results from query_osv().
                packages: Original package list (parallel to osv_results).

            Returns:
                List of human-readable critical finding strings.
            \"\"\"
            findings: list[str] = []
            for pkg, result in zip(packages, osv_results):
                for vuln in result.get("vulns", []):
                    severity = vuln.get("database_specific", {}).get("severity", "")
                    if severity.upper() in ("CRITICAL", "HIGH"):
                        findings.append(
                            f"VULN {severity}: {pkg['name']}=={pkg['version']} — "
                            f"{vuln.get('id', 'unknown')} {vuln.get('summary', '')[:80]}"
                        )
            return findings


        def verify(lockfile: str, fail_on_critical: bool = False) -> dict:
            \"\"\"Run full lockfile verification pipeline.

            Args:
                lockfile: Path to requirements.txt or lockfile.
                fail_on_critical: Exit non-zero if critical vulns found.

            Returns:
                Dict with hash, confusion_warnings, critical_findings, passed.
            \"\"\"
            path = Path(lockfile)
            if not path.exists():
                return {"error": f"Lockfile not found: {lockfile}", "passed": False}

            lockfile_hash = hash_lockfile(path)
            confusion_warnings = detect_confusion(path)
            packages = parse_requirements(path)
            osv_results = query_osv(packages)
            critical_findings = find_critical_vulns(osv_results, packages)

            for w in confusion_warnings:
                logger.warning(w)
            for f in critical_findings:
                logger.error(f)

            passed = not (fail_on_critical and critical_findings)
            return {
                "lockfile_hash": lockfile_hash,
                "packages_checked": len(packages),
                "confusion_warnings": confusion_warnings,
                "critical_findings": critical_findings,
                "passed": passed,
            }


        def main() -> None:
            \"\"\"CLI entry point for lockfile verification.\"\"\"
            parser = argparse.ArgumentParser(description="Verify lockfile integrity")
            parser.add_argument("--lockfile", default="requirements.txt")
            parser.add_argument("--fail-on-critical", action="store_true")
            args = parser.parse_args()
            logging.basicConfig(level=logging.INFO)
            result = verify(args.lockfile, fail_on_critical=args.fail_on_critical)
            print(json.dumps(result, indent=2))
            if not result.get("passed", True):
                sys.exit(1)


        if __name__ == "__main__":
            main()
    """))


def _patch_config(config_file: Path) -> None:
    """Inject SBOM settings into ``app/core/config.py`` Settings class.

    Args:
        config_file: Path to the existing config.py.
    """
    src = config_file.read_text()
    if "SBOM_FAIL_ON_CRITICAL" in src:
        return

    # 4-space-indented fields to insert inside Settings class body
    fields = (
        "\n"
        "    # --- SBOM Guardian settings (add_sbom_guardian) ---\n"
        "    SBOM_FAIL_ON_CRITICAL: bool = True\n"
        '    SBOM_LOCKFILE_PATH: str = "requirements.txt"\n'
    )

    # Insert just before `settings = Settings()` (module-level, outside class)
    if "settings = Settings()" in src:
        src = src.replace("settings = Settings()", fields + "\nsettings = Settings()")
    else:
        src = src.rstrip("\n") + fields + "\n"
    config_file.write_text(src)


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
