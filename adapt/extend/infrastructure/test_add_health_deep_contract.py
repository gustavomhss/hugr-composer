"""Generic tool-contract mutation coverage for add_health_deep.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_health_deep.py in the mutation
runner: ``--tests test_add_health_deep.py test_add_health_deep_contract.py``.
"""

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_health_deep import add_health_deep
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_health_deep, "add_health_deep")


# ---------------------------------------------------------------------------
# Tool-specific mutation kills (main.py router wiring)
# ---------------------------------------------------------------------------


def test_health_import_inserted_after_fastapi_import() -> None:
    """L233 (Compare In->NotIn): when ``from fastapi import FastAPI`` is
    present, the deep-health import must be inserted *immediately after* that
    line — never prepended at the top of the module.

    The In->NotIn flip would take the else branch and prepend the import at
    file position 0 (before the module docstring). Assert the ordering.
    """
    project = create_fixture_project(name="health_ctr_anchor")
    result = add_health_deep(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error

    main_src = (project / "app" / "main.py").read_text()
    fastapi_pos = main_src.find("from fastapi import FastAPI")
    health_pos = main_src.find(
        "from app.api.routes.health_deep import router as health_deep_router"
    )
    assert fastapi_pos >= 0, "fixture main.py must contain the FastAPI import anchor"
    assert health_pos >= 0, "deep-health import must be present in main.py"
    # The In->NotIn flip prepends at position 0; the correct branch inserts after.
    assert health_pos > fastapi_pos, (
        "deep-health import must follow the FastAPI import anchor, not precede it"
    )
    assert not main_src.lstrip().startswith("from app.api.routes.health_deep import"), (
        "import must NOT be prepended at the top of the module"
    )
    # Idempotent: a second run must not duplicate the import (the In->NotIn
    # flip also breaks the 'health_deep' guard path indirectly).
    assert main_src.count("import router as health_deep_router") == 1


def test_health_import_prepended_when_no_fastapi_anchor() -> None:
    """L239 (BinOp Add->Sub): when main.py has *no* ``from fastapi import
    FastAPI`` line, the tool falls into the else branch and computes
    ``health_import + src`` to prepend the import. The Add->Sub flip turns
    this into ``str - str`` which raises TypeError -> the tool would NOT
    succeed and the import would be missing.
    """
    project = create_fixture_project(name="health_ctr_noanchor")
    main_file = project / "app" / "main.py"
    # Rewrite main.py so the FastAPI import anchor is absent, forcing the
    # else branch where Add->Sub is observable.
    main_file.write_text('"""app main"""\nimport fastapi\n\napp = fastapi.FastAPI()\n')

    result = add_health_deep(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error

    main_src = main_file.read_text()
    health_import = "from app.api.routes.health_deep import router as health_deep_router"
    # The Add->Sub flip raises TypeError before write -> import absent.
    assert health_import in main_src, "deep-health import must be prepended"
    # Prepend means the import precedes the original module docstring.
    assert main_src.index(health_import) < main_src.index('"""app main"""'), (
        "import must be prepended ahead of the original module body"
    )
    # The include_router snippet is still appended at the end.
    assert main_src.rstrip().endswith("app.include_router(health_deep_router)")
