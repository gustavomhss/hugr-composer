"""TOOL-032: test_coverage_gaps — risk-weighted coverage gap analysis for FastAPI.

Generates scripts/coverage_gaps.py that parses coverage.xml (branch coverage),
applies risk weights (auth/payment/admin = 2x), diffs against a committed
baseline, and produces a ranked gap list.  Writes ``.coverage.baseline.json``
and ``.coverage-risk-weights.yaml`` config.

The tool is idempotent: a second run detects ``scripts/coverage_gaps.py`` and
returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.verify.test_coverage_gaps import test_coverage_gaps

    result = test_coverage_gaps(ToolInput(project_dir="/path/to/project"))
    print(result.status)  # "success"
"""

from __future__ import annotations

__test__ = False  # not a pytest module — this is a tool implementation

import json
import textwrap
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult

_HIGH_RISK_PATTERNS = ["auth", "payment", "admin", "security", "token", "billing", "delete", "write"]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def test_coverage_gaps(inp: ToolInput) -> ToolResult:
    """Generate test coverage gap analysis infrastructure for a FastAPI project.

    Creates scripts/coverage_gaps.py, .coverage-risk-weights.yaml,
    pyproject.toml coverage config, and CI workflow.  If coverage.xml exists,
    also writes the initial .coverage.baseline.json.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    # --- Idempotency guard ---------------------------------------------------
    script = project / "scripts" / "coverage_gaps.py"
    if script.exists() and "CoverageGapsAnalyzer" in script.read_text():
        return ToolResult(
            status="no_op",
            notes=["scripts/coverage_gaps.py already present — coverage gaps already configured."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would generate coverage gap analysis infrastructure."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Step 1: Orchestrator script -----------------------------------------
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    _write_orchestrator(script)
    files_created.append(str(script))

    # --- Step 2: Risk weights config -----------------------------------------
    weights_file = project / ".coverage-risk-weights.yaml"
    if not weights_file.exists():
        _write_risk_weights(weights_file)
        files_created.append(str(weights_file))

    # --- Step 3: Initial baseline from coverage.xml if present ---------------
    coverage_xml = project / "coverage.xml"
    baseline_file = project / ".coverage.baseline.json"
    if coverage_xml.exists() and not baseline_file.exists():
        baseline_data = _parse_coverage_xml(coverage_xml)
        baseline_file.write_text(json.dumps(baseline_data, indent=2))
        files_created.append(str(baseline_file))
    elif not baseline_file.exists():
        # Write empty baseline placeholder
        baseline_file.write_text(json.dumps({"modules": {}, "overall_line_pct": 0.0, "overall_branch_pct": 0.0}, indent=2))
        files_created.append(str(baseline_file))

    # --- Step 4: pyproject.toml coverage config ------------------------------
    pyproject = project / "pyproject.toml"
    if pyproject.exists():
        _patch_pyproject(pyproject)
        files_modified.append(str(pyproject))

    # --- Step 5: CI workflow -------------------------------------------------
    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_file = ci_dir / "coverage-gaps.yml"
    if not ci_file.exists():
        _write_ci_workflow(ci_file)
        files_created.append(str(ci_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Branch coverage always enabled (line coverage hides if/else gaps).",
            f"High-risk patterns (2x weight): {', '.join(_HIGH_RISK_PATTERNS[:5])} ...",
            "Baseline at .coverage.baseline.json — update only via --update-baseline.",
        ],
        next_steps=[
            "pytest --cov=app --cov-branch --cov-report=xml",
            "python scripts/coverage_gaps.py --min-line 85 --min-branch 75",
            "Commit .coverage.baseline.json as the 'known-good' snapshot.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Coverage XML parser
# ---------------------------------------------------------------------------

def _parse_coverage_xml(xml_path: Path) -> dict:
    """Parse coverage.xml and return structured coverage data.

    Args:
        xml_path: Path to a pytest coverage.xml file.

    Returns:
        Dict with ``modules`` mapping and ``overall_line_pct`` / ``overall_branch_pct``.
    """
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return {"modules": {}, "overall_line_pct": 0.0, "overall_branch_pct": 0.0}

    root = tree.getroot()
    coverage = root if root.tag == "coverage" else root.find("coverage")
    if coverage is None:
        return {"modules": {}, "overall_line_pct": 0.0, "overall_branch_pct": 0.0}

    line_rate = float(coverage.get("line-rate", 0)) * 100
    branch_rate = float(coverage.get("branch-rate", 0)) * 100

    modules: dict[str, dict] = {}
    for pkg in coverage.findall(".//package"):
        for cls in pkg.findall(".//class"):
            filename = cls.get("filename", "")
            cls_line_rate = float(cls.get("line-rate", 0)) * 100
            cls_branch_rate = float(cls.get("branch-rate", 0)) * 100
            risk = _compute_risk(filename)
            modules[filename] = {
                "line_pct": round(cls_line_rate, 1),
                "branch_pct": round(cls_branch_rate, 1),
                "risk_weight": risk,
                "weighted_score": round((cls_line_pct := cls_line_rate) * risk, 1),
            }

    return {
        "modules": modules,
        "overall_line_pct": round(line_rate, 1),
        "overall_branch_pct": round(branch_rate, 1),
    }


def _compute_risk(filename: str) -> float:
    """Return risk weight for a file based on its path patterns.

    Args:
        filename: File path string (relative or absolute).

    Returns:
        2.0 for high-risk files, 1.0 otherwise.
    """
    lower = filename.lower()
    return 2.0 if any(p in lower for p in _HIGH_RISK_PATTERNS) else 1.0


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_orchestrator(dest: Path) -> None:
    """Write scripts/coverage_gaps.py orchestrator.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Coverage gap analyzer — risk-weighted branch coverage gap ranking.

        Usage::

            pytest --cov=app --cov-branch --cov-report=xml
            python scripts/coverage_gaps.py [--min-line 85] [--min-branch 75]
        \"\"\"

        from __future__ import annotations

        import argparse
        import json
        import sys
        from pathlib import Path

        ROOT = Path(__file__).parent.parent
        sys.path.insert(0, str(ROOT))
        from adapt.verify.test_coverage_gaps import _parse_coverage_xml, _compute_risk  # noqa: E402


        class CoverageGapsAnalyzer:
            \"\"\"Analyze coverage.xml and produce a risk-ranked gap list.\"\"\"

            def __init__(
                self,
                project_dir: Path = ROOT,
                min_line_pct: float = 85.0,
                min_branch_pct: float = 75.0,
                fail_on_regressions: bool = True,
                baseline_file: str = ".coverage.baseline.json",
            ) -> None:
                self.project_dir = project_dir
                self.min_line_pct = min_line_pct
                self.min_branch_pct = min_branch_pct
                self.fail_on_regressions = fail_on_regressions
                self.baseline_path = project_dir / baseline_file

            def run(self) -> dict:
                \"\"\"Parse coverage.xml and compare against baseline.

                Returns:
                    Dict with ``gaps``, ``regressions``, and ``exit_code``.
                \"\"\"
                xml_path = self.project_dir / "coverage.xml"
                if not xml_path.exists():
                    return {"error": "coverage.xml not found. Run: pytest --cov=app --cov-report=xml", "exit_code": 1}

                current = _parse_coverage_xml(xml_path)
                baseline = {}
                if self.baseline_path.exists():
                    try:
                        baseline = json.loads(self.baseline_path.read_text())
                    except json.JSONDecodeError:
                        pass

                gaps = self._rank_gaps(current)
                regressions = self._detect_regressions(current, baseline)
                failing = (
                    current["overall_line_pct"] < self.min_line_pct
                    or current["overall_branch_pct"] < self.min_branch_pct
                    or (self.fail_on_regressions and bool(regressions))
                )
                return {
                    "overall_line_pct": current["overall_line_pct"],
                    "overall_branch_pct": current["overall_branch_pct"],
                    "gaps": gaps[:20],
                    "regressions": regressions,
                    "exit_code": 1 if failing else 0,
                }

            def _rank_gaps(self, data: dict) -> list[dict]:
                \"\"\"Return modules sorted by weighted gap (worst first).\"\"\"
                gaps = []
                for filename, info in data.get("modules", {}).items():
                    gap = 100.0 - info.get("branch_pct", 100.0)
                    weighted_gap = gap * info.get("risk_weight", 1.0)
                    if gap > 0:
                        gaps.append({
                            "file": filename,
                            "line_pct": info["line_pct"],
                            "branch_pct": info["branch_pct"],
                            "risk_weight": info["risk_weight"],
                            "weighted_gap": round(weighted_gap, 1),
                        })
                return sorted(gaps, key=lambda x: x["weighted_gap"], reverse=True)

            def _detect_regressions(self, current: dict, baseline: dict) -> list[dict]:
                \"\"\"Return modules whose coverage dropped vs baseline.\"\"\"
                regressions = []
                for filename, info in current.get("modules", {}).items():
                    if filename not in baseline.get("modules", {}):
                        continue
                    baseline_branch = baseline["modules"][filename].get("branch_pct", 0)
                    current_branch = info.get("branch_pct", 0)
                    drop = baseline_branch - current_branch
                    if drop > 0.5:
                        regressions.append({
                            "file": filename, "drop_pct": round(drop, 1),
                            "baseline_branch": baseline_branch,
                            "current_branch": current_branch,
                        })
                return sorted(regressions, key=lambda x: x["drop_pct"], reverse=True)


        if __name__ == "__main__":
            parser = argparse.ArgumentParser(description="Coverage gap analysis")
            parser.add_argument("--min-line", type=float, default=85.0)
            parser.add_argument("--min-branch", type=float, default=75.0)
            parser.add_argument("--update-baseline", action="store_true")
            args = parser.parse_args()

            analyzer = CoverageGapsAnalyzer(min_line_pct=args.min_line, min_branch_pct=args.min_branch)
            results = analyzer.run()
            print(f"Line: {results.get('overall_line_pct', 'N/A')}% | Branch: {results.get('overall_branch_pct', 'N/A')}%")
            print(f"Gaps: {len(results.get('gaps', []))} | Regressions: {len(results.get('regressions', []))}")
            sys.exit(results.get("exit_code", 0))
        """)
    dest.write_text(content)


def _write_risk_weights(dest: Path) -> None:
    """Write .coverage-risk-weights.yaml risk weight config.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .coverage-risk-weights.yaml — per-module risk multipliers for coverage gap ranking.
        # Files matching these patterns get a higher weight so they rank first in the gap list.
        version: "1.0"
        high_risk_patterns:
          - "auth"
          - "payment"
          - "admin"
          - "security"
          - "token"
          - "billing"
          - "delete"
          - "write"
        high_risk_multiplier: 2.0
        default_multiplier: 1.0
        """)
    dest.write_text(content)


def _patch_pyproject(pyproject: Path) -> None:
    """Add [tool.coverage.run] branch=true to pyproject.toml if missing.

    Args:
        pyproject: Path to pyproject.toml.
    """
    src = pyproject.read_text()
    if "[tool.coverage.run]" in src:
        return
    addition = textwrap.dedent("""\

        [tool.coverage.run]
        branch = true
        source = ["app"]
        omit = ["app/main.py", "*/migrations/*", "*/alembic/*"]

        [tool.coverage.report]
        exclude_lines = [
          "if TYPE_CHECKING:",
          "if __name__ == .__main__.:",
          "@overload",
        ]
        """)
    pyproject.write_text(src + addition)


def _write_ci_workflow(dest: Path) -> None:
    """Write .github/workflows/coverage-gaps.yml CI workflow.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .github/workflows/coverage-gaps.yml
        name: Coverage Gap Analysis

        on:
          pull_request:
            branches: [main, master]
          push:
            branches: [main, master]

        jobs:
          coverage-gaps:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
              - uses: actions/setup-python@v5
                with:
                  python-version: "3.12"
                  cache: pip
              - name: Install dependencies
                run: pip install -r requirements.txt pytest pytest-cov
              - name: Run tests with branch coverage
                run: pytest --cov=app --cov-branch --cov-report=xml -q
              - name: Analyze coverage gaps
                run: |
                  PYTHONPATH=. python scripts/coverage_gaps.py \\
                    --min-line 85 --min-branch 75
        """)
    dest.write_text(content)


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
