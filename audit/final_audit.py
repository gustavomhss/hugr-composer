"""Final comprehensive audit — runs every test suite and produces a single report.

Each suite is invoked via subprocess so failures are isolated.
Exit code 0 when ALL suites green, 1 otherwise.

Usage::

    cd skills/SKILL-001-fastapi-production
    PYTHONPATH=. python3 audit/final_audit.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).parent.parent
REPORTS_DIR = SKILL_ROOT / "audit" / "reports"

PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Suite definitions
# ---------------------------------------------------------------------------
# Each entry: (display_name, command_args, expected_label)
# command_args: list of args passed to subprocess (PYTHONPATH=. is set via env)
# expected_label: shown in the "Expected" column of the report

SUITES: list[tuple[str, list[str], str]] = [
    (
        "Unit tests (adapt/)",
        [PYTHON, "-m", "pytest", "adapt/", "-q", "--tb=no", "--no-header"],
        "1280+",
    ),
    (
        "Boot individual",
        [PYTHON, "tests/test_boot.py"],
        "27/27",
    ),
    (
        "Boot chains",
        [PYTHON, "tests/test_boot_chains.py"],
        "5/5",
    ),
    (
        "Property tests",
        [PYTHON, "tests/property_tests.py"],
        "5/5 properties",
    ),
    (
        "E2E advanced",
        [PYTHON, "tests/e2e_advanced.py"],
        "4/4",
    ),
    (
        "Red team",
        [PYTHON, "audit/red_team.py"],
        "25/25",
    ),
    (
        "HTTP smoke",
        [PYTHON, "-m", "pytest", "tests/test_http_smoke.py", "-q", "--tb=short", "--no-header"],
        "5/5",
    ),
    (
        "Spec compliance",
        [PYTHON, "-m", "pytest", "tests/test_spec_compliance.py", "-q", "--tb=short", "--no-header"],
        "79/79",
    ),
    (
        "Stress test",
        [PYTHON, "tests/test_stress.py"],
        "3/3",
    ),
    (
        "Security generated",
        [PYTHON, "-m", "pytest", "tests/test_security_generated.py", "-q", "--tb=short", "--no-header"],
        "15/15",
    ),
    (
        "Consistency",
        [PYTHON, "tests/test_consistency.py"],
        "6/6",
    ),
    (
        "Concurrent",
        [PYTHON, "tests/test_concurrent.py"],
        "3/3",
    ),
    (
        "Bandit + deps",
        [PYTHON, "-m", "pytest", "tests/test_bandit_deps.py", "-q", "--tb=short", "--no-header"],
        "3/3",
    ),
    (
        "Determinism",
        [PYTHON, "tests/test_determinism.py"],
        "4/4",
    ),
    (
        "Edge cases",
        [PYTHON, "tests/test_edge_cases.py"],
        "7/7",
    ),
    (
        "Generated quality",
        [PYTHON, "-m", "pytest", "tests/test_generated_quality.py", "-q", "--tb=short", "--no-header"],
        "13/13",
    ),
    (
        "Lint generated",
        [PYTHON, "-m", "pytest", "tests/test_lint_generated.py", "-q", "--tb=short", "--no-header"],
        "8/8",
    ),
    (
        "Benchmark score (Phase-3 harness)",
        [PYTHON, "-c",
         "import json, pathlib; d=json.loads(pathlib.Path('benchmarks/latest_score.json').read_text());"
         " print(f\"overall={d['overall']:.2f}  methodology={d['methodology']}\");"
         " raise SystemExit(0 if d['overall'] >= 30 else 1)"],
        "overall >= 30",
    ),
    (
        "Contract (37 rules)",
        [PYTHON, "-m", "engine.audit.contract_check", "--quiet"],
        "37/37 green",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(SKILL_ROOT),
            timeout=5,
        )
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _extract_result_line(stdout: str, stderr: str) -> str:
    """Extract a short result summary from subprocess output."""
    combined = stdout + "\n" + stderr
    lines = [l.strip() for l in combined.splitlines() if l.strip()]

    # Prefer lines with typical result patterns
    patterns = [
        r"\d+/\d+",           # N/N
        r"passed",
        r"PASS",
        r"FAIL",
        r"Grade",
        r"RESULT",
        r"checks passed",
    ]
    for line in reversed(lines):
        for pat in patterns:
            if re.search(pat, line, re.IGNORECASE):
                # Truncate long lines
                return line[:120]
    # Fallback: last non-empty line
    return lines[-1][:120] if lines else ""


def _run_suite(name: str, args: list[str]) -> dict:
    """Run one suite, return result dict."""
    env = {
        "PYTHONPATH": str(SKILL_ROOT),
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    }
    # Inherit HOME and other safe vars
    import os
    for key in ("HOME", "LANG", "TMPDIR", "VIRTUAL_ENV"):
        if key in os.environ:
            env[key] = os.environ[key]

    t0 = time.monotonic()
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(SKILL_ROOT),
            env=env,
            timeout=600,  # 10 min max per suite
        )
        elapsed_s = time.monotonic() - t0
        passed = r.returncode == 0
        result_line = _extract_result_line(r.stdout, r.stderr)
        return {
            "name": name,
            "passed": passed,
            "returncode": r.returncode,
            "elapsed_s": elapsed_s,
            "result_line": result_line,
            "stdout_tail": r.stdout[-800:] if r.stdout else "",
            "stderr_tail": r.stderr[-400:] if r.stderr else "",
        }
    except subprocess.TimeoutExpired:
        elapsed_s = time.monotonic() - t0
        return {
            "name": name,
            "passed": False,
            "returncode": -1,
            "elapsed_s": elapsed_s,
            "result_line": "TIMEOUT (>600s)",
            "stdout_tail": "",
            "stderr_tail": "",
        }
    except Exception as exc:
        elapsed_s = time.monotonic() - t0
        return {
            "name": name,
            "passed": False,
            "returncode": -2,
            "elapsed_s": elapsed_s,
            "result_line": f"RUNNER ERROR: {exc}",
            "stdout_tail": "",
            "stderr_tail": "",
        }


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def _bool_icon(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _build_report(
    timestamp: str,
    git_sha: str,
    results: list[dict],
    suites_meta: list[tuple[str, list[str], str]],
    elapsed_total: float,
) -> str:
    lines: list[str] = []
    a = lines.append

    total = len(results)
    green = sum(1 for r in results if r["passed"])
    all_green = green == total

    a("# SKILL-001 — Final Audit Report")
    a("")
    a(f"**Timestamp:** {timestamp}")
    a(f"**Git SHA:** `{git_sha}`")
    a(f"**Total elapsed:** {elapsed_total:.1f}s")
    a(f"**Suites:** {green}/{total} green")
    a("")

    # Grade
    if all_green:
        a("## Grade: A+ — ALL SUITES GREEN")
    else:
        pct = int(green / total * 100)
        a(f"## Grade: {pct}% — {green}/{total} suites green")
    a("")

    # Results table
    a("## Suite Results")
    a("")
    a("| # | Suite | Expected | Result | Elapsed |")
    a("|---|-------|----------|--------|---------|")

    for i, (r, meta) in enumerate(zip(results, suites_meta), 1):
        _, _, expected = meta
        icon = "✅" if r["passed"] else "❌"
        result_cell = r["result_line"].replace("|", "/")
        a(
            f"| {i} | {r['name']} | `{expected}` | "
            f"{icon} {_bool_icon(r['passed'])} — {result_cell} | "
            f"{r['elapsed_s']:.1f}s |"
        )

    a("")

    # Total checks summary
    a("## Check Counts")
    a("")
    a("| Category | Count |")
    a("|----------|-------|")
    a("| Unit tests (adapt/) | 1280+ |")
    a("| Boot individual tools | 27 |")
    a("| Boot chains | 5 |")
    a("| Property checks | 5 properties × 51 tools |")
    a("| E2E advanced scenarios | 4 |")
    a("| Red team attacks | 25 |")
    a("| HTTP smoke tests | 5 |")
    a("| Spec compliance | 79 |")
    a("| Stress tests | 3 |")
    a("| Security generated | 15 |")
    a("| Consistency checks | 6 |")
    a("| Concurrent tests | 3 |")
    a("| Bandit + deps | 3 |")
    a("| Determinism tests | 4 |")
    a("| Edge case tests | 7 |")
    a("| Generated quality | 13 |")
    a("| Lint generated | 8 |")
    a("| Benchmark checks | 100 |")
    a("")

    # Known issues / failures
    failed_suites = [r for r in results if not r["passed"]]
    if failed_suites:
        a("## Known Issues")
        a("")
        for r in failed_suites:
            a(f"### {r['name']}")
            a("")
            a(f"- Return code: `{r['returncode']}`")
            a(f"- Summary: {r['result_line']}")
            if r["stdout_tail"]:
                a("")
                a("```")
                a(r["stdout_tail"][-600:])
                a("```")
            if r["stderr_tail"]:
                a("")
                a("```")
                a(r["stderr_tail"][-300:])
                a("```")
            a("")
    else:
        a("## Known Issues")
        a("")
        a("None — all suites green.")
        a("")

    a("---")
    a("")
    if all_green:
        a(f"**Final: {green}/{total} suites green — ALL GREEN**")
    else:
        a(f"**Final: {green}/{total} suites green — {total - green} FAILING**")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_final_audit() -> int:
    """Run all suites and produce the definitive report.

    Returns:
        0 if all suites pass, 1 otherwise.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(tz=timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    date_tag = now.strftime("%Y-%m-%d")
    git_sha = _git_sha()

    print("=" * 70)
    print("SKILL-001 — Final Comprehensive Audit")
    print(f"Timestamp : {timestamp}")
    print(f"Git SHA   : {git_sha}")
    print(f"Suites    : {len(SUITES)}")
    print("=" * 70)
    print()

    t_global = time.monotonic()
    results: list[dict] = []

    for i, (name, args, expected) in enumerate(SUITES, 1):
        print(f"[{i:02d}/{len(SUITES):02d}] {name} … ", end="", flush=True)
        r = _run_suite(name, args)
        results.append(r)
        status = "PASS" if r["passed"] else "FAIL"
        print(f"{status}  ({r['elapsed_s']:.1f}s)  {r['result_line'][:80]}")

    elapsed_total = time.monotonic() - t_global

    green = sum(1 for r in results if r["passed"])
    total = len(results)
    all_green = green == total

    print()
    print("=" * 70)
    print(f"RESULT: {green}/{total} suites green  ({elapsed_total:.1f}s total)")
    if not all_green:
        print()
        print("FAILED suites:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['result_line'][:100]}")
    print("=" * 70)

    report_md = _build_report(timestamp, git_sha, results, SUITES, elapsed_total)
    report_path = REPORTS_DIR / f"FINAL_AUDIT_{date_tag}.md"
    report_path.write_text(report_md, encoding="utf-8")

    print()
    print(f"Report: {report_path}")
    print()
    print(f"Final audit: {green}/{total} suites green")

    return 0 if all_green else 1


if __name__ == "__main__":
    sys.exit(run_final_audit())
