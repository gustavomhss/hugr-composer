"""Generic tool-contract mutation coverage for add_passkey_auth.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_passkey_auth.py in the mutation
runner: ``--tests test_add_passkey_auth.py test_add_passkey_auth_contract.py``.

Tool-specific tests appended below target the bespoke insertion / patching
logic in ``_patch_models_init`` and ``_patch_routes_init`` (import / include
ordering, fallback branches when the routes file has no ``from app.`` imports,
and the auth-package bootstrap), which the generic preamble checks do not
exercise.
"""

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_passkey_auth import add_passkey_auth
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_passkey_auth, "add_passkey_auth")


# ---------------------------------------------------------------------------
# _non_empty: helper to drop blank lines for ordering assertions
# ---------------------------------------------------------------------------


def _idx(lines: list[str], needle: str) -> int:
    for i, ln in enumerate(lines):
        if needle in ln:
            return i
    raise AssertionError(f"{needle!r} not found in:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# L130 UnaryNot (`if not auth_init.exists()`) + L131 (`exist_ok=True`)
# The fixture has NO app/auth/__init__.py, so the branch MUST fire: the file
# is created and reported. Flipping `not` skips creation; the assertions fail.
# ---------------------------------------------------------------------------


def test_auth_package_init_created():
    project = create_fixture_project(name="pk_auth_init")
    auth_init = project / "app" / "auth" / "__init__.py"
    assert not auth_init.exists(), "fixture precondition: auth/__init__.py absent"

    result = add_passkey_auth(ToolInput(project_dir=str(project)))

    assert result.status == "success"
    assert auth_init.exists(), "auth/__init__.py must be bootstrapped when absent"
    assert str(Path(auth_init).resolve()) in {str(Path(p).resolve()) for p in result.files_created}
    assert "Auth package" in auth_init.read_text()


# ---------------------------------------------------------------------------
# L204 UnaryNot (`if not content.endswith("\\n")`) in _patch_models_init.
# The fixture models/__init__.py ends with a newline, so the guard must NOT
# add an extra one: the Passkey import sits directly under the last existing
# import with no intervening blank line. Flipping `not` injects a blank line.
# ---------------------------------------------------------------------------


def test_models_init_no_blank_line_before_passkey_import():
    project = create_fixture_project(name="pk_models_nl")
    add_passkey_auth(ToolInput(project_dir=str(project)))

    models_init = project / "app" / "models" / "__init__.py"
    text = models_init.read_text()
    assert "from app.models.passkey import Passkey" in text
    # No double newline anywhere (no blank line introduced by the guard).
    assert "\n\nfrom app.models.passkey import Passkey" not in text, (
        "passkey import must follow the previous import with no blank line"
    )
    lines = text.splitlines()
    passkey_idx = _idx(lines, "from app.models.passkey import Passkey")
    assert lines[passkey_idx - 1].strip() != "", "line above the passkey import must not be blank"


# ---------------------------------------------------------------------------
# L227 BinOp Add->Sub: import inserted at `last_app_import_idx + 1`, i.e.
# directly AFTER the last `from app.` import. Flip to `- 1` moves it before.
# Also covers L222 (== -1 stays False with real app imports present).
# ---------------------------------------------------------------------------


def test_routes_import_inserted_after_last_app_import():
    project = create_fixture_project(name="pk_routes_imp")
    add_passkey_auth(ToolInput(project_dir=str(project)))

    routes_init = project / "app" / "routes" / "__init__.py"
    lines = routes_init.read_text().splitlines()

    import_idx = _idx(lines, "from app.api.routes.passkeys import router as passkeys_router")
    # Every preceding `from app.` import must come before the new one, and the
    # line immediately above the new import is itself a `from app.` import
    # (proves insertion at last_app_import_idx + 1, not + 0 or - 1).
    assert lines[import_idx - 1].startswith("from app."), (
        f"passkeys import must land right after the last app import, "
        f"prev line was {lines[import_idx - 1]!r}"
    )
    for after in lines[import_idx + 1 :]:
        assert not after.startswith("from app.routes.health"), (
            "new import must come after the last pre-existing app import"
        )


# ---------------------------------------------------------------------------
# L237 BinOp Add->Sub: include inserted at `last_include_idx + 1`, directly
# AFTER the last existing include_router call. Flip to `- 1` moves it before.
# Also covers L232 (== -1 stays False when includes already present).
# ---------------------------------------------------------------------------


def test_routes_include_inserted_after_last_include():
    project = create_fixture_project(name="pk_routes_inc")
    add_passkey_auth(ToolInput(project_dir=str(project)))

    routes_init = project / "app" / "routes" / "__init__.py"
    lines = routes_init.read_text().splitlines()

    inc_idx = _idx(lines, "api_router.include_router(passkeys_router)")
    assert lines[inc_idx - 1].startswith("api_router.include_router("), (
        f"passkeys include must land right after the last include, "
        f"prev line was {lines[inc_idx - 1]!r}"
    )
    # The new include must come after the api_router = APIRouter() definition.
    def_idx = _idx(lines, "api_router = APIRouter()")
    assert inc_idx > def_idx, "include must follow the api_router definition"


# ---------------------------------------------------------------------------
# Fallback branch: routes/__init__.py with NO `from app.` imports and NO
# existing include_router calls. Exercises:
#   L222 (== -1 True -> fallback runs)
#   L224 (`"api_router" in line and "APIRouter()" in line` selects the def)
#   L225 (`idx - 1` then +1 -> import inserted JUST BEFORE the def line)
#   L232 (== -1 True -> include fallback runs)
#   L234 (same anchor match for include)
# Flips break the anchor match or the insertion position; we assert exact
# placement of both the import (immediately above the def) and the include
# (immediately below the def).
# ---------------------------------------------------------------------------


def _bare_routes_init() -> str:
    return (
        '"""Route registration."""\n'
        "\n"
        "from fastapi import APIRouter\n"
        "\n"
        "api_router = APIRouter()\n"
        "\n"
        '__all__ = ["api_router"]\n'
    )


def test_routes_fallback_no_app_imports():
    project = create_fixture_project(name="pk_routes_fb")
    routes_init = project / "app" / "routes" / "__init__.py"
    routes_init.write_text(_bare_routes_init())

    result = add_passkey_auth(ToolInput(project_dir=str(project)))
    assert result.status == "success"

    lines = routes_init.read_text().splitlines()
    def_idx = _idx(lines, "api_router = APIRouter()")
    import_idx = _idx(lines, "from app.api.routes.passkeys import router as passkeys_router")
    inc_idx = _idx(lines, "api_router.include_router(passkeys_router)")

    # Import lands immediately BEFORE the api_router definition (idx - 1, then
    # +1). Not at the very top (would mean L222 flip) and not after the def.
    assert import_idx == def_idx - 1, (
        f"fallback import must sit directly above the def (import={import_idx}, def={def_idx})"
    )
    # Include lands immediately AFTER the def (fallback include path).
    assert inc_idx == def_idx + 1, (
        f"fallback include must sit directly below the def (include={inc_idx}, def={def_idx})"
    )
    # Import must NOT be the first line (guards L222 flip -> insert at 0).
    assert import_idx != 0


# ---------------------------------------------------------------------------
# Idempotency of the routes patch: the import marker guards against a double
# insert (L215 `if import_line in src: return`). A second run is a model-level
# no_op, but assert the routes file was not double-patched on the first pass.
# ---------------------------------------------------------------------------


def test_routes_patch_single_insert():
    project = create_fixture_project(name="pk_routes_single")
    add_passkey_auth(ToolInput(project_dir=str(project)))

    text = (project / "app" / "routes" / "__init__.py").read_text()
    assert text.count("from app.api.routes.passkeys import router as passkeys_router") == 1
    assert text.count("api_router.include_router(passkeys_router)") == 1
