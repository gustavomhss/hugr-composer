"""Generic tool-contract mutation coverage for add_sbom_guardian.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_sbom_guardian.py in the mutation
runner: ``--tests test_add_sbom_guardian.py test_add_sbom_guardian_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_sbom_guardian import add_sbom_guardian
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_sbom_guardian import add_sbom_guardian

    for check in SCAFFOLDABLE_CHECKS:
        check(add_sbom_guardian, "add_sbom_guardian")


def test_scaffolded_prereqs_preserved_in_files_created():
    """L73 BoolOp Or->And: ``list(scaffolded or [])`` seeds files_created with
    the auto-scaffolded prereqs.

    On a bare directory (no app/core/config.py, no requirements.txt) the tool
    auto-scaffolds those prerequisites; the returned scaffolded paths must be
    carried into ``files_created``. The mutant ``scaffolded and []`` would
    discard them (a non-empty list AND [] -> []), so the scaffolded
    ``app/core/config.py`` would vanish from files_created.
    """
    bare = Path(tempfile.mkdtemp())
    try:
        result = add_sbom_guardian(ToolInput(project_dir=str(bare)))
        assert result.status == "success", result.error
        # config.py was missing -> auto-scaffolded -> must appear in files_created.
        assert any(p.endswith("app/core/config.py") for p in result.files_created), (
            f"scaffolded config.py missing from files_created: {result.files_created}"
        )
        # And it is a real file on disk that the tool reports having created.
        assert (bare / "app" / "core" / "config.py").is_file()
    finally:
        import shutil

        shutil.rmtree(bare, ignore_errors=True)


def test_scripts_init_created_on_fresh_project():
    """L100 UnaryNot: ``if not scripts_init.exists()`` creates scripts/__init__.py.

    On a fresh project scripts/__init__.py does NOT exist, so the tool writes it
    and reports it. The mutant (drop the ``not``) would only write it when it
    *already* exists -> on a fresh project the file would never be created.
    """
    project = create_fixture_project(name="sbom_scripts_init")
    result = add_sbom_guardian(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    scripts_init = project / "scripts" / "__init__.py"
    assert scripts_init.is_file(), "scripts/__init__.py was not created"
    assert any(p.endswith("scripts/__init__.py") for p in result.files_created), (
        f"scripts/__init__.py missing from files_created: {result.files_created}"
    )


def test_emitted_test_created_on_fresh_project():
    """L130 UnaryNot: ``if not emitted.exists()`` renders the emitted test file.

    On a fresh project tests/test_add_sbom_guardian_emitted.py does NOT exist,
    so the tool renders it. The mutant (drop the ``not``) would only render it
    when it already exists -> the emitted test would never be produced.
    """
    project = create_fixture_project(name="sbom_emitted")
    result = add_sbom_guardian(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    emitted = project / "tests" / "test_add_sbom_guardian_emitted.py"
    assert emitted.is_file(), "emitted test file was not created"
    assert any(
        p.endswith("tests/test_add_sbom_guardian_emitted.py") for p in result.files_created
    ), f"emitted test missing from files_created: {result.files_created}"
