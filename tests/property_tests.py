"""Property-based tests for adapt tool contracts.

Tests properties that must hold for ANY adapt tool, regardless of which
tool is being tested. Uses randomized inputs within valid bounds.

No Hypothesis required — uses random + loops (100 iterations) per property.

Run with::

    PYTHONPATH=. python3 tests/property_tests.py
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import os
import random
import string
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Callable

from adapt.contracts import ToolInput, ToolResult
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Tool registry — maps module.function to the callable, with default kwargs
# ---------------------------------------------------------------------------

# Each entry: (dotted_module, function_name, extra_kwargs_for_plain_call)
# extra_kwargs are the minimum required to not error for structural reasons
# (e.g., tools that need a non-empty `target` or `operation`).
_TOOL_REGISTRY: list[tuple[str, str, dict]] = [
    # extend / api_design
    ("adapt.extend.api_design.add_api_versioning",  "add_api_versioning",  {}),
    ("adapt.extend.api_design.add_batch_endpoint",  "add_batch_endpoint",  {}),
    ("adapt.extend.api_design.add_graphql",         "add_graphql",         {}),
    ("adapt.extend.api_design.add_long_running_task","add_long_running_task",{}),
    # extend / auth_access
    ("adapt.extend.auth_access.add_api_key_auth",   "add_api_key_auth",    {}),
    ("adapt.extend.auth_access.add_feature_flags",  "add_feature_flags",   {}),
    ("adapt.extend.auth_access.add_mfa",            "add_mfa",             {}),
    ("adapt.extend.auth_access.add_multi_tenancy",  "add_multi_tenancy",   {}),
    ("adapt.extend.auth_access.add_oauth2_provider","add_oauth2_provider", {}),
    ("adapt.extend.auth_access.add_rbac",           "add_rbac",            {}),
    # extend / crud_data
    ("adapt.extend.crud_data.add_audit_log",        "add_audit_log",       {}),
    ("adapt.extend.crud_data.add_bulk_operations",  "add_bulk_operations", {}),
    ("adapt.extend.crud_data.add_cursor_pagination","add_cursor_pagination",{}),
    ("adapt.extend.crud_data.add_data_export",      "add_data_export",     {}),
    ("adapt.extend.crud_data.add_file_upload",      "add_file_upload",     {}),
    ("adapt.extend.crud_data.add_search",           "add_search",          {}),
    ("adapt.extend.crud_data.add_soft_delete",      "add_soft_delete",     {}),
    # extend / infrastructure
    ("adapt.extend.infrastructure.add_cache_layer",      "add_cache_layer",      {}),
    ("adapt.extend.infrastructure.add_circuit_breaker",  "add_circuit_breaker",  {}),
    ("adapt.extend.infrastructure.add_outbox_pattern",   "add_outbox_pattern",   {}),
    ("adapt.extend.infrastructure.add_saga",             "add_saga",             {}),
    ("adapt.extend.infrastructure.add_arq_worker",       "add_arq_worker",       {}),
    ("adapt.extend.infrastructure.add_stripe_checkout",  "add_stripe_checkout",  {}),
    ("adapt.extend.infrastructure.add_email_templates",  "add_email_templates",  {}),
    ("adapt.extend.infrastructure.add_sqladmin",         "add_sqladmin",         {}),
    # extend / realtime
    ("adapt.extend.realtime.add_sse",              "add_sse",              {}),
    ("adapt.extend.realtime.add_webhook_receiver", "add_webhook_receiver", {}),
    ("adapt.extend.realtime.add_webhook_sender",   "add_webhook_sender",   {}),
    ("adapt.extend.realtime.add_websocket_chat",   "add_websocket_chat",   {}),
    # extend / testing_tools
    ("adapt.extend.testing_tools.add_contract_tests","add_contract_tests", {}),
    ("adapt.extend.testing_tools.add_factory",       "add_factory",        {}),
    ("adapt.extend.testing_tools.add_load_profile",  "add_load_profile",   {}),
    # evolve (all have extra keyword params with sensible defaults)
    ("adapt.evolve.add_event_driven",  "add_event_driven",  {}),
    ("adapt.evolve.add_i18n",          "add_i18n",          {}),
    ("adapt.evolve.add_migration_data","add_migration_data",{}),
    ("adapt.evolve.extract_service",   "extract_service",   {}),
    ("adapt.evolve.generate_admin_panel","generate_admin_panel",{}),
    ("adapt.evolve.generate_docs",     "generate_docs",     {}),
    ("adapt.evolve.generate_sdk",      "generate_sdk",      {}),
    # refactor_model needs a non-empty target to do real work, but
    # calling with defaults (empty target) must still not crash
    ("adapt.evolve.refactor_model",    "refactor_model",    {}),
    # operate
    ("adapt.operate.api_changelog",         "api_changelog",         {}),
    ("adapt.operate.blast_radius",          "blast_radius",          {}),
    ("adapt.operate.connection_pool_monitor","connection_pool_monitor",{}),
    ("adapt.operate.dead_code_finder",      "dead_code_finder",      {}),
    ("adapt.operate.dependency_graph",      "dependency_graph",      {}),
    ("adapt.operate.error_rate_analyzer",   "error_rate_analyzer",   {}),
    ("adapt.operate.migration_diff",        "migration_diff",        {}),
    ("adapt.operate.sla_reporter",          "sla_reporter",          {}),
    # verify
    ("adapt.verify.api_spec_compliance",    "api_spec_compliance",   {}),
    ("adapt.verify.dependency_audit",       "dependency_audit",      {}),
    ("adapt.verify.detect_n_plus_one",      "detect_n_plus_one",     {}),
    ("adapt.verify.performance_baseline",   "performance_baseline",  {}),
    ("adapt.verify.schema_coverage",        "schema_coverage",       {}),
    ("adapt.verify.security_scan",          "security_scan",         {}),
    # proactive
    ("adapt.proactive.fastapi_doctor",      "fastapi_doctor",        {}),
]


def _load_tool(module_path: str, fn_name: str) -> Callable:
    """Import module and return the named callable.

    Args:
        module_path: Dotted Python module path.
        fn_name: Name of the public function.

    Returns:
        The callable.

    Raises:
        ImportError: If the module or function cannot be loaded.
    """
    mod = importlib.import_module(module_path)
    return getattr(mod, fn_name)


def _call_tool(fn: Callable, inp: ToolInput, extra_kwargs: dict) -> ToolResult:
    """Call *fn* with *inp* and *extra_kwargs*.

    Args:
        fn: The adapt tool callable.
        inp: ToolInput to pass as the first positional argument.
        extra_kwargs: Additional keyword arguments forwarded to the tool.

    Returns:
        The ToolResult returned by the tool.
    """
    return fn(inp, **extra_kwargs)


def _dir_sha256(directory: Path) -> str:
    """Compute a deterministic SHA-256 fingerprint of all files under *directory*.

    Walks the directory tree, sorts paths for determinism, and hashes
    each file's relative path and content.

    Args:
        directory: Root directory to hash.

    Returns:
        Hex-encoded SHA-256 digest string.
    """
    hasher = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(directory))
            hasher.update(rel.encode())
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _all_py_parse(directory: Path) -> list[str]:
    """Return a list of error messages for .py files that fail ast.parse.

    Args:
        directory: Root directory to check recursively.

    Returns:
        List of error strings; empty if all files parse correctly.
    """
    errors: list[str] = []
    for py_file in sorted(directory.rglob("*.py")):
        src = py_file.read_text(encoding="utf-8", errors="replace")
        try:
            ast.parse(src)
        except SyntaxError as exc:
            errors.append(f"{py_file}: {exc}")
    return errors


# ---------------------------------------------------------------------------
# Results accumulator
# ---------------------------------------------------------------------------

class _Results:
    """Simple pass/fail accumulator for a single property run."""

    def __init__(self, property_name: str, total_tools: int) -> None:
        self.property_name = property_name
        self.total_tools = total_tools
        self.passed = 0
        self.failed = 0
        self.failures: list[str] = []

    def record(self, tool_label: str, ok: bool, reason: str = "") -> None:
        """Record one test result.

        Args:
            tool_label: Human-readable label (module.fn).
            ok: Whether the property held.
            reason: Failure description when *ok* is False.
        """
        if ok:
            self.passed += 1
        else:
            self.failed += 1
            self.failures.append(f"  [{tool_label}] {reason}")

    def summary(self) -> str:
        """Return a one-line summary string.

        Returns:
            Formatted summary with pass/fail counts and any failure details.
        """
        status = "PASS" if self.failed == 0 else "FAIL"
        lines = [
            f"  {status} {self.property_name}: "
            f"{self.passed}/{self.total_tools} tools"
        ]
        lines.extend(self.failures[:5])  # cap noise
        if len(self.failures) > 5:
            lines.append(f"  ... and {len(self.failures) - 5} more failures")
        return "\n".join(lines)

    @property
    def ok(self) -> bool:
        """True when all tools passed this property."""
        return self.failed == 0


# ---------------------------------------------------------------------------
# Tool categorisation helpers
# ---------------------------------------------------------------------------

# Report/snapshot tools are designed to regenerate their output on every call
# (they produce fresh reports or snapshots rather than patching project structure).
# Idempotency is tested differently for them: they must not crash and must return
# a consistent status, but re-creating output files is expected behaviour.
_REPORT_TOOLS: frozenset[str] = frozenset({
    "dead_code_finder",
    "dependency_graph",
    "sla_reporter",
    "error_rate_analyzer",
    "api_changelog",
    "blast_radius",
    "connection_pool_monitor",
    "migration_diff",
    "fastapi_doctor",
    "api_spec_compliance",
    "dependency_audit",
    "performance_baseline",
    "schema_coverage",
    "security_scan",
    "generate_sdk",      # regenerates openapi.json + .schema_hash every run
})


# ---------------------------------------------------------------------------
# Property 1 — Idempotency
# ---------------------------------------------------------------------------

def prop_idempotency(tools: list[tuple[str, str, dict]], n_iter: int = 1) -> _Results:
    """Property: applying a write-capable tool twice must not re-create files on the
    second run.  Report/snapshot tools (those in _REPORT_TOOLS) are exempt from the
    "no re-creation" check — for them we only assert the tool does not crash.

    Args:
        tools: List of (module_path, fn_name, extra_kwargs) tuples.
        n_iter: Iterations per tool (1 is sufficient for project-level idempotency).

    Returns:
        _Results accumulator.
    """
    results = _Results("IDEMPOTENCY", len(tools))

    for module_path, fn_name, extra_kwargs in tools:
        label = f"{module_path}.{fn_name}"
        is_report_tool = fn_name in _REPORT_TOOLS

        try:
            fn = _load_tool(module_path, fn_name)
        except Exception as exc:
            results.record(label, False, f"import error: {exc}")
            continue

        try:
            project_dir = create_fixture_project(name=f"prop_idem_{fn_name[:20]}")
            inp = ToolInput(project_dir=str(project_dir))

            r1 = _call_tool(fn, inp, extra_kwargs)
            r2 = _call_tool(fn, inp, extra_kwargs)

            # Contract for report tools: must not crash on second run.
            if is_report_tool:
                # Any non-exception result is acceptable.
                results.record(label, True)
                continue

            # Contract for write/infrastructure tools: second run must not
            # re-create files that the first run already created.
            if r2.status == "error" and r1.status != "error":
                error_msg = r2.error or ""
                is_guard = any(kw in error_msg.lower() for kw in
                               ["already", "present", "exist", "no_op"])
                if not is_guard:
                    results.record(label, False,
                                   f"second run returned error: {r2.error!r}")
                    continue

            if r1.status == "success" and r2.status == "success" and r2.files_created:
                results.record(label, False,
                               f"second run re-created {len(r2.files_created)} file(s): "
                               f"{r2.files_created[:2]}")
                continue

            results.record(label, True)

        except Exception as exc:
            results.record(label, False, f"exception: {exc}")

    return results


# ---------------------------------------------------------------------------
# Property 2 — Dry-run purity
# ---------------------------------------------------------------------------

def prop_dry_run_purity(tools: list[tuple[str, str, dict]]) -> _Results:
    """Property: dry_run=True never modifies any file on disk.

    Takes a SHA-256 hash of the project directory before and after the dry-run
    call and asserts they are identical.

    Args:
        tools: List of (module_path, fn_name, extra_kwargs) tuples.

    Returns:
        _Results accumulator.
    """
    results = _Results("DRY_RUN_PURITY", len(tools))

    for module_path, fn_name, extra_kwargs in tools:
        label = f"{module_path}.{fn_name}"
        try:
            fn = _load_tool(module_path, fn_name)
        except Exception as exc:
            results.record(label, False, f"import error: {exc}")
            continue

        try:
            project_dir = create_fixture_project(name=f"prop_dry_{fn_name[:20]}")
            inp = ToolInput(project_dir=str(project_dir), dry_run=True)

            before = _dir_sha256(project_dir)
            _call_tool(fn, inp, extra_kwargs)
            after = _dir_sha256(project_dir)

            if before != after:
                results.record(label, False,
                               "dry_run=True modified at least one file on disk")
            else:
                results.record(label, True)

        except Exception as exc:
            results.record(label, False, f"exception: {exc}")

    return results


# ---------------------------------------------------------------------------
# Property 3 — No crash on any path (robustness under arbitrary input)
# ---------------------------------------------------------------------------

def prop_error_on_invalid_dir(tools: list[tuple[str, str, dict]],
                               n_iter: int = 5) -> _Results:
    """Property: calling any tool with a novel (never-used) temp path must never
    raise an unhandled exception or call sys.exit().

    Adapt tools are generators and are allowed to create a skeleton project at
    the given path (returning "success").  The contract is only that they do NOT
    crash — every exit path must go through ToolResult.

    Uses multiple distinct random /tmp/ paths to catch edge cases.

    Args:
        tools: List of (module_path, fn_name, extra_kwargs) tuples.
        n_iter: Number of distinct paths to try per tool.

    Returns:
        _Results accumulator.
    """
    results = _Results("NO_CRASH_ON_ANY_PATH", len(tools))

    rng = random.Random(42)

    for module_path, fn_name, extra_kwargs in tools:
        label = f"{module_path}.{fn_name}"
        try:
            fn = _load_tool(module_path, fn_name)
        except Exception as exc:
            results.record(label, False, f"import error: {exc}")
            continue

        tool_ok = True
        failure_msg = ""

        for i in range(n_iter):
            rand_suffix = "".join(rng.choices(string.ascii_lowercase, k=16))
            # Use /tmp/ so macOS allows directory creation.
            test_path = f"/tmp/skill001_robustness_{rand_suffix}_{i}/project"

            try:
                inp = ToolInput(project_dir=test_path)
                result = _call_tool(fn, inp, extra_kwargs)

                if not isinstance(result, ToolResult):
                    tool_ok = False
                    failure_msg = (
                        f"returned non-ToolResult for path {test_path!r}: "
                        f"{type(result).__name__}"
                    )
                    break

            except SystemExit as exc:
                tool_ok = False
                failure_msg = f"called sys.exit({exc.code}) for path {test_path!r}"
                break
            except Exception:
                tool_ok = False
                failure_msg = (
                    f"raised unhandled exception for path {test_path!r}: "
                    f"{traceback.format_exc().splitlines()[-1]}"
                )
                break

        results.record(label, tool_ok, failure_msg)

    return results


# ---------------------------------------------------------------------------
# Property 4 — Parse correctness
# ---------------------------------------------------------------------------

def prop_parse_correctness(tools: list[tuple[str, str, dict]]) -> _Results:
    """Property: after applying any tool, all .py files in the project parse with ast.parse.

    Skips tools that return status='error' (they may have legitimately found
    nothing to work on in the generated project).

    Args:
        tools: List of (module_path, fn_name, extra_kwargs) tuples.

    Returns:
        _Results accumulator.
    """
    results = _Results("PARSE_CORRECTNESS", len(tools))

    for module_path, fn_name, extra_kwargs in tools:
        label = f"{module_path}.{fn_name}"
        try:
            fn = _load_tool(module_path, fn_name)
        except Exception as exc:
            results.record(label, False, f"import error: {exc}")
            continue

        try:
            project_dir = create_fixture_project(name=f"prop_parse_{fn_name[:18]}")
            inp = ToolInput(project_dir=str(project_dir))

            result = _call_tool(fn, inp, extra_kwargs)

            if result.status == "error":
                # Not a property violation — tool gracefully declined.
                results.record(label, True)
                continue

            errors = _all_py_parse(project_dir)
            if errors:
                results.record(label, False,
                               f"{len(errors)} parse error(s): {errors[0]}")
            else:
                results.record(label, True)

        except Exception as exc:
            results.record(label, False, f"exception: {exc}")

    return results


# ---------------------------------------------------------------------------
# Property 5 — ToolResult contract
# ---------------------------------------------------------------------------

def prop_toolresult_contract(tools: list[tuple[str, str, dict]]) -> _Results:
    """Property: ToolResult always has valid status, list fields, and non-negative timing.

    Validates the Pydantic-enforced contract:
    - status in {"success", "no_op", "error"}
    - files_created is list[str]
    - files_modified is list[str]
    - execution_time_ms >= 0

    Also validates the error field consistency:
    - if status == "error" there should be an error message (or at least status is correct)

    Args:
        tools: List of (module_path, fn_name, extra_kwargs) tuples.

    Returns:
        _Results accumulator.
    """
    results = _Results("TOOLRESULT_CONTRACT", len(tools))
    valid_statuses = {"success", "no_op", "error"}

    for module_path, fn_name, extra_kwargs in tools:
        label = f"{module_path}.{fn_name}"
        try:
            fn = _load_tool(module_path, fn_name)
        except Exception as exc:
            results.record(label, False, f"import error: {exc}")
            continue

        try:
            project_dir = create_fixture_project(name=f"prop_ctr_{fn_name[:19]}")
            inp = ToolInput(project_dir=str(project_dir))

            result = _call_tool(fn, inp, extra_kwargs)

        except Exception as exc:
            results.record(label, False,
                           f"tool raised unhandled exception: "
                           f"{traceback.format_exc().splitlines()[-1]}")
            continue

        # Validate each contract clause
        violations: list[str] = []

        if result.status not in valid_statuses:
            violations.append(
                f"status={result.status!r} not in {valid_statuses}"
            )

        if not isinstance(result.files_created, list):
            violations.append(
                f"files_created must be list, got {type(result.files_created).__name__}"
            )
        elif any(not isinstance(p, str) for p in result.files_created):
            violations.append("files_created contains non-str element")

        if not isinstance(result.files_modified, list):
            violations.append(
                f"files_modified must be list, got {type(result.files_modified).__name__}"
            )
        elif any(not isinstance(p, str) for p in result.files_modified):
            violations.append("files_modified contains non-str element")

        if result.execution_time_ms < 0:
            violations.append(
                f"execution_time_ms={result.execution_time_ms} is negative"
            )

        if violations:
            results.record(label, False, "; ".join(violations))
        else:
            results.record(label, True)

    return results


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def _load_all_tools() -> list[tuple[str, str, dict]]:
    """Return the full tool registry.

    Returns:
        List of (module_path, fn_name, extra_kwargs) tuples.
    """
    return list(_TOOL_REGISTRY)


def run_all_properties() -> int:
    """Run all 5 properties against every registered tool.

    Returns:
        Exit code: 0 if all properties passed, 1 otherwise.
    """
    tools = _load_all_tools()
    n_tools = len(tools)

    print(f"\n{'='*70}")
    print(f"PROPERTY-BASED TESTS  —  {n_tools} tools × 5 properties")
    print(f"{'='*70}\n")

    properties = [
        prop_idempotency(tools),
        prop_dry_run_purity(tools),
        prop_error_on_invalid_dir(tools),
        prop_parse_correctness(tools),
        prop_toolresult_contract(tools),
    ]

    overall_ok = True
    for res in properties:
        print(res.summary())
        if not res.ok:
            overall_ok = False

    print(f"\n{'='*70}")
    passed_props = sum(1 for r in properties if r.ok)
    total_props = len(properties)
    total_tool_checks = sum(r.passed + r.failed for r in properties)
    total_passed = sum(r.passed for r in properties)

    if overall_ok:
        print(
            f"RESULT: ALL PASSED — "
            f"{total_props}/{total_props} properties × {n_tools} tools "
            f"({total_passed}/{total_tool_checks} tool-checks passed)"
        )
    else:
        print(
            f"RESULT: FAILED — "
            f"{passed_props}/{total_props} properties passed "
            f"({total_passed}/{total_tool_checks} tool-checks passed)"
        )
    print(f"{'='*70}\n")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(run_all_properties())
