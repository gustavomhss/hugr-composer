"""Generic tool-contract mutation coverage for add_cursor_pagination.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_cursor_pagination.py in the mutation
runner: ``--tests test_add_cursor_pagination.py test_add_cursor_pagination_contract.py``.

The ``test_kills_*`` functions below target this tool's BESPOKE logic mutants
(branch flags, requirement-dedup guards, route/schema anchor lookups, migration
down-revision fallback) that the shared contract preamble does not cover.
"""

from __future__ import annotations

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_cursor_pagination import add_cursor_pagination
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    for check in UNIVERSAL_CHECKS:
        check(add_cursor_pagination, "add_cursor_pagination")


# ---------------------------------------------------------------------------
# L67 (auto_scaffold=not inp.dry_run) + L72 (prereq-error message concat)
# ---------------------------------------------------------------------------


def test_kills_dry_run_does_not_auto_scaffold_missing_prereq():
    """L67 `not inp.dry_run` + L72 error concat.

    On a dry_run with a missing (but scaffoldable) prerequisite, auto_scaffold
    MUST be off — the tool returns an error and leaves the project untouched.
    The mutant `auto_scaffold=inp.dry_run` would silently scaffold config.py and
    proceed to a dry_run 'success'. The L72 `"..." + "\\n".join(...)` concat is
    exercised on this branch too (Add->Sub mutant raises TypeError).
    """
    project_dir = create_fixture_project(name="cp_kill_l67")
    config = project_dir / "app" / "core" / "config.py"
    config.unlink()

    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir), dry_run=True))

    assert result.status == "error", f"dry_run with missing prereq must error, got {result.status}"
    assert result.error and "Prerequisites not met" in result.error
    assert not config.exists(), "dry_run must NOT auto-scaffold the missing config.py"


# ---------------------------------------------------------------------------
# L79 (discover_models require_route=True)
# ---------------------------------------------------------------------------


def test_kills_model_without_route_is_skipped():
    """L79 `require_route=True`.

    A model whose route file is absent must be DROPPED from discovery. The
    mutant `require_route=False` would include it, surfacing its class name in
    the success notes and attempting to patch a non-existent route.
    """
    project_dir = create_fixture_project(
        name="cp_kill_l79",
        models={"Order": {"code": "str"}, "Widget": {"name": "str"}},
    )
    (project_dir / "app" / "api" / "routes" / "widget.py").unlink()

    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    notes = " ".join(result.notes or [])
    assert "Order" in notes, "routed model Order must be processed"
    assert "Widget" not in notes, "model without a route file must be skipped (require_route=True)"


# ---------------------------------------------------------------------------
# L87 (files_created = list(scaffolded or []))
# ---------------------------------------------------------------------------


def test_kills_scaffolded_prereqs_reported_in_files_created():
    """L87 `list(scaffolded or [])`.

    When a scaffoldable prereq is missing on a non-dry-run, the auto-created
    file MUST appear in files_created (seeded from `scaffolded`). The mutant
    `scaffolded and []` collapses to `[]`, dropping the scaffolded paths.
    """
    project_dir = create_fixture_project(name="cp_kill_l87")
    config = project_dir / "app" / "core" / "config.py"
    config.unlink()

    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    assert config.exists(), "missing prereq should have been auto-scaffolded"
    assert any(p.endswith("app/core/config.py") for p in result.files_created), (
        "auto-scaffolded config.py must be reported in files_created"
    )


# ---------------------------------------------------------------------------
# L184 (down_rev = find_migration_head(...) or "0001_initial")
# ---------------------------------------------------------------------------


def test_kills_migration_uses_actual_head_as_down_revision():
    """L184 `find_migration_head(...) or "0001_initial"`.

    The emitted migration's down_revision must chain off the REAL current head
    (0002_baseline_schema in the fixture). The mutant `head and "0001_initial"`
    would wrongly point down_revision at the literal fallback.
    """
    project_dir = create_fixture_project(name="cp_kill_l184")

    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"

    migs = list((project_dir / "alembic" / "versions").glob("cursor_idx_items*.py"))
    assert migs, "cursor migration file must be created"
    content = migs[0].read_text()
    assert 'down_revision = "0002_baseline_schema"' in content, (
        "down_revision must chain off the actual migration head, not the fallback"
    )


# ---------------------------------------------------------------------------
# L234 (not exists or 'get_multi_cursor' not in ...) + L235 (return False)
# ---------------------------------------------------------------------------


def test_kills_partial_state_completes_instead_of_no_op():
    """L234 BoolOp Or->And + L235 `return False`.

    With cursor.py AND the emitted test present but the CRUD NOT yet patched,
    _all_models_fully_patched must return False so the run completes the missing
    CRUD work. The L234 mutant (`not exists AND not-in`) and the L235 mutant
    (`return True`) both make it report 'fully patched' -> wrong no_op.
    """
    project_dir = create_fixture_project(name="cp_kill_l234")

    core = project_dir / "app" / "core" / "cursor.py"
    core.parent.mkdir(parents=True, exist_ok=True)
    core.write_text("# stub cursor module\n")
    emitted = project_dir / "tests" / "test_cursor_pagination.py"
    emitted.parent.mkdir(parents=True, exist_ok=True)
    emitted.write_text("# stub emitted test\n")

    crud = project_dir / "app" / "crud" / "item.py"
    assert "get_multi_cursor" not in crud.read_text(), "precondition: CRUD unpatched"

    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success", (
        f"partial state must complete, not no_op (got {result.status})"
    )
    assert any("crud" in p for p in result.files_modified), "CRUD must be patched"
    assert "get_multi_cursor" in crud.read_text()


# ---------------------------------------------------------------------------
# L244 (plural_class in route_file) Compare In->NotIn
# ---------------------------------------------------------------------------


def test_kills_route_with_plural_class_is_patched_via_route_anchor():
    """L244 `if plural_class in probe.read(route_file): return True`.

    When the route file already references ItemsPublic, the route MUST be
    patched off that anchor — even with the schema file removed. The mutant
    (In->NotIn) falls through to the schema branch, which (no schema) returns
    False, leaving the route unpatched.
    """
    project_dir = create_fixture_project(name="cp_kill_l244")
    route = project_dir / "app" / "api" / "routes" / "item.py"
    assert "ItemsPublic" in route.read_text(), "precondition: route references plural class"
    (project_dir / "app" / "schemas" / "item.py").unlink()

    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    assert any(p.endswith("api/routes/item.py") for p in result.files_modified), (
        "route must be patched when its own file references the plural class"
    )
    assert "list_items_cursor" in route.read_text()


# ---------------------------------------------------------------------------
# L246 (schema_file.exists() and plural_class in schema) BoolOp + Compare
# ---------------------------------------------------------------------------


def test_kills_route_patched_via_schema_anchor():
    """L246 Compare In->NotIn (schema fallback branch).

    Route file lacks the plural class but the schema declares it -> the route
    must still be patched via the schema fallback. The In->NotIn mutant inverts
    the schema-content check and refuses to patch.
    """
    project_dir = create_fixture_project(name="cp_kill_l246_in")
    route = project_dir / "app" / "api" / "routes" / "item.py"
    route.write_text(route.read_text().replace("ItemsPublic", "ItemListResp"))
    assert "ItemsPublic" not in route.read_text()
    assert "ItemsPublic" in (project_dir / "app" / "schemas" / "item.py").read_text()

    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    assert any(p.endswith("api/routes/item.py") for p in result.files_modified), (
        "route must be patched via the schema-anchor fallback"
    )
    assert "list_items_cursor" in route.read_text()


def test_kills_no_patch_when_neither_route_nor_schema_has_plural_class():
    """L246 BoolOp And->Or (schema_file.exists() short-circuit).

    Route lacks the plural class AND the schema file is gone -> the route must
    NOT be patched (the guard returns False without reading a missing schema).
    The And->Or mutant evaluates the second operand and reads the absent schema
    file, raising FileNotFoundError.
    """
    project_dir = create_fixture_project(name="cp_kill_l246_and")
    route = project_dir / "app" / "api" / "routes" / "item.py"
    route.write_text(route.read_text().replace("ItemsPublic", "ItemListResp"))
    (project_dir / "app" / "schemas" / "item.py").unlink()

    result = add_cursor_pagination(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    assert not any(p.endswith("api/routes/item.py") for p in result.files_modified), (
        "route must NOT be patched when neither route nor schema declares the plural class"
    )
    assert "list_items_cursor" not in route.read_text()
