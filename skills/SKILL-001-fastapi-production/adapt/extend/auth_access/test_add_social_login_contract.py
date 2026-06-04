"""Generic tool-contract mutation coverage for add_social_login.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_social_login.py in the mutation
runner: ``--tests test_add_social_login.py test_add_social_login_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_social_login import (
    _patch_models_init,
    _patch_routes_init,
    add_social_login,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_social_login, "add_social_login")


# ---------------------------------------------------------------------------
# _patch_models_init: marker placement (L182-193)
# ---------------------------------------------------------------------------


def _lines_with(content: str, needle: str) -> list[str]:
    return [ln for ln in content.splitlines() if needle in ln]


def test_models_init_marker_on_own_line_no_trailing_newline():
    """L190 UnaryNot / models patch: source WITHOUT a trailing newline must get a
    newline inserted before the marker so the import is on its own line.

    If ``not content.endswith`` is flipped, the marker concatenates onto the
    last existing line, producing a single invalid joined line.
    """
    d = Path(tempfile.mkdtemp())
    mi = d / "__init__.py"
    # Deliberately NO trailing newline on the final line.
    mi.write_text('"""Models."""\nfrom app.models.user import User  # noqa: F401')
    _patch_models_init(mi)
    content = mi.read_text()
    marker = "from app.models.social_account import SocialAccount"
    assert marker in content
    # The marker must live on its very own line — never glued to "User".
    marker_lines = _lines_with(content, marker)
    assert len(marker_lines) == 1
    assert "User" not in marker_lines[0], (
        f"marker was glued onto the previous line: {marker_lines[0]!r}"
    )
    # And the original import line must remain intact on its own line.
    assert any(
        ln.strip() == "from app.models.user import User  # noqa: F401"
        for ln in content.splitlines()
    )


def test_models_init_idempotent_no_double_import():
    """models patch: re-running must not append the marker twice."""
    d = Path(tempfile.mkdtemp())
    mi = d / "__init__.py"
    mi.write_text('"""Models."""\nfrom app.models.user import User  # noqa: F401\n')
    _patch_models_init(mi)
    once = mi.read_text()
    _patch_models_init(mi)
    twice = mi.read_text()
    assert once == twice
    marker = "from app.models.social_account import SocialAccount"
    assert len(_lines_with(twice, marker)) == 1


# ---------------------------------------------------------------------------
# auth/__init__.py creation (L120 UnaryNot / L121 exist_ok BoolLiteral)
# ---------------------------------------------------------------------------


def test_auth_init_created_when_absent():
    """L120/L121: the fixture has no app/auth/__init__.py, so the tool must
    create it (status stays 'success' and the package marker exists).

    Flipping ``not auth_init.exists()`` skips creation (file missing). Flipping
    ``exist_ok=True`` -> ``False`` raises because render_to already created the
    app/auth directory, turning the run into an error.
    """
    project_dir = create_fixture_project(name="t074_c_auth_init")
    auth_init = project_dir / "app" / "auth" / "__init__.py"
    assert not auth_init.exists()
    result = add_social_login(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    assert auth_init.exists(), "app/auth/__init__.py was not created"
    assert "Auth package" in auth_init.read_text()
    assert str(Path(auth_init).resolve()) in {str(Path(p).resolve()) for p in result.files_created}


# ---------------------------------------------------------------------------
# Migration down_revision uses the real head (L144 BoolOp Or)
# ---------------------------------------------------------------------------


def test_migration_down_revision_is_real_head():
    """L144: ``find_migration_head(...) or '0001_initial'`` must select the real
    head ('0002_baseline_schema' in the fixture), never the fallback.

    Flipping Or -> And evaluates to '0001_initial' (head is truthy), so
    down_revision would wrongly point at the fallback.
    """
    project_dir = create_fixture_project(name="t074_c_down_rev")
    result = add_social_login(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    mig = project_dir / "alembic" / "versions" / "0074_add_social_login.py"
    content = mig.read_text()
    assert 'down_revision = "0002_baseline_schema"' in content
    assert 'down_revision = "0001_initial"' not in content


# ---------------------------------------------------------------------------
# _patch_routes_init: ordering against real anchors (L226-235, L236-245)
# ---------------------------------------------------------------------------


def _bare_routes_init(text: str) -> Path:
    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text(text)
    return ri


_FULL_ROUTES = (
    '"""Route registration."""\n\n'
    "from fastapi import APIRouter\n\n"
    "from app.api.routes.item import router as item_router\n"
    "from app.api.routes.users import router as users_router\n\n"
    "api_router = APIRouter()\n"
    "api_router.include_router(item_router)\n"
    "api_router.include_router(users_router)\n\n"
    '__all__ = ["api_router"]\n'
)


def test_routes_import_inserted_after_last_app_import():
    """L233/L235 (Add) + L230 (== -1) + L232 (In/And): the import line lands
    immediately AFTER the last existing ``from app.`` import — before the
    ``api_router = APIRouter()`` anchor — not at index 0 or after the includes.
    """
    ri = _bare_routes_init(_FULL_ROUTES)
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()
    imp = "from app.api.routes.social_auth import router as social_auth_router"
    inc = "api_router.include_router(social_auth_router)"
    assert imp in lines and inc in lines
    imp_idx = lines.index(imp)
    last_app = max(i for i, ln in enumerate(lines) if ln.startswith("from app.") and ln != imp)
    apirouter_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    # Import sits right after the last pre-existing app import...
    assert imp_idx == last_app + 1
    # ...and strictly BEFORE the APIRouter() construction line.
    assert imp_idx < apirouter_idx


def test_routes_include_inserted_after_last_include():
    """L245 (Add) + L240 (== -1) + L242 (In/And): the include line lands
    immediately AFTER the last existing ``api_router.include_router`` call.
    """
    ri = _bare_routes_init(_FULL_ROUTES)
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()
    inc = "api_router.include_router(social_auth_router)"
    inc_idx = lines.index(inc)
    prev_includes = [
        i
        for i, ln in enumerate(lines)
        if ln.startswith("api_router.include_router") and i != inc_idx
    ]
    assert prev_includes, "expected pre-existing include_router calls"
    assert inc_idx == max(prev_includes) + 1


def test_routes_import_fallback_when_no_app_imports():
    """L230 (== -1 true branch) + L232 (In/And) + L233 (idx - 1, Sub): with NO
    ``from app.`` imports, the fallback inserts the import just before the
    ``api_router = APIRouter()`` line (idx-1 then +1 == idx).
    """
    ri = _bare_routes_init(
        "from fastapi import APIRouter\n\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(item_router)\n"
    )
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()
    imp = "from app.api.routes.social_auth import router as social_auth_router"
    apirouter_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    assert lines[apirouter_idx - 1] == imp, (
        f"fallback import not placed directly before APIRouter(): {lines!r}"
    )


def test_routes_include_fallback_when_no_includes():
    """L240 (== -1 true branch) + L242 (In/And): with NO existing include calls,
    the fallback inserts the include directly after ``api_router = APIRouter()``.
    """
    ri = _bare_routes_init("from fastapi import APIRouter\n\napi_router = APIRouter()\n")
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()
    inc = "api_router.include_router(social_auth_router)"
    apirouter_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    assert lines[apirouter_idx + 1] == inc, (
        f"fallback include not placed right after APIRouter(): {lines!r}"
    )


def test_routes_patch_idempotent():
    """_patch_routes_init guard (import_line in src) must no-op on a second run."""
    ri = _bare_routes_init(_FULL_ROUTES)
    _patch_routes_init(ri)
    once = ri.read_text()
    _patch_routes_init(ri)
    assert ri.read_text() == once
    imp = "from app.api.routes.social_auth import router as social_auth_router"
    assert once.count(imp) == 1
    assert once.count("api_router.include_router(social_auth_router)") == 1
