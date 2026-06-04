"""Generic tool-contract mutation coverage for add_contract_tests.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_contract_tests.py in the mutation
runner: ``--tests test_add_contract_tests.py test_add_contract_tests_contract.py``.

The ``test_kills_*`` functions below target tool-specific survivors that the
shared preamble checks do not reach.
"""

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_contract_tests import add_contract_tests
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_contract_tests import add_contract_tests

    for check in SCAFFOLDABLE_CHECKS:
        check(add_contract_tests, "add_contract_tests")


def test_kills_default_stateful_false() -> None:
    """L34 BoolLiteral False->True: the ``stateful`` default must be False.

    With the default (no ``stateful`` arg), the emitted stateful test file is
    the disabled variant carrying ``pytest.mark.skip``. If the default flipped
    to True the skip marker would vanish.
    """
    project_dir = create_fixture_project(name="ct_kill_stateful_default")
    result = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    src = (project_dir / "tests" / "contracts" / "test_stateful.py").read_text()
    assert "pytest.mark.skip" in src
    assert "Stateful.links" in src


def test_kills_scaffolded_boolop_or() -> None:
    """L73 BoolOp Or->And on ``list(scaffolded or [])``.

    On a complete fixture project the prerequisites are already met, so
    ``scaffolded`` is falsy (None / empty). ``None and []`` evaluates to None
    and ``list(None)`` would raise TypeError; the Or short-circuit yields ``[]``
    instead. Asserting a clean success run kills the And mutant.
    """
    project_dir = create_fixture_project(name="ct_kill_scaffolded")
    result = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    assert isinstance(result.files_created, list)
    assert result.files_created


def test_kills_pacts_mkdir_exist_ok() -> None:
    """L101 BoolLiteral True->False on ``pacts_dir.mkdir(exist_ok=True)``.

    Pre-create the ``pacts/`` directory. With ``exist_ok=True`` the run still
    succeeds; flipping to ``exist_ok=False`` would raise FileExistsError.
    """
    project_dir = create_fixture_project(name="ct_kill_pacts_mkdir")
    (project_dir / "pacts").mkdir()
    result = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error


def test_kills_tests_mkdir_exist_ok() -> None:
    """L156 BoolLiteral True->False on ``(project / "tests").mkdir(...)``.

    The ``tests/`` directory always exists by this point (the fixture ships it
    and the tool just wrote ``tests/contracts/``). ``exist_ok=True`` keeps the
    run green; flipping to False would raise FileExistsError before the emitted
    test is rendered.
    """
    project_dir = create_fixture_project(name="ct_kill_tests_mkdir")
    assert (project_dir / "tests").is_dir()
    result = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    assert (project_dir / "tests" / "test_add_contract_tests_emitted.py").exists()


def test_kills_emitted_unary_not() -> None:
    """L158 UnaryNot ``not emitted.exists()`` -> ``emitted.exists()``.

    On a fresh project the emitted regression test does not yet exist, so the
    ``not ... exists()`` guard is True and the file IS rendered. Flipping to
    drop the ``not`` would skip rendering it. Assert it lands and is listed.
    """
    project_dir = create_fixture_project(name="ct_kill_emitted")
    emitted = project_dir / "tests" / "test_add_contract_tests_emitted.py"
    assert not emitted.exists()
    result = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    assert emitted.exists()
    assert any(p.endswith("tests/test_add_contract_tests_emitted.py") for p in result.files_created)


def test_kills_excludes_note_boolop_or() -> None:
    """L169 BoolOp Or->And on ``excludes or ['(none)']`` in the notes.

    With no ``exclude_endpoints`` the excludes list is empty, so the Or yields
    the ``['(none)']`` placeholder in the formatted note. ``[] and [...]`` would
    evaluate to ``[]`` and the note would render ``[]`` instead.
    """
    project_dir = create_fixture_project(name="ct_kill_excludes_note")
    result = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    combined = " ".join(result.notes)
    assert "(none)" in combined


def test_kills_pyproject_dedup_compare_in() -> None:
    """L358 Compare In->NotIn on ``if "schemathesis" in src`` guard.

    Pre-write a pyproject that already mentions ``schemathesis``. The dedup
    guard returns early, so NO TOOL-026 marker block is appended. Flipping the
    membership test to NotIn would append the block.
    """
    project_dir = create_fixture_project(name="ct_kill_pyproject_dedup")
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text("[tool.placeholder]\nschemathesis = 1\n")
    result = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    text = pyproject.read_text()
    assert "TOOL-026" not in text
    assert text.count("[tool.pytest.ini_options]") == 0


def test_kills_pyproject_patch_binop_add() -> None:
    """L369 BinOp Add->Sub on ``src + marker_block`` in ``_patch_pyproject``.

    A pyproject WITHOUT ``schemathesis`` gets the marker block appended. The
    write is ``src + marker_block``; ``str - str`` would raise TypeError. Assert
    the original content is preserved AND the marker block is present after it.
    """
    project_dir = create_fixture_project(name="ct_kill_pyproject_patch")
    pyproject = project_dir / "pyproject.toml"
    original = '[project]\nname = "demo-app"\nversion = "0.1.0"\n'
    pyproject.write_text(original)
    result = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    text = pyproject.read_text()
    assert text.startswith(original)
    assert "TOOL-026" in text
    assert "schemathesis: schemathesis property-based API contract tests" in text
    assert any(p.endswith("pyproject.toml") for p in result.files_modified)
