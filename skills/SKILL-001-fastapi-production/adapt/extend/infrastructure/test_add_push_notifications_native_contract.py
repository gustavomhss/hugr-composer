"""Generic tool-contract mutation coverage for add_push_notifications_native.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_push_notifications_native.py in the mutation
runner: ``--tests test_add_push_notifications_native.py test_add_push_notifications_native_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_push_notifications_native import (
    _patch_config,
    _patch_models_init,
    _patch_routes_init,
    add_push_notifications_native,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_push_notifications_native import (
        add_push_notifications_native,
    )

    for check in SCAFFOLDABLE_CHECKS:
        check(add_push_notifications_native, "add_push_notifications_native")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _line_index(lines: list[str], needle: str) -> int:
    """Return the index of the first line containing *needle* (-1 if absent)."""
    for idx, line in enumerate(lines):
        if needle in line:
            return idx
    return -1


# ---------------------------------------------------------------------------
# config.py patch — anchor branch (L207 In->NotIn, L208) — driven via full tool.
# The fixture config carries `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`, so the
# push block MUST land immediately after that anchor line and BEFORE
# `settings = Settings()`. Flipping `in`->`not in` skips this branch and the
# block lands before the settings line instead -> different position.
# ---------------------------------------------------------------------------


def test_config_block_lands_directly_after_anchor():
    project = create_fixture_project(name="push_cfg_anchor")
    add_push_notifications_native(ToolInput(project_dir=str(project)))
    lines = (project / "app" / "core" / "config.py").read_text().splitlines()

    anchor_idx = _line_index(lines, "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30")
    fcm_idx = _line_index(lines, "FCM_CREDENTIALS_PATH")
    settings_idx = _line_index(lines, "settings = Settings()")

    assert anchor_idx != -1, "anchor line missing from fixture config"
    assert fcm_idx != -1, "push block not injected"
    # The block (comment then FCM line) starts right after the anchor: the
    # comment is anchor+1 and the FCM field is anchor+2.
    assert fcm_idx == anchor_idx + 2, (
        f"FCM field expected at anchor+2 ({anchor_idx + 2}), got {fcm_idx}"
    )
    assert "Push notifications" in lines[anchor_idx + 1], (
        "push comment block not immediately after the anchor line"
    )
    # And it must precede the settings instantiation (anchor branch, not the
    # settings_line fallback which would place it just before settings).
    assert settings_idx == -1 or fcm_idx < settings_idx, (
        "push block must come before `settings = Settings()`"
    )


# ---------------------------------------------------------------------------
# config.py patch — settings_line fallback (L211 In->NotIn, L212 Add->Sub).
# No anchor present but `settings = Settings()` is -> block injected directly
# before the settings instantiation. Driven via the helper for determinism.
# ---------------------------------------------------------------------------


def test_config_fallback_inserts_before_settings_line():
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text(
        'class Settings(BaseSettings):\n    PROJECT_NAME: str = "app"\n\n\nsettings = Settings()\n'
    )
    _patch_config(cfg)
    lines = cfg.read_text().splitlines()

    fcm_idx = _line_index(lines, "FCM_CREDENTIALS_PATH")
    settings_idx = _line_index(lines, "settings = Settings()")

    assert fcm_idx != -1, "push block not injected in settings_line fallback"
    assert settings_idx != -1, "settings line vanished"
    # L211 In->NotIn would skip this branch and append at EOF (after settings);
    # the correct behaviour places the block strictly before the settings line.
    assert fcm_idx < settings_idx, "push block must be injected before `settings = Settings()`"
    # L212 Add->Sub on the replacement string would raise TypeError; reaching
    # here at all means the `+` concatenation executed.
    assert "settings = Settings()" in cfg.read_text()


# ---------------------------------------------------------------------------
# config.py patch — EOF fallback (L214 Add->Sub). No anchor, no settings line
# -> block appended at end of file via `src.rstrip(...) + "\n" + block`.
# Add->Sub would raise TypeError on the string concat.
# ---------------------------------------------------------------------------


def test_config_eof_fallback_appends_block():
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text('class Settings(BaseSettings):\n    PROJECT_NAME: str = "app"\n')
    _patch_config(cfg)
    text = cfg.read_text()

    assert "FCM_CREDENTIALS_PATH" in text, "push block not appended at EOF"
    lines = text.splitlines()
    # Block must come AFTER the existing PROJECT_NAME content (appended).
    assert _line_index(lines, "PROJECT_NAME") < _line_index(lines, "FCM_CREDENTIALS_PATH")
    # Exactly one separating blank-collapse: no anchor / settings line present.
    assert "settings = Settings()" not in text


# ---------------------------------------------------------------------------
# models/__init__.py patch — trailing-newline guard (L185 UnaryNot not X -> X).
# A file WITHOUT a trailing newline must have `\n` prepended before the marker
# so the import lands on its own line. Flipping `not` would concatenate the
# marker onto the last existing line.
# ---------------------------------------------------------------------------


def test_models_init_no_trailing_newline_gets_own_line():
    d = Path(tempfile.mkdtemp())
    mi = d / "__init__.py"
    # Deliberately NO trailing newline.
    mi.write_text("from app.models.user import User  # noqa: F401")
    _patch_models_init(mi)
    lines = mi.read_text().splitlines()

    user_idx = _line_index(lines, "import User")
    marker_idx = _line_index(lines, "from app.models.device_token import DeviceToken")
    assert user_idx != -1, "pre-existing User import lost"
    assert marker_idx != -1, "DeviceToken marker not added"
    # The marker must be on its OWN line, not concatenated onto the User import.
    assert marker_idx != user_idx, (
        "DeviceToken import was concatenated onto the previous line (missing newline separation)"
    )
    assert "User" not in lines[marker_idx], "marker line is fused with the previous import"


def test_models_init_idempotent_no_double_insert():
    d = Path(tempfile.mkdtemp())
    mi = d / "__init__.py"
    mi.write_text("from app.models.user import User  # noqa: F401\n")
    _patch_models_init(mi)
    _patch_models_init(mi)
    text = mi.read_text()
    assert text.count("from app.models.device_token import DeviceToken") == 1, (
        "DeviceToken import inserted more than once"
    )


# ---------------------------------------------------------------------------
# alembic migration — head selection (L117 BoolOp Or->And).
# `find_migration_head(...) or "0001_initial"`. The fixture head is
# `0002_baseline_schema` (NOT the fallback). Or->And would discard the real
# head and emit the fallback string as down_revision.
# ---------------------------------------------------------------------------


def test_migration_chains_off_real_head_not_fallback():
    project = create_fixture_project(name="push_mig_head")
    add_push_notifications_native(ToolInput(project_dir=str(project)))
    mig = project / "alembic" / "versions" / "add_device_tokens.py"
    assert mig.exists(), "migration file not created"
    text = mig.read_text()
    assert "0002_baseline_schema" in text, (
        "migration must chain off the real head (0002_baseline_schema), not the hard-coded fallback"
    )
    assert 'down_revision = "0001_initial"' not in text, (
        "migration fell back to 0001_initial despite a real head being present"
    )


# ---------------------------------------------------------------------------
# routes/__init__.py — primary path ordering
# (L231 Eq->NotEq, L236 Add->Sub, L242 Eq->NotEq, L247 Add->Sub).
# Fixture has `from app.` imports AND existing include_router lines, so both
# primary branches fire. The push import must land immediately after the LAST
# `from app.` import; the push include immediately after the LAST existing
# include.
# ---------------------------------------------------------------------------


def test_routes_primary_import_after_last_app_import():
    project = create_fixture_project(name="push_routes_primary")
    add_push_notifications_native(ToolInput(project_dir=str(project)))
    routes_init = project / "app" / "routes" / "__init__.py"
    lines = routes_init.read_text().splitlines()

    health_idx = _line_index(lines, "from app.routes.health import")
    push_import_idx = _line_index(lines, "from app.api.routes.push import")
    router_def_idx = _line_index(lines, "api_router = APIRouter()")

    assert health_idx != -1 and push_import_idx != -1
    # L236 Add->Sub moves the import earlier; L231 NotEq re-runs the fallback
    # and lands it just before APIRouter(). Correct: directly after the last
    # `from app.` import (the health import) and BEFORE the router definition.
    assert push_import_idx == health_idx + 1, (
        f"push import expected right after last app import "
        f"(idx {health_idx + 1}), got {push_import_idx}"
    )
    assert push_import_idx < router_def_idx, "push import must precede api_router = APIRouter()"


def test_routes_primary_include_after_last_include():
    project = create_fixture_project(name="push_routes_inc")
    add_push_notifications_native(ToolInput(project_dir=str(project)))
    routes_init = project / "app" / "routes" / "__init__.py"
    lines = routes_init.read_text().splitlines()

    item_inc_idx = _line_index(lines, "api_router.include_router(item_router)")
    push_inc_idx = _line_index(lines, "api_router.include_router(push_router)")

    assert item_inc_idx != -1, "fixture item include missing"
    assert push_inc_idx != -1, "push include not added"
    # L247 Add->Sub would land it before the last existing include; L242 NotEq
    # would re-run the fallback. Correct: right after the last include.
    assert push_inc_idx == item_inc_idx + 1, (
        f"push include expected right after last include (idx {item_inc_idx + 1}), "
        f"got {push_inc_idx}"
    )


# ---------------------------------------------------------------------------
# routes/__init__.py — import fallback (L233 And->Or & In->NotIn, L234 Sub->Add).
# No `from app.` imports -> last_app_import stays -1 -> fallback loop finds the
# `api_router = APIRouter()` line and inserts the import directly before it.
# A comment that mentions `api_router` (but not `APIRouter()`) precedes the def
# so And->Or / In->NotIn would match the WRONG line.
# ---------------------------------------------------------------------------


def test_routes_import_fallback_lands_before_router_def():
    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text(
        "from fastapi import APIRouter\n"
        "\n"
        "# api_router assembled below\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(other_router)\n"
    )
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()

    push_import_idx = _line_index(lines, "from app.api.routes.push import")
    router_def_idx = _line_index(lines, "api_router = APIRouter()")
    comment_idx = _line_index(lines, "# api_router assembled below")

    assert push_import_idx != -1, "import fallback did not insert the push import"
    # Correct: import directly before the router definition (and AFTER the
    # comment). And->Or / In->NotIn would match the comment first (wrong line);
    # Sub->Add (L234) shifts the insert past the definition.
    assert push_import_idx == router_def_idx - 1, (
        f"push import expected directly before router def "
        f"(idx {router_def_idx - 1}), got {push_import_idx}"
    )
    assert comment_idx < push_import_idx, (
        "push import landed before the api_router comment (matched wrong line)"
    )


# ---------------------------------------------------------------------------
# routes/__init__.py — include fallback (L244 And->Or & In->NotIn).
# Has `from app.` imports (so import fallback is NOT used) but NO existing
# include_router lines -> last_include stays -1 -> fallback finds the
# `api_router = APIRouter()` line and inserts the include after it. A comment
# mentioning `api_router` precedes the def to distinguish And from Or.
# ---------------------------------------------------------------------------


def test_routes_include_fallback_lands_after_router_def():
    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text(
        "from fastapi import APIRouter\n"
        "from app.api.routes.item import router as item_router\n"
        "\n"
        "# api_router is built below\n"
        "api_router = APIRouter()\n"
    )
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()

    push_inc_idx = _line_index(lines, "api_router.include_router(push_router)")
    router_def_idx = _line_index(lines, "api_router = APIRouter()")

    assert push_inc_idx != -1, "include fallback did not insert the push include"
    # Correct: include directly AFTER the router definition. And->Or / In->NotIn
    # would match the comment line first and insert the include BEFORE the def
    # (a NameError at runtime).
    assert push_inc_idx == router_def_idx + 1, (
        f"push include expected directly after router def "
        f"(idx {router_def_idx + 1}), got {push_inc_idx}"
    )
    assert push_inc_idx > router_def_idx, "push include landed before api_router was defined"
