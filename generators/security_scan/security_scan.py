"""Generator for security scanning (pip-audit, safety, bandit, trivy)."""

from __future__ import annotations

import textwrap
from pathlib import Path

MCP_TOOL = {
    "name": "fastapi_security_scan_generate",
    "description": "Generate security scanning configuration (pip-audit, bandit, trivy, dependabot).",
    "tags": ["generator", "security_scan"],
    "entry": "generate_security_scan",
}


def generate_security_scan(
    output_dir: str,
    include_dependabot: bool = True,
    include_trivy: bool = True,
) -> dict:
    """Generate security scanning configuration files.

    Args:
        output_dir: Root directory of the generated project.
        include_dependabot: Whether to generate dependabot.yml.
        include_trivy: Whether to generate Trivy config.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir)
    files_created = []
    notes = []

    # 1. pip-audit in CI (already in CI, but add pre-commit hook)
    pre_commit_config = textwrap.dedent("""\
        # pre-commit-config.yaml — security-focused hooks
        repos:
        - repo: https://github.com/pycqa/bandit
          rev: "1.7.5"
          hooks:
          - id: bandit
            args: ["-r", "app", "-ll", "-f", "json", "-o", "bandit-report.json"]
            stages: [commit, push]

        - repo: https://github.com/pycqa/isort
          rev: "5.12.0"
          hooks:
          - id: isort
            args: ["--profile=black", "--filter-files"]

        - repo: https://github.com/psf/black
          rev: "23.12.1"
          hooks:
          - id: black
            language_version: python3.12

        - repo: https://github.com/pycqa/flake8
          rev: "6.1.0"
          hooks:
          - id: flake8
            args: ["--max-line-length=100", "--extend-ignore=E203,W503"]

        - repo: https://github.com/PyCQA/flake8-bandit
          rev: "4.0.0"
          hooks:
          - id: flake8-bandit

        - repo: https://github.com/PyCQA/flake8-bugbear
          rev: "23.9.1"
          hooks:
          - id: flake8-bugbear

        - repo: https://github.com/PyCQA/bandit
          rev: "1.7.5"
          hooks:
          - id: bandit
            args: ["-r", "app", "-ll"]
    """)
    pre_commit_path = out / "pre-commit-config.yaml"
    pre_commit_path.write_text(textwrap.dedent(pre_commit_config))
    files_created = ["pre-commit-config.yaml"]
    notes.append("pre-commit-config.yaml with bandit, isort, black, flake8, flake8-bandit, flake8-bugbear")

    # 2. Dependabot configuration
    if include_dependabot:
        dependabot_config = textwrap.dedent("""\
            # dependabot.yml — automated dependency updates
            version: 2
            updates:
              # Python dependencies
              - package-ecosystem: "pip"
                directory: "/"
                schedule:
                  interval: "weekly"
                  day: "monday"
                  time: "04:00"
                  timezone: "UTC"
                open-pull-requests-limit: 10
                reviewers:
                  - "security-team"
                labels:
                  - "dependencies"
                  - "security"
                allow:
                  - dependency-type: "direct"
                  - dependency-type: "indirect"
                ignore:
                  - dependency-name: "*"
                    versions: ["*"]  # Use for pinning if needed
                commit-message:
                  prefix: "deps(pip): "
                  prefix-development: "deps(pip-dev): "
                allow-unsecure-commands: false

              # GitHub Actions
              - package-ecosystem: "github-actions"
                directory: "/"
                schedule:
                  interval: "weekly"
                  day: "monday"
                  time: "04:00"
                  timezone: "UTC"
                open-pull-requests-limit: 5
                labels:
                  - "github-actions"
                  - "dependencies"
    """)
        dependabot_path = out / ".github" / "dependabot.yml"
        dependabot_path.parent.mkdir(parents=True, exist_ok=True)
        dependabot_path.write_text(textwrap.dedent(dependabot_config))
        files_created.append(".github/dependabot.yml")
        notes.append("dependabot.yml for automated dependency updates (pip + github-actions)")

    # 3. Trivy configuration for container scanning
    if include_trivy:
        trivy_config = textwrap.dedent("""\
            # trivy.yaml — Trivy vulnerability scanner config
            # Run: trivy image --config trivy.yaml <image>
            # Or in CI: trivy image --config trivy.yaml --exit-code 1 --severity HIGH,CRITICAL <image>

            scan:
              vuln-type:
                - os
                - lang
              severity:
                - HIGH
                - CRITICAL
              ignored-unfixed: true
              skip-dirs:
                - /usr/share/doc
                - /usr/share/man
                - /var/cache
                - /tmp
              skip-files:
                - "*.md"
                - "*.txt"
                - "*.rst"
              ignored-vulnerabilities: []
              ignore-unfixed: true

            report:
              format: "sarif"
              output: "trivy-results.sarif"

            db:
              download-timeout: 10m
              skip-update: false

            cache:
              dir: "/tmp/trivy-cache"
        """)
        trivy_path = out / "trivy.yaml"
        trivy_path.write_text(textwrap.dedent(trivy_config))
        files_created.append("trivy.yaml")
        notes.append("trivy.yaml for container vulnerability scanning (HIGH/CRITICAL only)")

    # 4. pip-audit in CI (documentation - already in CI template, but add local script)
    audit_script = '''\
        #!/usr/bin/env python
        """Run pip-audit locally with same settings as CI."""
        import subprocess
        import sys
        from pathlib import Path

        def run(cmd: list[str]) -> int:
            result = subprocess.run(cmd, capture_output=True, text=True)
            print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return result.returncode

        def main() -> int:
            import subprocess
            import sys

            # Check if requirements.lock exists
            lockfile = Path("requirements.lock")
            if not lockfile.exists():
                print("requirements.lock not found. Run pip-compile first.")
                return 1

            # Run pip-audit on lockfile
            cmd = [
                "pip-audit",
                "-r", "requirements.lock",
                "--format", "json",
                "--output", "pip-audit-report.json",
                "--desc", "on",
            ]
            print(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)

            if result.returncode != 0:
                print(f"pip-audit found vulnerabilities (exit code {result.returncode})")
                print("See pip-audit-report.json for details")
                return result.returncode

            print("No known vulnerabilities found")
            return 0

        if __name__ == "__main__":
            import sys
            sys.exit(main())
    '''
    audit_script_path = out / "scripts" / "audit_deps.py"
    audit_script_path.parent.mkdir(parents=True, exist_ok=True)
    audit_script_path.write_text(textwrap.dedent(audit_script))
    files_created.append("scripts/audit_deps.py")
    notes.append("scripts/audit_deps.py for local pip-audit runs")

    return {
        "files_created": files_created,
        "notes": notes,
    }


MCP_TOOL = {
    "name": "fastapi_security_scan_generate",
    "description": "Generate security scanning configuration (pip-audit, bandit, trivy, dependabot).",
    "tags": ["generator", "security_scan"],
    "entry": "generate_security_scan",
}