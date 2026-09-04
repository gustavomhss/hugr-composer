#!/usr/bin/env python
"""Run pip-audit locally with same settings as CI."""
import subprocess
import sys

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
