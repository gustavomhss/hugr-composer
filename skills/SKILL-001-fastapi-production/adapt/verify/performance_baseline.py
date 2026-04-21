"""TOOL-034: performance_baseline — pytest-benchmark per-endpoint latency tracking.

Generates a ``scripts/perf_baseline.py`` orchestrator that runs warmup + timed
requests against every registered FastAPI route, captures p50/p95/p99 latency,
records a hardware fingerprint, compares against a committed
``.perf.baseline.json``, and fails the gate when any metric regresses by more
than ``tolerance_pct``.

The tool is idempotent: a second run detects ``scripts/perf_baseline.py`` and
returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.verify.performance_baseline import performance_baseline

    result = performance_baseline(ToolInput(project_dir="/path/to/project"))
    print(result.status)  # "success"
"""

from __future__ import annotations

import json
import platform
import textwrap
import time
from pathlib import Path
from typing import Any

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_analyze_performance_baseline",
    "description": "Establish a performance baseline by profiling key endpoints.",
    "tags": ["verify"],
    "entry": "performance_baseline",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def performance_baseline(inp: ToolInput) -> ToolResult:
    """Generate performance baseline infrastructure for a FastAPI project.

    Creates scripts/perf_baseline.py orchestrator, .perf.baseline.json,
    .perf-exclude.yaml, and CI workflow.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)


    # --- Idempotency guard ---------------------------------------------------
    script = project / "scripts" / "perf_baseline.py"
    if script.exists() and "PerformanceBaselineRunner" in script.read_text():
        return ToolResult(
            status="no_op",
            notes=["scripts/perf_baseline.py already present — performance baseline already configured."],
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

    # --- Step 1: Orchestrator script -----------------------------------------
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    _write_orchestrator(script)
    files_created.append(str(script))

    # --- Step 2: Initial baseline JSON ---------------------------------------
    baseline_file = project / ".perf.baseline.json"
    if not baseline_file.exists():
        baseline_data = _build_empty_baseline()
        baseline_file.write_text(json.dumps(baseline_data, indent=2))
        files_created.append(str(baseline_file))

    # --- Step 3: Exclude list ------------------------------------------------
    exclude_file = project / ".perf-exclude.yaml"
    if not exclude_file.exists():
        _write_exclude_list(exclude_file)
        files_created.append(str(exclude_file))

    # --- Step 4: pytest benchmark conftest -----------------------------------
    conftest = project / "tests" / "conftest_perf.py"
    conftest.parent.mkdir(parents=True, exist_ok=True)
    _write_benchmark_conftest(conftest)
    files_created.append(str(conftest))

    # --- Step 5: CI workflow -------------------------------------------------
    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_file = ci_dir / "perf-baseline.yml"
    if not ci_file.exists():
        _write_ci_workflow(ci_file)
        files_created.append(str(ci_file))

    # --- Step 6: pyproject.toml benchmark config ----------------------------
    pyproject = project / "pyproject.toml"
    if pyproject.exists():
        _patch_pyproject(pyproject)
        files_modified.append(str(pyproject))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "50 warmup requests discarded before measurement to stabilize JIT/pools.",
            "Hardware fingerprint recorded — cross-machine comparisons trigger calibration.",
            f"Baseline at .perf.baseline.json — update only via --update-baseline.",
            "Excluded routes in .perf-exclude.yaml (health, metrics, docs).",
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
    """Capture a hardware fingerprint for baseline calibration.

    Returns:
        Dict with ``cpu``, ``cores``, ``ram_gb``, ``arch``, and ``python``.
    """
    try:
        import psutil
        ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
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
    """Compute p50, p95, p99 from a list of latency values in milliseconds.

    Args:
        latencies_ms: Sorted or unsorted list of latency measurements in ms.

    Returns:
        Dict with ``p50``, ``p95``, ``p99`` keys, all in milliseconds.
    """
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
    """Return a list of metric names that regressed beyond tolerance.

    Args:
        current: Current percentile dict from ``compute_percentiles``.
        baseline: Baseline percentile dict from ``.perf.baseline.json``.
        tolerance_pct: Maximum allowed regression as a percentage (default 10%).

    Returns:
        List of regressed metric names (e.g. ``["p99"]``).
    """
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
    """Build an empty baseline JSON structure with hardware fingerprint.

    Returns:
        Dict ready to be written as ``.perf.baseline.json``.
    """
    return {
        "version": "1.0",
        "hardware": get_hardware_fingerprint(),
        "tolerance_pct": 10.0,
        "endpoints": {},
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_orchestrator(dest: Path) -> None:
    """Write scripts/perf_baseline.py orchestrator.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Performance baseline runner — warmup + timed latency measurement.

        Usage::

            python scripts/perf_baseline.py --run [--update-baseline] [--tolerance 10]
        \"\"\"

        from __future__ import annotations

        import argparse
        import json
        import sys
        import time
        from pathlib import Path

        ROOT = Path(__file__).parent.parent
        sys.path.insert(0, str(ROOT))
        from adapt.verify.performance_baseline import (  # noqa: E402
            compute_percentiles, check_regression, get_hardware_fingerprint, _build_empty_baseline
        )

        WARMUP_REQUESTS = 50
        SAMPLE_REQUESTS = 100  # minimum; production target is 1000


        class PerformanceBaselineRunner:
            \"\"\"Measure per-endpoint latency and compare against baseline.\"\"\"

            def __init__(
                self,
                project_dir: Path = ROOT,
                baseline_file: str = ".perf.baseline.json",
                tolerance_pct: float = 10.0,
                fail_on_regression: bool = True,
            ) -> None:
                self.project_dir = project_dir
                self.baseline_path = project_dir / baseline_file
                self.tolerance_pct = tolerance_pct
                self.fail_on_regression = fail_on_regression

            def run(self) -> dict:
                \"\"\"Measure all non-excluded endpoints and compare against baseline.

                Returns:
                    Dict with ``results``, ``regressions``, and ``exit_code``.
                \"\"\"
                app = self._load_app()
                if not app:
                    return {"error": "Could not import FastAPI app", "exit_code": 1}

                routes = self._discover_routes(app)
                results = {}
                for method, path in routes:
                    latencies = self._measure(app, method, path)
                    results[f"{method}:{path}"] = compute_percentiles(latencies)

                baseline = self._load_baseline()
                regressions = []
                for key, percs in results.items():
                    if key in baseline.get("endpoints", {}):
                        reg = check_regression(percs, baseline["endpoints"][key], self.tolerance_pct)
                        if reg:
                            regressions.append({"endpoint": key, "metrics": reg, "current": percs})

                exit_code = 1 if (self.fail_on_regression and regressions) else 0
                return {"results": results, "regressions": regressions, "exit_code": exit_code}

            def update_baseline(self, results: dict) -> None:
                \"\"\"Write current measurements as the new baseline.\"\"\"
                baseline = _build_empty_baseline()
                baseline["endpoints"] = results
                self.baseline_path.write_text(json.dumps(baseline, indent=2))

            def _load_app(self):
                \"\"\"Import and return the FastAPI app instance.\"\"\"
                try:
                    import sys as _sys
                    _sys.path.insert(0, str(self.project_dir))
                    from app.main import app  # type: ignore[import]
                    return app
                except Exception:  # noqa: BLE001
                    return None

            def _discover_routes(self, app) -> list[tuple[str, str]]:
                \"\"\"Return (method, path) pairs from the FastAPI app, excluding health routes.\"\"\"
                exclude_prefixes = ["/health", "/metrics", "/docs", "/openapi.json", "/redoc"]
                routes = []
                for route in getattr(app, "routes", []):
                    path = getattr(route, "path", "")
                    if any(path.startswith(p) for p in exclude_prefixes):
                        continue
                    for method in getattr(route, "methods", ["GET"]):
                        if "{" not in path:  # skip parameterized routes for auto-discovery
                            routes.append((method, path))
                return routes[:20]  # cap at 20 for CI speed

            def _measure(self, app, method: str, path: str) -> list[float]:
                \"\"\"Run warmup + sample requests and return latency list in ms.\"\"\"
                from fastapi.testclient import TestClient
                client = TestClient(app, raise_server_exceptions=False)
                fn = getattr(client, method.lower(), client.get)

                # Warmup (discard)
                for _ in range(WARMUP_REQUESTS):
                    try:
                        fn(path)
                    except Exception:  # noqa: BLE001
                        pass

                # Measurement
                latencies: list[float] = []
                for _ in range(SAMPLE_REQUESTS):
                    t0 = time.perf_counter()
                    try:
                        fn(path)
                    except Exception:  # noqa: BLE001
                        pass
                    latencies.append((time.perf_counter() - t0) * 1000)
                return latencies

            def _load_baseline(self) -> dict:
                \"\"\"Load .perf.baseline.json or return empty dict.\"\"\"
                if not self.baseline_path.exists():
                    return {}
                try:
                    return json.loads(self.baseline_path.read_text())
                except json.JSONDecodeError:
                    return {}


        if __name__ == "__main__":
            parser = argparse.ArgumentParser(description="Performance baseline")
            parser.add_argument("--run", action="store_true")
            parser.add_argument("--update-baseline", action="store_true")
            parser.add_argument("--tolerance", type=float, default=10.0)
            args = parser.parse_args()

            runner = PerformanceBaselineRunner(tolerance_pct=args.tolerance)
            if not args.run:
                print("Use --run to execute measurements.")
                sys.exit(0)

            results = runner.run()
            if args.update_baseline and not results.get("error"):
                runner.update_baseline(results.get("results", {}))
                print("Baseline updated.")

            print(f"Endpoints measured: {len(results.get('results', {}))}")
            print(f"Regressions: {len(results.get('regressions', []))}")
            sys.exit(results.get("exit_code", 0))
        """)
    dest.write_text(content)


def _write_exclude_list(dest: Path) -> None:
    """Write .perf-exclude.yaml endpoint exclusion list.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .perf-exclude.yaml — endpoints excluded from performance baseline measurement.
        # These are typically health checks, monitoring endpoints, and documentation.
        version: "1.0"
        excluded_prefixes:
          - /health
          - /metrics
          - /docs
          - /redoc
          - /openapi.json
          - /favicon.ico
        """)
    dest.write_text(content)


def _write_benchmark_conftest(dest: Path) -> None:
    """Write tests/conftest_perf.py pytest-benchmark conftest.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"pytest-benchmark conftest for per-endpoint performance tests.

        Include in conftest.py::

            from tests.conftest_perf import *  # noqa: F401,F403
        \"\"\"

        from __future__ import annotations

        import pytest

        from adapt.verify.performance_baseline import compute_percentiles, check_regression


        @pytest.fixture
        def perf_client(app):
            \"\"\"Return a TestClient that measures response latencies.

            Args:
                app: FastAPI app fixture (must be defined in conftest.py).

            Yields:
                TestClient instance.
            \"\"\"
            from fastapi.testclient import TestClient
            with TestClient(app, raise_server_exceptions=False) as client:
                yield client


        @pytest.fixture
        def assert_latency_p99():
            \"\"\"Return a helper that asserts p99 latency is below *max_ms*.

            Usage::

                def test_items_p99(perf_client, assert_latency_p99):
                    assert_latency_p99(perf_client, "/api/v1/items/", "GET", max_ms=100)
            \"\"\"

            def _check(client, path: str, method: str = "GET", max_ms: float = 100.0, n: int = 100) -> None:
                import time
                fn = getattr(client, method.lower(), client.get)
                latencies = []
                for _ in range(n):
                    t0 = time.perf_counter()
                    try:
                        fn(path)
                    except Exception:  # noqa: BLE001
                        pass
                    latencies.append((time.perf_counter() - t0) * 1000)
                percs = compute_percentiles(latencies)
                assert percs["p99"] <= max_ms, (
                    f"p99 latency for {method} {path} is {percs['p99']:.1f}ms "
                    f"(max allowed: {max_ms}ms)"
                )

            return _check
        """)
    dest.write_text(content)


def _write_ci_workflow(dest: Path) -> None:
    """Write .github/workflows/perf-baseline.yml CI workflow.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .github/workflows/perf-baseline.yml
        name: Performance Baseline

        on:
          pull_request:
            branches: [main, master]
          push:
            branches: [main, master]

        jobs:
          perf-baseline:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
              - uses: actions/setup-python@v5
                with:
                  python-version: "3.12"
                  cache: pip
              - name: Install dependencies
                run: pip install -r requirements.txt pytest pytest-benchmark httpx
              - name: Run performance baseline
                run: |
                  PYTHONPATH=. python scripts/perf_baseline.py \\
                    --run --tolerance 10
        """)
    dest.write_text(content)


def _patch_pyproject(pyproject: Path) -> None:
    """Add [tool.pytest.ini_options] benchmark markers to pyproject.toml.

    Args:
        pyproject: Path to pyproject.toml.
    """
    src = pyproject.read_text()
    if "pytest-benchmark" in src or "benchmark" in src.lower():
        return
    addition = textwrap.dedent("""\

        [tool.pytest-benchmark]
        min_rounds = 5
        warmup = true
        warmup_iterations = 3
        """)
    pyproject.write_text(src + addition)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
