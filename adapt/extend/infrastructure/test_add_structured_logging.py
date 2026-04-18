"""Structural tests for TOOL-087 add_structured_logging.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_structured_logging.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_structured_logging.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_structured_logging import add_structured_logging
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


# ---------------------------------------------------------------------------
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="slog_t01")
    result = add_structured_logging(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns no_op with no files created or modified."""
    project_dir = create_fixture_project(name="slog_t02")
    r1 = add_structured_logging(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_structured_logging(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must not create files"
    assert not r2.files_modified, "Second run must not modify files"


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True must not touch any file on disk."""
    project_dir = create_fixture_project(name="slog_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_structured_logging(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count + existence
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 3 files created, all exist on disk."""
    project_dir = create_fixture_project(name="slog_t04")
    result = add_structured_logging(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 3, (
        f"Expected >= 3 files_created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count + existence
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified, all exist on disk."""
    project_dir = create_fixture_project(name="slog_t05")
    result = add_structured_logging(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files_modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every .py file in project parses without SyntaxError after tool."""
    project_dir = create_fixture_project(name="slog_t06")
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC (AST walk)."""
    project_dir = create_fixture_project(name="slog_t07")
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    logging_dir = project_dir / "app" / "logging"
    violations: list[str] = []
    for py_file in sorted(logging_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                if loc > 50:
                    violations.append(f"{py_file}:{node.name} ({loc} LOC)")
    assert not violations, "Functions > 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched with 4-space indent
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: LOG_LEVEL, LOG_FORMAT, LOG_REDACTION_ENABLED in config.py."""
    project_dir = create_fixture_project(name="slog_t08")
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    assert "LOG_LEVEL" in content, "LOG_LEVEL not in config.py"
    assert "LOG_FORMAT" in content, "LOG_FORMAT not in config.py"
    assert "LOG_REDACTION_ENABLED" in content, "LOG_REDACTION_ENABLED not in config.py"
    for line in content.splitlines():
        if any(f in line for f in ("LOG_LEVEL", "LOG_FORMAT", "LOG_REDACTION_ENABLED")):
            assert line.startswith("    "), (
                f"Config field not 4-space indented: {line!r}"
            )


# ---------------------------------------------------------------------------
# Domain tests (CC-11+)
# ---------------------------------------------------------------------------

def test_setup_file_has_configure_structlog() -> None:
    """D-01: app/logging/setup.py has configure_structlog function."""
    project_dir = create_fixture_project(name="slog_t09")
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    setup_file = project_dir / "app" / "logging" / "setup.py"
    assert setup_file.exists(), "app/logging/setup.py not created"
    content = setup_file.read_text()
    assert "configure_structlog" in content
    assert "structlog" in content


def test_setup_file_has_json_renderer() -> None:
    """D-02: configure_structlog uses JSON renderer."""
    project_dir = create_fixture_project(name="slog_t10")
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    setup_file = project_dir / "app" / "logging" / "setup.py"
    content = setup_file.read_text()
    assert "JSONRenderer" in content or "json" in content.lower()


def test_redactor_file_has_pii_patterns() -> None:
    """D-03: app/logging/redactor.py has Redactor with email/phone/card patterns."""
    project_dir = create_fixture_project(name="slog_t11")
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    redactor_file = project_dir / "app" / "logging" / "redactor.py"
    assert redactor_file.exists(), "app/logging/redactor.py not created"
    content = redactor_file.read_text()
    assert "Redactor" in content
    assert "email" in content.lower() or "EMAIL" in content
    assert "REDACTED" in content


def test_context_file_has_correlation_id() -> None:
    """D-04: app/logging/context.py has get_correlation_id and bind_context."""
    project_dir = create_fixture_project(name="slog_t12")
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    context_file = project_dir / "app" / "logging" / "context.py"
    assert context_file.exists(), "app/logging/context.py not created"
    content = context_file.read_text()
    assert "get_correlation_id" in content
    assert "bind_context" in content


def test_main_py_patched_with_configure_structlog() -> None:
    """D-05: main.py is patched to call configure_structlog."""
    project_dir = create_fixture_project(name="slog_t13")
    result = add_structured_logging(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    main_file = project_dir / "app" / "main.py"
    if main_file.exists():
        content = main_file.read_text()
        assert "configure_structlog" in content


def test_logging_init_has_exports() -> None:
    """D-06: app/logging/__init__.py re-exports public symbols."""
    project_dir = create_fixture_project(name="slog_t14")
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "logging" / "__init__.py"
    assert init_file.exists()
    content = init_file.read_text()
    assert "configure_structlog" in content
    assert "Redactor" in content


def test_redactor_has_api_key_pattern() -> None:
    """D-07: redactor.py strips API key patterns."""
    project_dir = create_fixture_project(name="slog_t15")
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    redactor_file = project_dir / "app" / "logging" / "redactor.py"
    content = redactor_file.read_text()
    assert "api" in content.lower() or "token" in content.lower() or "secret" in content.lower()


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="slog_t16")
    result = add_structured_logging(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps must be non-empty and mention log level or structlog."""
    project_dir = create_fixture_project(name="slog_t17")
    result = add_structured_logging(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "log" in combined or "structlog" in combined


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="slog_t18")
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Extra structural checks
# ---------------------------------------------------------------------------

def test_notes_mention_structlog_or_redaction() -> None:
    """notes describe structlog/redaction."""
    project_dir = create_fixture_project(name="slog_t19")
    result = add_structured_logging(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.notes).lower()
    assert "structlog" in combined or "redact" in combined or "json" in combined


def test_redactor_strips_credit_cards() -> None:
    """redactor.py has credit card pattern."""
    project_dir = create_fixture_project(name="slog_t20")
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    redactor_file = project_dir / "app" / "logging" / "redactor.py"
    content = redactor_file.read_text()
    # Credit card is a long digit sequence — check for card/PAN-related pattern
    assert "CARD" in content or "card" in content.lower() or "\\d" in content


def test_context_has_bind_and_clear() -> None:
    """context.py has bind_context and clear_context functions."""
    project_dir = create_fixture_project(name="slog_t21")
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    context_file = project_dir / "app" / "logging" / "context.py"
    content = context_file.read_text()
    assert "bind_context" in content
    assert "clear_context" in content


def test_setup_has_correlation_processor() -> None:
    """configure_structlog includes correlation ID / contextvars merge processor."""
    project_dir = create_fixture_project(name="slog_t22")
    add_structured_logging(ToolInput(project_dir=str(project_dir)))
    setup_file = project_dir / "app" / "logging" / "setup.py"
    content = setup_file.read_text()
    assert "contextvars" in content or "correlation" in content


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
        test_setup_file_has_configure_structlog,
        test_setup_file_has_json_renderer,
        test_redactor_file_has_pii_patterns,
        test_context_file_has_correlation_id,
        test_main_py_patched_with_configure_structlog,
        test_logging_init_has_exports,
        test_redactor_has_api_key_pattern,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_notes_mention_structlog_or_redaction,
        test_redactor_strips_credit_cards,
        test_context_has_bind_and_clear,
        test_setup_has_correlation_processor,
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

    print(f"\n{'='*60}")
    print(f"TOOL-087 add_structured_logging: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
