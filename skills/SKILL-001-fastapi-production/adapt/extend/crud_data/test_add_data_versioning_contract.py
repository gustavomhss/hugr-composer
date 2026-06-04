"""Generic tool-contract mutation coverage for add_data_versioning.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_data_versioning.py in the mutation
runner: ``--tests test_add_data_versioning.py test_add_data_versioning_contract.py``.
"""

from adapt.contracts import ToolInput
from adapt.contracts.migration_helper import find_migration_head
from adapt.extend.crud_data.add_data_versioning import add_data_versioning
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_data_versioning, "add_data_versioning")


# ---------------------------------------------------------------------------
# Tool-specific survivors (not covered by the generic preamble contract)
# ---------------------------------------------------------------------------


def test_scaffolded_prereqs_retained_in_files_created():
    """L60 BoolOp Or->And: files_created seeds from ``list(scaffolded or [])``.

    A bare project (only app/main.py) forces ensure_prerequisites to
    auto-scaffold the BASE_MODEL/MODELS_INIT/CONFIG/ROUTES prereqs; those
    scaffolded paths are the ones returned in ``scaffolded`` and must survive
    into files_created. With ``scaffolded and []`` they would all be dropped
    (files_created would start empty), so the auto-created base files vanish
    from the result.
    """
    import tempfile
    from pathlib import Path

    d = Path(tempfile.mkdtemp())
    (d / "app").mkdir()
    (d / "app" / "main.py").write_text("app = 1\n")

    result = add_data_versioning(ToolInput(project_dir=str(d)))
    assert result.status == "success", result.error

    # These come from the prereq auto-scaffold (``scaffolded``), not from the
    # tool's own ``files_created.append`` calls (which start at versioning/).
    assert any(p.endswith("app/models/base.py") for p in result.files_created), (
        "scaffolded base model dropped from files_created (Or->And mutation)"
    )
    assert any(p.endswith("app/core/config.py") for p in result.files_created), (
        "scaffolded config dropped from files_created (Or->And mutation)"
    )


def test_migration_chains_off_real_head_not_hardcoded_fallback():
    """L115 BoolOp Or->And: ``find_migration_head(...) or "0001_initial"``.

    The fixture's Alembic chain HEAD is ``0002_baseline_schema`` (later than
    the ``0001_initial`` fallback). The generated migration's down_revision must
    chain off the discovered HEAD. With ``find_migration_head(...) and
    "0001_initial"`` the result would be the constant ``0001_initial`` even
    though a real head exists, forking the chain.
    """
    project_dir = create_fixture_project(name="ver_c_mig_head")
    versions_dir = project_dir / "alembic" / "versions"
    real_head = find_migration_head(versions_dir)
    assert real_head and real_head != "0001_initial", (
        "fixture precondition: head must differ from fallback"
    )

    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    mig = versions_dir / "add_content_versions.py"
    assert mig.exists(), "migration not generated"
    content = mig.read_text()
    assert f'down_revision: str | None = "{real_head}"' in content, (
        "migration did not chain off the real head (Or->And mutation)"
    )
    assert 'down_revision: str | None = "0001_initial"' not in content, (
        "migration fell back to hardcoded 0001_initial despite a real head"
    )


def test_models_init_import_lands_on_its_own_line_without_trailing_newline():
    """L181 UnaryNot: ``if not content.endswith(chr(10))`` in _patch_models_init.

    When models/__init__.py lacks a trailing newline the tool must insert one
    before appending the ContentVersion import, so the new import is on its own
    line. Flipping ``not`` skips that fix and glues the new import onto the last
    existing import line, corrupting the previous statement.
    """
    project_dir = create_fixture_project(name="ver_c_models_nl")
    models_init = project_dir / "app" / "models" / "__init__.py"
    # Force the no-trailing-newline branch.
    models_init.write_text(models_init.read_text().rstrip("\n"))
    last_line_before = models_init.read_text().splitlines()[-1]
    assert last_line_before, "fixture precondition: a final import line exists"

    add_data_versioning(ToolInput(project_dir=str(project_dir)))
    lines = models_init.read_text().splitlines()

    # The pre-existing final import line must remain intact (not glued).
    assert last_line_before in lines, (
        "previous import line was corrupted; newline guard was skipped (UnaryNot mutation)"
    )
    # The new import must appear as its own standalone line.
    assert "from app.models.content_version import ContentVersion  # noqa: F401" in lines, (
        "ContentVersion import not on its own line (UnaryNot mutation)"
    )


def test_emit_project_test_tolerates_preexisting_tests_dir():
    """L205 BoolLiteral True->False: tests dir mkdir uses exist_ok=True.

    When the tests/ directory already exists, mkdir(exist_ok=False) would raise
    FileExistsError and abort the run. The tool must still succeed and still
    emit the project test.
    """
    project_dir = create_fixture_project(name="ver_c_tests_exist")
    (project_dir / "tests").mkdir(parents=True, exist_ok=True)
    assert (project_dir / "tests").exists(), "fixture precondition: tests dir present"

    result = add_data_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"pre-existing tests/ dir broke the run (exist_ok flipped to False): {result.error}"
    )
    emitted = project_dir / "tests" / "test_add_data_versioning_emitted.py"
    assert emitted.exists(), "project test not emitted into existing tests dir"


def test_execution_time_uses_millisecond_scale():
    """L214 BinOp Mult->FloorDiv: ``int((monotonic - start) * 1000)``.

    A full scaffold (14 files + ast.parse) takes tens of milliseconds, so the
    reported execution_time_ms is comfortably greater than 1. With
    ``... // 1000`` the sub-second elapsed collapses to 0 and max(1, 0) pins the
    value at exactly 1 regardless of real work.
    """
    project_dir = create_fixture_project(name="ver_c_ms_scale")
    result = add_data_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    assert result.execution_time_ms > 1, (
        "execution_time_ms pinned at 1 — millisecond scaling lost (Mult->FloorDiv mutation)"
    )
