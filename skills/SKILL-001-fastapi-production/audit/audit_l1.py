"""L1 Correctness audit for SKILL-001.

Checks:
1. AST-parse every .py under adapt/ — zero syntax errors.
2. Run every test_*.py via subprocess — all must exit 0.
3. Orchestrator smoke-test — generate_project produces expected files.

Usage::

    PYTHONPATH=. python3 audit/audit_l1.py
    PYTHONPATH=. python3 audit/audit_l1.py --tests-only
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).parent.parent
ADAPT_DIR = SKILL_ROOT / "adapt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_py_files(root: Path):
    """Yield all .py files under root recursively."""
    return sorted(root.rglob("*.py"))


def _iter_test_files(root: Path):
    """Yield all test_*.py files under root recursively."""
    return sorted(root.rglob("test_*.py"))


# ---------------------------------------------------------------------------
# Phase 1: AST parse
# ---------------------------------------------------------------------------

def _check_parse(root: Path) -> dict:
    """Return parse results for all .py files under root."""
    errors: list[str] = []
    checked = 0
    for f in _iter_py_files(root):
        checked += 1
        try:
            ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            errors.append(f"{f.relative_to(SKILL_ROOT)}: {exc}")
    return {"checked": checked, "errors": errors}


# ---------------------------------------------------------------------------
# Phase 2: Run tests
# ---------------------------------------------------------------------------

def _run_tests(root: Path) -> dict:
    """Run every test_*.py and collect pass/fail."""
    test_files = _iter_test_files(root)
    total = len(test_files)
    passed = 0
    failed_details: list[str] = []

    for tf in test_files:
        result = subprocess.run(
            [sys.executable, str(tf)],
            capture_output=True,
            text=True,
            cwd=str(SKILL_ROOT),
            env={**__import__("os").environ, "PYTHONPATH": str(SKILL_ROOT)},
            timeout=120,
        )
        if result.returncode == 0:
            passed += 1
        else:
            rel = tf.relative_to(SKILL_ROOT)
            # Capture last 5 lines of output for the report
            combined = (result.stdout + result.stderr).strip()
            tail = "\n".join(combined.splitlines()[-5:]) if combined else "(no output)"
            failed_details.append(f"{rel}:\n{tail}")

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "failed_details": failed_details,
    }


# ---------------------------------------------------------------------------
# Phase 3: Orchestrator smoke-test
# ---------------------------------------------------------------------------

def _smoke_orchestrator() -> dict:
    """Generate a minimal project and confirm key files exist."""
    try:
        from generators.orchestrator import generate_project  # type: ignore
    except ImportError as exc:
        return {"ok": False, "error": f"ImportError: {exc}", "files_found": 0}

    with tempfile.TemporaryDirectory(prefix="_skill001_audit_") as tmpdir:
        out = Path(tmpdir) / "smoke"
        try:
            result = generate_project(str(out), name="smoke", models={})
        except Exception as exc:
            return {"ok": False, "error": str(exc), "files_found": 0}

        expected = [
            "app/main.py",
            "app/core/config.py",
            "alembic.ini",
            "Dockerfile",
            ".env.example",
        ]
        missing = [e for e in expected if not (out / e).exists()]
        raw = result.get("files_created", result.get("total_files", 0))
        created = len(raw) if isinstance(raw, list) else int(raw or 0)
        return {
            "ok": len(missing) == 0,
            "missing_expected": missing,
            "files_created": created,
            "error": None,
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def audit_l1_correctness(*, tests_only: bool = False) -> dict:
    """Run the full L1 correctness audit.

    Args:
        tests_only: When True, only run the test-runner phase.

    Returns:
        Result dict with ``passed`` bool and per-phase details.
    """
    results: dict = {}

    if not tests_only:
        parse = _check_parse(ADAPT_DIR)
        results["parse"] = parse

    test_run = _run_tests(ADAPT_DIR)
    results["tests"] = test_run

    if not tests_only:
        smoke = _smoke_orchestrator()
        results["orchestrator_smoke"] = smoke

    # Overall pass/fail
    parse_ok = tests_only or (len(results["parse"]["errors"]) == 0)
    tests_ok = test_run["failed"] == 0
    smoke_ok = tests_only or results["orchestrator_smoke"]["ok"]

    results["passed"] = parse_ok and tests_ok and smoke_ok
    results["tests_run"] = test_run["total"]
    results["tests_passed"] = test_run["passed"]
    results["parse_errors"] = [] if tests_only else results["parse"]["errors"]
    results["details"] = results

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    tests_only = "--tests-only" in argv

    print("L1 Correctness Audit — SKILL-001-fastapi-production")
    print("=" * 60)

    results = audit_l1_correctness(tests_only=tests_only)

    if not tests_only:
        parse = results["parse"]
        status = "OK" if not parse["errors"] else "FAIL"
        print(f"[{status}] Parse check: {parse['checked']} files, {len(parse['errors'])} errors")
        for e in parse["errors"][:10]:
            print(f"      {e}")

    tr = results["tests"]
    status = "OK" if tr["failed"] == 0 else "FAIL"
    print(f"[{status}] Test runner: {tr['passed']}/{tr['total']} passed")
    for d in tr["failed_details"][:5]:
        print(f"  FAILED: {d[:200]}")

    if not tests_only:
        smoke = results["orchestrator_smoke"]
        status = "OK" if smoke["ok"] else "FAIL"
        fc = smoke.get('files_created', '?')
        fc_display = len(fc) if isinstance(fc, list) else fc
        print(f"[{status}] Orchestrator smoke: {fc_display} files created")
        if not smoke["ok"]:
            print(f"      Error: {smoke.get('error')}")
            for m in smoke.get("missing_expected", []):
                print(f"      Missing: {m}")

    print()
    verdict = "ALL GREEN" if results["passed"] else "ISSUES FOUND"
    print(f"L1 Result: {verdict}")
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
