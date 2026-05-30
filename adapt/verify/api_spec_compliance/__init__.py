"""TOOL-033: api_spec_compliance — OpenAPI snapshot diff and documentation gate.

Extracts the live OpenAPI schema from a FastAPI app via ``app.openapi()``,
diffs it against a committed ``openapi.json`` snapshot, classifies changes as
BREAKING / NON_BREAKING / METADATA, runs a documentation gate (every route
must have ``summary``, ``description >= 20 chars``, ``response_model``, and at
least one ``tag``), and suggests a semver bump.

The tool is idempotent: a second run detects ``scripts/api_spec_compliance.py``
and returns ``status="no_op"``.

Honesty (WP-14 §11): the emitted CI workflow runs the check but does NOT use
``continue-on-error: false`` plus a required-status gate; therefore the
``warnings`` text describes the check as "reports BREAKING changes" — it
does not claim to *block* PRs. Calibration of merge-blocking is a project
policy decision (configure as required check in repo settings).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent


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
    """Generate API spec compliance infrastructure for a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    script = project / "scripts" / "api_spec_compliance.py"
    if script.exists() and "APISpecComplianceChecker" in script.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "scripts/api_spec_compliance.py already present — API spec compliance already configured."
            ],
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

    (project / "scripts").mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "orchestrator.py.tmpl", dest=script, substitutions={})
    files_created.append(str(script))

    diff_rules = project / ".api-diff-rules.yaml"
    if not diff_rules.exists():
        render_to(_HERE, "diff_rules.yaml.tmpl", dest=diff_rules, substitutions={})
        files_created.append(str(diff_rules))

    snapshot_file = project / "openapi.json"
    if not snapshot_file.exists():
        schema = _try_extract_schema(project)
        if schema:
            snapshot_file.write_text(json.dumps(schema, indent=2, sort_keys=True))
            files_created.append(str(snapshot_file))

    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_file = ci_dir / "api-spec-compliance.yml"
    if not ci_file.exists():
        render_to(_HERE, "ci_workflow.yml.tmpl", dest=ci_file, substitutions={})
        files_created.append(str(ci_file))

    # Phase-5 emitted test (P1 #15)
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted_test = project / "tests" / "test_api_spec_compliance_emitted.py"
    if not emitted_test.exists():
        render_to(_HERE, "test_emitted.py.tmpl", dest=emitted_test, substitutions={})
        files_created.append(str(emitted_test))

    return ToolResult(
        status="success",
        files_created=files_created,
        notes=[
            "Snapshot in openapi.json — update only via --update-snapshot with justification.",
            "Documentation gate: every route needs summary, description≥20ch, response_model, tag.",
            "Change classification: BREAKING / NON_BREAKING / METADATA with semver suggestion.",
        ],
        warnings=[
            "Advisory check: scripts/api_spec_compliance.py reports BREAKING changes and "
            "doc violations; the emitted CI workflow runs the check but does NOT register "
            "a required status — configure branch protection separately to actually block PRs."
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
    """Diff two OpenAPI schemas and classify each change."""
    changes: list[dict[str, Any]] = []
    old_paths = old.get("paths", {})
    new_paths = new.get("paths", {})

    for route in set(old_paths) - set(new_paths):
        changes.append({"type": "BREAKING", "path": route, "description": f"Route {route} removed"})

    for route in set(new_paths) - set(old_paths):
        changes.append(
            {"type": "NON_BREAKING", "path": route, "description": f"Route {route} added"}
        )

    for route in set(old_paths) & set(new_paths):
        changes.extend(_diff_route(route, old_paths[route], new_paths[route]))

    if old.get("info", {}).get("description") != new.get("info", {}).get("description"):
        changes.append(
            {
                "type": "METADATA",
                "path": "info.description",
                "description": "API description changed",
            }
        )

    return changes


def _diff_route(route: str, old: dict, new: dict) -> list[dict]:
    """Diff a single route's methods and return classified changes."""
    changes: list[dict] = []
    for method in set(old) | set(new):
        if method not in old:
            changes.append(
                {
                    "type": "NON_BREAKING",
                    "path": f"{route}.{method}",
                    "description": f"Method {method.upper()} added",
                }
            )
        elif method not in new:
            changes.append(
                {
                    "type": "BREAKING",
                    "path": f"{route}.{method}",
                    "description": f"Method {method.upper()} removed",
                }
            )
        else:
            old_params = {p["name"]: p for p in old[method].get("parameters", [])}
            new_params = {p["name"]: p for p in new[method].get("parameters", [])}
            for param_name, param in new_params.items():
                if param_name not in old_params and param.get("required"):
                    changes.append(
                        {
                            "type": "BREAKING",
                            "path": f"{route}.{method}.{param_name}",
                            "description": f"Required parameter {param_name!r} added",
                        }
                    )
    return changes


def suggest_semver(changes: list[dict]) -> str:
    """Suggest a semver bump based on the change classification."""
    types = {c["type"] for c in changes}
    if "BREAKING" in types:
        return "major"
    if "NON_BREAKING" in types:
        return "minor"
    return "patch"


def check_documentation(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Return routes that fail the documentation gate."""
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


def _try_extract_schema(project: Path) -> dict[str, Any] | None:
    """Try to import the FastAPI app and extract its OpenAPI schema."""
    import sys

    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(project))
        sys.path.insert(0, str(project / "app"))
        from app.main import app  # type: ignore[import]

        return app.openapi()
    except Exception:  # noqa: BLE001
        return None
    finally:
        sys.path[:] = old_path


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
