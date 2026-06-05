"""Generic tool-contract mutation coverage for add_graceful_shutdown.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_graceful_shutdown.py in the mutation
runner: ``--tests test_add_graceful_shutdown.py test_add_graceful_shutdown_contract.py``.

The ``test_kill_*`` functions below target this tool's bespoke survivors
(scaffolded-file propagation, exist_ok mkdir guards, and the config-patch
dedup guard) that the generic preamble checks do not cover.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_graceful_shutdown import add_graceful_shutdown
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_graceful_shutdown import add_graceful_shutdown

    for check in SCAFFOLDABLE_CHECKS:
        check(add_graceful_shutdown, "add_graceful_shutdown")


def test_kill_l71_scaffolded_files_propagate_to_created():
    """L71 ``list(scaffolded or [])`` Or->And.

    On a bare project the prerequisite auto-scaffolder creates ``config.py``
    (and ``app/__init__.py`` etc.). Those scaffolded paths must be carried
    into ``files_created``. The Or->And mutant evaluates ``scaffolded and []``
    which is always ``[]`` for a truthy ``scaffolded`` list, dropping the
    scaffolded prerequisites from the result.
    """
    project = Path(tempfile.mkdtemp())
    result = add_graceful_shutdown(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    # The auto-scaffolded config.py must be reported as created.
    assert any(p.endswith("app/core/config.py") for p in result.files_created), (
        f"scaffolded config.py missing from files_created: {result.files_created}"
    )
    # And the scaffolder produces more than just the tool's own outputs
    # (shutdown.py + manifest + emitted test); the prereq package files too.
    assert any(p.endswith("app/__init__.py") for p in result.files_created), (
        f"scaffolded package init missing from files_created: {result.files_created}"
    )


def test_kill_l102_app_dir_mkdir_exist_ok():
    """L102 ``app_dir.mkdir(parents=True, exist_ok=True)`` True->False.

    When ``app/`` already exists, the True->False mutant turns the mkdir into
    a ``FileExistsError`` raise. Pre-creating ``app/`` and asserting a clean
    success with the glue written kills it.
    """
    project = Path(tempfile.mkdtemp())
    (project / "app").mkdir()
    result = add_graceful_shutdown(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert (project / "app" / "shutdown.py").exists()
    assert any(p.endswith("app/shutdown.py") for p in result.files_created)


def test_kill_l142_tests_dir_mkdir_exist_ok():
    """L142 ``(project / "tests").mkdir(parents=True, exist_ok=True)`` True->False.

    When ``tests/`` already exists, the True->False mutant raises
    ``FileExistsError`` while emitting the project test. Pre-creating
    ``tests/`` and asserting the emitted test still lands kills it.
    """
    project = Path(tempfile.mkdtemp())
    (project / "tests").mkdir()
    result = add_graceful_shutdown(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    emitted = project / "tests" / "test_add_graceful_shutdown_emitted.py"
    assert emitted.exists(), "emitted project test not written into existing tests/ dir"
    assert any(
        p.endswith("tests/test_add_graceful_shutdown_emitted.py") for p in result.files_created
    )


def test_kill_l108_config_patch_dedup_guard():
    """L108 ``config.exists() and "SHUTDOWN_DRAIN_SECONDS" not in text`` And->Or.

    The guard must only re-patch config when the field is absent. We drive the
    "config already has the field but shutdown.py is gone" state: run once
    (adds field + glue), delete the glue, run again. The second run reaches
    L108 with the field already present, so the original (And) skips the patch
    and config is NOT in ``files_modified``. The And->Or mutant
    (``exists() or ...`` -> True) re-enters the patch branch and reports the
    config as modified.
    """
    project = create_fixture_project(name="gs_kill_l108")
    r1 = add_graceful_shutdown(ToolInput(project_dir=str(project)))
    assert r1.status == "success", r1.error
    assert any(p.endswith("app/core/config.py") for p in r1.files_modified)

    # Remove the glue so the idempotency short-circuit (L75) does not fire and
    # we actually reach the L108 config guard again.
    (project / "app" / "shutdown.py").unlink()

    r2 = add_graceful_shutdown(ToolInput(project_dir=str(project)))
    assert r2.status == "success", r2.error
    assert not any(p.endswith("app/core/config.py") for p in r2.files_modified), (
        f"config re-patched though field already present: {r2.files_modified}"
    )
