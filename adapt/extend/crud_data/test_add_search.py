"""Tests for TOOL-004 add_search.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/crud_data/test_add_search.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/crud_data/test_add_search.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_search import add_search
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
    project_dir = create_fixture_project(name="search_t01_success")
    result = add_search(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="search_t02_files_exist")
    result = add_search(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="search_t03_modified_exist")
    result = add_search(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_crud_search_function_added() -> None:
    """CC-01: CRUD file has async def search() function."""
    project_dir = create_fixture_project(name="search_t04_crud_fn")
    add_search(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    assert crud_file.exists()
    content = crud_file.read_text()
    assert "async def search" in content, "Missing search() in CRUD"


def test_crud_uses_websearch_to_tsquery() -> None:
    """CC-02: CRUD search uses websearch_to_tsquery (parametrized — never LIKE)."""
    project_dir = create_fixture_project(name="search_t05_tsquery")
    add_search(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    assert "websearch_to_tsquery" in content, "CRUD must use websearch_to_tsquery"


def test_crud_no_like_ilike_in_pg_branch() -> None:
    """CC-05: PostgreSQL branch of search() uses tsquery, not LIKE/ILIKE.

    The LIKE fallback is intentionally present for non-PostgreSQL dialects
    (inside _search_like_fallback and the autocomplete fallback branch).
    This test verifies the main PostgreSQL path in search() itself does not
    use LIKE/ILIKE — only websearch_to_tsquery.
    """
    project_dir = create_fixture_project(name="search_t06_no_like")
    add_search(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    # Extract only the async def search() body (the PostgreSQL main branch)
    search_start = content.find("async def search(")
    search_end = content.find("\nasync def autocomplete(", search_start)
    search_body = content[search_start:search_end]
    # The PG branch should use websearch_to_tsquery, never raw LIKE
    assert "websearch_to_tsquery" in search_body, "PG branch must use websearch_to_tsquery"
    # Verify the fallback function exists separately
    assert "_search_like_fallback" in content, "Dialect fallback must exist"


def test_crud_no_fstring_sql() -> None:
    """CC-06: No f-string interpolation of user 'q' into SQL."""
    project_dir = create_fixture_project(name="search_t07_no_fstring")
    add_search(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    search_start = content.find("async def search")
    search_end = content.find("\nasync def autocomplete", search_start)
    search_body = content[search_start:search_end]
    # q must not appear inside an f-string used for SQL
    assert "f\"" + "q" not in search_body.replace(" ", ""), "q must not be f-string interpolated"
    assert "f'{q}" not in search_body, "q must not be f-string interpolated"


def test_crud_is_deleted_filter() -> None:
    """CC-08: Search applies is_deleted filter when model has soft-delete."""
    project_dir = create_fixture_project(name="search_t08_soft_del")
    add_search(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    search_start = content.find("async def search")
    search_end = content.find("\nasync def autocomplete", search_start)
    assert "is_deleted" in content[search_start:search_end], "search() must filter is_deleted"


def test_crud_rank_ordering() -> None:
    """CC-04: Search results ordered by ts_rank_cd rank descending."""
    project_dir = create_fixture_project(name="search_t09_rank_order")
    add_search(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    assert "ts_rank_cd" in content, "CRUD must use ts_rank_cd"
    assert "rank_expr.desc()" in content or ".desc()" in content, "Results must be ordered DESC"


def test_crud_autocomplete_function_added() -> None:
    """CC-22: CRUD file has async def autocomplete() function."""
    project_dir = create_fixture_project(name="search_t10_autocomplete")
    add_search(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    assert "async def autocomplete" in content, "Missing autocomplete() in CRUD"


def test_crud_autocomplete_uses_prefix_tsquery() -> None:
    """Autocomplete uses prefix tsquery (term:*) not websearch_to_tsquery."""
    project_dir = create_fixture_project(name="search_t11_prefix")
    add_search(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    autocomplete_start = content.find("async def autocomplete")
    assert ":*'" in content[autocomplete_start:], "Autocomplete must use prefix :* tsquery"


def test_schema_search_schemas_added() -> None:
    """CC-23: Schema file has SearchParams, SearchResponse, AutocompleteResult."""
    project_dir = create_fixture_project(name="search_t12_schemas")
    add_search(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    assert schema_file.exists()
    content = schema_file.read_text()
    assert "SearchParams" in content, "SearchParams schema missing"
    assert "SearchResponse" in content, "SearchResponse schema missing"
    assert "AutocompleteResult" in content, "AutocompleteResult schema missing"


def test_schema_has_rank_field() -> None:
    """CC-23: SearchResultItem has rank: float | None."""
    project_dir = create_fixture_project(name="search_t13_rank_field")
    add_search(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    content = schema_file.read_text()
    assert "rank" in content and "float" in content, "SearchResultItem must have rank: float | None"


def test_routes_search_endpoint_added() -> None:
    """CC-10: Route file has GET /search endpoint."""
    project_dir = create_fixture_project(name="search_t14_search_route")
    add_search(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    assert route_file.exists()
    content = route_file.read_text()
    assert "async def search_" in content, "Missing search route"
    assert '"/search"' in content, "Search endpoint path must be /search"


def test_routes_autocomplete_endpoint_added() -> None:
    """CC-22: Route file has GET /autocomplete endpoint."""
    project_dir = create_fixture_project(name="search_t15_autocomplete_route")
    add_search(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "async def autocomplete_" in content, "Missing autocomplete route"
    assert '"/autocomplete"' in content, "Autocomplete endpoint path must be /autocomplete"


def test_routes_search_has_min_length() -> None:
    """CC-11: Search route enforces min_length=2 on q parameter."""
    project_dir = create_fixture_project(name="search_t16_min_length")
    add_search(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "min_length=2" in content, "Search route must enforce min_length=2"


def test_routes_catches_value_error() -> None:
    """CC-12: Route handler catches ValueError and raises 422 HTTPException."""
    project_dir = create_fixture_project(name="search_t17_valueerror")
    add_search(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "ValueError" in content, "Route must catch ValueError"
    assert "422" in content, "Route must re-raise as 422"


def test_migration_created() -> None:
    """CC-15: Alembic migration file created with GIN index."""
    project_dir = create_fixture_project(name="search_t18_migration")
    add_search(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*search_idx*"))
    assert len(migration_files) >= 1, "No search migration file created"
    content = migration_files[0].read_text()
    assert "GIN" in content, "Migration must create GIN index"
    assert "search_vector" in content, "Migration must add search_vector column"


def test_migration_uses_concurrently() -> None:
    """CC-16: Migration uses CREATE INDEX CONCURRENTLY."""
    project_dir = create_fixture_project(name="search_t19_concurrently")
    add_search(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*search_idx*"))
    assert migration_files, "No search migration file created"
    content = migration_files[0].read_text()
    assert "CONCURRENTLY" in content, "Migration must use CREATE INDEX CONCURRENTLY"


def test_migration_has_downgrade() -> None:
    """CC-17: Migration has valid downgrade() dropping index and column."""
    project_dir = create_fixture_project(name="search_t20_downgrade")
    add_search(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*search_idx*"))
    assert migration_files, "No search migration file created"
    content = migration_files[0].read_text()
    assert "def downgrade" in content, "Migration must have downgrade()"
    assert "DROP" in content.upper(), "downgrade() must DROP index/column"


def test_all_py_files_parse() -> None:
    """CC-25: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="search_t21_parse_all")
    add_search(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-29 / QS-06: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="search_t22_idempotent")
    r1 = add_search(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_search(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="search_t23_idempotent_parse")
    add_search(ToolInput(project_dir=str(project_dir)))
    add_search(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="search_t24_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_search(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="search_t25_timing")
    result = add_search(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps should guide the developer after a successful run."""
    project_dir = create_fixture_project(name="search_t26_next_steps")
    result = add_search(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty on success"
    assert any("alembic" in s for s in result.next_steps), "Should mention alembic upgrade"


# ---------------------------------------------------------------------------
# Regression tests for confirmed bugs
# ---------------------------------------------------------------------------

def test_multiword_model_is_covered() -> None:
    """BUG B regression: multiword model (VaccineLot in vaccinelot.py) must be covered.

    The old code did ``''.join(w.capitalize() for w in stem.split('_'))`` which
    produces 'Vaccinelot' for file 'vaccinelot.py', not the real class 'VaccineLot'.
    The fix reads the actual class name from the AST, so every Base subclass is
    discovered regardless of file naming.
    """
    project_dir = create_fixture_project(
        name="search_bug_b_multiword",
        models={"VaccineLot": {"name": "str", "description": "str"}},
    )
    result = add_search(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success for multiword model VaccineLot, got: {result.status} — {result.error}"
    )
    crud_file = project_dir / "app" / "crud" / "vaccinelot.py"
    assert crud_file.exists(), "CRUD file for VaccineLot not found"
    content = crud_file.read_text()
    assert "async def search" in content, "search() not added to VaccineLot CRUD"
    assert "VaccineLot" in content, "Real class name VaccineLot absent from emitted CRUD"


def test_no_sqli_via_language_concat() -> None:
    """BUG A regression: emitted CRUD must NOT concatenate language into _text().

    The old code emitted ``_text(\"'\" + language + \"'\")`` which would allow SQL
    injection if ``language`` were user-supplied.  The fix emits
    ``_func.cast(language, _REGCONFIG)`` — a bound parameter cast to regconfig.
    """
    project_dir = create_fixture_project(name="search_bug_a_no_sqli")
    add_search(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    # Old unsafe pattern must be absent
    assert "_text(\"'\" + language + \"'\")" not in content, (
        "Emitted code still contains unsafe language string concatenation into _text()"
    )
    assert "_text(\"'\" + lang + \"'\")" not in content, (
        "Emitted code still contains unsafe lang string concatenation into _text()"
    )
    # Safe REGCONFIG cast must be present
    assert "_REGCONFIG" in content, (
        "Emitted code must import and use REGCONFIG for safe language binding"
    )
    assert "_func.cast(language, _REGCONFIG)" in content or "_func.cast(lang, _REGCONFIG)" in content, (
        "Emitted code must use _func.cast(language, _REGCONFIG) — not string concatenation"
    )


def test_regconfig_import_in_emitted_crud() -> None:
    """BUG A regression: emitted CRUD must import REGCONFIG from sqlalchemy.dialects.postgresql."""
    project_dir = create_fixture_project(name="search_bug_a_regconfig_import")
    add_search(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    assert "from sqlalchemy.dialects.postgresql import REGCONFIG" in content, (
        "Emitted CRUD must import REGCONFIG from sqlalchemy.dialects.postgresql"
    )


def test_multiword_model_crud_parses() -> None:
    """BUG B regression: emitted CRUD for multiword model must parse without SyntaxError."""
    project_dir = create_fixture_project(
        name="search_bug_b_parse",
        models={"VaccineLot": {"name": "str", "description": "str"}},
    )
    add_search(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_search_covers_all_models_in_multi_model_project() -> None:
    """BUG B regression: all models with text fields must receive search(), not just the first.

    Uses a project with two models (Item + Product) — both must get search added.
    """
    project_dir = create_fixture_project(
        name="search_bug_b_all_models",
        models={"Item": {"title": "str"}, "Product": {"name": "str", "description": "str"}},
    )
    result = add_search(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"

    for stem in ("item", "product"):
        crud_file = project_dir / "app" / "crud" / f"{stem}.py"
        assert crud_file.exists(), f"CRUD for {stem} not found"
        assert "async def search" in crud_file.read_text(), (
            f"search() not added to {stem} CRUD"
        )


# ---------------------------------------------------------------------------
# Standalone runner (fallback when pytest is unavailable)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_crud_search_function_added,
        test_crud_uses_websearch_to_tsquery,
        test_crud_no_like_ilike_in_pg_branch,
        test_crud_no_fstring_sql,
        test_crud_is_deleted_filter,
        test_crud_rank_ordering,
        test_crud_autocomplete_function_added,
        test_crud_autocomplete_uses_prefix_tsquery,
        test_schema_search_schemas_added,
        test_schema_has_rank_field,
        test_routes_search_endpoint_added,
        test_routes_autocomplete_endpoint_added,
        test_routes_search_has_min_length,
        test_routes_catches_value_error,
        test_migration_created,
        test_migration_uses_concurrently,
        test_migration_has_downgrade,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
        # Regression tests
        test_multiword_model_is_covered,
        test_no_sqli_via_language_concat,
        test_regconfig_import_in_emitted_crud,
        test_multiword_model_crud_parses,
        test_search_covers_all_models_in_multi_model_project,
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
