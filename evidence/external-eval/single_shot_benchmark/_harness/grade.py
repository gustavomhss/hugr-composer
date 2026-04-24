"""Grade a single single_shot_benchmark run.

Called by `run.py` after each Maestro session. Produces a per-spec
record under `results.json` and returns pass/fail for logging.

4-check rubric:
    1. Emitted project boots (`.venv/bin/uvicorn` returns 200 on /healthz).
    2. Emitted test_*.py all pass.
    3. Bandit clean on emitted app/ (0 HIGH + 0 MEDIUM).
    4. All acceptance criteria in spec covered by at least one emitted test
       (grep-based — each AC string appears in at least one test docstring).

Pass = 4/4 green.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import time


def _uvicorn_boot(project_dir: pathlib.Path, timeout_s: int = 30) -> tuple[bool, str]:
    """Start the emitted uvicorn, curl /healthz, return (ok, reason)."""
    venv_uvicorn = project_dir / ".venv" / "bin" / "uvicorn"
    if not venv_uvicorn.exists():
        return False, f"no {venv_uvicorn}"
    proc = subprocess.Popen(
        [str(venv_uvicorn), "app.main:app", "--port", "8799"],
        cwd=project_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                import urllib.request
                resp = urllib.request.urlopen("http://127.0.0.1:8799/healthz", timeout=2)
                if resp.status == 200:
                    return True, "healthz 200"
            except Exception:
                time.sleep(0.5)
        return False, f"timeout after {timeout_s}s"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def _pytest_all_pass(project_dir: pathlib.Path) -> tuple[bool, str]:
    venv_pytest = project_dir / ".venv" / "bin" / "pytest"
    if not venv_pytest.exists():
        return False, f"no {venv_pytest}"
    r = subprocess.run(
        [str(venv_pytest), "-q", "--tb=line"],
        cwd=project_dir, capture_output=True, text=True,
    )
    ok = r.returncode == 0
    tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    return ok, tail


def _bandit_clean(project_dir: pathlib.Path) -> tuple[bool, str]:
    venv_py = project_dir / ".venv" / "bin" / "python"
    if not venv_py.exists():
        return False, f"no {venv_py}"
    r = subprocess.run(
        [str(venv_py), "-m", "bandit", "-r", "app/", "-f", "txt"],
        cwd=project_dir, capture_output=True, text=True,
    )
    high = re.search(r"^\s*High:\s*(\d+)", r.stdout, re.MULTILINE)
    med = re.search(r"^\s*Medium:\s*(\d+)", r.stdout, re.MULTILINE)
    h = int(high.group(1)) if high else 0
    m = int(med.group(1)) if med else 0
    return (h == 0 and m == 0), f"high={h} medium={m}"


def _ac_coverage(project_dir: pathlib.Path, acceptance_criteria: list[str]) -> tuple[bool, str]:
    tests_glob = list(project_dir.rglob("test_*.py"))
    text = "\n".join(p.read_text() for p in tests_glob)
    missed = [ac for ac in acceptance_criteria if not _ac_mentioned(ac, text)]
    return (len(missed) == 0), f"{len(acceptance_criteria) - len(missed)}/{len(acceptance_criteria)} covered"


def _ac_mentioned(ac: str, corpus: str) -> bool:
    # A permissive grep: lowercase, remove punctuation, require the first 4 content words to co-occur in SOME test.
    words = [w for w in re.findall(r"\w+", ac.lower()) if len(w) > 2][:4]
    if not words:
        return False
    corpus_l = corpus.lower()
    return all(w in corpus_l for w in words)


def grade(project_dir: pathlib.Path, acceptance_criteria: list[str]) -> dict:
    checks = {}
    checks["boot"] = _uvicorn_boot(project_dir)
    checks["pytest"] = _pytest_all_pass(project_dir)
    checks["bandit"] = _bandit_clean(project_dir)
    checks["ac_coverage"] = _ac_coverage(project_dir, acceptance_criteria)

    passed = all(ok for ok, _ in checks.values())
    return {
        "passed": passed,
        "checks": {k: {"ok": ok, "note": note} for k, (ok, note) in checks.items()},
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: grade.py <project_dir> <spec.md>", file=sys.stderr)
        sys.exit(2)
    project_dir = pathlib.Path(sys.argv[1])
    spec = pathlib.Path(sys.argv[2]).read_text()
    # Pull "Acceptance criteria" section bullet points
    match = re.search(r"## Acceptance criteria\s*\n((?:\s*-\s+.+\n?)+)", spec)
    acs: list[str] = []
    if match:
        for line in match.group(1).splitlines():
            line = line.strip()
            if line.startswith("-"):
                acs.append(line.lstrip("- ").strip())
    out = grade(project_dir, acs)
    print(json.dumps(out, indent=2))
    sys.exit(0 if out["passed"] else 1)
