"""TOOL-104: add_schema_evolution_guard — CI OpenAPI schema compatibility checker.

Writes a SchemaComparator that diffs two OpenAPI JSON schemas and classifies
changes as BREAKING, COMPATIBLE, or ADDITIVE.  Generates a ``scripts/``
CI script that exits 1 on breaking changes and a GitHub Actions workflow
template.

Breaking change rules enforced:
- Field removed from a request/response schema
- Field type changed
- Required field added (client may not send it yet)
- Enum values shrunk (fewer choices)
- Response shape changed (top-level keys removed)

The tool is idempotent: a second run detects the ``SchemaComparator``
fingerprint and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.testing_tools.add_schema_evolution_guard import add_schema_evolution_guard

    result = add_schema_evolution_guard(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/schema_guard/comparator.py", ...]
    print(result.next_steps)    # ["Set SCHEMA_GUARD_BASELINE_PATH=...", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_testing_add_schema_evolution_guard",
    "description": "Add CI OpenAPI schema compatibility checker that detects breaking changes.",
    "tags": ["extend", "testing_tools"],
    "entry": "add_schema_evolution_guard",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_schema_evolution_guard(inp: ToolInput) -> ToolResult:
    """Add an OpenAPI schema evolution guard with breaking-change detection.

    Creates the SchemaComparator, rule engine, CI script, and GitHub Actions
    workflow template.  Patches ``app/core/config.py`` with guard settings.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # Idempotency guard
    comparator_file = app_dir / "schema_guard" / "comparator.py"
    if comparator_file.exists() and "SchemaComparator" in comparator_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["SchemaComparator already present — schema evolution guard is already installed, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/schema_guard/ (comparator.py, rules.py),",
                "         scripts/check_schema_compat.py CI script,",
                "         .github/workflows/schema_guard.yml GitHub Actions template.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — schema_guard package
    guard_dir = app_dir / "schema_guard"
    guard_dir.mkdir(parents=True, exist_ok=True)
    guard_init = guard_dir / "__init__.py"
    if not guard_init.exists():
        guard_init.write_text('"""OpenAPI schema evolution guard package."""\n')
        files_created.append(str(guard_init))

    # Step 2 — rules module
    rules_file = guard_dir / "rules.py"
    _write_rules_module(rules_file)
    files_created.append(str(rules_file))

    # Step 3 — comparator module
    _write_comparator_module(comparator_file)
    files_created.append(str(comparator_file))

    # Step 4 — CI script
    scripts_dir = project / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    ci_script = scripts_dir / "check_schema_compat.py"
    _write_ci_script(ci_script)
    files_created.append(str(ci_script))

    # Step 5 — GitHub Actions workflow template
    workflows_dir = project / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    workflow_file = workflows_dir / "schema_guard.yml"
    if not workflow_file.exists():
        workflow_file.write_text(_GITHUB_WORKFLOW_TEMPLATE)
        files_created.append(str(workflow_file))

    # Step 6 — patch config.py
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Validate generated Python files
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Schema evolution guard added: SchemaComparator, breaking-change rules,",
            "CI script (scripts/check_schema_compat.py), GitHub Actions workflow.",
            "Breaking rules enforced: field removed, type changed, required added, enum shrunk,",
            "response shape changed.",
        ],
        next_steps=[
            "Set SCHEMA_GUARD_BASELINE_PATH=/path/to/baseline_openapi.json in .env",
            "Export baseline: python scripts/check_schema_compat.py --export-baseline",
            "Run in CI: python scripts/check_schema_compat.py (exits 1 on breaking changes)",
            "Set SCHEMA_GUARD_FAIL_ON_BREAKING=false to warn-only (default is fail=true)",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _write_rules_module(dest: Path) -> None:
    """Write ``app/schema_guard/rules.py`` with breaking-change rule definitions.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Breaking-change rules for OpenAPI schema comparison.

        Each rule is a plain function that accepts two schema dicts (baseline,
        current) and returns a list of human-readable violation strings.
        An empty list means the rule passes.
        \"\"\"

        from __future__ import annotations

        import logging
        from typing import Any

        logger = logging.getLogger(__name__)


        def check_fields_removed(
            baseline: dict[str, Any],
            current: dict[str, Any],
            path: str = "",
        ) -> list[str]:
            \"\"\"Detect fields present in baseline but absent in current schema.

            Args:
                baseline: Baseline OpenAPI component schema properties dict.
                current: Current OpenAPI component schema properties dict.
                path: Dot-separated schema path for error messages.

            Returns:
                List of violation strings, empty if no removals detected.
            \"\"\"
            violations: list[str] = []
            for field, _spec in baseline.items():
                if field not in current:
                    violations.append(
                        f"BREAKING: field '{path}.{field}' removed from schema"
                    )
            return violations


        def check_types_changed(
            baseline: dict[str, Any],
            current: dict[str, Any],
            path: str = "",
        ) -> list[str]:
            \"\"\"Detect fields whose type changed between baseline and current.

            Args:
                baseline: Baseline OpenAPI component schema properties dict.
                current: Current OpenAPI component schema properties dict.
                path: Dot-separated schema path for error messages.

            Returns:
                List of violation strings, empty if no type changes detected.
            \"\"\"
            violations: list[str] = []
            for field, spec in baseline.items():
                if field not in current:
                    continue
                old_type = spec.get("type") or spec.get("$ref", "")
                new_type = current[field].get("type") or current[field].get("$ref", "")
                if old_type and new_type and old_type != new_type:
                    violations.append(
                        f"BREAKING: field '{path}.{field}' type changed "
                        f"'{old_type}' -> '{new_type}'"
                    )
            return violations


        def check_required_added(
            baseline: dict[str, Any],
            current: dict[str, Any],
            path: str = "",
        ) -> list[str]:
            \"\"\"Detect required fields added that were not required in baseline.

            Args:
                baseline: Baseline OpenAPI schema dict (with 'required' key).
                current: Current OpenAPI schema dict (with 'required' key).
                path: Dot-separated schema path for error messages.

            Returns:
                List of violation strings, empty if no new required fields.
            \"\"\"
            violations: list[str] = []
            old_required = set(baseline.get("required") or [])
            new_required = set(current.get("required") or [])
            for field in sorted(new_required - old_required):
                violations.append(
                    f"BREAKING: field '{path}.{field}' is now required "
                    "(was optional in baseline)"
                )
            return violations


        def check_enum_shrunk(
            baseline: dict[str, Any],
            current: dict[str, Any],
            path: str = "",
        ) -> list[str]:
            \"\"\"Detect enum fields that lost values between baseline and current.

            Args:
                baseline: Baseline OpenAPI component schema properties dict.
                current: Current OpenAPI component schema properties dict.
                path: Dot-separated schema path for error messages.

            Returns:
                List of violation strings, empty if no enum shrinkage detected.
            \"\"\"
            violations: list[str] = []
            for field, spec in baseline.items():
                if field not in current:
                    continue
                old_enum = set(spec.get("enum") or [])
                new_enum = set(current[field].get("enum") or [])
                if not old_enum:
                    continue
                removed = old_enum - new_enum
                if removed:
                    violations.append(
                        f"BREAKING: enum field '{path}.{field}' lost values: "
                        + ", ".join(sorted(str(v) for v in removed))
                    )
            return violations


        def check_response_shape_changed(
            baseline_responses: dict[str, Any],
            current_responses: dict[str, Any],
            path: str = "",
        ) -> list[str]:
            \"\"\"Detect top-level response keys removed from successful responses.

            Args:
                baseline_responses: Baseline OpenAPI responses dict for an endpoint.
                current_responses: Current OpenAPI responses dict for an endpoint.
                path: Endpoint path for error messages.

            Returns:
                List of violation strings, empty if response shape unchanged.
            \"\"\"
            violations: list[str] = []
            for status_code in ("200", "201"):
                old_resp = baseline_responses.get(status_code, {})
                new_resp = current_responses.get(status_code, {})
                if not old_resp:
                    continue
                old_keys = set(_extract_response_keys(old_resp))
                new_keys = set(_extract_response_keys(new_resp))
                for key in sorted(old_keys - new_keys):
                    violations.append(
                        f"BREAKING: response key '{key}' removed from "
                        f"{path} {status_code}"
                    )
            return violations


        def _extract_response_keys(response: dict[str, Any]) -> list[str]:
            \"\"\"Extract top-level property keys from an OpenAPI response object.

            Args:
                response: OpenAPI response dict (may contain content/schema nesting).

            Returns:
                List of property key names, empty when schema cannot be resolved.
            \"\"\"
            content = response.get("content", {})
            for media_type in ("application/json", "*/*"):
                media = content.get(media_type, {})
                schema = media.get("schema", {})
                props = schema.get("properties", {})
                if props:
                    return list(props.keys())
            return []
    """)
    dest.write_text(content)


def _write_comparator_module(dest: Path) -> None:
    """Write ``app/schema_guard/comparator.py`` with SchemaComparator.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"SchemaComparator — diff two OpenAPI schemas and classify changes.

        Usage::

            from app.schema_guard.comparator import SchemaComparator, ChangeClass

            comparator = SchemaComparator()
            result = comparator.compare(baseline_schema, current_schema)
            if result.classification == ChangeClass.BREAKING:
                sys.exit(1)
        \"\"\"

        from __future__ import annotations

        import logging
        from dataclasses import dataclass, field
        from enum import Enum
        from typing import Any

        from app.schema_guard.rules import (
            check_enum_shrunk,
            check_fields_removed,
            check_required_added,
            check_response_shape_changed,
            check_types_changed,
        )

        logger = logging.getLogger(__name__)


        class ChangeClass(str, Enum):
            \"\"\"Classification of the overall schema diff result.\"\"\"

            BREAKING = "BREAKING"
            COMPATIBLE = "COMPATIBLE"
            ADDITIVE = "ADDITIVE"
            IDENTICAL = "IDENTICAL"


        @dataclass
        class ComparisonResult:
            \"\"\"Result of comparing two OpenAPI schemas.

            Attributes:
                classification: Overall severity of detected changes.
                breaking: List of breaking-change violation strings.
                compatible: List of compatible-change descriptions.
                additive: List of additive-change descriptions.
                summary: Human-readable one-line summary.
            \"\"\"

            classification: ChangeClass
            breaking: list[str] = field(default_factory=list)
            compatible: list[str] = field(default_factory=list)
            additive: list[str] = field(default_factory=list)
            summary: str = ""

            @property
            def is_breaking(self) -> bool:
                \"\"\"Return True when classification is BREAKING.\"\"\"
                return self.classification == ChangeClass.BREAKING


        class SchemaComparator:
            \"\"\"Diff two OpenAPI 3.x JSON schemas and classify the changes.\"\"\"

            def compare(
                self,
                baseline: dict[str, Any],
                current: dict[str, Any],
            ) -> ComparisonResult:
                \"\"\"Compare baseline schema against current, return classified result.

                Args:
                    baseline: Baseline OpenAPI schema dict (JSON-loaded).
                    current: Current OpenAPI schema dict (JSON-loaded).

                Returns:
                    ``ComparisonResult`` with classification and violation lists.
                \"\"\"
                breaking: list[str] = []
                compatible: list[str] = []
                additive: list[str] = []

                self._compare_components(baseline, current, breaking, compatible, additive)
                self._compare_paths(baseline, current, breaking, compatible, additive)

                classification = self._classify(breaking, compatible, additive)
                summary = self._build_summary(classification, breaking, additive)

                return ComparisonResult(
                    classification=classification,
                    breaking=breaking,
                    compatible=compatible,
                    additive=additive,
                    summary=summary,
                )

            def _compare_components(
                self,
                baseline: dict[str, Any],
                current: dict[str, Any],
                breaking: list[str],
                compatible: list[str],
                additive: list[str],
            ) -> None:
                \"\"\"Compare OpenAPI components/schemas between baseline and current.

                Args:
                    baseline: Baseline OpenAPI schema dict.
                    current: Current OpenAPI schema dict.
                    breaking: Accumulator for breaking violations.
                    compatible: Accumulator for compatible change descriptions.
                    additive: Accumulator for additive change descriptions.
                \"\"\"
                base_schemas = (
                    baseline.get("components", {}).get("schemas", {})
                )
                curr_schemas = (
                    current.get("components", {}).get("schemas", {})
                )
                for name, base_schema in base_schemas.items():
                    if name not in curr_schemas:
                        breaking.append(f"BREAKING: schema '{name}' removed from components")
                        continue
                    curr_schema = curr_schemas[name]
                    base_props = base_schema.get("properties", {})
                    curr_props = curr_schema.get("properties", {})
                    path = f"components.{name}"
                    breaking.extend(check_fields_removed(base_props, curr_props, path))
                    breaking.extend(check_types_changed(base_props, curr_props, path))
                    breaking.extend(check_required_added(base_schema, curr_schema, path))
                    breaking.extend(check_enum_shrunk(base_props, curr_props, path))
                    for new_field in sorted(set(curr_props) - set(base_props)):
                        additive.append(f"ADDITIVE: field '{path}.{new_field}' added")
                for name in sorted(set(curr_schemas) - set(base_schemas)):
                    additive.append(f"ADDITIVE: schema '{name}' added to components")

            def _compare_paths(
                self,
                baseline: dict[str, Any],
                current: dict[str, Any],
                breaking: list[str],
                compatible: list[str],
                additive: list[str],
            ) -> None:
                \"\"\"Compare OpenAPI paths between baseline and current.

                Args:
                    baseline: Baseline OpenAPI schema dict.
                    current: Current OpenAPI schema dict.
                    breaking: Accumulator for breaking violations.
                    compatible: Accumulator for compatible change descriptions.
                    additive: Accumulator for additive change descriptions.
                \"\"\"
                base_paths = baseline.get("paths", {})
                curr_paths = current.get("paths", {})
                for path, base_item in base_paths.items():
                    if path not in curr_paths:
                        breaking.append(f"BREAKING: endpoint '{path}' removed")
                        continue
                    curr_item = curr_paths[path]
                    for method in ("get", "post", "put", "patch", "delete"):
                        base_op = base_item.get(method, {})
                        curr_op = curr_item.get(method, {})
                        if base_op and not curr_op:
                            breaking.append(
                                f"BREAKING: {method.upper()} '{path}' removed"
                            )
                            continue
                        if base_op and curr_op:
                            base_resp = base_op.get("responses", {})
                            curr_resp = curr_op.get("responses", {})
                            op_path = f"{method.upper()} {path}"
                            breaking.extend(
                                check_response_shape_changed(base_resp, curr_resp, op_path)
                            )
                for path in sorted(set(curr_paths) - set(base_paths)):
                    additive.append(f"ADDITIVE: endpoint '{path}' added")

            def _classify(
                self,
                breaking: list[str],
                compatible: list[str],
                additive: list[str],
            ) -> ChangeClass:
                \"\"\"Classify diff into BREAKING/COMPATIBLE/ADDITIVE/IDENTICAL.

                Args:
                    breaking: List of breaking violations.
                    compatible: List of compatible changes.
                    additive: List of additive changes.

                Returns:
                    The most severe ``ChangeClass`` applicable.
                \"\"\"
                if breaking:
                    return ChangeClass.BREAKING
                if compatible:
                    return ChangeClass.COMPATIBLE
                if additive:
                    return ChangeClass.ADDITIVE
                return ChangeClass.IDENTICAL

            def _build_summary(
                self,
                classification: ChangeClass,
                breaking: list[str],
                additive: list[str],
            ) -> str:
                \"\"\"Build a concise one-line summary of the comparison result.

                Args:
                    classification: Overall change classification.
                    breaking: Breaking violation list.
                    additive: Additive change list.

                Returns:
                    Human-readable summary string.
                \"\"\"
                if classification == ChangeClass.IDENTICAL:
                    return "Schemas are identical — no changes detected."
                return (
                    f"{classification.value}: "
                    f"{len(breaking)} breaking, {len(additive)} additive changes."
                )
    """)
    dest.write_text(content)


def _write_ci_script(dest: Path) -> None:
    """Write ``scripts/check_schema_compat.py`` CI script.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"CI script: compare current OpenAPI schema against baseline.

        Exit codes:
            0 — no breaking changes (or SCHEMA_GUARD_FAIL_ON_BREAKING=false)
            1 — breaking changes detected (when SCHEMA_GUARD_FAIL_ON_BREAKING=true)

        Usage::

            # Standard CI run (exit 1 on breaking changes)
            python scripts/check_schema_compat.py

            # Export current schema as the new baseline
            python scripts/check_schema_compat.py --export-baseline

            # Warn only (never exit 1)
            SCHEMA_GUARD_FAIL_ON_BREAKING=false python scripts/check_schema_compat.py
        \"\"\"

        from __future__ import annotations

        import argparse
        import json
        import os
        import sys
        from pathlib import Path


        def _load_app_schema() -> dict:
            \"\"\"Load the current OpenAPI schema from the running FastAPI app.

            Returns:
                The OpenAPI schema dict from the app's /openapi.json route.

            Raises:
                SystemExit: When the app cannot be imported or schema loading fails.
            \"\"\"
            project_root = Path(__file__).parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            try:
                import importlib
                app_module = importlib.import_module("app.main")
                return app_module.app.openapi()
            except Exception as exc:
                print(f"ERROR: Cannot load app schema: {exc}", file=sys.stderr)
                sys.exit(1)


        def _load_baseline(baseline_path: str) -> dict | None:
            \"\"\"Load baseline OpenAPI schema from file.

            Args:
                baseline_path: Path to the baseline JSON file.

            Returns:
                Parsed schema dict, or None when the file does not exist.
            \"\"\"
            p = Path(baseline_path)
            if not p.exists():
                return None
            try:
                return json.loads(p.read_text())
            except json.JSONDecodeError as exc:
                print(f"ERROR: Invalid JSON in baseline {p}: {exc}", file=sys.stderr)
                sys.exit(1)


        def _export_baseline(schema: dict, baseline_path: str) -> None:
            \"\"\"Write schema dict to baseline JSON file.

            Args:
                schema: Current OpenAPI schema dict.
                baseline_path: Destination file path.
            \"\"\"
            p = Path(baseline_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(schema, indent=2) + "\\n")
            print(f"Baseline exported to {p}")


        def _run_check(
            baseline: dict,
            current: dict,
            fail_on_breaking: bool,
        ) -> int:
            \"\"\"Run schema comparison and return exit code.

            Args:
                baseline: Baseline OpenAPI schema dict.
                current: Current OpenAPI schema dict.
                fail_on_breaking: When True, return 1 on breaking changes.

            Returns:
                0 on no breaking changes, 1 if breaking and fail_on_breaking.
            \"\"\"
            from app.schema_guard.comparator import SchemaComparator

            comparator = SchemaComparator()
            result = comparator.compare(baseline, current)

            print(f"Schema check: {result.summary}")
            for msg in result.breaking:
                print(f"  {msg}")
            for msg in result.additive:
                print(f"  {msg}")

            if result.is_breaking:
                if fail_on_breaking:
                    print("FAIL: Breaking changes detected. Set SCHEMA_GUARD_FAIL_ON_BREAKING=false to warn only.")
                    return 1
                print("WARN: Breaking changes detected (fail_on_breaking=false).")
            return 0


        def main() -> None:
            \"\"\"Entry point: parse args and run the schema compatibility check.\"\"\"
            parser = argparse.ArgumentParser(description="Check OpenAPI schema compatibility.")
            parser.add_argument(
                "--export-baseline",
                action="store_true",
                help="Export current schema as the new baseline file.",
            )
            args = parser.parse_args()

            baseline_path = os.environ.get(
                "SCHEMA_GUARD_BASELINE_PATH", ".schema_baseline.json"
            )
            fail_on_breaking = (
                os.environ.get("SCHEMA_GUARD_FAIL_ON_BREAKING", "true").lower() != "false"
            )

            current_schema = _load_app_schema()

            if args.export_baseline:
                _export_baseline(current_schema, baseline_path)
                sys.exit(0)

            baseline = _load_baseline(baseline_path)
            if baseline is None:
                print(f"No baseline found at '{baseline_path}'. Export one with --export-baseline.")
                sys.exit(0)

            exit_code = _run_check(baseline, current_schema, fail_on_breaking)
            sys.exit(exit_code)


        if __name__ == "__main__":
            main()
    """)
    dest.write_text(content)


_GITHUB_WORKFLOW_TEMPLATE = textwrap.dedent("""\
    # Schema Guard — detect breaking OpenAPI changes in CI
    # Generated by TOOL-104 add_schema_evolution_guard
    name: Schema Guard

    on:
      pull_request:
        paths:
          - "app/**"

    jobs:
      schema-guard:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4

          - name: Set up Python
            uses: actions/setup-python@v5
            with:
              python-version: "3.12"

          - name: Install dependencies
            run: pip install -r requirements.txt

          - name: Check schema compatibility
            env:
              SCHEMA_GUARD_BASELINE_PATH: .schema_baseline.json
              SCHEMA_GUARD_FAIL_ON_BREAKING: "true"
            run: PYTHONPATH=. python scripts/check_schema_compat.py
""")


def _patch_config(config_file: Path) -> None:
    """Append SCHEMA_GUARD_* settings to app/core/config.py idempotently.

    Args:
        config_file: Path to the project's ``app/core/config.py``.
    """
    content = config_file.read_text()
    fields = [
        "    SCHEMA_GUARD_BASELINE_PATH: str = \".schema_baseline.json\"",
        "    SCHEMA_GUARD_FAIL_ON_BREAKING: bool = True",
    ]
    new_lines: list[str] = []
    for field in fields:
        field_name = field.strip().split(":")[0]
        if field_name not in content:
            new_lines.append(field)
    if not new_lines:
        return
    # Insert before the closing of the Settings class
    if "settings = Settings()" in content:
        content = content.replace(
            "settings = Settings()",
            "\n".join(new_lines) + "\n\nsettings = Settings()",
        )
    else:
        content = content.rstrip("\n") + "\n" + "\n".join(new_lines) + "\n"
    config_file.write_text(content)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: ``time.monotonic()`` snapshot taken at function entry.

    Returns:
        Elapsed time in integer milliseconds.
    """
    return int((time.monotonic() - start) * 1000)
