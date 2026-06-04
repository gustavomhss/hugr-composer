"""Generic tool-contract mutation coverage for add_api_fuzzer.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_api_fuzzer.py in the mutation
runner: ``--tests test_add_api_fuzzer.py test_add_api_fuzzer_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_api_fuzzer import add_api_fuzzer
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_api_fuzzer import add_api_fuzzer

    for check in SCAFFOLDABLE_CHECKS:
        check(add_api_fuzzer, "add_api_fuzzer")


def _endswith_any(paths: list[str], suffix: str) -> bool:
    """True if any path ends with *suffix* (symlink-safe membership)."""
    return any(p.endswith(suffix) for p in paths)


# ---------------------------------------------------------------------------
# L70  BoolOp: `list(scaffolded or [])` Or -> And
# On a BARE project the prerequisite auto-scaffolder creates app/core/config.py
# (and the package __init__.py files). Those live in `scaffolded` and seed
# files_created via `scaffolded or []`. Flipping Or->And makes the seed an empty
# list, so the scaffolded prerequisites vanish from files_created.
# ---------------------------------------------------------------------------


def test_scaffolded_prereqs_seed_files_created() -> None:
    """L70: auto-scaffolded prerequisites appear in files_created (Or, not And)."""
    bare = Path(tempfile.mkdtemp())
    result = add_api_fuzzer(ToolInput(project_dir=str(bare)))
    assert result.status == "success", result.error
    # config.py is auto-scaffolded for a bare project and recorded as a created
    # .py file. With Or->And it would be dropped from the seed list.
    assert _endswith_any(result.files_created, "app/core/config.py"), (
        "auto-scaffolded app/core/config.py must be reported in files_created; "
        f"got {result.files_created}"
    )
    # The package __init__ scaffold artefacts are also seeded from `scaffolded`.
    assert _endswith_any(result.files_created, "app/__init__.py"), (
        "auto-scaffolded app/__init__.py must be reported in files_created"
    )


# ---------------------------------------------------------------------------
# L132  BoolLiteral: `(project / "tests").mkdir(parents=True, exist_ok=True)`
# A fixture project already ships a tests/ directory. If exist_ok is flipped to
# False the mkdir raises FileExistsError, which propagates out of the tool
# instead of returning status="success".
# ---------------------------------------------------------------------------


def test_succeeds_when_tests_dir_already_exists() -> None:
    """L132: tool succeeds even though tests/ pre-exists (mkdir exist_ok=True)."""
    project_dir = create_fixture_project(name="fuzz_contract_tests_exist")
    assert (project_dir / "tests").exists(), "fixture should ship a tests/ dir"
    # Must not raise FileExistsError; must complete successfully.
    result = add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error


# ---------------------------------------------------------------------------
# L134  UnaryNot: `if not emitted.exists()` not X -> X
# On a fresh project the emitted regression test does not yet exist, so the
# guard renders it and records it in files_created. Flipping `not` skips the
# render, so the emitted test is neither written nor reported.
# ---------------------------------------------------------------------------


def test_emitted_regression_test_created() -> None:
    """L134: emitted test is rendered + reported when absent (not X branch)."""
    project_dir = create_fixture_project(name="fuzz_contract_emitted")
    emitted = project_dir / "tests" / "test_add_api_fuzzer_emitted.py"
    assert not emitted.exists(), "emitted test must not pre-exist on a fresh project"
    result = add_api_fuzzer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    assert emitted.exists(), "emitted regression test must be written to disk"
    assert _endswith_any(result.files_created, "tests/test_add_api_fuzzer_emitted.py"), (
        "emitted regression test must be reported in files_created"
    )
