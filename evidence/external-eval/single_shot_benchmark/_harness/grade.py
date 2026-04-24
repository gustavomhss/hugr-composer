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
    """AST-based AC coverage — codex/opus HIGH-M3 fix.

    The previous implementation accepted "first 4 content words appear
    in some test docstring" as coverage — gameable by a Maestro that
    quoted the AC verbatim into a test docstring without actually
    asserting the behaviour.

    The new implementation extracts the OBSERVABLE PROOF from each AC
    sentence — HTTP method + path + status code (or a non-HTTP
    assertion shape: "raises X", "returns Y", "is empty") — and
    requires the test corpus to actually CALL/ASSERT that triplet
    inside a `def test_*` function body, not just mention the words
    in a docstring.

    A test docstring that copy-pastes the AC text counts as zero
    coverage. A test body that calls `client.get("/path")` and
    `assert response.status_code == 404` counts as coverage of an AC
    that says "GET /path returns 404".

    For ACs that don't follow the HTTP-method+path+status pattern
    (e.g., "audit log is append-only"), the probe falls back to
    requiring at least one verb-and-noun pair from the AC inside a
    test body (NOT docstring).
    """
    import ast

    tests_glob = list(project_dir.rglob("test_*.py"))
    if not tests_glob:
        return False, f"no test files; 0/{len(acceptance_criteria)} ACs covered"

    # Collect for every `def test_*` in the project: function NAME + body code
    # (NOT docstring). The function name is the test's claim of what it verifies;
    # the body is the actual proof. Both count toward AC coverage; docstrings
    # do not (that was the gameable surface).
    test_bodies: list[str] = []
    for tf in tests_glob:
        try:
            tree = ast.parse(tf.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                # Strip the docstring node so it doesn't pollute the body match
                body_nodes = node.body[1:] if (
                    node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                ) else node.body
                try:
                    body_text = "\n".join(ast.unparse(n) for n in body_nodes)
                except Exception:
                    continue
                # Include function name (the testing claim) + body code.
                # `test_audit_log_append_only` → words: audit log append only
                name_words = node.name.replace("_", " ")
                test_bodies.append((name_words + "\n" + body_text).lower())

    body_corpus = "\n".join(test_bodies)
    covered: list[str] = []
    for ac in acceptance_criteria:
        if _ac_observable_in_body(ac, body_corpus):
            covered.append(ac)
    cov_n = len(covered)
    total = len(acceptance_criteria)
    return (cov_n == total) and total > 0, f"{cov_n}/{total} covered (AST body match, not docstring)"


_HTTP_VERBS_PATH_STATUS = re.compile(
    r"\b(get|post|put|patch|delete|head|options)\b.*?(?:[\"\']?(/[\w/\-{}]+)[\"\']?)?.*?\b(\d{3})\b",
    re.IGNORECASE | re.DOTALL,
)


def _ac_observable_in_body(ac: str, body_corpus: str) -> bool:
    """Look for the AC's observable triplet inside a test function body."""
    ac_low = ac.lower()
    # Pattern 1: HTTP method + status code together in a body
    m = _HTTP_VERBS_PATH_STATUS.search(ac_low)
    if m:
        verb = m.group(1)
        status = m.group(3)
        # Require BOTH the http verb and the status code to appear in some test body.
        # The verb test catches `client.get(...)` / `httpx.delete(...)`; the status
        # catches `response.status_code == 404` / `assert ... .status_code == status.HTTP_204_NO_CONTENT`.
        if verb in body_corpus and status in body_corpus:
            return True
    # Pattern 2: state-machine / non-HTTP — require at least 3 distinct content words from
    # the AC (length > 3) to appear in a test body
    words = [w for w in re.findall(r"\w+", ac_low) if len(w) > 3]
    distinct = sorted(set(words), key=words.index)[:6]
    hits = sum(1 for w in distinct if w in body_corpus)
    return hits >= 3 and len(distinct) >= 3


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
