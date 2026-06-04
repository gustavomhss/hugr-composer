"""Generic tool-contract mutation coverage for add_database_migrations_ci.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_database_migrations_ci.py in the mutation
runner: ``--tests test_add_database_migrations_ci.py test_add_database_migrations_ci_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_database_migrations_ci import add_database_migrations_ci
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def _bare() -> Path:
    d = Path(tempfile.mkdtemp()) / "bare"
    d.mkdir(parents=True)
    return d


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_database_migrations_ci, "add_database_migrations_ci")


# ---------------------------------------------------------------------------
# L66 BoolOp Or->And: files_created starts as list(scaffolded or []).
# On a bare project the prereqs are auto-scaffolded, so the scaffolded files
# (e.g. app/core/config.py) MUST appear in files_created. With `scaffolded and
# []` they would be dropped (files_created would start empty).
# ---------------------------------------------------------------------------
def test_scaffolded_prereq_files_reported_in_files_created():
    """L66: auto-scaffolded prereq files are carried into files_created."""
    d = _bare()
    r = add_database_migrations_ci(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error
    assert any(p.endswith("app/core/config.py") for p in r.files_created), (
        f"scaffolded prereq (config.py) must be reported in files_created; got {r.files_created}"
    )


# ---------------------------------------------------------------------------
# L129 UnaryNot (not emitted.exists() -> emitted.exists()): on a fresh run the
# emitted test file does NOT exist, so the `not` branch fires and the file is
# rendered + appended. Flipping `not` skips creation entirely.
# ---------------------------------------------------------------------------
def test_emitted_test_file_created_on_fresh_run():
    """L129: the emitted test file is written and reported on a fresh run."""
    p = create_fixture_project(name="mci_emit")
    r = add_database_migrations_ci(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error
    emitted = Path(p) / "tests" / "test_add_database_migrations_ci_emitted.py"
    assert emitted.exists(), "emitted test file must be created on a fresh run"
    assert any(
        s.endswith("tests/test_add_database_migrations_ci_emitted.py") for s in r.files_created
    ), f"emitted test file must be in files_created; got {r.files_created}"


# ---------------------------------------------------------------------------
# L91 mkdir(exist_ok=True) for app/migrations: when the directory already
# exists, exist_ok=False would raise FileExistsError. Pre-create it (empty, so
# no no_op) and assert the run still succeeds. Wrapped so an unhandled raise
# surfaces as an assertion failure (a kill), not a test error.
# ---------------------------------------------------------------------------
def test_succeeds_when_migrations_dir_preexists():
    """L91: app/migrations/ pre-existing must not break the run."""
    p = create_fixture_project(name="mci_mig_pre")
    (Path(p) / "app" / "migrations").mkdir(parents=True, exist_ok=True)
    try:
        r = add_database_migrations_ci(ToolInput(project_dir=str(p)))
    except Exception as exc:  # noqa: BLE001 - convert raise into a kill
        raise AssertionError(
            f"run must not raise when app/migrations/ pre-exists: {exc!r}"
        ) from exc
    assert r.status == "success", r.error


# ---------------------------------------------------------------------------
# L105 mkdir(exist_ok=True) for scripts/: same logic for the scripts dir.
# ---------------------------------------------------------------------------
def test_succeeds_when_scripts_dir_preexists():
    """L105: scripts/ pre-existing must not break the run."""
    p = create_fixture_project(name="mci_scripts_pre")
    (Path(p) / "scripts").mkdir(parents=True, exist_ok=True)
    try:
        r = add_database_migrations_ci(ToolInput(project_dir=str(p)))
    except Exception as exc:  # noqa: BLE001 - convert raise into a kill
        raise AssertionError(f"run must not raise when scripts/ pre-exists: {exc!r}") from exc
    assert r.status == "success", r.error


# ---------------------------------------------------------------------------
# L127 mkdir(exist_ok=True) for tests/: fixture projects already ship a tests/
# dir, so exist_ok=False would raise FileExistsError. Assert the run succeeds.
# ---------------------------------------------------------------------------
def test_succeeds_when_tests_dir_preexists():
    """L127: tests/ pre-existing (as in real projects) must not break the run."""
    p = create_fixture_project(name="mci_tests_pre")
    (Path(p) / "tests").mkdir(parents=True, exist_ok=True)
    try:
        r = add_database_migrations_ci(ToolInput(project_dir=str(p)))
    except Exception as exc:  # noqa: BLE001 - convert raise into a kill
        raise AssertionError(f"run must not raise when tests/ pre-exists: {exc!r}") from exc
    assert r.status == "success", r.error
