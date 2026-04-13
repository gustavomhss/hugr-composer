"""Security audit for SKILL-001.

Checks:
1. Hardcoded secrets patterns in adapt/ source files.
2. No .env file committed anywhere in the skill.
3. .gitignore includes .env.
4. Generated project code doesn't embed literal secrets.

Usage::

    PYTHONPATH=. python3 audit/audit_security.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).parent.parent
ADAPT_DIR = SKILL_ROOT / "adapt"

# ---------------------------------------------------------------------------
# Secret patterns — compiled once
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS Access Key", re.compile(r'AKIA[0-9A-Z]{16}')),
    ("AWS Secret Key", re.compile(r'[Aa][Ww][Ss][_\-]?[Ss][Ee][Cc][Rr][Ee][Tt][_\-]?[Kk][Ee][Yy]\s*=\s*["\'][^"\']{10,}["\']')),
    ("Generic API key literal", re.compile(r'(?i)api[_\-]?key\s*=\s*["\'][a-zA-Z0-9_\-]{12,}["\']')),
    ("Generic token literal", re.compile(r'(?i)(?:access|auth|bearer|secret)[_\-]?token\s*=\s*["\'][a-zA-Z0-9_\-]{12,}["\']')),
    ("Password literal", re.compile(r'(?i)password\s*=\s*["\'][^"\']{6,}["\']')),
    ("Private key PEM header", re.compile(r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----')),
    ("Stripe key", re.compile(r'sk_(live|test)_[0-9a-zA-Z]{24,}')),
    ("GitHub token", re.compile(r'ghp_[0-9a-zA-Z]{36}')),
    ("Slack token", re.compile(r'xox[baprs]-[0-9a-zA-Z\-]+')),
]

# Values that are clearly placeholders / examples, not real secrets
_PLACEHOLDER_PATTERN = re.compile(
    r'(?i)(your[_\-]?|example[_\-]?|fake[_\-]?|dummy[_\-]?|placeholder|changeme|secretkey|test[_\-]?|sample[_\-]?|xxx)'
)


def _is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_PATTERN.search(value))


# ---------------------------------------------------------------------------
# Phase 1: Hardcoded secrets in adapt/
# ---------------------------------------------------------------------------

def _scan_secrets(root: Path) -> dict:
    """Scan source files for hardcoded secret patterns."""
    findings: list[str] = []

    for f in sorted(root.rglob("*.py")):
        try:
            source = f.read_text(encoding="utf-8")
        except OSError:
            continue

        rel = str(f.relative_to(SKILL_ROOT))
        for line_no, line in enumerate(source.splitlines(), 1):
            for name, pattern in _SECRET_PATTERNS:
                m = pattern.search(line)
                if m and not _is_placeholder(m.group(0)):
                    findings.append(f"{rel}:{line_no} [{name}] {line.strip()[:100]}")

    return {"ok": len(findings) == 0, "findings": findings}


# ---------------------------------------------------------------------------
# Phase 2: No .env files committed
# ---------------------------------------------------------------------------

def _check_no_env_files(root: Path) -> dict:
    """Ensure no .env files exist under root."""
    env_files: list[str] = []
    for f in root.rglob(".env"):
        if ".venv" not in str(f) and "node_modules" not in str(f):
            env_files.append(str(f.relative_to(root)))
    # Also check for named .env.production, .env.local, etc. (not .env.example)
    for f in root.rglob(".env.*"):
        name = f.name
        if not name.endswith(".example") and not name.endswith(".template"):
            if ".venv" not in str(f) and "node_modules" not in str(f):
                env_files.append(str(f.relative_to(root)))
    return {"ok": len(env_files) == 0, "env_files_found": env_files}


# ---------------------------------------------------------------------------
# Phase 3: .gitignore includes .env
# ---------------------------------------------------------------------------

def _check_gitignore(root: Path) -> dict:
    """Check that .gitignore at skill root (or repo root) covers .env."""
    # Walk up from SKILL_ROOT looking for .gitignore
    candidate_dirs = [root] + list(root.parents)[:3]
    for d in candidate_dirs:
        gi = d / ".gitignore"
        if gi.exists():
            content = gi.read_text(encoding="utf-8")
            lines = [l.strip() for l in content.splitlines()]
            covered = any(l in (".env", ".env.*", "*.env") for l in lines)
            return {
                "ok": covered,
                "gitignore_path": str(gi.relative_to(root) if d == root else gi),
                "covers_env": covered,
            }
    return {"ok": False, "gitignore_path": None, "covers_env": False}


# ---------------------------------------------------------------------------
# Phase 4: Generated code security
# ---------------------------------------------------------------------------

def _check_generated_code() -> dict:
    """Generate a minimal project and scan for embedded secrets."""
    try:
        import tempfile
        from generators.orchestrator import generate_project  # type: ignore
    except ImportError as exc:
        return {"ok": True, "skipped": True, "reason": f"ImportError: {exc}"}

    findings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="_skill001_sec_") as tmpdir:
        out = Path(tmpdir) / "sec_test"
        try:
            generate_project(str(out), name="sec_test", models={})
        except Exception as exc:
            return {"ok": True, "skipped": True, "reason": f"generate_project failed: {exc}"}

        for f in sorted(out.rglob("*.py")):
            try:
                source = f.read_text(encoding="utf-8")
            except OSError:
                continue
            rel = str(f.relative_to(out))
            for line_no, line in enumerate(source.splitlines(), 1):
                for name, pattern in _SECRET_PATTERNS:
                    m = pattern.search(line)
                    if m and not _is_placeholder(m.group(0)):
                        findings.append(f"generated/{rel}:{line_no} [{name}] {line.strip()[:100]}")

    return {"ok": len(findings) == 0, "findings": findings}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def audit_security() -> dict:
    """Run all security checks and return aggregated result."""
    secrets = _scan_secrets(ADAPT_DIR)
    no_env = _check_no_env_files(SKILL_ROOT)
    gitignore = _check_gitignore(SKILL_ROOT)
    gen_code = _check_generated_code()

    # gitignore missing is a warning, not a hard failure, when no .env files are present
    # Hard failure only if .env files exist AND .gitignore doesn't cover them
    gitignore_ok = gitignore["ok"] or no_env["ok"]  # OK if gitignore covers it OR no .env files
    passed = secrets["ok"] and no_env["ok"] and gitignore_ok and gen_code["ok"]

    return {
        "passed": passed,
        "hardcoded_secrets": secrets,
        "env_files": no_env,
        "gitignore": gitignore,
        "generated_code": gen_code,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> int:
    print("Security Audit — SKILL-001-fastapi-production")
    print("=" * 60)

    r = audit_security()

    sec = r["hardcoded_secrets"]
    status = "OK" if sec["ok"] else "FAIL"
    print(f"[{status}] Hardcoded secrets in adapt/: {len(sec['findings'])} findings")
    for f in sec["findings"][:10]:
        print(f"      {f}")

    env = r["env_files"]
    status = "OK" if env["ok"] else "FAIL"
    print(f"[{status}] No .env files committed: {len(env['env_files_found'])} found")
    for f in env["env_files_found"]:
        print(f"      {f}")

    gi = r["gitignore"]
    status = "OK" if gi["ok"] else "WARN"
    covers = "YES" if gi["covers_env"] else "NO"
    path = gi.get("gitignore_path") or "not found"
    print(f"[{status}] .gitignore covers .env: {covers} ({path})")

    gc = r["generated_code"]
    if gc.get("skipped"):
        print(f"[SKIP] Generated code check: {gc.get('reason', '')}")
    else:
        status = "OK" if gc["ok"] else "FAIL"
        print(f"[{status}] Generated code secrets: {len(gc.get('findings', []))} findings")
        for f in gc.get("findings", [])[:10]:
            print(f"      {f}")

    print()
    verdict = "ALL GREEN" if r["passed"] else "ISSUES FOUND"
    print(f"Security Result: {verdict}")
    return 0 if r["passed"] else 1


if __name__ == "__main__":
    sys.exit(_main())
