"""Generic tool-contract mutation coverage for add_api_deprecation.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_api_deprecation.py in the mutation
runner: ``--tests test_add_api_deprecation.py test_add_api_deprecation_contract.py``.

The ``test_*`` functions below the generic check target the tool-specific
survivors in ``_patch_main`` / ``_patch_routes_init`` and the scaffolded-files
merge — logic the shared contract suite does not exercise.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_api_deprecation import (
    _patch_main,
    _patch_routes_init,
    add_api_deprecation,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.api_design.add_api_deprecation import add_api_deprecation

    for check in SCAFFOLDABLE_CHECKS:
        check(add_api_deprecation, "add_api_deprecation")


# ---------------------------------------------------------------------------
# L114 — files_created = list(scaffolded or [])  [BoolOp Or -> And]
# When prerequisites are missing the tool auto-scaffolds them; those scaffolded
# paths MUST be merged into files_created. The And-mutant collapses the list to
# [] and the scaffolded prereqs vanish from the report.
# ---------------------------------------------------------------------------


def test_scaffolded_prereqs_merged_into_files_created():
    bare = Path(tempfile.mkdtemp())
    (bare / "app").mkdir()
    result = add_api_deprecation(ToolInput(project_dir=str(bare)))
    assert result.status == "success", result.error
    # config.py + routes/__init__.py are scaffolded by the prereq step (they did
    # not exist in the bare project). Both must surface in files_created.
    assert any(f.endswith("core/config.py") for f in result.files_created), (
        f"scaffolded config.py absent from files_created: {result.files_created}"
    )
    assert any(f.endswith("routes/__init__.py") for f in result.files_created), (
        f"scaffolded routes/__init__.py absent from files_created: {result.files_created}"
    )


# ---------------------------------------------------------------------------
# _patch_main: L216 / L217 / L220 / L221 / L229 / L232
# Drive the full tool against a real fixture (which ships app/main.py) and assert
# the middleware import + registration actually land, that main.py is reported as
# modified, and that everything is inserted exactly once.
# ---------------------------------------------------------------------------


def test_main_patched_with_middleware_and_reported():
    project = create_fixture_project(name="depr_main_patch")
    main_path = project / "app" / "main.py"
    result = add_api_deprecation(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error

    # L232 (return True) + the files_modified append: main.py must be reported.
    assert str(main_path) in result.files_modified, (
        f"main.py not reported as modified: {result.files_modified}"
    )

    content = main_path.read_text()
    import_line = "from app.deprecation.middleware import DeprecationMiddleware"
    add_line = "app.add_middleware(DeprecationMiddleware)"

    # L216/L217 (DeprecationMiddleware guard) + L220/L221 (import guard): if any
    # guard short-circuits to return False on the fresh file, the import would
    # never be written. So the import MUST be present.
    assert import_line in content, "DeprecationMiddleware import not injected"
    # L229 (And + 'app = FastAPI' in / add_line not in): the registration line
    # is only appended when both halves hold. It must be present.
    assert add_line in content, "DeprecationMiddleware not registered (add_middleware)"


def test_main_patch_inserts_exactly_once():
    # L216/L220 guards prevent duplicate injection. Call _patch_main twice on the
    # same file: the second call must be a no-op (returns False, no second copy).
    project = create_fixture_project(name="depr_main_once")
    main_path = project / "app" / "main.py"
    first = _patch_main(main_path)
    assert first is True, "first _patch_main should report a modification (L232)"
    second = _patch_main(main_path)
    assert second is False, "second _patch_main must be a no-op (L217/L221)"

    content = main_path.read_text()
    assert content.count("from app.deprecation.middleware import DeprecationMiddleware") == 1, (
        "import line duplicated — idempotency guard failed"
    )
    assert content.count("app.add_middleware(DeprecationMiddleware)") == 1, (
        "add_middleware line duplicated — registration guard failed"
    )


# ---------------------------------------------------------------------------
# _patch_main: L225 (startswith from/import) + L226 (insert_idx = i + 1)
# The middleware import must be inserted *after* the last existing import line,
# never at the top of the module. Use a bare main.py with a known import block.
# ---------------------------------------------------------------------------


def test_main_import_inserted_after_last_import():
    src = (
        '"""entry."""\n'
        "from fastapi import FastAPI\n"
        "from app.core.config import settings\n"
        "\n"
        "app = FastAPI(title=settings.TITLE)\n"
    )
    main_path = Path(tempfile.mkdtemp()) / "main.py"
    main_path.write_text(src)
    assert _patch_main(main_path) is True

    lines = main_path.read_text().splitlines()
    import_line = "from app.deprecation.middleware import DeprecationMiddleware"
    idx = lines.index(import_line)

    # L225 Or->And would never match a real import line -> insert_idx stays 0 ->
    # the new import lands at the very top (idx == 0). Assert it does not.
    assert idx > 0, "middleware import wrongly inserted at top of module"
    # L226 Add->Sub (i-1) would place the import before the last import line.
    # The line directly preceding it must be the last original import.
    assert lines[idx - 1] == "from app.core.config import settings", (
        f"import not placed immediately after last import; preceding line={lines[idx - 1]!r}"
    )


def test_main_add_middleware_appended_after_app_definition():
    # L229: registration only happens when 'app = FastAPI' is present in the
    # module. The add_middleware call must appear after the app definition.
    src = '"""entry."""\nfrom fastapi import FastAPI\n\napp = FastAPI()\n'
    main_path = Path(tempfile.mkdtemp()) / "main.py"
    main_path.write_text(src)
    assert _patch_main(main_path) is True
    content = main_path.read_text()
    app_pos = content.index("app = FastAPI()")
    add_pos = content.index("app.add_middleware(DeprecationMiddleware)")
    assert add_pos > app_pos, "add_middleware must be appended after the app definition"


def test_main_not_patched_without_app_definition():
    # L229 (the 'app = FastAPI' in new_content half): when no FastAPI app is
    # defined, the registration line must NOT be appended (only the import).
    src = '"""helpers."""\nfrom fastapi import APIRouter\n\nrouter = APIRouter()\n'
    main_path = Path(tempfile.mkdtemp()) / "main.py"
    main_path.write_text(src)
    assert _patch_main(main_path) is True
    content = main_path.read_text()
    assert "from app.deprecation.middleware import DeprecationMiddleware" in content
    assert "app.add_middleware(DeprecationMiddleware)" not in content, (
        "add_middleware appended despite no 'app = FastAPI' definition"
    )


# ---------------------------------------------------------------------------
# _patch_routes_init: L207  (if not content.endswith("\n"))
# When the existing file has no trailing newline, a separating blank line must
# be inserted before the appended import block. The UnaryNot-mutant skips it and
# glues the import onto the last content line.
# ---------------------------------------------------------------------------


def test_routes_init_no_trailing_newline_gets_blank_separator():
    routes_init = Path(tempfile.mkdtemp()) / "__init__.py"
    routes_init.write_text("api_router = APIRouter()")  # no trailing newline
    _patch_routes_init(routes_init)
    content = routes_init.read_text()
    # Original guarantees a blank line between old content and the new block.
    assert "APIRouter()\n\nfrom app.api.routes.deprecation" in content, (
        f"missing blank-line separator before appended import: {content!r}"
    )


def test_routes_init_idempotent_no_double_register():
    routes_init = Path(tempfile.mkdtemp()) / "__init__.py"
    routes_init.write_text("api_router = APIRouter()\n")
    _patch_routes_init(routes_init)
    _patch_routes_init(routes_init)
    content = routes_init.read_text()
    assert content.count("import router as deprecation_router") == 1, (
        "deprecation router registered twice — idempotency guard failed"
    )
