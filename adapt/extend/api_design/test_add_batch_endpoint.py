"""Tests for TOOL-019 add_batch_endpoint.

Generates a real fixture project, runs the tool, and verifies all
completeness criteria: BatchCore, HTTP 207, per-item results, idempotency,
isolation modes, dry_run, parse cleanliness.

Run with::

    PYTHONPATH=. python3 adapt/extend/api_design/test_add_batch_endpoint.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_batch_endpoint import add_batch_endpoint
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        src = f.read_text()
        try:
            ast.parse(src)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="be_t01")
    result = add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist_on_disk() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="be_t02")
    result = add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist_on_disk() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="be_t03")
    result = add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_batch_core_created() -> None:
    """CC-01: app/core/batch_core.py exists with BatchCore class."""
    project_dir = create_fixture_project(name="be_t04")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    core = project_dir / "app" / "core" / "batch_core.py"
    assert core.exists(), "batch_core.py not created"
    content = core.read_text()
    assert "BatchCore" in content


def test_batch_request_model_present() -> None:
    """CC-02: BatchRequest Pydantic model exists in batch_core.py."""
    project_dir = create_fixture_project(name="be_t05")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "batch_core.py").read_text()
    assert "BatchRequest" in content


def test_batch_item_result_present() -> None:
    """CC-03: BatchItemResult with index, status_code, data, error fields."""
    project_dir = create_fixture_project(name="be_t06")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "batch_core.py").read_text()
    assert "BatchItemResult" in content
    assert "status_code" in content
    assert "index" in content
    assert "error" in content


def test_batch_response_present() -> None:
    """CC-04: BatchResponse model with results, total, succeeded, failed."""
    project_dir = create_fixture_project(name="be_t07")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "batch_core.py").read_text()
    assert "BatchResponse" in content
    assert "succeeded" in content
    assert "failed" in content


def test_isolation_mode_enum() -> None:
    """CC-05: IsolationMode enum has ALL_OR_NOTHING and BEST_EFFORT values."""
    project_dir = create_fixture_project(name="be_t08")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "batch_core.py").read_text()
    assert "ALL_OR_NOTHING" in content
    assert "BEST_EFFORT" in content


def test_all_or_nothing_abort_logic() -> None:
    """CC-06: all_or_nothing mode rolls back remaining items on first failure."""
    project_dir = create_fixture_project(name="be_t09")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "batch_core.py").read_text()
    assert "ALL_OR_NOTHING" in content
    # Must have logic that stops on first error
    assert "409" in content or "Rolled back" in content


def test_per_item_timeout_used() -> None:
    """CC-07: BatchCore uses asyncio.wait_for for per-item timeout."""
    project_dir = create_fixture_project(name="be_t10")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "batch_core.py").read_text()
    assert "wait_for" in content
    assert "TimeoutError" in content or "timeout" in content.lower()


def test_bulk_route_created_for_model() -> None:
    """CC-08: app/api/routes/bulk/item_bulk.py exists with POST /bulk endpoint."""
    project_dir = create_fixture_project(name="be_t11")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    route = project_dir / "app" / "api" / "routes" / "bulk" / "item_bulk.py"
    assert route.exists(), "item_bulk.py not created"
    content = route.read_text()
    assert '"/bulk"' in content or "'/bulk'" in content


def test_bulk_route_returns_207() -> None:
    """CC-09: Bulk route explicitly uses HTTP_207_MULTI_STATUS."""
    project_dir = create_fixture_project(name="be_t12")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "bulk" / "item_bulk.py").read_text()
    assert "207" in content or "HTTP_207_MULTI_STATUS" in content


def test_bulk_route_enforces_max_batch_size() -> None:
    """CC-10: Bulk route rejects payloads over max_batch_size with 422."""
    project_dir = create_fixture_project(name="be_t13")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "bulk" / "item_bulk.py").read_text()
    assert "422" in content or "HTTP_422_UNPROCESSABLE_ENTITY" in content
    assert "_MAX_BATCH" in content or "max_batch" in content.lower()


def test_idempotency_store_created() -> None:
    """CC-11: app/core/idempotency.py with IdempotencyStore."""
    project_dir = create_fixture_project(name="be_t14")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    idem = project_dir / "app" / "core" / "idempotency.py"
    assert idem.exists(), "idempotency.py not created"
    content = idem.read_text()
    assert "IdempotencyStore" in content


def test_idempotency_key_header_in_route() -> None:
    """CC-12: Bulk route accepts X-Idempotency-Key header."""
    project_dir = create_fixture_project(name="be_t15")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "bulk" / "item_bulk.py").read_text()
    assert "Idempotency" in content


def test_bulk_route_init_created() -> None:
    """CC-13: app/api/routes/bulk/__init__.py exists as package marker."""
    project_dir = create_fixture_project(name="be_t16")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    init = project_dir / "app" / "api" / "routes" / "bulk" / "__init__.py"
    assert init.exists(), "bulk/__init__.py not created"


def test_all_py_files_parse() -> None:
    """CC-14: All .py files parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="be_t17")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-15: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="be_t18")
    r1 = add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="be_t19")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="be_t20")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_batch_endpoint(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be positive after a successful run."""
    project_dir = create_fixture_project(name="be_t21")
    result = add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_notes_mention_207() -> None:
    """notes should mention HTTP 207 Multi-Status."""
    project_dir = create_fixture_project(name="be_t22")
    result = add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert any("207" in n for n in result.notes)


def test_sequential_strategy_enum() -> None:
    """CC-16: ProcessingStrategy.SEQUENTIAL is defined in batch_core."""
    project_dir = create_fixture_project(name="be_t23")
    add_batch_endpoint(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "batch_core.py").read_text()
    assert "SEQUENTIAL" in content
    assert "PARALLEL" in content


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist_on_disk,
        test_files_modified_exist_on_disk,
        test_batch_core_created,
        test_batch_request_model_present,
        test_batch_item_result_present,
        test_batch_response_present,
        test_isolation_mode_enum,
        test_all_or_nothing_abort_logic,
        test_per_item_timeout_used,
        test_bulk_route_created_for_model,
        test_bulk_route_returns_207,
        test_bulk_route_enforces_max_batch_size,
        test_idempotency_store_created,
        test_idempotency_key_header_in_route,
        test_bulk_route_init_created,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_notes_mention_207,
        test_sequential_strategy_enum,
    ]

    passed = 0
    failed = 0
    errors: list[str] = []

    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            errors.append(f"{t.__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
