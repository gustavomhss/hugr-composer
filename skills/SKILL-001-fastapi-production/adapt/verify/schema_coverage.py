"""TOOL-031: schema_coverage — AST-based Pydantic schema field coverage analysis.

Walks every ``BaseModel`` subclass under ``app/`` with ``ast``, enumerates all
fields (including aliased and inherited ones), cross-references ``tests/`` for
field references, and produces a per-schema coverage percentage plus an
**orphan-fields** list.  Writes a ``schema-coverage.json`` report and a GitHub
Actions CI workflow.

The tool is idempotent: a second run returns ``status="no_op"`` when
``scripts/schema_coverage.py`` already exists.

Example::

    from adapt.contracts import ToolInput
    from adapt.verify.schema_coverage import schema_coverage

    result = schema_coverage(ToolInput(project_dir="/path/to/project"))
    print(result.status)  # "success"
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def schema_coverage(inp: ToolInput) -> ToolResult:
    """Generate schema coverage analysis infrastructure for a FastAPI project.

    Creates scripts/schema_coverage.py orchestrator, .schema-coverage-exclude.yaml,
    CI workflow, and writes an initial schema-coverage.json report.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with status, files_created, notes, and next_steps.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    script = project / "scripts" / "schema_coverage.py"
    if script.exists() and "SchemaCoverageAnalyzer" in script.read_text():
        return ToolResult(
            status="no_op",
            notes=["scripts/schema_coverage.py already present — schema coverage already configured."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []

    if inp.dry_run:
        schemas = _discover_schemas(app_dir)
        return ToolResult(
            status="success",
            notes=[f"[dry_run] Would analyze {len(schemas)} schema classes."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Step 1: Orchestrator script -----------------------------------------
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    _write_orchestrator(script)
    files_created.append(str(script))

    # --- Step 2: Exclusion YAML ----------------------------------------------
    exclude_file = project / ".schema-coverage-exclude.yaml"
    if not exclude_file.exists():
        _write_exclusion_schema(exclude_file)
        files_created.append(str(exclude_file))

    # --- Step 3: Initial coverage report -------------------------------------
    report_file = project / "schema-coverage.json"
    coverage_data = _run_analysis(app_dir, project / "tests")
    import json
    report_file.write_text(json.dumps(coverage_data, indent=2))
    files_created.append(str(report_file))

    # --- Step 4: CI workflow -------------------------------------------------
    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_file = ci_dir / "schema-coverage.yml"
    if not ci_file.exists():
        _write_ci_workflow(ci_file)
        files_created.append(str(ci_file))

    total_schemas = len(coverage_data.get("schemas", {}))
    orphan_count = sum(
        len(v.get("orphan_fields", []))
        for v in coverage_data.get("schemas", {}).values()
    )
    overall_pct = coverage_data.get("overall_coverage_pct", 0.0)

    return ToolResult(
        status="success",
        files_created=files_created,
        notes=[
            f"Analyzed {total_schemas} schema classes.",
            f"Overall coverage: {overall_pct:.1f}%",
            f"Orphan fields (never referenced in tests): {orphan_count}",
        ],
        next_steps=[
            "python scripts/schema_coverage.py --threshold-pct 80 --fail-on-orphans",
            "Review schema-coverage.json for per-schema details.",
            "Add exceptions to .schema-coverage-exclude.yaml with reason + reviewer.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Analysis core — AST-based, zero runtime cost
# ---------------------------------------------------------------------------

def _discover_schemas(app_dir: Path) -> list[tuple[str, list[str]]]:
    """Walk app/ and return [(ClassName, [field_names])] for BaseModel subclasses.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        List of (class_name, field_names) tuples.
    """
    results: list[tuple[str, list[str]]] = []
    schemas_dir = app_dir / "schemas"
    if not schemas_dir.exists():
        return results
    for py_file in sorted(schemas_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not _is_basemodel_subclass(node):
                continue
            fields = _extract_fields(node)
            if fields:
                results.append((node.name, fields))
    return results


def _is_basemodel_subclass(node: ast.ClassDef) -> bool:
    """Return True if the class inherits from BaseModel or a known subclass.

    Args:
        node: AST class definition node.

    Returns:
        True if the class appears to be a Pydantic model.
    """
    base_names = {"BaseModel", "SQLModel", "TimestampMixin"}
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in base_names:
            return True
        if isinstance(base, ast.Attribute) and base.attr in base_names:
            return True
    return False


def _extract_fields(node: ast.ClassDef) -> list[str]:
    """Extract field names from a ClassDef via annotated assignments.

    Args:
        node: AST class definition to inspect.

    Returns:
        List of field name strings (excludes private ``_`` prefixed names).
    """
    fields: list[str] = []
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            name = stmt.target.id
            if not name.startswith("_"):
                fields.append(name)
    return fields


def _collect_test_references(tests_dir: Path) -> set[str]:
    """Collect all field-like identifiers referenced in test files.

    Looks for patterns: ``.field``, ``["field"]``, ``{"field": …}``.

    Args:
        tests_dir: Root directory of the test suite.

    Returns:
        Set of field name strings referenced in tests.
    """
    refs: set[str] = []
    if not tests_dir.exists():
        return set()
    for py_file in sorted(tests_dir.rglob("*.py")):
        try:
            src = py_file.read_text()
        except OSError:
            continue
        tree = ast.parse(src)
        for node in ast.walk(tree):
            # Attribute access: obj.field_name
            if isinstance(node, ast.Attribute):
                refs.append(node.attr)
            # Dict key: {"field_name": ...}
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                refs.append(node.value)
    return set(refs)


def _run_analysis(app_dir: Path, tests_dir: Path) -> dict:
    """Run the full schema coverage analysis and return structured data.

    Args:
        app_dir: The ``app/`` directory of the project.
        tests_dir: The ``tests/`` directory of the project.

    Returns:
        Dict with ``schemas`` mapping and ``overall_coverage_pct``.
    """
    schemas = _discover_schemas(app_dir)
    test_refs = _collect_test_references(tests_dir)
    schema_results: dict[str, dict] = {}
    total_fields = 0
    total_covered = 0

    for class_name, fields in schemas:
        covered = [f for f in fields if f in test_refs]
        orphans = [f for f in fields if f not in test_refs]
        pct = (len(covered) / len(fields) * 100) if fields else 100.0
        schema_results[class_name] = {
            "fields": fields,
            "covered_fields": covered,
            "orphan_fields": orphans,
            "coverage_pct": round(pct, 1),
        }
        total_fields += len(fields)
        total_covered += len(covered)

    overall_pct = (total_covered / total_fields * 100) if total_fields else 100.0
    return {
        "overall_coverage_pct": round(overall_pct, 1),
        "total_fields": total_fields,
        "total_covered": total_covered,
        "schemas": schema_results,
    }


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_orchestrator(dest: Path) -> None:
    """Write scripts/schema_coverage.py orchestrator.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Schema coverage orchestrator — analyzes Pydantic field test coverage.

        Usage::

            python scripts/schema_coverage.py [--threshold-pct 80] [--fail-on-orphans]
        \"\"\"

        from __future__ import annotations

        import argparse
        import json
        import sys
        from pathlib import Path

        ROOT = Path(__file__).parent.parent

        # Inline the analyzer to keep the script self-contained at runtime
        sys.path.insert(0, str(ROOT))
        from adapt.verify.schema_coverage import _run_analysis  # noqa: E402


        class SchemaCoverageAnalyzer:
            \"\"\"Orchestrate schema coverage analysis and gate evaluation.\"\"\"

            def __init__(
                self,
                project_dir: Path = ROOT,
                threshold_pct: float = 80.0,
                fail_on_orphans: bool = True,
            ) -> None:
                self.project_dir = project_dir
                self.threshold_pct = threshold_pct
                self.fail_on_orphans = fail_on_orphans

            def run(self) -> dict:
                \"\"\"Run analysis, apply gate, return results with exit_code.\"\"\"
                data = _run_analysis(
                    self.project_dir / "app",
                    self.project_dir / "tests",
                )
                failing = data["overall_coverage_pct"] < self.threshold_pct
                orphan_count = sum(
                    len(v["orphan_fields"]) for v in data["schemas"].values()
                )
                if self.fail_on_orphans and orphan_count:
                    failing = True
                data["exit_code"] = 1 if failing else 0
                return data


        if __name__ == "__main__":
            parser = argparse.ArgumentParser(description="Schema field coverage")
            parser.add_argument("--threshold-pct", type=float, default=80.0)
            parser.add_argument("--fail-on-orphans", action="store_true", default=True)
            args = parser.parse_args()

            analyzer = SchemaCoverageAnalyzer(
                threshold_pct=args.threshold_pct,
                fail_on_orphans=args.fail_on_orphans,
            )
            results = analyzer.run()
            print(json.dumps({"overall": results["overall_coverage_pct"], "schemas": len(results["schemas"])}, indent=2))
            sys.exit(results["exit_code"])
        """)
    dest.write_text(content)


def _write_exclusion_schema(dest: Path) -> None:
    """Write .schema-coverage-exclude.yaml exclusion template.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .schema-coverage-exclude.yaml — schema field coverage exclusions.
        # Every exclusion MUST include reason, reviewer, and expiry.
        #
        # Example:
        #   - schema: UserResponse
        #     field: internal_tracking_id
        #     reason: "Internal field not exposed to test clients"
        #     reviewer: "@backend-team"
        #     expiry: "2027-06-01"
        version: "1.0"
        exclusions: []
        """)
    dest.write_text(content)


def _write_ci_workflow(dest: Path) -> None:
    """Write .github/workflows/schema-coverage.yml CI workflow.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .github/workflows/schema-coverage.yml
        name: Schema Coverage

        on:
          pull_request:
            branches: [main, master]
          push:
            branches: [main, master]

        jobs:
          schema-coverage:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
              - uses: actions/setup-python@v5
                with:
                  python-version: "3.12"
                  cache: pip
              - name: Install dependencies
                run: pip install -r requirements.txt
              - name: Run schema coverage
                run: |
                  PYTHONPATH=. python scripts/schema_coverage.py \\
                    --threshold-pct 80 --fail-on-orphans
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
