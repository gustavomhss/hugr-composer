"""Generic tool-contract mutation coverage for add_dependency_health_map.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_dependency_health_map.py in the mutation
runner: ``--tests test_add_dependency_health_map.py test_add_dependency_health_map_contract.py``.
"""

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_dependency_health_map import add_dependency_health_map
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_dependency_health_map, "add_dependency_health_map")


# ---------------------------------------------------------------------------
# Tool-specific mutation kills (beyond the shared preamble checks)
# ---------------------------------------------------------------------------


def test_main_import_inserted_right_after_fastapi_anchor():
    """L196 In->NotIn: the health_map import is spliced directly after the
    ``from fastapi import FastAPI`` anchor, NOT prepended to the top of the file.

    If the ``in`` guard flips to ``not in``, the tool takes the else branch and
    prepends the import before the module docstring instead of after the anchor.
    """
    project_dir = create_fixture_project(name="hmap_anchor_after")
    main_file = project_dir / "app" / "main.py"
    original = main_file.read_text()
    assert "from fastapi import FastAPI" in original, "fixture precondition"

    result = add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error

    patched = main_file.read_text()
    anchor = "from fastapi import FastAPI"
    import_line = "from app.api.routes.health_map import router as health_map_router"
    assert import_line in patched, "health_map import missing from main.py"

    anchor_idx = patched.index(anchor)
    import_idx = patched.index(import_line)
    # Import must come AFTER the anchor (NotIn flip would prepend it to the top).
    assert import_idx > anchor_idx, (
        "health_map import must be inserted after the FastAPI anchor, not before it"
    )
    # And it must land immediately after the anchor line (no other source between
    # the anchor and the spliced import beyond the anchor token itself).
    between = patched[anchor_idx + len(anchor) : import_idx]
    assert between.strip() == "", (
        f"health_map import should immediately follow the anchor, got: {between!r}"
    )
    # The file must NOT begin with the health_map import (the else-branch prepend).
    assert not patched.lstrip().startswith(import_line), (
        "health_map import was prepended to the top — anchor splice did not run"
    )


def test_main_import_prepended_when_no_fastapi_anchor():
    """L202 BinOp Add->Sub: when main.py lacks the ``from fastapi import FastAPI``
    anchor, the else branch prepends the import via ``hmap_import + src``.

    Add->Sub turns string concatenation into ``hmap_import - src`` (TypeError),
    so the tool would crash instead of succeeding. Driving the anchor-less branch
    and asserting success + the import present kills that mutant.
    """
    project_dir = create_fixture_project(name="hmap_anchor_missing")
    main_file = project_dir / "app" / "main.py"
    original = main_file.read_text()
    # Remove the FastAPI anchor so the tool must take the else (prepend) branch.
    stripped = original.replace("from fastapi import FastAPI", "import fastapi")
    assert "from fastapi import FastAPI" not in stripped, "fixture precondition"
    main_file.write_text(stripped)

    result = add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error

    patched = main_file.read_text()
    import_line = "from app.api.routes.health_map import router as health_map_router"
    assert import_line in patched, "health_map import missing after anchor-less patch"
    # Else branch prepends the import to the very front of the source.
    assert patched.lstrip().startswith(import_line), (
        "anchor-less patch must prepend the health_map import to the top of main.py"
    )
