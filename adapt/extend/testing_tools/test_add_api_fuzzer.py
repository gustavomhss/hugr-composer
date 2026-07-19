"""Tests for TOOL-124 add_api_fuzzer.

Generates real fixture projects, runs the tool, and verifies all completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_api_fuzzer.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_api_fuzzer.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_api_fuzzer import add_api_fuzzer
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under root, sorted.

    Args:
        root: Directory to walk recursively.
    """
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Assert every .py file under root parses without SyntaxError.

    Args:
        root: Directory to walk recursively.
    """
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _fresh(name: str) -> Path:
    """Return a fresh fixture project.

    Args:
        name: Unique project name.
    """
    return create_fixture_project(name=name)


# ---------------------------------------------------------------------------
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = _fresh("fuzz_t01")
    result = add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: Idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns no_op with no files created or modified."""
    project_dir = _fresh("fuzz_t02")
    r1 = add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = _fresh("fuzz_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_api_fuzzer(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files created exist on disk
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 4 files are created and all exist on disk."""
    project_dir = _fresh("fuzz_t04")
    result = add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files_created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files modified exist on disk
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file is modified and all exist on disk."""
    project_dir = _fresh("fuzz_t05")
    result = add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files_modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: All .py files parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every .py file in the project parses without SyntaxError."""
    project_dir = _fresh("fuzz_t06")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: No function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC (AST walk)."""
    project_dir = _fresh("fuzz_t07")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    fuzzer_dir = project_dir / "app" / "fuzzer"
    for py_file in sorted(fuzzer_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                assert loc <= 50, (
                    f"Function '{node.name}' in {py_file} has {loc} LOC (max 50)"
                )


# ---------------------------------------------------------------------------
# CC-08: Config fields patched with 4-space indent
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: FUZZ_ITERATIONS, FUZZ_TIMEOUT_S, FUZZ_EXCLUDE_PATHS in config."""
    project_dir = _fresh("fuzz_t08")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "FUZZ_ITERATIONS" in content
    assert "FUZZ_TIMEOUT_S" in content
    assert "FUZZ_EXCLUDE_PATHS" in content
    for line in content.splitlines():
        if "FUZZ_ITERATIONS" in line:
            assert line.startswith("    "), f"Field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# CC-09: APIFuzzer created in __init__.py
# ---------------------------------------------------------------------------

def test_api_fuzzer_init() -> None:
    """CC-09: app/fuzzer/__init__.py exists with APIFuzzer class."""
    project_dir = _fresh("fuzz_t09")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "fuzzer" / "__init__.py"
    assert init_file.exists(), "app/fuzzer/__init__.py not created"
    content = init_file.read_text()
    assert "APIFuzzer" in content, "APIFuzzer class not found"
    assert "endpoint_list" in content, "endpoint_list() method not found"
    assert "generate_payloads" in content, "generate_payloads() method not found"


# ---------------------------------------------------------------------------
# CC-10: generators.py with adversarial value functions
# ---------------------------------------------------------------------------

def test_generators_file() -> None:
    """CC-10: app/fuzzer/generators.py has adversarial generators."""
    project_dir = _fresh("fuzz_t10")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    gen_file = project_dir / "app" / "fuzzer" / "generators.py"
    assert gen_file.exists(), "generators.py not created"
    content = gen_file.read_text()
    assert "int_values" in content, "int_values() not found"
    assert "string_values" in content, "string_values() not found"
    assert "bool_values" in content, "bool_values() not found"
    assert "number_values" in content, "number_values() not found"
    assert "build_payloads_for_schema" in content, "build_payloads_for_schema() not found"


# ---------------------------------------------------------------------------
# CC-11: SQL and XSS payloads in generators
# ---------------------------------------------------------------------------

def test_adversarial_payloads_in_generators() -> None:
    """CC-11: generators.py includes SQL injection and XSS vectors."""
    project_dir = _fresh("fuzz_t11")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    gen_file = project_dir / "app" / "fuzzer" / "generators.py"
    content = gen_file.read_text()
    assert "DROP TABLE" in content or "OR '1'='1'" in content, (
        "SQL injection payloads not found in generators.py"
    )
    assert "script" in content.lower() or "xss" in content.lower() or "onerror" in content, (
        "XSS vectors not found in generators.py"
    )


# ---------------------------------------------------------------------------
# CC-12: runner.py with FuzzRunner and FuzzResult
# ---------------------------------------------------------------------------

def test_runner_file() -> None:
    """CC-12: app/fuzzer/runner.py has FuzzRunner and FuzzResult classes."""
    project_dir = _fresh("fuzz_t12")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    runner_file = project_dir / "app" / "fuzzer" / "runner.py"
    assert runner_file.exists(), "runner.py not created"
    content = runner_file.read_text()
    assert "FuzzRunner" in content, "FuzzRunner not found"
    assert "FuzzResult" in content, "FuzzResult not found"
    assert "async def run" in content, "FuzzRunner.run() not found"
    assert "is_finding" in content, "FuzzResult.is_finding() not found"


# ---------------------------------------------------------------------------
# CC-13: CLI script created
# ---------------------------------------------------------------------------

def test_cli_script_created() -> None:
    """CC-13: scripts/run_fuzz.py exists with CLI arg parsing."""
    project_dir = _fresh("fuzz_t13")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    cli_file = project_dir / "scripts" / "run_fuzz.py"
    assert cli_file.exists(), "scripts/run_fuzz.py not created"
    content = cli_file.read_text()
    assert "argparse" in content or "ArgumentParser" in content, (
        "CLI script must use argparse"
    )
    assert "--base-url" in content or "base_url" in content, (
        "CLI must accept --base-url argument"
    )
    assert "__main__" in content, "CLI script must have __main__ guard"


# ---------------------------------------------------------------------------
# CC-14: Boundary integers in generators
# ---------------------------------------------------------------------------

def test_boundary_integers_in_generators() -> None:
    """CC-14: generators.py includes boundary integer values (2**31-1, etc.)."""
    project_dir = _fresh("fuzz_t14")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    gen_file = project_dir / "app" / "fuzzer" / "generators.py"
    content = gen_file.read_text()
    assert "2**31" in content or "2147483647" in content, (
        "Boundary integer 2^31-1 not found in generators.py"
    )


# ---------------------------------------------------------------------------
# CC-15: Unicode edge cases in generators
# ---------------------------------------------------------------------------

def test_unicode_edge_cases_in_generators() -> None:
    """CC-15: generators.py includes unicode edge case strings."""
    project_dir = _fresh("fuzz_t15")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    gen_file = project_dir / "app" / "fuzzer" / "generators.py"
    content = gen_file.read_text()
    assert "\\x00" in content or "\\uffff" in content or "unicode" in content.lower(), (
        "Unicode edge cases not found in generators.py"
    )


# ---------------------------------------------------------------------------
# CC-16: Huge string in generators (1 MB)
# ---------------------------------------------------------------------------

def test_huge_string_in_generators() -> None:
    """CC-16: generators.py includes a 1 MB string for size fuzzing."""
    project_dir = _fresh("fuzz_t16")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    gen_file = project_dir / "app" / "fuzzer" / "generators.py"
    content = gen_file.read_text()
    assert "1_048_576" in content or "1048576" in content, (
        "1 MB string test not found in generators.py"
    )


# ---------------------------------------------------------------------------
# CC-17: No external deps beyond httpx
# ---------------------------------------------------------------------------

def test_no_external_deps_beyond_httpx() -> None:
    """CC-17: Generated fuzzer files use no external deps beyond httpx."""
    project_dir = _fresh("fuzz_t17")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    external_forbidden = {"hypothesis", "atheris", "boofuzz", "schemathesis"}
    fuzzer_dir = project_dir / "app" / "fuzzer"
    for py_file in sorted(fuzzer_dir.rglob("*.py")):
        content = py_file.read_text()
        for forbidden in external_forbidden:
            assert forbidden not in content, (
                f"Forbidden external fuzzing dep '{forbidden}' found in {py_file}"
            )


# ---------------------------------------------------------------------------
# CC-18: FuzzResult.is_finding() detects 5xx and timeouts
# ---------------------------------------------------------------------------

def test_fuzz_result_finding_detection() -> None:
    """CC-18: FuzzResult.is_finding() detects non-JSON 5xx and request errors."""
    project_dir = _fresh("fuzz_t18")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    runner_file = project_dir / "app" / "fuzzer" / "runner.py"
    content = runner_file.read_text()
    assert "500" in content or ">= 500" in content, (
        "FuzzResult must check for 5xx status codes"
    )
    assert "is_json" in content, "FuzzResult must track whether response is JSON"


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms recorded
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = _fresh("fuzz_t19")
    result = add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps present with keyword
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps is non-empty and mentions run_fuzz.py or FUZZ_ITERATIONS."""
    project_dir = _fresh("fuzz_t20")
    result = add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps)
    assert "run_fuzz" in combined or "FUZZ_ITERATIONS" in combined or "fuzz" in combined.lower()


# ---------------------------------------------------------------------------
# CC-19: Lazy httpx import in runner
# ---------------------------------------------------------------------------

def test_httpx_import_is_lazy() -> None:
    """CC-19: httpx is imported lazily inside run(), not at module top level."""
    project_dir = _fresh("fuzz_t21")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    runner_file = project_dir / "app" / "fuzzer" / "runner.py"
    tree = ast.parse(runner_file.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                assert "httpx" not in name, (
                    "httpx must be imported lazily inside function, not at module top level"
                )


# ---------------------------------------------------------------------------
# CC-20: FuzzRunner accepts FUZZ_ITERATIONS from env
# ---------------------------------------------------------------------------

def test_fuzz_runner_reads_env_vars() -> None:
    """CC-20: FuzzRunner reads FUZZ_ITERATIONS and FUZZ_TIMEOUT_S from environment."""
    project_dir = _fresh("fuzz_t22")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    runner_file = project_dir / "app" / "fuzzer" / "runner.py"
    content = runner_file.read_text()
    assert "FUZZ_ITERATIONS" in content, "FuzzRunner must read FUZZ_ITERATIONS env var"
    assert "FUZZ_TIMEOUT_S" in content, "FuzzRunner must read FUZZ_TIMEOUT_S env var"


# ---------------------------------------------------------------------------
# CC-21: Notes mention OpenAPI schema reading
# ---------------------------------------------------------------------------

def test_notes_mention_openapi_and_schema() -> None:
    """CC-21: notes describe reading the OpenAPI schema."""
    project_dir = _fresh("fuzz_t23")
    result = add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.notes).lower()
    assert "openapi" in combined or "schema" in combined, (
        "notes should mention reading the OpenAPI schema"
    )
    assert "fuzz" in combined or "adversar" in combined, (
        "notes should describe fuzzing/adversarial inputs"
    )


# ---------------------------------------------------------------------------
# CC-LAST: Project still parses after two runs
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = _fresh("fuzz_t24")
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run,
        test_files_created_count,
        test_files_modified_count,
        test_all_py_parse,
        test_no_function_over_50_loc,
        test_config_fields_patched,
        test_api_fuzzer_init,
        test_generators_file,
        test_adversarial_payloads_in_generators,
        test_runner_file,
        test_cli_script_created,
        test_boundary_integers_in_generators,
        test_unicode_edge_cases_in_generators,
        test_huge_string_in_generators,
        test_no_external_deps_beyond_httpx,
        test_fuzz_result_finding_detection,
        test_execution_time_recorded,
        test_next_steps_present,
        test_httpx_import_is_lazy,
        test_fuzz_runner_reads_env_vars,
        test_notes_mention_openapi_and_schema,
        test_idempotent_project_still_parses,
    ]

    passed = failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"TOOL-124 add_api_fuzzer: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
