"""Judge runner — boots the emitted app + runs the sealed test suite.

One judge invocation per (spec, workdir) pair. The judge mounts the
spec's sealed `judge/` directory into the run directory, boots the app
via the spec's `boot_command`, runs pytest, and returns a structured
`JudgeResult` with per-test detail (Layer A/B/C/D/E per PROTOCOL §4).

Layer boundaries are enforced by `_bucket_from_test_id()` — test-id
naming convention encodes the layer:

    test_A_functional__<name>     Layer A (smoke / acceptance)
    test_B_property__<name>       Layer B (hypothesis-based)
    test_C_concurrency__<name>    Layer C (asyncio stress)
    test_D_chaos__<name>          Layer D (failure injection)
    test_E_static__<name>         Layer E (AST scan only; no boot)

Authors follow this convention in each spec's judge/test_*.py.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


LAYER_PREFIX = re.compile(r"^test_([A-E])_([a-z_]+)__")


@dataclass
class TestRecord:
    __test__ = False  # not a pytest test class despite the "Test" prefix
    test_id: str
    outcome: str                     # "pass" | "fail" | "error" | "skip"
    layer: str                       # "A" | "B" | "C" | "D" | "E"
    bucket: str                      # "concurrency" | "exactly_once" | ...
    elapsed_ms: int
    stderr_snippet: str = ""
    hypothesis_minimal: dict | None = None
    rubric_trace: str = ""           # prose: what this test asserted + why pass/fail

    def as_dict(self) -> dict:
        d = {
            "test_id": self.test_id, "outcome": self.outcome,
            "layer": self.layer, "bucket": self.bucket,
            "elapsed_ms": self.elapsed_ms,
        }
        if self.stderr_snippet:
            d["stderr_snippet"] = self.stderr_snippet
        if self.hypothesis_minimal:
            d["hypothesis_minimal"] = self.hypothesis_minimal
        if self.rubric_trace:
            d["rubric_trace"] = self.rubric_trace
        return d


def _collect_docstrings(judge_dir: Path) -> dict[str, str]:
    """Map each `test_*` function in judge_dir → its docstring (or empty).

    Used to populate `TestRecord.rubric_trace` with the human-readable
    intent of each assertion. Rubric-generation models train on
    (test_id → docstring → outcome) triples.
    """
    import ast as _ast
    out: dict[str, str] = {}
    for py in judge_dir.glob("test_*.py"):
        try:
            tree = _ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                if not node.name.startswith("test_"):
                    continue
                doc = _ast.get_docstring(node) or ""
                out[node.name] = doc.strip()
    return out


@dataclass
class JudgeResult:
    boot_status: str                 # "success" | "boot_timeout" | "boot_error" | "skipped"
    boot_log_path: Path | None
    test_records: list[TestRecord] = field(default_factory=list)
    per_layer: dict[str, float] = field(default_factory=dict)
    per_bucket: dict[str, float] = field(default_factory=dict)
    tests_passed: int = 0
    tests_total: int = 0
    final_score: float = 0.0
    notes: str = ""


def _free_port(*, retries: int = 5) -> int:
    """Ask the OS for an ephemeral port. Retries on transient races where
    the port was re-used between bind() and the caller's actual listen().

    SO_REUSEADDR is deliberately NOT set — we want the kernel to actually
    release the port after close so the caller (uvicorn) can bind without
    a TIME_WAIT collision. In ~5 years of production harnesses this has
    converged in one attempt; the retry loop is defence in depth.
    """
    last: OSError | None = None
    for _ in range(max(1, retries)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
            return port
        except OSError as exc:
            last = exc
            time.sleep(0.05)
    raise RuntimeError(f"_free_port exhausted {retries} retries: {last!r}")


def _wait_for_health(url: str, *, timeout_s: int) -> tuple[bool, str]:
    t0 = time.perf_counter()
    last_err = ""
    while time.perf_counter() - t0 < timeout_s:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if 200 <= resp.status < 300:
                    return True, ""
                last_err = f"status {resp.status}"
        except (urllib.error.URLError, OSError, ConnectionResetError) as exc:
            last_err = str(exc)
        time.sleep(0.3)
    return False, f"timeout after {timeout_s}s (last: {last_err})"


def _classify(test_id: str) -> tuple[str, str]:
    """Return (layer, bucket) parsed from the test_id. Unknown → ('A', 'unknown')."""
    m = LAYER_PREFIX.match(test_id.split("::")[-1])
    if not m:
        return ("A", "unknown")
    layer = m.group(1)
    bucket = m.group(2)
    return (layer, bucket)


def run_judge(spec, workdir: Path, *, boot_extra_env: dict | None = None) -> JudgeResult:  # noqa: ANN001
    """Boot the emitted app and run the sealed pytest suite against it.

    Args:
      spec     — loaded Spec (provides boot_command, health_probe, judge_dir, timeout_s)
      workdir  — directory the adapter emitted into (app root)

    The judge injects the port via {PORT} placeholder in boot_command and
    exposes the base URL to pytest via BLIND_BASE_URL env. Chaos events
    (subprocess lifecycle, kills, recoveries) are written to
    `judge/chaos_log.jsonl` separately from pytest output.
    """
    judge_src = spec.judge_dir
    run_judge_dir = workdir.parent / "judge"
    run_judge_dir.mkdir(parents=True, exist_ok=True)
    boot_log_path = run_judge_dir / "boot_log.txt"
    test_results_path = run_judge_dir / "test_results.jsonl"
    chaos_log_path = run_judge_dir / "chaos_log.jsonl"
    chaos_writer = _ChaosWriter(chaos_log_path)
    chaos_writer.event("judge_start", spec_id=spec.spec_id, workdir=str(workdir))

    static_only = all(
        _classify(p.name)[0] == "E" for p in judge_src.glob("test_*.py")
    ) if any(judge_src.glob("test_*.py")) else False

    # Copy sealed tests into workdir for pytest discovery (keep source pristine).
    # We use a temp subdir under workdir.parent so the agent's emitted code is
    # untouched. pytest will collect from this subdir.
    judge_copy = workdir.parent / "_judge_tests"
    if judge_copy.exists():
        shutil.rmtree(judge_copy)
    shutil.copytree(judge_src, judge_copy)

    if static_only:
        boot_status = "skipped"
        proc = None
        port = None
        chaos_writer.event("boot_skipped", reason="all tests are Layer E static")
    else:
        port = _free_port()
        boot_cmd_str = (
            spec.boot_command
            .replace("{PORT}", str(port))
            .replace("{PYTHON}", sys.executable)
        )
        # If the spec boot_command uses `python ...` directly (not {PYTHON}),
        # still substitute — the judge's venv Python is the authoritative
        # interpreter for any emitted app.
        if boot_cmd_str.startswith("python "):
            boot_cmd_str = sys.executable + boot_cmd_str[len("python"):]
        env = {**os.environ, "PORT": str(port), **(boot_extra_env or {})}
        # Start the emitted app as a subprocess.
        try:
            with boot_log_path.open("w") as log:
                proc = subprocess.Popen(
                    boot_cmd_str, shell=True, cwd=workdir,
                    stdout=log, stderr=log,
                    preexec_fn=os.setsid if hasattr(os, "setsid") else None,
                    env=env,
                )
        except OSError as exc:
            chaos_writer.event("boot_error", error=str(exc))
            return JudgeResult(
                boot_status="boot_error",
                boot_log_path=boot_log_path,
                notes=f"failed to start subprocess: {exc}",
            )
        chaos_writer.event("boot_spawn", pid=proc.pid, port=port, cmd=boot_cmd_str[:400])
        health_url = f"http://127.0.0.1:{port}{spec.health_probe}"
        boot_timeout = min(spec.boot_health_timeout_s, spec.timeout_s)
        ok, err = _wait_for_health(health_url, timeout_s=boot_timeout)
        if not ok:
            chaos_writer.event("boot_timeout", health_url=health_url, err=err)
            _kill(proc)
            chaos_writer.event("kill_on_boot_timeout", pid=proc.pid)
            return JudgeResult(
                boot_status="boot_timeout",
                boot_log_path=boot_log_path,
                notes=f"health probe {health_url} failed after {boot_timeout}s: {err}",
            )
        chaos_writer.event("boot_success", health_url=health_url)
        boot_status = "success"

    # Run pytest with json-report for precise per-test outcomes.
    report_path = run_judge_dir / "pytest_report.json"
    pytest_env = {
        **os.environ,
        "BLIND_BASE_URL": f"http://127.0.0.1:{port}" if port else "",
        "BLIND_EMITTED_DIR": str(workdir),
    }
    if boot_extra_env:
        pytest_env.update(boot_extra_env)

    cmd = [
        sys.executable, "-m", "pytest", str(judge_copy),
        "-q", "--tb=short", "--no-header",
        "--json-report", f"--json-report-file={report_path}",
        "--json-report-omit=collectors,log,keywords",
    ]
    # Let tests append to the chaos log via env (Layer D tests that kill
    # dependencies or inject faults can call into engine.bench.blind.chaos).
    pytest_env["BLIND_CHAOS_LOG"] = str(chaos_log_path)
    chaos_writer.event("pytest_start", cmd=" ".join(cmd[1:])[:400])
    try:
        pr = subprocess.run(
            cmd, capture_output=True, text=True, check=False,
            cwd=workdir, timeout=spec.timeout_s,
            env=pytest_env,
        )
    except subprocess.TimeoutExpired:
        chaos_writer.event("pytest_timeout", after_s=spec.timeout_s)
        if proc:
            _kill(proc)
            chaos_writer.event("kill_on_pytest_timeout", pid=proc.pid)
        return JudgeResult(
            boot_status=boot_status, boot_log_path=boot_log_path,
            notes=f"pytest timed out after {spec.timeout_s}s",
        )
    chaos_writer.event("pytest_done", returncode=pr.returncode)

    if proc is not None:
        _kill(proc)
        chaos_writer.event("kill_teardown", pid=proc.pid)

    records = _parse_pytest_json(report_path, pr.stdout + "\n" + pr.stderr)

    # Attach rubric traces from each test's docstring. For failing tests
    # append a compact "why" line extracted from the longrepr snippet
    # already stored on the record.
    docstrings = _collect_docstrings(judge_copy)
    for r in records:
        fn_name = r.test_id.rsplit("::", 1)[-1]
        doc = docstrings.get(fn_name, "")
        if r.outcome == "pass":
            trace = f"PASS: {doc}" if doc else "PASS"
        elif r.outcome == "skip":
            trace = f"SKIP: {doc}" if doc else "SKIP"
        else:
            why = (r.stderr_snippet.strip().split("\n")[-1] if r.stderr_snippet else "").strip()
            trace = f"{r.outcome.upper()}: {doc} — {why}" if doc else f"{r.outcome.upper()}: {why}"
        r.rubric_trace = trace[:1200]

    test_results_path.write_text(
        "\n".join(json.dumps(r.as_dict()) for r in records) + ("\n" if records else "")
    )

    return _aggregate(records, boot_status=boot_status, boot_log_path=boot_log_path)


class _ChaosWriter:
    """Append-only JSONL logger for chaos + judge lifecycle events."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Truncate on open so re-runs under the same attempt dir start fresh.
        self._path.write_text("")

    def event(self, kind: str, **details: object) -> None:
        from time import time as _now
        line = {"ts": round(_now(), 3), "kind": kind, **details}
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, default=str) + "\n")


def _kill(proc: subprocess.Popen) -> None:
    with contextlib.suppress(Exception):
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            time.sleep(0.3)
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.terminate()
            proc.kill()


def _parse_pytest_json(report_path: Path, fallback: str) -> list[TestRecord]:
    """Prefer pytest-json-report output; fall back to parsing stdout."""
    if report_path.exists():
        try:
            data = json.loads(report_path.read_text())
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and "tests" in data:
            records: list[TestRecord] = []
            for t in data["tests"]:
                nid = t.get("nodeid", "")
                layer, bucket = _classify(nid)
                outcome = t.get("outcome", "error")
                outcome = {
                    "passed": "pass", "failed": "fail",
                    "error": "error", "skipped": "skip",
                }.get(outcome, outcome)
                elapsed_ms = int(float(t.get("duration", 0.0)) * 1000)
                call = t.get("call", {}) or {}
                crash = (call.get("longrepr") or "").split("\n")[-1] if outcome != "pass" else ""
                records.append(TestRecord(
                    test_id=nid, outcome=outcome, layer=layer, bucket=bucket,
                    elapsed_ms=elapsed_ms, stderr_snippet=crash[:400],
                ))
            return records
    # Fallback: best-effort parse of pytest stdout summary.
    records = []
    for line in fallback.splitlines():
        m = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED)\s+(\S+)", line)
        if m:
            outcome = {"PASSED": "pass", "FAILED": "fail",
                       "ERROR": "error", "SKIPPED": "skip"}[m.group(1)]
            nid = m.group(2)
            layer, bucket = _classify(nid)
            records.append(TestRecord(
                test_id=nid, outcome=outcome, layer=layer, bucket=bucket,
                elapsed_ms=0,
            ))
    return records


def _aggregate(
    records: list[TestRecord], *, boot_status: str, boot_log_path: Path | None,
) -> JudgeResult:
    if not records:
        return JudgeResult(
            boot_status=boot_status, boot_log_path=boot_log_path,
            notes="no tests collected",
        )
    passed = sum(1 for r in records if r.outcome == "pass")
    failing = sum(1 for r in records if r.outcome in ("fail", "error"))
    total_counted = passed + failing  # skips do not count for score
    score = 100.0 * passed / total_counted if total_counted else 0.0

    by_layer_totals: Counter = Counter()
    by_layer_passed: Counter = Counter()
    by_bucket_totals: Counter = Counter()
    by_bucket_passed: Counter = Counter()
    for r in records:
        if r.outcome == "skip":
            continue
        by_layer_totals[r.layer] += 1
        by_bucket_totals[r.bucket] += 1
        if r.outcome == "pass":
            by_layer_passed[r.layer] += 1
            by_bucket_passed[r.bucket] += 1

    per_layer = {
        k: round(100.0 * by_layer_passed[k] / t, 2)
        for k, t in by_layer_totals.items() if t
    }
    per_bucket = {
        k: round(100.0 * by_bucket_passed[k] / t, 2)
        for k, t in by_bucket_totals.items() if t
    }

    return JudgeResult(
        boot_status=boot_status,
        boot_log_path=boot_log_path,
        test_records=records,
        per_layer=per_layer, per_bucket=per_bucket,
        tests_passed=passed, tests_total=total_counted,
        final_score=round(score, 2),
    )
