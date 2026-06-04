"""Generic tool-contract mutation coverage for add_data_import.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_data_import.py in the mutation
runner: ``--tests test_add_data_import.py test_add_data_import_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_data_import import add_data_import
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_data_import, "add_data_import")


# ---------------------------------------------------------------------------
# Tool-specific mutation kills (survivors beyond the shared preamble).
# ---------------------------------------------------------------------------


def test_scaffolded_prereqs_preserved_in_files_created() -> None:
    """Kill L60 BoolOp Or->And: ``list(scaffolded or [])``.

    On a bare (non-skill) project the prerequisite auto-scaffolder creates
    files such as ``app/models/base.py``. The correct ``scaffolded or []``
    seeds ``files_created`` with those paths; the ``and`` flip would discard
    them (``list(<truthy> and []) == []``), so the scaffolded prereq would
    vanish from the reported ``files_created``.
    """
    bare = Path(tempfile.mkdtemp())
    result = add_data_import(ToolInput(project_dir=str(bare)))
    assert result.status == "success", result.error
    assert any(p.endswith("app/models/base.py") for p in result.files_created), (
        "scaffolded prereq app/models/base.py missing from files_created"
    )


def test_models_init_import_lands_on_its_own_line() -> None:
    """Kill L188 UnaryNot ``not content.endswith("\\n")``.

    When ``app/models/__init__.py`` does NOT already end with a newline, the
    guard must add one before appending the ImportJob import so it lands on a
    fresh line. The flip would skip the newline and glue the import onto the
    previous line, breaking the file.
    """
    project = create_fixture_project(name="cimp_models_init_newline")
    models_init = project / "app" / "models" / "__init__.py"
    # Force the no-trailing-newline branch.
    models_init.write_text(models_init.read_text().rstrip("\n"))

    result = add_data_import(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error

    marker = "from app.models.import_job import ImportJob  # noqa: F401"
    lines = models_init.read_text().splitlines()
    assert marker in lines, (
        "ImportJob import was glued onto the previous line instead of landing on its own line"
    )


def test_config_file_reported_modified() -> None:
    """Kill L216 Compare NotEq->Eq: ``if config_file.read_text() != before``.

    The IMPORT_* settings change config.py, so the tool must report config.py
    in ``files_modified``. The ``==`` flip would only append on an UNCHANGED
    file, so a freshly-patched config would be omitted from ``files_modified``.
    """
    project = create_fixture_project(name="cimp_config_modified")
    result = add_data_import(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert any(p.endswith("app/core/config.py") for p in result.files_modified), (
        "patched config.py missing from files_modified"
    )


def test_migration_down_revision_uses_actual_head() -> None:
    """Kill L114 BoolOp Or->And: ``find_migration_head(...) or "0001_initial"``.

    A real fixture project's head is ``0002_baseline_schema`` (not the
    ``0001_initial`` fallback). The correct ``or`` keeps the discovered head;
    the ``and`` flip would substitute the literal fallback, producing a broken
    migration chain.
    """
    project = create_fixture_project(name="cimp_mig_downrev")
    result = add_data_import(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error

    mig = project / "alembic" / "versions" / "add_import_jobs.py"
    assert mig.exists(), "add_import_jobs migration not created"
    text = mig.read_text()
    assert '"0002_baseline_schema"' in text, (
        "migration down_revision did not use the discovered head (fallback literal leaked in)"
    )


def test_emitted_test_dir_created_when_tests_already_exist() -> None:
    """Kill L222 BoolLiteral True->False: ``mkdir(..., exist_ok=True)``.

    A real fixture project already has a ``tests/`` directory. With the
    correct ``exist_ok=True`` the mkdir is a no-op and the emitted test is
    written; the ``exist_ok=False`` flip would raise ``FileExistsError`` and
    blow up the tool instead of returning success.
    """
    project = create_fixture_project(name="cimp_emitted_test_dir")
    assert (project / "tests").exists(), "fixture should already have tests/"

    result = add_data_import(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    emitted = project / "tests" / "test_add_data_import_emitted.py"
    assert emitted.exists(), "emitted project test was not written"
