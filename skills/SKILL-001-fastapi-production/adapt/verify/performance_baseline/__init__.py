"""TOOL-034: performance_baseline — pytest-benchmark per-endpoint latency tracking.

Generates a ``scripts/perf_baseline.py`` orchestrator that runs warmup + timed
requests against every registered FastAPI route, captures p50/p95/p99 latency,
records a hardware fingerprint, compares against a committed
``.perf.baseline.json``, and reports when any metric regresses by more than
``tolerance_pct``.

The tool is idempotent: a second run detects ``scripts/perf_baseline.py`` and
returns ``status="no_op"``.

Honesty (WP-14 §11): the initial ``.perf.baseline.json`` is empty (no
``endpoints``) — regression detection requires a curated baseline AND a
calibrated ``tolerance_pct`` for the deployment environment. ``warnings`` is
worded as "advisory baseline; regression detection requires manual threshold
tuning" — it does not claim "regression detected" pre-calibration.
"""

from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Any

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent


MCP_TOOL = {
    "name": "fastapi_resiliency_analyze_performance_baseline",
    "description": "Establish a performance baseline by profiling key endpoints.",
    "tags": ["verify"],
    "entry": "performance_baseline",
}


def performance_baseline(inp: ToolInput) -> ToolResult:
    """Generate performance baseline infrastructure for a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    script = project / "scripts" / "perf_baseline.py"
    if script.exists() and "PerformanceBaselineRunner" in script.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "scripts/perf_baseline.py already present — performance baseline already configured."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would generate performance baseline infrastructure."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    (project / "scripts").mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "orchestrator.py.tmpl", dest=script, substitutions={})
    files_created.append(str(script))

    baseline_file = project / ".perf.baseline.json"
    if not baseline_file.exists():
        baseline_data = _build_empty_baseline()
        baseline_file.write_text(json.dumps(baseline_data, indent=2))
        files_created.append(str(baseline_file))

    exclude_file = project / ".perf-exclude.yaml"
    if not exclude_file.exists():
        render_to(_HERE, "exclude_list.yaml.tmpl", dest=exclude_file, substitutions={})
        files_created.append(str(exclude_file))

    conftest = project / "tests" / "conftest_perf.py"
    conftest.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "conftest_perf.py.tmpl", dest=conftest, substitutions={})
    files_created.append(str(conftest))

    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_file = ci_dir / "perf-baseline.yml"
    if not ci_file.exists():
        render_to(_HERE, "ci_workflow.yml.tmpl", dest=ci_file, substitutions={})
        files_created.append(str(ci_file))

    pyproject = project / "pyproject.toml"
    if pyproject.exists():
        _patch_pyproject(pyproject)
        files_modified.append(str(pyproject))

    # Phase-5 emitted test (P1 #15)
    emitted_test = project / "tests" / "test_performance_baseline_emitted.py"
    if not emitted_test.exists():
        render_to(_HERE, "test_emitted.py.tmpl", dest=emitted_test, substitutions={})
        files_created.append(str(emitted_test))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "50 warmup requests discarded before measurement to stabilize JIT/pools.",
            "Hardware fingerprint recorded — cross-machine comparisons trigger calibration.",
            "Baseline at .perf.baseline.json — update only via --update-baseline.",
            "Excluded routes in .perf-exclude.yaml (health, metrics, docs).",
        ],
        warnings=[
            "Advisory baseline: the initial .perf.baseline.json is empty; regression "
            "detection requires (1) running --update-baseline on a stable host to seed "
            "the baseline, and (2) manually calibrating tolerance_pct for the target "
            "deployment environment. No regression is reported until a baseline exists."
        ],
        next_steps=[
            "pip install pytest-benchmark httpx",
            "python scripts/perf_baseline.py --run",
            "Commit .perf.baseline.json after first clean run.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Baseline utilities (importable by orchestrator)
# ---------------------------------------------------------------------------


def get_hardware_fingerprint() -> dict[str, Any]:
    """Capture a hardware fingerprint for baseline calibration."""
    try:
        import psutil

        ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
    except ImportError:
        ram_gb = None

    return {
        "cpu": platform.processor() or platform.machine(),
        "cores": (lambda: __import__("os").cpu_count())(),
        "ram_gb": ram_gb,
        "arch": platform.machine(),
        "python": platform.python_version(),
        "system": platform.system(),
    }


def compute_percentiles(latencies_ms: list[float]) -> dict[str, float]:
    """Compute p50, p95, p99 from a list of latency values in milliseconds."""
    if not latencies_ms:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    sorted_lat = sorted(latencies_ms)
    n = len(sorted_lat)
    return {
        "p50": sorted_lat[int(n * 0.50)],
        "p95": sorted_lat[int(n * 0.95)],
        "p99": sorted_lat[min(int(n * 0.99), n - 1)],
    }


def check_regression(
    current: dict[str, float],
    baseline: dict[str, float],
    tolerance_pct: float = 10.0,
) -> list[str]:
    """Return a list of metric names that regressed beyond tolerance."""
    regressions: list[str] = []
    for metric in ("p50", "p95", "p99"):
        base_val = baseline.get(metric, 0.0)
        curr_val = current.get(metric, 0.0)
        if base_val <= 0:
            continue
        pct_change = (curr_val - base_val) / base_val * 100
        if pct_change > tolerance_pct:
            regressions.append(metric)
    return regressions


def _build_empty_baseline() -> dict[str, Any]:
    """Build an empty baseline JSON structure with hardware fingerprint."""
    return {
        "version": "1.0",
        "hardware": get_hardware_fingerprint(),
        "tolerance_pct": 10.0,
        "endpoints": {},
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _patch_pyproject(pyproject: Path) -> None:
    """Add [tool.pytest-benchmark] markers to pyproject.toml."""
    src = pyproject.read_text()
    if "pytest-benchmark" in src or "benchmark" in src.lower():
        return
    from adapt._base import render

    addition = render(_HERE, "pyproject_addition.toml.tmpl", {})
    pyproject.write_text(src + addition)


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
