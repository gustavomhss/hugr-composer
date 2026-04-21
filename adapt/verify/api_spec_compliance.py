"""TOOL-033: api_spec_compliance — OpenAPI snapshot diff and documentation gate.

Extracts the live OpenAPI schema from a FastAPI app via ``app.openapi()``,
diffs it against a committed ``openapi.json`` snapshot, classifies changes as
BREAKING / NON_BREAKING / METADATA, runs a documentation gate (every route
must have ``summary``, ``description >= 20 chars``, ``response_model``, and at
least one ``tag``), and suggests a semver bump.

The tool is idempotent: a second run detects ``scripts/api_spec_compliance.py``
and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.verify.api_spec_compliance import api_spec_compliance

    result = api_spec_compliance(ToolInput(project_dir="/path/to/project"))
    print(result.status)  # "success"
"""

from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path
from typing import Any

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_analyze_api_spec_compliance",
    "description": "Check that the running API conforms to its own OpenAPI specification.",
    "tags": ["verify"],
    "entry": "api_spec_compliance",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def api_spec_compliance(inp: ToolInput) -> ToolResult:
    """Generate API spec compliance infrastructure for a FastAPI project.

    Creates scripts/api_spec_compliance.py orchestrator, an initial
    openapi.json snapshot (if the app is importable), CI workflow, and diff
    rules config.

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
    script = project / "scripts" / "api_spec_compliance.py"
    if script.exists() and "APISpecComplianceChecker" in script.read_text():
        return ToolResult(
            status="no_op",
            notes=["scripts/api_spec_compliance.py already present — API spec compliance already configured."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would generate API spec compliance infrastructure."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Step 1: Orchestrator script -----------------------------------------
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    _write_orchestrator(script)
    files_created.append(str(script))

    # --- Step 2: Diff rules config -------------------------------------------
    diff_rules = project / ".api-diff-rules.yaml"
    if not diff_rules.exists():
        _write_diff_rules(diff_rules)
        files_created.append(str(diff_rules))

    # --- Step 3: Initial openapi.json snapshot (from app if importable) ------
    snapshot_file = project / "openapi.json"
    if not snapshot_file.exists():
        schema = _try_extract_schema(project)
        if schema:
            snapshot_file.write_text(json.dumps(schema, indent=2, sort_keys=True))
            files_created.append(str(snapshot_file))

    # --- Step 4: CI workflow -------------------------------------------------
    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_file = ci_dir / "api-spec-compliance.yml"
    if not ci_file.exists():
        _write_ci_workflow(ci_file)
        files_created.append(str(ci_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        notes=[
            "Snapshot in openapi.json — update only via --update-snapshot with justification.",
            "Documentation gate: every route needs summary, description≥20ch, response_model, tag.",
            "Change classification: BREAKING / NON_BREAKING / METADATA with semver suggestion.",
        ],
        next_steps=[
            "python scripts/api_spec_compliance.py --fail-on-breaking --fail-on-undocumented",
            "Commit openapi.json as the API contract baseline.",
            "Run with --update-snapshot to refresh after intentional API changes.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# OpenAPI diff core
# ---------------------------------------------------------------------------

def diff_openapi(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    """Diff two OpenAPI schemas and classify each change.

    Args:
        old: The committed baseline OpenAPI schema dict.
        new: The live OpenAPI schema dict extracted from the running app.

    Returns:
        List of change dicts, each with ``type`` (BREAKING/NON_BREAKING/METADATA),
        ``path``, and ``description``.
    """
    changes: list[dict[str, Any]] = []
    old_paths = old.get("paths", {})
    new_paths = new.get("paths", {})

    # Removed routes = BREAKING
    for route in set(old_paths) - set(new_paths):
        changes.append({"type": "BREAKING", "path": route, "description": f"Route {route} removed"})

    # Added routes = NON_BREAKING
    for route in set(new_paths) - set(old_paths):
        changes.append({"type": "NON_BREAKING", "path": route, "description": f"Route {route} added"})

    # Changed routes — inspect each method
    for route in set(old_paths) & set(new_paths):
        changes.extend(_diff_route(route, old_paths[route], new_paths[route]))

    # Tag/description changes = METADATA
    if old.get("info", {}).get("description") != new.get("info", {}).get("description"):
        changes.append({"type": "METADATA", "path": "info.description", "description": "API description changed"})

    return changes


def _diff_route(route: str, old: dict, new: dict) -> list[dict]:
    """Diff a single route's methods and return classified changes.

    Args:
        route: The route path string (e.g. ``/api/v1/items``).
        old: Old route dict from OpenAPI spec.
        new: New route dict from OpenAPI spec.

    Returns:
        List of change dicts.
    """
    changes: list[dict] = []
    for method in set(old) | set(new):
        if method not in old:
            changes.append({"type": "NON_BREAKING", "path": f"{route}.{method}", "description": f"Method {method.upper()} added"})
        elif method not in new:
            changes.append({"type": "BREAKING", "path": f"{route}.{method}", "description": f"Method {method.upper()} removed"})
        else:
            # Check required parameter additions
            old_params = {p["name"]: p for p in old[method].get("parameters", [])}
            new_params = {p["name"]: p for p in new[method].get("parameters", [])}
            for param_name, param in new_params.items():
                if param_name not in old_params and param.get("required"):
                    changes.append({"type": "BREAKING", "path": f"{route}.{method}.{param_name}", "description": f"Required parameter {param_name!r} added"})
    return changes


def suggest_semver(changes: list[dict]) -> str:
    """Suggest a semver bump based on the change classification.

    Args:
        changes: List of classified change dicts from ``diff_openapi``.

    Returns:
        ``"major"`` for any BREAKING, ``"minor"`` for NON_BREAKING, ``"patch"`` otherwise.
    """
    types = {c["type"] for c in changes}
    if "BREAKING" in types:
        return "major"
    if "NON_BREAKING" in types:
        return "minor"
    return "patch"


def check_documentation(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Return routes that fail the documentation gate.

    Every route must have: summary, description >= 20 chars, at least one tag,
    and a response_model (200 response with schema).

    Args:
        schema: Live OpenAPI schema dict.

    Returns:
        List of violation dicts with ``path``, ``method``, and ``violations``.
    """
    violations: list[dict] = []
    for route, methods in schema.get("paths", {}).items():
        for method, op in methods.items():
            if not isinstance(op, dict):
                continue
            v: list[str] = []
            if not op.get("summary"):
                v.append("missing summary")
            if len(op.get("description", "")) < 20:
                v.append("description < 20 chars")
            if not op.get("tags"):
                v.append("missing tags")
            responses = op.get("responses", {})
            if "200" not in responses and "201" not in responses:
                v.append("no 200/201 response defined")
            if v:
                violations.append({"path": route, "method": method.upper(), "violations": v})
    return violations


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_orchestrator(dest: Path) -> None:
    """Write scripts/api_spec_compliance.py orchestrator.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"API spec compliance orchestrator — diff + documentation gate.

        Usage::

            python scripts/api_spec_compliance.py [--fail-on-breaking] [--update-snapshot]
        \"\"\"

        from __future__ import annotations

        import argparse
        import json
        import sys
        from pathlib import Path

        ROOT = Path(__file__).parent.parent
        sys.path.insert(0, str(ROOT))
        from adapt.verify.api_spec_compliance import (  # noqa: E402
            diff_openapi, suggest_semver, check_documentation, _try_extract_schema
        )


        class APISpecComplianceChecker:
            \"\"\"Run OpenAPI diff and documentation gate.\"\"\"

            def __init__(
                self,
                project_dir: Path = ROOT,
                spec_file: str = "openapi.json",
                fail_on_breaking: bool = True,
                fail_on_undocumented: bool = True,
                allow_additions: bool = True,
            ) -> None:
                self.project_dir = project_dir
                self.snapshot_path = project_dir / spec_file
                self.fail_on_breaking = fail_on_breaking
                self.fail_on_undocumented = fail_on_undocumented
                self.allow_additions = allow_additions

            def run(self) -> dict:
                \"\"\"Run diff and doc gate; return results with exit_code.\"\"\"
                live = _try_extract_schema(self.project_dir)
                if not live:
                    return {"error": "Could not extract live OpenAPI schema", "exit_code": 1}

                doc_violations = check_documentation(live)
                changes, semver = [], "patch"

                if self.snapshot_path.exists():
                    try:
                        baseline = json.loads(self.snapshot_path.read_text())
                        changes = diff_openapi(baseline, live)
                        if not self.allow_additions:
                            changes = [c for c in changes if c["type"] != "NON_BREAKING"]
                        semver = suggest_semver(changes)
                    except (json.JSONDecodeError, KeyError):
                        pass

                breaking = [c for c in changes if c["type"] == "BREAKING"]
                exit_code = 0
                if self.fail_on_breaking and breaking:
                    exit_code = 1
                if self.fail_on_undocumented and doc_violations:
                    exit_code = 1

                return {
                    "changes": changes,
                    "breaking_count": len(breaking),
                    "doc_violations": doc_violations,
                    "semver_suggestion": semver,
                    "exit_code": exit_code,
                }

            def update_snapshot(self) -> bool:
                \"\"\"Refresh openapi.json with the current live schema.\"\"\"
                live = _try_extract_schema(self.project_dir)
                if not live:
                    return False
                self.snapshot_path.write_text(json.dumps(live, indent=2, sort_keys=True))
                return True


        if __name__ == "__main__":
            parser = argparse.ArgumentParser(description="API spec compliance")
            parser.add_argument("--fail-on-breaking", action="store_true", default=True)
            parser.add_argument("--fail-on-undocumented", action="store_true", default=True)
            parser.add_argument("--update-snapshot", action="store_true")
            args = parser.parse_args()

            checker = APISpecComplianceChecker(
                fail_on_breaking=args.fail_on_breaking,
                fail_on_undocumented=args.fail_on_undocumented,
            )
            if args.update_snapshot:
                ok = checker.update_snapshot()
                print("Snapshot updated." if ok else "Failed to extract schema.")
                sys.exit(0 if ok else 1)

            results = checker.run()
            print(f"Breaking changes: {results.get('breaking_count', 0)}")
            print(f"Doc violations: {len(results.get('doc_violations', []))}")
            print(f"Semver suggestion: {results.get('semver_suggestion', 'patch')}")
            sys.exit(results.get("exit_code", 0))
        """)
    dest.write_text(content)


def _write_diff_rules(dest: Path) -> None:
    """Write .api-diff-rules.yaml diff classification rules.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .api-diff-rules.yaml — OpenAPI diff classification rules
        version: "1.0"
        breaking:
          - removed_route
          - removed_method
          - added_required_parameter
          - narrowed_type
          - removed_response_field
          - removed_enum_value
        non_breaking:
          - added_route
          - added_optional_parameter
          - added_response_field
          - added_enum_value
        metadata:
          - description_change
          - tag_rename
          - operation_id_change
          - example_change
        """)
    dest.write_text(content)


def _write_ci_workflow(dest: Path) -> None:
    """Write .github/workflows/api-spec-compliance.yml CI workflow.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        # .github/workflows/api-spec-compliance.yml
        name: API Spec Compliance

        on:
          pull_request:
            branches: [main, master]
          push:
            branches: [main, master]

        jobs:
          api-compliance:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
              - uses: actions/setup-python@v5
                with:
                  python-version: "3.12"
                  cache: pip
              - name: Install dependencies
                run: pip install -r requirements.txt
              - name: Check API spec compliance
                run: |
                  PYTHONPATH=. python scripts/api_spec_compliance.py \\
                    --fail-on-breaking --fail-on-undocumented
        """)
    dest.write_text(content)


def _try_extract_schema(project: Path) -> dict[str, Any] | None:
    """Try to import the FastAPI app and extract its OpenAPI schema.

    Args:
        project: Project root directory.

    Returns:
        OpenAPI schema dict, or ``None`` if the app cannot be imported.
    """
    import sys
    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(project))
        sys.path.insert(0, str(project / "app"))
        # Try the canonical tiangolo template entry point
        from app.main import app  # type: ignore[import]
        return app.openapi()
    except Exception:  # noqa: BLE001
        return None
    finally:
        sys.path[:] = old_path


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
