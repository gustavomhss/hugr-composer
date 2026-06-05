"""Generic tool-contract mutation coverage for add_retry_budget.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_retry_budget.py in the mutation
runner: ``--tests test_add_retry_budget.py test_add_retry_budget_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_retry_budget import add_retry_budget
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_retry_budget import add_retry_budget

    for check in SCAFFOLDABLE_CHECKS:
        check(add_retry_budget, "add_retry_budget")


def test_auto_scaffolded_files_are_reported_in_files_created():
    """L65 BoolOp Or->And: ``files_created = list(scaffolded or [])``.

    On a *bare* tempdir the prerequisite step auto-scaffolds app/core/config.py
    et al, so ``scaffolded`` is a non-empty list. The ``or`` keeps those paths;
    the ``and`` mutant collapses them to ``[]`` and drops every scaffolded file
    from ``files_created``. Assert the scaffolded config.py is reported.
    """
    d = tempfile.mkdtemp()
    r = add_retry_budget(ToolInput(project_dir=d))
    assert r.status == "success", r.error
    # The bare project had no config.py, so the prereq step scaffolded it and it
    # MUST appear in files_created (the `and` mutant would have dropped it).
    assert any(p.endswith("app/core/config.py") for p in r.files_created), r.files_created
    # Glue + emitted test (created later) must still be there too.
    assert any(p.endswith("app/retry.py") for p in r.files_created), r.files_created


def test_config_not_repatched_when_already_present():
    """L102 BoolOp And->Or: ``config.exists() and "RETRY..." not in text``.

    Set up the divergent state: the glue (app/retry.py) is ABSENT but config.py
    already carries the RETRY_* fields. With ``and`` the guard is False so the
    patcher is skipped and config is not re-modified. The ``or`` mutant fires
    the branch (config exists is True), re-patching config and listing it in
    files_modified / duplicating the fields.
    """
    d = create_fixture_project(name="rb_contract_l102")
    first = add_retry_budget(ToolInput(project_dir=str(d)))
    assert first.status == "success", first.error
    config_file = d / "app" / "core" / "config.py"
    assert "RETRY_MAX_ATTEMPTS" in config_file.read_text()
    field_count_before = config_file.read_text().count("RETRY_MAX_ATTEMPTS")

    # Drop only the glue so the no_op short-circuit is bypassed and L102 runs,
    # while config still holds the RETRY_* fields.
    (d / "app" / "retry.py").unlink()

    second = add_retry_budget(ToolInput(project_dir=str(d)))
    assert second.status == "success", second.error
    # And-guard False => config untouched.
    assert not any(p.endswith("app/core/config.py") for p in second.files_modified), (
        second.files_modified
    )
    # No duplicate RETRY_* fields injected.
    assert config_file.read_text().count("RETRY_MAX_ATTEMPTS") == field_count_before


def test_succeeds_when_app_and_tests_dirs_preexist():
    """L96 / L140 BoolLiteral exist_ok=True->False.

    A normal fixture already has app/ and tests/ on disk. The two mkdir calls
    use exist_ok=True; flipping the exist_ok literal to False raises
    FileExistsError and aborts the run. A clean success here proves the dirs
    are tolerated.
    """
    d = create_fixture_project(name="rb_contract_dirs")
    assert (d / "app").exists()
    assert (d / "tests").exists()
    r = add_retry_budget(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error
    assert (d / "app" / "retry.py").exists()
    assert (d / "tests" / "test_add_retry_budget_emitted.py").exists()


def test_emitted_test_path_uses_project_tests_dir():
    """The emitted project test lands under <project>/tests/ (anchor sanity)."""
    d = create_fixture_project(name="rb_contract_emit")
    r = add_retry_budget(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error
    emitted = d / "tests" / "test_add_retry_budget_emitted.py"
    assert emitted.exists()
    resolved = {str(Path(p).resolve()) for p in r.files_created}
    assert str(emitted.resolve()) in resolved
