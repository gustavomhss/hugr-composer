"""Generic tool-contract mutation coverage for add_api_key_auth.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_api_key_auth.py in the mutation
runner: ``--tests test_add_api_key_auth.py test_add_api_key_auth_contract.py``.

Below the generic check we add TOOL-SPECIFIC tests that pin the bespoke
logic of the two patchers (``_patch_models_init`` / ``_patch_routes_init``)
and the migration down-revision wiring, killing the survivors that the
generic preamble contract cannot reach.
"""

import ast

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_api_key_auth import add_api_key_auth
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_api_key_auth import add_api_key_auth

    for check in SCAFFOLDABLE_CHECKS:
        check(add_api_key_auth, "add_api_key_auth")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(name: str):
    project_dir = create_fixture_project(name=name)
    result = add_api_key_auth(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"setup run failed: {result.status}: {result.error}"
    return project_dir


def _models_init(project_dir):
    return project_dir / "app" / "models" / "__init__.py"


def _routes_init(project_dir):
    return project_dir / "app" / "routes" / "__init__.py"


_MODEL_MARKER = "from app.models.api_key import APIKey"
_IMPORT_LINE = "from app.api.routes.api_keys import router as api_keys_router"
_INCLUDE_LINE = "api_router.include_router(api_keys_router)"


# ---------------------------------------------------------------------------
# _patch_models_init — L199 / L203 / L205
# ---------------------------------------------------------------------------


def test_models_init_gets_apikey_import() -> None:
    """L199 (UnaryNot on `not models_init.exists()`): the existing models
    __init__.py must actually receive the APIKey import. Flipping the guard
    returns early and the marker is never appended.
    """
    project_dir = _run("t010_c_models_import")
    content = _models_init(project_dir).read_text()
    assert _MODEL_MARKER in content, "models/__init__.py must import APIKey after run"
    # It must be a real import statement (own line starting with the marker),
    # not glued onto a previous line / swallowed by a comment.
    lines = content.splitlines()
    assert any(ln.startswith(_MODEL_MARKER) for ln in lines), (
        "APIKey import must be its own standalone import line"
    )
    # And the emitted module must still parse.
    ast.parse(content)


def test_models_init_apikey_import_not_duplicated() -> None:
    """L203 (Compare In->NotIn on `if marker in content`): the dedup guard.
    Running twice must leave exactly one APIKey import line. Flipping the
    membership test would re-append on the second run (or skip on the first).
    """
    project_dir = create_fixture_project(name="t010_c_models_dedup")
    add_api_key_auth(ToolInput(project_dir=str(project_dir)))
    add_api_key_auth(ToolInput(project_dir=str(project_dir)))
    content = _models_init(project_dir).read_text()
    assert content.count(_MODEL_MARKER) == 1, (
        "APIKey import must appear exactly once after two runs (idempotent dedup)"
    )


def test_models_init_marker_on_its_own_line_no_blank_gap() -> None:
    """L205 (UnaryNot on `not content.endswith(chr(10))`): newline hygiene.

    The fixture models __init__.py already ends with a newline, so the
    original guard is False and NO extra blank line is inserted: the APIKey
    import line immediately follows the previous import. Flipping the guard
    injects a spurious blank line before the marker.
    """
    project_dir = _run("t010_c_models_newline")
    lines = _models_init(project_dir).read_text().splitlines()
    marker_idx = next(i for i, ln in enumerate(lines) if ln.startswith(_MODEL_MARKER))
    prev = lines[marker_idx - 1]
    assert prev.strip() != "", (
        "APIKey import must follow the previous import with no blank-line gap"
    )
    assert prev.startswith("from app.models."), (
        "APIKey import must directly follow the last existing model import"
    )


# ---------------------------------------------------------------------------
# _patch_routes_init — main path: L216 / L223 / L228 / L233 / L238
# ---------------------------------------------------------------------------


def test_routes_init_import_after_last_app_import() -> None:
    """L223 (Eq->NotEq on `last_app_import_idx == -1`) + L228 (Add->Sub on the
    insert index). On the real fixture there ARE `from app.` imports, so the
    tool inserts the api_keys import RIGHT AFTER the last existing `from app.`
    import and BEFORE the `api_router = APIRouter()` definition.

    - Eq->NotEq would wrongly enter the no-imports fallback and reposition.
    - Add->Sub would insert one slot too early (before the last app import).
    """
    project_dir = _run("t010_c_routes_import_pos")
    lines = _routes_init(project_dir).read_text().splitlines()
    imp_idx = lines.index(_IMPORT_LINE)
    # The line directly above must be an existing `from app.` import.
    assert lines[imp_idx - 1].startswith("from app."), (
        "api_keys import must land immediately after the last existing app import"
    )
    # And it must sit before the api_router definition line.
    router_def_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    assert imp_idx < router_def_idx, "import must precede the api_router definition"
    # No `from app.` import may appear after the new import (it's the last one).
    assert not any(ln.startswith("from app.") for ln in lines[imp_idx + 1 :]), (
        "api_keys import must be the final app import (Add->Sub would break this)"
    )


def test_routes_init_include_after_last_include() -> None:
    """L233 (Eq->NotEq on `last_include_idx == -1`) + L238 (Add->Sub on the
    insert index). The include call must land RIGHT AFTER the last existing
    `api_router.include_router(...)` call.

    - Eq->NotEq would enter the no-includes fallback and reposition the call.
    - Add->Sub would insert it before the last existing include.
    """
    project_dir = _run("t010_c_routes_include_pos")
    lines = _routes_init(project_dir).read_text().splitlines()
    inc_idx = lines.index(_INCLUDE_LINE)
    assert lines[inc_idx - 1].startswith("api_router.include_router("), (
        "api_keys include must land immediately after the last existing include"
    )
    assert not any(ln.startswith("api_router.include_router(") for ln in lines[inc_idx + 1 :]), (
        "api_keys include must be the final include call (Add->Sub would break this)"
    )


def test_routes_init_idempotent_no_double_wire() -> None:
    """L216 (Compare In->NotIn on `if import_line in src`): the dedup guard.
    Two runs must leave exactly one import line and one include line. Flipping
    the membership test re-wires on the second run (or skips on the first).
    """
    project_dir = create_fixture_project(name="t010_c_routes_dedup")
    add_api_key_auth(ToolInput(project_dir=str(project_dir)))
    add_api_key_auth(ToolInput(project_dir=str(project_dir)))
    content = _routes_init(project_dir).read_text()
    assert content.count(_IMPORT_LINE) == 1, "import line must appear exactly once"
    assert content.count(_INCLUDE_LINE) == 1, "include line must appear exactly once"
    ast.parse(content)


# ---------------------------------------------------------------------------
# _patch_routes_init — fallback path (no `from app.` imports):
# L225 / L226 / L235
# ---------------------------------------------------------------------------

_FALLBACK_IMPORT_INIT = (
    '"""Route registration."""\n'
    "\n"
    "from fastapi import APIRouter\n"
    "\n"
    "api_router = APIRouter()\n"
    "api_router.include_router\n"
)

_FALLBACK_FULL_INIT = (
    '"""Route registration."""\n\nfrom fastapi import APIRouter\n\napi_router = APIRouter()\n'
)


def test_routes_init_import_fallback_anchors_on_router_def() -> None:
    """L225 (BoolOp And->Or / Compare In->NotIn) + L226 (BinOp Sub->Add) in the
    no-`from app.` import fallback.

    With no `from app.` imports the tool must anchor the import on the
    `api_router = APIRouter()` line, inserting the import directly BEFORE it.

    - In->NotIn / And->Or never matches the anchor -> import lands at line 0.
    - Sub->Add (idx-1 -> idx+1) shifts the import to the end of the file.
    """
    project_dir = create_fixture_project(name="t010_c_routes_fallback_import")
    routes_init = _routes_init(project_dir)
    routes_init.write_text(_FALLBACK_IMPORT_INIT)
    result = add_api_key_auth(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    lines = routes_init.read_text().splitlines()
    imp_idx = lines.index(_IMPORT_LINE)
    router_def_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    # Import must sit immediately before the router definition.
    assert imp_idx == router_def_idx - 1, (
        "fallback import must anchor directly above `api_router = APIRouter()`"
    )
    # Not at the top of the file (that's the In->NotIn / And->Or failure mode).
    assert imp_idx != 0, "fallback import must not be inserted at file top"
    ast.parse(routes_init.read_text())


def test_routes_init_include_fallback_anchors_on_router_def() -> None:
    """L235 (BoolOp And->Or / Compare In->NotIn) in the no-include fallback.

    With no existing `api_router.include_router(...)` call the tool must
    anchor the include on the `api_router = APIRouter()` line and insert the
    include directly AFTER it. A broken match would dump the include at the
    file top instead.
    """
    project_dir = create_fixture_project(name="t010_c_routes_fallback_include")
    routes_init = _routes_init(project_dir)
    routes_init.write_text(_FALLBACK_FULL_INIT)
    result = add_api_key_auth(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    lines = routes_init.read_text().splitlines()
    inc_idx = lines.index(_INCLUDE_LINE)
    router_def_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    # Include must sit immediately after the router definition.
    assert inc_idx == router_def_idx + 1, (
        "fallback include must anchor directly below `api_router = APIRouter()`"
    )
    assert inc_idx != 0, "fallback include must not be inserted at file top"
    ast.parse(routes_init.read_text())


# ---------------------------------------------------------------------------
# Migration down-revision — L164
# ---------------------------------------------------------------------------


def test_migration_down_revision_is_real_head_not_fallback() -> None:
    """L164 (BoolOp Or->And on `find_migration_head(...) or "0001_initial"`).

    The fixture has a real migration head (`0002_baseline_schema`). The
    emitted migration's down_revision must reference that real head. Flipping
    Or->And evaluates `head and "0001_initial"` -> "0001_initial", chaining
    the new migration onto the wrong (stale) revision.
    """
    project_dir = _run("t010_c_migration_downrev")
    mig = project_dir / "alembic" / "versions" / "0010_add_api_key_auth.py"
    content = mig.read_text()
    assert 'down_revision = "0002_baseline_schema"' in content, (
        "migration must chain onto the real head, not the fallback revision"
    )
    assert '"0001_initial"' not in content, (
        "Or->And mutant would substitute the fallback revision 0001_initial"
    )
