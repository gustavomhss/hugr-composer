"""Per-example pytest matrix — 20 examples × (import + pytest) attestation.

Opus HIGH-6 / Codex Q1: 20 examples had per-example bandit + semgrep but
no per-example "boots + tests pass" evidence. This probe closes that.

Each of the 20 `/examples/NN-*/` directories is a pedagogical reference
(not a generator-emitted scaffold; fresh-emit evidence lives in
external-eval). Each has `app.py` + `test_app.py` + `conftest.py`. The
canonical verification is: Python can import app.py without error AND
pytest passes all tests in test_app.py.

Checks per example:
    1. app_py_present
    2. test_py_present
    3. app_imports_ok (`python -c "import app"` exit 0)
    4. pytest_passes (`pytest test_app.py -q` exit 0)
    5. pytest_pass_count + pytest_fail_count + pytest_skipped_count (informative)

Output JSON:
    evidence/deterministic/per_example_pytest_matrix.json
    {
      "_meta": {...},
      "examples_scanned": 20,
      "per_example": [{name, checks, tests_passed, tests_failed, duration_s}],
      "summary": {pass, total, total_tests, passed}
    }

Exit 0 iff all 20 pass all 4 required checks.

Runtime: ~60s total (pytest invoked 20× sequentially; each example has
3-8 tests).
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import subprocess
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
EXAMPLES_ROOT = REPO_ROOT / "examples"
VENV_PY = REPO_ROOT / "skills" / "SKILL-001-fastapi-production" / ".venv" / "bin" / "python"

CHECKS = [
    "app_py_present",
    "test_py_present",
    "app_imports_ok",
    "pytest_passes",
]


def _import_app(ex_dir: pathlib.Path) -> tuple[bool, str]:
    r = subprocess.run(
        [str(VENV_PY), "-c", "import app"],
        cwd=ex_dir,
        capture_output=True,
        text=True,
    )
    tail = (r.stderr or r.stdout).strip().splitlines()
    return (r.returncode == 0, tail[-1] if tail else "ok")


def _pytest_run(ex_dir: pathlib.Path) -> tuple[bool, dict]:
    start = time.monotonic()
    r = subprocess.run(
        [str(VENV_PY), "-m", "pytest", "test_app.py", "-q", "--tb=line", "-p", "no:cacheprovider"],
        cwd=ex_dir,
        capture_output=True,
        text=True,
    )
    duration_s = round(time.monotonic() - start, 2)
    output = (r.stdout + r.stderr).strip()
    summary_line = output.splitlines()[-1] if output else ""
    m = re.search(r"(\d+) passed", summary_line)
    passed_n = int(m.group(1)) if m else 0
    f = re.search(r"(\d+) failed", summary_line)
    failed_n = int(f.group(1)) if f else 0
    s = re.search(r"(\d+) skipped", summary_line)
    skipped_n = int(s.group(1)) if s else 0
    return (r.returncode == 0, {
        "summary_line": summary_line,
        "duration_s": duration_s,
        "passed": passed_n,
        "failed": failed_n,
        "skipped": skipped_n,
        "exit_code": r.returncode,
    })


def audit_example(ex_dir: pathlib.Path) -> dict:
    app = ex_dir / "app.py"
    test = ex_dir / "test_app.py"
    checks = {
        "app_py_present": app.exists(),
        "test_py_present": test.exists(),
        "app_imports_ok": False,
        "pytest_passes": False,
    }
    pytest_details = {}
    import_note = ""
    if app.exists():
        ok, import_note = _import_app(ex_dir)
        checks["app_imports_ok"] = ok
    if test.exists():
        pt_ok, pytest_details = _pytest_run(ex_dir)
        checks["pytest_passes"] = pt_ok
    return {
        "name": ex_dir.name,
        "checks": checks,
        "pytest": pytest_details,
        "import_note": import_note,
        "all_pass": all(checks.values()),
    }


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def main() -> int:
    examples = sorted(
        p for p in EXAMPLES_ROOT.iterdir()
        if p.is_dir() and p.name[0:2].isdigit()
    )
    per_example = [audit_example(e) for e in examples]
    total = len(per_example)
    all_pass = sum(1 for r in per_example if r["all_pass"])
    total_tests = sum((r["pytest"] or {}).get("passed", 0) for r in per_example)
    total_failed = sum((r["pytest"] or {}).get("failed", 0) for r in per_example)
    passed = (all_pass == total) and (total == 20) and (total_failed == 0)

    out = {
        "_meta": {
            "command": ".venv/bin/python evidence/_harness/per_example_pytest_matrix.py",
            "cwd": "repo root",
            "commit": _git("rev-parse", "HEAD"),
            "tree": _git("rev-parse", "HEAD^{tree}"),
            "generated": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "grading": "exit 0 iff 20 examples pass all 4 checks AND zero pytest failures",
        },
        "examples_scanned": total,
        "checks": CHECKS,
        "summary": {
            "examples_pass": all_pass,
            "total_examples": total,
            "total_tests_passed": total_tests,
            "total_tests_failed": total_failed,
            "passed": passed,
        },
        "per_example": per_example,
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
