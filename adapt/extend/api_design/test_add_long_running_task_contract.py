"""Generic tool-contract mutation coverage for add_long_running_task.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_long_running_task.py in the mutation
runner: ``--tests test_add_long_running_task.py test_add_long_running_task_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_long_running_task import add_long_running_task
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_long_running_task, "add_long_running_task")


def _bare_project() -> Path:
    """A minimal project (only ``app/``) so prerequisites must auto-scaffold."""
    d = Path(tempfile.mkdtemp()) / "bare"
    (d / "app").mkdir(parents=True)
    (d / "app" / "__init__.py").write_text("")
    return d


def test_scaffolded_prereqs_kept_in_files_created() -> None:
    """L75 BoolOp ``scaffolded or []``: auto-scaffolded prereq files must be
    carried into ``files_created``.

    On a bare project ``ensure_prerequisites`` scaffolds non-empty files
    (app/core/config.py, app/routes/__init__.py, ...). With ``or`` the
    seed list is preserved; flipping to ``and`` would discard a non-empty
    ``scaffolded`` list, dropping those paths from ``files_created``.
    """
    d = _bare_project()
    r = add_long_running_task(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error
    created = set(r.files_created)
    assert str(Path(d / "app" / "core" / "config.py").resolve()) in {
        str(Path(p).resolve()) for p in created
    }
    assert str(Path(d / "app" / "routes" / "__init__.py").resolve()) in {
        str(Path(p).resolve()) for p in created
    }


def test_app_dir_mkdir_tolerates_existing_dir() -> None:
    """L114 BoolLiteral ``exist_ok=True``: ``app/`` already exists in a real
    project, so ``mkdir(exist_ok=True)`` must not raise.

    Flipping the literal to ``False`` makes ``mkdir`` raise
    ``FileExistsError`` on the pre-existing ``app/`` dir, breaking the run.
    """
    d = create_fixture_project(name="lrt_c_mkdir")
    assert (d / "app").is_dir()  # precondition the mutant would trip over
    r = add_long_running_task(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error
    assert (d / "app" / "workflow.py").exists()


def test_existing_routes_init_not_overwritten() -> None:
    """L121 UnaryNot ``not routes_init.exists()``: the api/routes package
    ``__init__.py`` already exists (empty) in a real project, so the guard is
    False and the file is left untouched.

    Flipping ``not X`` -> ``X`` makes the guard True for the existing file,
    overwriting it with the ``\"\"\"API routes package.\"\"\"`` stub.
    """
    d = create_fixture_project(name="lrt_c_init")
    routes_init = d / "app" / "api" / "routes" / "__init__.py"
    assert routes_init.exists()
    before = routes_init.read_text()
    assert before == ""  # fixture ships it empty
    r = add_long_running_task(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error
    # Untouched: the mutant would have written the stub docstring instead.
    assert routes_init.read_text() == ""
    assert "API routes package" not in routes_init.read_text()


def test_tasks_router_wired_into_routes_init() -> None:
    """L132 Compare ``"tasks_router" not in content``: on a first run the
    aggregator ``app/routes/__init__.py`` does NOT yet mention ``tasks_router``,
    so the dedup guard is True and the include lines get appended.

    Flipping ``not in`` -> ``in`` inverts the guard: the include would only be
    written when already present, so a first run would never wire the router.
    """
    d = _bare_project()
    r = add_long_running_task(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error
    routes_init = d / "app" / "routes" / "__init__.py"
    content = routes_init.read_text()
    assert "from app.api.routes.tasks import router as tasks_router" in content
    assert "api_router.include_router(tasks_router)" in content
    assert str(routes_init) in r.files_modified
    # Exactly once — no double-wiring.
    assert content.count("include_router(tasks_router)") == 1


def test_emitted_project_test_written() -> None:
    """L170 BoolLiteral ``exist_ok=True`` in ``_emit_project_test``: the
    ``tests/`` dir already exists in a real project, so the emit step must not
    raise and must drop the emitted test file.

    Flipping the literal to ``False`` makes ``mkdir`` raise on the existing
    ``tests/`` dir, aborting before the emitted test is written.
    """
    d = create_fixture_project(name="lrt_c_emit")
    assert (d / "tests").is_dir()  # precondition the mutant would trip over
    r = add_long_running_task(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error
    emitted = d / "tests" / "test_add_long_running_task_emitted.py"
    assert emitted.exists()
    assert str(Path(emitted).resolve()) in {str(Path(p).resolve()) for p in r.files_created}
