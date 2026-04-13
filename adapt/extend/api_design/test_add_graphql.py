"""Tests for TOOL-018 add_graphql.

Generates a real fixture project, runs the tool, and verifies all
completeness criteria: schema assembled, types generated, dataloaders
wired, depth/complexity extensions present, idempotency, dry_run.

Run with::

    PYTHONPATH=. python3 adapt/extend/api_design/test_add_graphql.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_graphql import add_graphql
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
    project_dir = create_fixture_project(name="gql_t01")
    result = add_graphql(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist_on_disk() -> None:
    """T-02: Every path in files_created exists on disk."""
    project_dir = create_fixture_project(name="gql_t02")
    result = add_graphql(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist_on_disk() -> None:
    """T-03: Every path in files_modified exists on disk."""
    project_dir = create_fixture_project(name="gql_t03")
    result = add_graphql(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_schema_file_created() -> None:
    """CC-01: app/graphql/schema.py exists and contains strawberry.Schema."""
    project_dir = create_fixture_project(name="gql_t04")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    schema = project_dir / "app" / "graphql" / "schema.py"
    assert schema.exists(), "schema.py not created"
    content = schema.read_text()
    assert "strawberry.Schema" in content
    assert "Query" in content
    assert "Mutation" in content


def test_types_file_created() -> None:
    """CC-02: app/graphql/types.py exists with strawberry.type classes."""
    project_dir = create_fixture_project(name="gql_t05")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    types_file = project_dir / "app" / "graphql" / "types.py"
    assert types_file.exists(), "types.py not created"
    content = types_file.read_text()
    assert "@strawberry.type" in content
    assert "@strawberry.input" in content


def test_dataloaders_file_created() -> None:
    """CC-03: app/graphql/dataloaders.py with DataLoaderRegistry."""
    project_dir = create_fixture_project(name="gql_t06")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    loaders_file = project_dir / "app" / "graphql" / "dataloaders.py"
    assert loaders_file.exists(), "dataloaders.py not created"
    content = loaders_file.read_text()
    assert "DataLoaderRegistry" in content
    assert "DataLoader" in content


def test_dataloader_batch_load_fn_prevents_n_plus_1() -> None:
    """CC-04: DataLoader uses batch_load_fn with IN query for N+1 prevention."""
    project_dir = create_fixture_project(name="gql_t07")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "graphql" / "dataloaders.py").read_text()
    assert "batch_load_fn" in content
    assert ".in_(" in content or "in_(" in content


def test_context_file_created() -> None:
    """CC-05: app/graphql/context.py with GraphQLContext and get_graphql_context."""
    project_dir = create_fixture_project(name="gql_t08")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    ctx_file = project_dir / "app" / "graphql" / "context.py"
    assert ctx_file.exists(), "context.py not created"
    content = ctx_file.read_text()
    assert "GraphQLContext" in content
    assert "get_graphql_context" in content


def test_context_attaches_dataloaders() -> None:
    """CC-06: GraphQLContext instantiates DataLoaderRegistry per request."""
    project_dir = create_fixture_project(name="gql_t09")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "graphql" / "context.py").read_text()
    assert "DataLoaderRegistry" in content


def test_extensions_file_created() -> None:
    """CC-07: app/graphql/extensions.py with depth and complexity extensions."""
    project_dir = create_fixture_project(name="gql_t10")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    ext_file = project_dir / "app" / "graphql" / "extensions.py"
    assert ext_file.exists(), "extensions.py not created"
    content = ext_file.read_text()
    assert "DepthLimitExtension" in content
    assert "ComplexityLimitExtension" in content


def test_depth_limit_default_is_8() -> None:
    """CC-08: Default max_depth is 8 per spec."""
    project_dir = create_fixture_project(name="gql_t11")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "graphql" / "extensions.py").read_text()
    assert "= 8" in content or "8)" in content or "8," in content


def test_complexity_limit_default_is_1000() -> None:
    """CC-09: Default max_complexity is 1000 per spec."""
    project_dir = create_fixture_project(name="gql_t12")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "graphql" / "extensions.py").read_text()
    assert "1000" in content


def test_queries_file_created() -> None:
    """CC-10: app/graphql/queries.py with Query class."""
    project_dir = create_fixture_project(name="gql_t13")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    queries_file = project_dir / "app" / "graphql" / "queries.py"
    assert queries_file.exists(), "queries.py not created"
    content = queries_file.read_text()
    assert "class Query" in content
    assert "@strawberry.type" in content


def test_mutations_file_created() -> None:
    """CC-11: app/graphql/mutations.py with Mutation class."""
    project_dir = create_fixture_project(name="gql_t14")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    mut_file = project_dir / "app" / "graphql" / "mutations.py"
    assert mut_file.exists(), "mutations.py not created"
    content = mut_file.read_text()
    assert "class Mutation" in content
    assert "@strawberry.mutation" in content


def test_mutations_delegate_to_crud() -> None:
    """CC-12: Mutation resolvers call CRUD functions (no duplicate logic)."""
    project_dir = create_fixture_project(name="gql_t15")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "graphql" / "mutations.py").read_text()
    assert "crud" in content.lower() or "_create" in content


def test_main_patched_with_graphql_router() -> None:
    """CC-13: app/main.py imports and mounts GraphQLRouter."""
    project_dir = create_fixture_project(name="gql_t16")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "main.py").read_text()
    assert "GraphQLRouter" in content or "_GraphQLRouter" in content
    assert "/graphql" in content


def test_all_py_files_parse() -> None:
    """CC-14: All generated .py files parse without SyntaxError."""
    project_dir = create_fixture_project(name="gql_t17")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-15: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="gql_t18")
    r1 = add_graphql(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_graphql(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="gql_t19")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    add_graphql(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="gql_t20")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_graphql(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be positive after a successful run."""
    project_dir = create_fixture_project(name="gql_t21")
    result = add_graphql(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_mention_strawberry() -> None:
    """next_steps should mention installing strawberry-graphql."""
    project_dir = create_fixture_project(name="gql_t22")
    result = add_graphql(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert any("strawberry" in s.lower() for s in result.next_steps)


def test_graphql_init_created() -> None:
    """app/graphql/__init__.py must exist as package marker."""
    project_dir = create_fixture_project(name="gql_t23")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    init = project_dir / "app" / "graphql" / "__init__.py"
    assert init.exists(), "app/graphql/__init__.py not created"


def test_schema_includes_extensions() -> None:
    """CC-16: strawberry.Schema passes extensions=[Depth..., Complexity...]."""
    project_dir = create_fixture_project(name="gql_t24")
    add_graphql(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "graphql" / "schema.py").read_text()
    assert "DepthLimitExtension" in content
    assert "ComplexityLimitExtension" in content


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist_on_disk,
        test_files_modified_exist_on_disk,
        test_schema_file_created,
        test_types_file_created,
        test_dataloaders_file_created,
        test_dataloader_batch_load_fn_prevents_n_plus_1,
        test_context_file_created,
        test_context_attaches_dataloaders,
        test_extensions_file_created,
        test_depth_limit_default_is_8,
        test_complexity_limit_default_is_1000,
        test_queries_file_created,
        test_mutations_file_created,
        test_mutations_delegate_to_crud,
        test_main_patched_with_graphql_router,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_mention_strawberry,
        test_graphql_init_created,
        test_schema_includes_extensions,
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
