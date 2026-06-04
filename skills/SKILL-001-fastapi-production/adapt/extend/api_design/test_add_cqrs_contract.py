"""Generic tool-contract mutation coverage for add_cqrs.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_cqrs.py in the mutation
runner: ``--tests test_add_cqrs.py test_add_cqrs_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS

IMPORT_LINE = "from app.api.routes.cqrs import router as cqrs_router"
INCLUDE_LINE = "api_router.include_router(cqrs_router)"


def test_contract():
    from adapt.extend.api_design.add_cqrs import add_cqrs

    for check in SCAFFOLDABLE_CHECKS:
        check(add_cqrs, "add_cqrs")


def test_router_import_lands_after_last_app_import():
    """Kills L201 Eq->NotEq, L206 Add->Sub.

    On a real fixture (which HAS ``from app.`` imports) the cqrs import line
    must be inserted immediately after the LAST ``from app.`` import. The
    ``last_app_import == -1`` guard must stay false (Eq->NotEq would wrongly
    take the fallback branch) and the insert offset must be ``+1`` (Add->Sub
    would place it one line too early, breaking ordering / parseability).
    """
    from adapt.extend.api_design.add_cqrs import add_cqrs

    project = create_fixture_project(name="cqrs_import_pos")
    routes_init = project / "app" / "routes" / "__init__.py"
    before = routes_init.read_text().splitlines()
    last_app = max(i for i, ln in enumerate(before) if ln.startswith("from app."))

    result = add_cqrs(ToolInput(project_dir=str(project)))
    assert result.status == "success"

    after = routes_init.read_text().splitlines()
    assert IMPORT_LINE in after
    # The new import must sit exactly one line after the previous last app
    # import (which is unchanged at index ``last_app``).
    assert after[last_app + 1] == IMPORT_LINE
    assert after[last_app] == before[last_app]


def test_router_include_lands_after_last_include():
    """Kills L212 Eq->NotEq, L217 Add->Sub.

    The cqrs ``include_router`` line must be inserted immediately after the
    LAST existing ``api_router.include_router(...)`` line. The
    ``last_include == -1`` guard must stay false and the insert offset must
    be ``+1``.
    """
    from adapt.extend.api_design.add_cqrs import add_cqrs

    project = create_fixture_project(name="cqrs_include_pos")
    routes_init = project / "app" / "routes" / "__init__.py"
    before = routes_init.read_text().splitlines()
    last_inc = max(i for i, ln in enumerate(before) if ln.startswith("api_router.include_router"))

    result = add_cqrs(ToolInput(project_dir=str(project)))
    assert result.status == "success"

    after = routes_init.read_text().splitlines()
    assert INCLUDE_LINE in after
    # The import line inserted earlier shifts every include index down by one,
    # so the cqrs include must land exactly two lines after the previous last
    # include's original index, and right after the old last include.
    assert after[last_inc + 2] == INCLUDE_LINE
    assert after[last_inc + 1].startswith("api_router.include_router")


def _bare_routes_init() -> Path:
    """Routes file with NO ``from app.`` imports and NO existing includes.

    Forces both fallback branches (the ``== -1`` paths) to run.
    """
    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text(
        'from fastapi import APIRouter\n\napi_router = APIRouter()\n\n__all__ = ["api_router"]\n'
    )
    return ri


def test_fallback_import_anchors_on_apirouter_construction():
    """Kills L203 In->NotIn / And->Or, L204 Sub->Add.

    With no ``from app.`` import the tool falls back to anchoring on the
    ``api_router = APIRouter()`` construction line. The import must land
    immediately BEFORE that construction line:
      - In->NotIn / And->Or would match the wrong (or no) line.
      - Sub->Add would shift the import one line past the anchor.
    """
    from adapt.extend.api_design.add_cqrs import _patch_routes_init

    ri = _bare_routes_init()
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()

    assert IMPORT_LINE in lines
    ctor_idx = next(i for i, ln in enumerate(lines) if "api_router" in ln and "APIRouter()" in ln)
    # Import inserted at idx-1+1 == ctor line index, pushing ctor down by one:
    # the import must be the line directly above the construction.
    assert lines[ctor_idx - 1] == IMPORT_LINE


def test_fallback_include_anchors_after_apirouter_construction():
    """Kills L214 In->NotIn / And->Or, L217 Add->Sub (fallback arm).

    With no existing include the tool falls back to anchoring on the
    ``api_router = APIRouter()`` construction line and inserts the include
    right after it.
    """
    from adapt.extend.api_design.add_cqrs import _patch_routes_init

    ri = _bare_routes_init()
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()

    assert INCLUDE_LINE in lines
    ctor_idx = next(i for i, ln in enumerate(lines) if "api_router" in ln and "APIRouter()" in ln)
    # Include inserted at ctor_idx + 1: directly below the construction line.
    assert lines[ctor_idx + 1] == INCLUDE_LINE


def test_idempotent_routes_patch_no_double_insert():
    """Guards the ``import_line in src`` early-return: no duplicate wiring."""
    from adapt.extend.api_design.add_cqrs import _patch_routes_init

    ri = _bare_routes_init()
    _patch_routes_init(ri)
    first = ri.read_text()
    _patch_routes_init(ri)
    second = ri.read_text()

    assert first == second
    assert second.count(IMPORT_LINE) == 1
    assert second.count(INCLUDE_LINE) == 1


def test_succeeds_when_cqrs_dir_preexists():
    """Kills L125 True->False (``exist_ok``).

    A pre-existing ``app/cqrs`` dir (without ``CommandBus``, so the
    idempotency guard does not fire) must not break the package mkdir.
    With ``exist_ok=False`` the mkdir would raise FileExistsError.
    """
    from adapt.extend.api_design.add_cqrs import add_cqrs

    project = create_fixture_project(name="cqrs_predir")
    (project / "app" / "cqrs").mkdir(parents=True, exist_ok=True)

    result = add_cqrs(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    assert any(p.endswith("app/cqrs/__init__.py") for p in result.files_created)


def test_emits_project_test_into_existing_tests_dir():
    """Kills L223 True->False (``exist_ok`` on the ``tests/`` mkdir).

    The fixture already ships a ``tests/`` directory; emitting the project
    test must still succeed (``exist_ok=False`` would raise on the existing
    dir).
    """
    from adapt.extend.api_design.add_cqrs import add_cqrs

    project = create_fixture_project(name="cqrs_emit")
    assert (project / "tests").exists()

    result = add_cqrs(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    assert (project / "tests" / "test_add_cqrs_emitted.py").exists()
