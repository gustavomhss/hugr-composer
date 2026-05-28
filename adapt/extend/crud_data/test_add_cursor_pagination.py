"""Tests for TOOL-002 add_cursor_pagination.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/crud_data/test_add_cursor_pagination.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/crud_data/test_add_cursor_pagination.py
"""

from __future__ import annotations

import ast
import base64
import json
import sys
from datetime import UTC
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_cursor_pagination import add_cursor_pagination
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
# Test cases
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="cp_t01_success")
    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="cp_t02_files_exist")
    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="cp_t03_modified_exist")
    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_cursor_module_created() -> None:
    """CC-01: app/core/cursor.py exists with encode_cursor and decode_cursor."""
    project_dir = create_fixture_project(name="cp_t04_cursor_module")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    cursor_file = project_dir / "app" / "core" / "cursor.py"
    assert cursor_file.exists(), "cursor.py not created"
    content = cursor_file.read_text()
    assert "encode_cursor" in content
    assert "decode_cursor" in content


def test_cursor_paginator_created() -> None:
    """CC-34: app/core/cursor_paginator.py exists with CursorPaginator class."""
    project_dir = create_fixture_project(name="cp_t05_paginator")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    paginator_file = project_dir / "app" / "core" / "cursor_paginator.py"
    assert paginator_file.exists(), "cursor_paginator.py not created"
    content = paginator_file.read_text()
    assert "CursorPaginator" in content
    assert "paginate" in content


def test_encode_cursor_returns_urlsafe() -> None:
    """CC-02: encode_cursor returns URL-safe base64 — no +, /, or = characters."""
    import re

    project_dir = create_fixture_project(name="cp_t06_urlsafe")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    cursor_file = project_dir / "app" / "core" / "cursor.py"
    assert cursor_file.exists()
    # Import and test the generated function directly
    import importlib.util

    spec = importlib.util.spec_from_file_location("cursor_mod", cursor_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from datetime import datetime

    encoded = mod.encode_cursor("created_at", datetime(2026, 1, 1, tzinfo=UTC))
    assert "+" not in encoded
    assert "/" not in encoded
    assert "=" not in encoded
    assert re.match(r"^[A-Za-z0-9_-]+$", encoded)


def test_decode_cursor_round_trip() -> None:
    """CC-03: decode_cursor handles missing padding (round-trip works)."""
    project_dir = create_fixture_project(name="cp_t07_roundtrip")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    cursor_file = project_dir / "app" / "core" / "cursor.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("cursor_mod2", cursor_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from datetime import datetime

    encoded = mod.encode_cursor("created_at", datetime(2026, 4, 1, tzinfo=UTC))
    decoded = mod.decode_cursor(encoded)
    assert decoded["field"] == "created_at"
    assert decoded["value"] is not None


def test_decode_cursor_rejects_malformed_base64() -> None:
    """CC-04: decode_cursor raises ValueError on invalid base64."""
    project_dir = create_fixture_project(name="cp_t08_bad_b64")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    cursor_file = project_dir / "app" / "core" / "cursor.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("cursor_mod3", cursor_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    raised = False
    try:
        mod.decode_cursor("!@#garbage")
    except ValueError:
        raised = True
    assert raised, "decode_cursor must raise ValueError on malformed base64"


def test_decode_cursor_rejects_invalid_json() -> None:
    """CC-05: decode_cursor raises ValueError on valid base64 but invalid JSON."""
    project_dir = create_fixture_project(name="cp_t09_bad_json")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    cursor_file = project_dir / "app" / "core" / "cursor.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("cursor_mod4", cursor_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bad_payload = base64.urlsafe_b64encode(b"not-json").decode("ascii").rstrip("=")
    raised = False
    try:
        mod.decode_cursor(bad_payload)
    except ValueError:
        raised = True
    assert raised, "decode_cursor must raise ValueError on invalid JSON"


def test_decode_cursor_rejects_oversized() -> None:
    """CC-06: decode_cursor raises ValueError when cursor exceeds 1 KB."""
    project_dir = create_fixture_project(name="cp_t10_oversized")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    cursor_file = project_dir / "app" / "core" / "cursor.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("cursor_mod5", cursor_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    huge = "A" * 2000
    raised = False
    try:
        mod.decode_cursor(huge)
    except ValueError as exc:
        raised = True
        assert "maximum size" in str(exc)
    assert raised, "decode_cursor must raise ValueError for oversized cursor"


def test_decode_cursor_rejects_missing_keys() -> None:
    """CC-07: decode_cursor raises ValueError when 'f' or 'v' keys are absent."""
    project_dir = create_fixture_project(name="cp_t11_missing_keys")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    cursor_file = project_dir / "app" / "core" / "cursor.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("cursor_mod6", cursor_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bad_payload = (
        base64.urlsafe_b64encode(json.dumps({"x": 1}).encode()).decode("ascii").rstrip("=")
    )
    raised = False
    try:
        mod.decode_cursor(bad_payload)
    except ValueError:
        raised = True
    assert raised, "decode_cursor must raise ValueError on missing 'f'/'v' keys"


def test_schema_next_cursor_added() -> None:
    """CC-08: ItemsPublic schema has next_cursor: str | None = None field."""
    project_dir = create_fixture_project(name="cp_t12_next_cursor")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    assert schema_file.exists()
    content = schema_file.read_text()
    assert "next_cursor" in content


def test_schema_has_more_added() -> None:
    """CC-09: ItemsPublic schema has has_more: bool = False field."""
    project_dir = create_fixture_project(name="cp_t13_has_more")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    content = schema_file.read_text()
    assert "has_more" in content


def test_schema_data_field_preserved() -> None:
    """CC-10: ItemsPublic retains existing data: list[ItemPublic] field."""
    project_dir = create_fixture_project(name="cp_t14_data_field")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    content = schema_file.read_text()
    assert "data" in content, "data field must be preserved"


def test_schema_count_field_preserved() -> None:
    """CC-11: ItemsPublic retains existing count: int field."""
    project_dir = create_fixture_project(name="cp_t15_count_field")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    content = schema_file.read_text()
    assert "count" in content, "count field must be preserved"


def test_crud_get_multi_cursor_exists() -> None:
    """CC-12: crud.get_multi_cursor() function exists with correct signature."""
    project_dir = create_fixture_project(name="cp_t16_crud_fn")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    assert crud_file.exists()
    content = crud_file.read_text()
    assert "async def get_multi_cursor" in content
    assert "cursor" in content
    assert "page_size" in content


def test_crud_no_offset() -> None:
    """CC-13: Generated CRUD query does NOT use OFFSET."""
    project_dir = create_fixture_project(name="cp_t17_no_offset")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    # Find only the cursor function body
    start = content.find("async def get_multi_cursor")
    cursor_body = content[start:] if start != -1 else ""
    assert ".offset(" not in cursor_body, "get_multi_cursor must NOT use .offset()"


def test_crud_fetches_page_size_plus_one() -> None:
    """CC-14: CursorPaginator fetches page_size + 1 rows to detect has_more.

    The N+1 fetch is implemented inside cursor_paginator.py (shared helper),
    not duplicated in each per-model CRUD stub.
    """
    project_dir = create_fixture_project(name="cp_t18_n_plus_one")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    paginator_file = project_dir / "app" / "core" / "cursor_paginator.py"
    assert paginator_file.exists(), "cursor_paginator.py not found"
    content = paginator_file.read_text()
    assert "page_size + 1" in content, "CursorPaginator must fetch page_size + 1 rows"


def test_crud_soft_delete_aware() -> None:
    """CC-19: Soft-delete filter applied if model has is_deleted attribute."""
    project_dir = create_fixture_project(name="cp_t19_soft_delete")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    assert "is_deleted" in content, "cursor CRUD should conditionally filter is_deleted"


def test_route_cursor_endpoint_added() -> None:
    """CC-20/21: Route accepts cursor and page_size query params."""
    project_dir = create_fixture_project(name="cp_t20_route")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    assert route_file.exists()
    content = route_file.read_text()
    assert "cursor" in content
    assert "page_size" in content


def test_route_wraps_in_try_except_400() -> None:
    """CC-23: Route wraps cursor call in try/except ValueError → HTTP 400."""
    project_dir = create_fixture_project(name="cp_t21_try_except")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "status_code=400" in content, "Route must return 400 for invalid cursor"
    assert "ValueError" in content, "Route must catch ValueError"


def test_migration_file_created() -> None:
    """CC-24/25/26/27: Alembic migration created with correct index content."""
    project_dir = create_fixture_project(name="cp_t22_migration")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*cursor_idx_items*"))
    assert len(migration_files) >= 1, "No cursor pagination migration file created"
    content = migration_files[0].read_text()
    assert "created_at DESC" in content, "Migration must create DESC index"
    assert "def upgrade" in content
    assert "def downgrade" in content
    assert "drop_index" in content


def test_all_py_files_parse() -> None:
    """CC-28: All .py files in project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="cp_t23_parse_all")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """QS-06 / CC: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="cp_t24_idempotent")
    r1 = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="cp_t25_idem_parse")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="cp_t26_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="cp_t27_timing")
    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps should guide the developer after a successful run."""
    project_dir = create_fixture_project(name="cp_t28_next_steps")
    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty on success"
    assert any("alembic" in s for s in result.next_steps), "Should mention alembic upgrade"


# ---------------------------------------------------------------------------
# BUG B regression — multiword model discovery
# ---------------------------------------------------------------------------


def test_multiword_model_not_skipped() -> None:
    """Regression: a model whose filename is all-lowercase multiword (vaccinelot.py
    containing class VaccineLot) must be discovered and patched, not silently skipped.

    Before the fix, _discover_models derived the class name from the filename via
    ``''.join(w.capitalize() for w in stem.split('_'))``, which produced
    'Vaccinelot' != 'VaccineLot', causing the model to be silently excluded.
    """
    project_dir = create_fixture_project(
        name="cp_multiword_model",
        models={"Order": {"code": "str"}, "VaccineLot": {"lot": "str"}},
    )
    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    # Both models must appear in the success notes
    notes_combined = " ".join(result.notes or [])
    assert "VaccineLot" in notes_combined, (
        f"VaccineLot not in notes — multiword model was skipped. Notes: {result.notes}"
    )
    # VaccineLot CRUD must have get_multi_cursor patched in
    crud_files = list((project_dir / "app" / "crud").glob("vaccinelot*.py"))
    assert crud_files, "No CRUD file found for VaccineLot model"
    assert "get_multi_cursor" in crud_files[0].read_text(), (
        "VaccineLot CRUD file missing get_multi_cursor — multiword model was skipped"
    )


def test_flat_model_still_discovered_alongside_multiword() -> None:
    """Flat model (Order) must still be discovered when a multiword model coexists."""
    project_dir = create_fixture_project(
        name="cp_flat_alongside_multiword",
        models={"Order": {"code": "str"}, "VaccineLot": {"lot": "str"}},
    )
    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    crud_order = project_dir / "app" / "crud" / "order.py"
    assert crud_order.exists(), "crud/order.py not found"
    assert "get_multi_cursor" in crud_order.read_text(), "Order CRUD missing get_multi_cursor"


# ---------------------------------------------------------------------------
# WAVE0-F1 regression — new behaviour added by per-tool-dir migration
# ---------------------------------------------------------------------------


def test_emitted_test_file_created() -> None:
    """WAVE0-F1: tool emits tests/test_cursor_pagination.py."""
    project_dir = create_fixture_project(name="cp_emitted_test")
    add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    emitted = project_dir / "tests" / "test_cursor_pagination.py"
    assert emitted.exists(), "tool must emit tests/test_cursor_pagination.py"
    ast.parse(emitted.read_text())


def test_idempotency_partial_state_does_not_skip() -> None:
    """Regression: cursor.py present but CRUD not patched -> 2nd run must complete missing pieces, not no_op."""
    project_dir = create_fixture_project(name="cp_partial_state")
    core = project_dir / "app" / "core" / "cursor.py"
    core.parent.mkdir(parents=True, exist_ok=True)
    core.write_text("# stub\nencode_cursor = decode_cursor = None\n")
    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert any("crud" in p for p in result.files_modified)


# ---------------------------------------------------------------------------
# Standalone runner (fallback when pytest is unavailable)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_cursor_module_created,
        test_cursor_paginator_created,
        test_encode_cursor_returns_urlsafe,
        test_decode_cursor_round_trip,
        test_decode_cursor_rejects_malformed_base64,
        test_decode_cursor_rejects_invalid_json,
        test_decode_cursor_rejects_oversized,
        test_decode_cursor_rejects_missing_keys,
        test_schema_next_cursor_added,
        test_schema_has_more_added,
        test_schema_data_field_preserved,
        test_schema_count_field_preserved,
        test_crud_get_multi_cursor_exists,
        test_crud_no_offset,
        test_crud_fetches_page_size_plus_one,
        test_crud_soft_delete_aware,
        test_route_cursor_endpoint_added,
        test_route_wraps_in_try_except_400,
        test_migration_file_created,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
        test_emitted_test_file_created,
        test_idempotency_partial_state_does_not_skip,
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
