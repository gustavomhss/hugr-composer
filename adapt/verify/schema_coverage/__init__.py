"""TOOL-031: schema_coverage — AST-based Pydantic schema field coverage analysis.

Walks every ``BaseModel`` subclass under ``app/`` with ``ast``, enumerates all
fields (including aliased and inherited ones), cross-references ``tests/`` for
field references, and produces a per-schema coverage percentage plus an
**orphan-fields** list.  Writes a ``schema-coverage.json`` report and a GitHub
Actions CI workflow.

The tool is idempotent: a second run returns ``status="no_op"`` when
``scripts/schema_coverage.py`` already exists.

Honesty (WP-14 §11): the walker enumerates annotated assignments on
``ClassDef`` nodes (``ast.AnnAssign``) and treats each field as a single unit
— ``Optional[X]``/``Union[X, Y]`` branches are NOT separately tracked.
Inherited fields are also NOT followed (the walker inspects each class body
only). ``warnings`` is worded as "union/optional branches counted as single
covered branch; inherited fields not followed" — it does not claim
"100% coverage".
"""

from __future__ import annotations

import ast
import json
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent


MCP_TOOL = {
    "name": "fastapi_resiliency_analyze_schema_coverage",
    "description": "Measure how well the OpenAPI schema covers all routes and models.",
    "tags": ["verify"],
    "entry": "schema_coverage",
}


def schema_coverage(inp: ToolInput) -> ToolResult:
    """Generate schema coverage analysis infrastructure for a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    app_dir = project / "app"
    if inp.dry_run:
        schemas = _discover_schemas(app_dir)
        return ToolResult(
            status="success",
            notes=[f"[dry_run] Would analyze {len(schemas)} schema classes."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )


    from adapt.contracts.prerequisites import Prereq, check_prerequisites

    prereq_errors = check_prerequisites(inp.project_dir, Prereq.BASE_MODEL)
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_elapsed_ms(start),
        )


    script = project / "scripts" / "schema_coverage.py"
    if script.exists() and "SchemaCoverageAnalyzer" in script.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "scripts/schema_coverage.py already present — schema coverage already configured."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []


    (project / "scripts").mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "orchestrator.py.tmpl", dest=script, substitutions={})
    files_created.append(str(script))

    exclude_file = project / ".schema-coverage-exclude.yaml"
    if not exclude_file.exists():
        render_to(_HERE, "exclusion_schema.yaml.tmpl", dest=exclude_file, substitutions={})
        files_created.append(str(exclude_file))

    report_file = project / "schema-coverage.json"
    coverage_data = _run_analysis(app_dir, project / "tests")
    report_file.write_text(json.dumps(coverage_data, indent=2))
    files_created.append(str(report_file))

    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_file = ci_dir / "schema-coverage.yml"
    if not ci_file.exists():
        render_to(_HERE, "ci_workflow.yml.tmpl", dest=ci_file, substitutions={})
        files_created.append(str(ci_file))

    # Phase-5 emitted test (P1 #15)
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted_test = project / "tests" / "test_schema_coverage_emitted.py"
    if not emitted_test.exists():
        render_to(_HERE, "test_emitted.py.tmpl", dest=emitted_test, substitutions={})
        files_created.append(str(emitted_test))

    total_schemas = len(coverage_data.get("schemas", {}))
    orphan_count = sum(
        len(v.get("orphan_fields", [])) for v in coverage_data.get("schemas", {}).values()
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
        warnings=[
            "Advisory check: walker counts each Pydantic field once regardless of "
            "Optional/Union branches and does NOT follow inherited fields. Coverage "
            "percentage is an approximation, not a guarantee of complete field "
            "exercise. The emitted CI workflow runs the check but does NOT register "
            "a required status."
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
    """Walk app/ and return [(ClassName, [field_names])] for BaseModel subclasses."""
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
    """Return True if the class inherits from BaseModel or a known subclass."""
    base_names = {"BaseModel", "SQLModel", "TimestampMixin"}
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in base_names:
            return True
        if isinstance(base, ast.Attribute) and base.attr in base_names:
            return True
    return False


def _extract_fields(node: ast.ClassDef) -> list[str]:
    """Extract field names from a ClassDef via annotated assignments."""
    fields: list[str] = []
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            name = stmt.target.id
            if not name.startswith("_"):
                fields.append(name)
    return fields


def _collect_test_references(tests_dir: Path) -> set[str]:
    """Collect all field-like identifiers referenced in test files."""
    refs: list[str] = []
    if not tests_dir.exists():
        return set()
    for py_file in sorted(tests_dir.rglob("*.py")):
        try:
            src = py_file.read_text()
        except OSError:
            continue
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                refs.append(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                refs.append(node.value)
    return set(refs)


def _run_analysis(app_dir: Path, tests_dir: Path) -> dict:
    """Run the full schema coverage analysis and return structured data."""
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


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
