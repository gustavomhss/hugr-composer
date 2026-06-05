"""Generic tool-contract mutation coverage for add_notifications.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_notifications.py in the mutation
runner: ``--tests test_add_notifications.py test_add_notifications_contract.py``.
"""

from adapt.contracts import ToolInput
from adapt.contracts.migration_helper import find_migration_head
from adapt.extend.infrastructure.add_notifications import add_notifications
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_notifications, "add_notifications")


# ---------------------------------------------------------------------------
# Tool-specific mutation kills (beyond the shared preamble checks above).
# Each test targets a named survivor in the tool source's bespoke logic.
# ---------------------------------------------------------------------------


def _config_lines(project):
    """Return the non-empty stripped lines of the patched config.py."""
    text = (project / "app" / "core" / "config.py").read_text()
    return text.splitlines()


# --- _patch_config: anchor placement (L259/L260/L261) -----------------------


def test_config_block_lands_immediately_after_access_token_anchor():
    """Kills L260 In->NotIn and L261 placement: the notification block is
    injected directly after the ACCESS_TOKEN_EXPIRE_MINUTES anchor line, not
    via the settings = Settings() fallback branch."""
    project = create_fixture_project(name="notif_ct_anchor")
    add_notifications(ToolInput(project_dir=str(project)))
    lines = _config_lines(project)

    anchor_idx = next(
        i for i, ln in enumerate(lines) if "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30" in ln
    )
    # The very next non-blank line must be the notification marker comment,
    # proving the In-branch (not the settings_line fallback) was taken.
    following = [ln for ln in lines[anchor_idx + 1 : anchor_idx + 4]]
    assert any("added by add_notifications tool" in ln for ln in following), (
        f"NOTIFICATION block not directly after anchor; got {following!r}"
    )
    # And the block must precede the settings = Settings() instantiation, so
    # the fallback append-at-end path was definitely not used.
    text = "\n".join(lines)
    if "settings = Settings()" in text:
        assert text.index("NOTIFICATION_CHANNELS") < text.index("settings = Settings()")


def test_config_block_in_settings_class_fallback_when_no_anchor():
    """Kills L260 (In->NotIn would always fall through) + L267 Add->Sub:
    when neither the ACCESS_TOKEN anchor nor a settings = Settings() line is
    present, the block is appended (rstrip + '\\n' + block) so the fields
    still appear exactly once and the file still ends cleanly."""
    project = create_fixture_project(name="notif_ct_bareconfig")
    config_file = project / "app" / "core" / "config.py"
    config_file.write_text("class Settings:\n    DEBUG: bool = False\n")
    add_notifications(ToolInput(project_dir=str(project)))
    text = config_file.read_text()
    # Exactly one occurrence (no double-append) and present.
    assert text.count("NOTIFICATION_CHANNELS") == 1
    # L267 is `src.rstrip("\n") + "\n" + block`: a Sub would be a TypeError on
    # str, but Add->Sub at runtime still must yield original content followed
    # by the block. Assert the pre-existing DEBUG line survives and the block
    # comes after it (append semantics, not prepend/overwrite).
    assert "DEBUG: bool = False" in text
    assert text.index("DEBUG: bool = False") < text.index("NOTIFICATION_CHANNELS")


def test_config_max_per_page_value_threaded_through():
    """The max_per_page kwarg is rendered into NOTIFICATION_MAX_PER_PAGE."""
    project = create_fixture_project(name="notif_ct_maxpp")
    add_notifications(ToolInput(project_dir=str(project)), max_per_page=77)
    text = (project / "app" / "core" / "config.py").read_text()
    assert "NOTIFICATION_MAX_PER_PAGE: int = 77" in text


# --- _patch_models_init: trailing-newline guard (L239) ----------------------


def test_models_init_import_on_its_own_line_without_trailing_newline():
    """Kills L239 UnaryNot (not content.endswith): when models/__init__.py
    has NO trailing newline, the tool must prepend a '\\n' so the new import
    lands on its own line instead of being glued onto the last import."""
    project = create_fixture_project(name="notif_ct_nonewline")
    models_init = project / "app" / "models" / "__init__.py"
    models_init.write_text(models_init.read_text().rstrip("\n"))  # strip newline
    add_notifications(ToolInput(project_dir=str(project)))
    text = models_init.read_text()
    # No line may carry two `import` statements glued together.
    for ln in text.splitlines():
        assert not ("import User" in ln and "import Notification" in ln), (
            f"notification import glued onto previous line: {ln!r}"
        )
    # The notification import is present and on its own well-formed line.
    notif_lines = [ln for ln in text.splitlines() if "app.models.notification" in ln]
    assert len(notif_lines) == 1
    assert notif_lines[0].startswith("from app.models.notification import Notification")


def test_models_init_no_duplicate_on_rerun_guard():
    """The marker-not-in-content dedup means a model already registered is not
    re-appended (supports the idempotency contract for the patch helper)."""
    project = create_fixture_project(name="notif_ct_modeldedup")
    add_notifications(ToolInput(project_dir=str(project)))
    text = (project / "app" / "models" / "__init__.py").read_text()
    assert text.count("from app.models.notification import Notification") == 1


# --- _register_router: anchor scan + insert indices (L283-L306) -------------


def test_router_import_inserted_right_after_last_app_import():
    """Kills L290 Eq->NotEq, L295 Add->Sub: with real `from app.` imports the
    fallback (L291-294) is skipped and the notifications import lands directly
    after the LAST existing `from app.` import line."""
    project = create_fixture_project(name="notif_ct_importpos")
    add_notifications(ToolInput(project_dir=str(project)))
    lines = (project / "app" / "routes" / "__init__.py").read_text().splitlines()

    notif_import_idx = next(
        i for i, ln in enumerate(lines) if "import router as notifications_router" in ln
    )
    # Line immediately before must be a `from app.` import (proves insert at
    # last_app_import + 1, not -1 or via the fallback recompute).
    assert lines[notif_import_idx - 1].startswith("from app."), (
        f"import not directly after last app import: prev={lines[notif_import_idx - 1]!r}"
    )
    # And no further `from app.` import appears after it (it really was last).
    after = lines[notif_import_idx + 1 :]
    assert not any(ln.startswith("from app.") and "notifications_router" not in ln for ln in after)


def test_router_include_inserted_right_after_last_include():
    """Kills L300 Eq->NotEq, L305 Add->Sub: with real include_router calls the
    include fallback is skipped and the notifications include lands directly
    after the LAST existing api_router.include_router line."""
    project = create_fixture_project(name="notif_ct_includepos")
    add_notifications(ToolInput(project_dir=str(project)))
    lines = (project / "app" / "routes" / "__init__.py").read_text().splitlines()

    notif_inc_idx = next(
        i for i, ln in enumerate(lines) if "include_router(notifications_router)" in ln
    )
    # Line immediately before is another include_router call.
    assert lines[notif_inc_idx - 1].startswith("api_router.include_router"), (
        f"include not after last include: prev={lines[notif_inc_idx - 1]!r}"
    )
    # The include comes AFTER the import (Add->Sub on either insert would
    # scramble this relative order).
    text = "\n".join(lines)
    assert text.index("import router as notifications_router") < text.index(
        "include_router(notifications_router)"
    )


def test_router_fallback_uses_apirouter_anchor_when_no_app_imports():
    """Kills the fallback-branch mutants L292/L302 (And->Or, In->NotIn) and
    L293 Sub->Add: with NO `from app.` imports and NO existing include_router
    lines, the tool must locate the `api_router = APIRouter()` line and insert
    the import just before it and the include just after it."""
    project = create_fixture_project(name="notif_ct_fallback")
    routes_init = project / "app" / "routes" / "__init__.py"
    routes_init.write_text(
        '"""Route registration."""\n\n'
        "from fastapi import APIRouter\n\n"
        "api_router = APIRouter()\n\n"
        '__all__ = ["api_router"]\n'
    )
    add_notifications(ToolInput(project_dir=str(project)))
    lines = routes_init.read_text().splitlines()

    anchor_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    import_idx = next(
        i for i, ln in enumerate(lines) if "import router as notifications_router" in ln
    )
    include_idx = next(
        i for i, ln in enumerate(lines) if "include_router(notifications_router)" in ln
    )
    # L293 (idx - 1) means import inserts BEFORE the api_router anchor; a flip
    # to idx + 1 would push it after the anchor.
    assert import_idx < anchor_idx, (
        f"fallback import must precede api_router anchor: import={import_idx} anchor={anchor_idx}"
    )
    # Include inserts AFTER the anchor (last_include = anchor idx, +1).
    assert include_idx > anchor_idx, (
        f"fallback include must follow api_router anchor: include={include_idx} anchor={anchor_idx}"
    )


def test_router_registration_idempotent_no_double_register():
    """The import_line-in-src guard prevents a duplicate import/include on a
    re-run path (second run is no_op, but the guard itself must hold)."""
    project = create_fixture_project(name="notif_ct_routerdedup")
    add_notifications(ToolInput(project_dir=str(project)))
    text = (project / "app" / "routes" / "__init__.py").read_text()
    assert text.count("import router as notifications_router") == 1
    assert text.count("include_router(notifications_router)") == 1


# --- migration down_revision (L131) -----------------------------------------


def test_migration_down_revision_is_real_head_not_default():
    """Kills L131 BoolOp Or->And: down_revision must be the actual migration
    head returned by find_migration_head, NOT the '0001_initial' default. With
    `or` flipped to `and`, a truthy head would collapse to the default."""
    project = create_fixture_project(name="notif_ct_downrev")
    versions_dir = project / "alembic" / "versions"
    head = find_migration_head(versions_dir)
    assert head, "fixture should have a discoverable migration head"
    assert head != "0001_initial", "fixture head unexpectedly equals the default"

    add_notifications(ToolInput(project_dir=str(project)))
    mig_text = (versions_dir / "add_notifications.py").read_text()
    assert f'down_revision: str = "{head}"' in mig_text, (
        f"down_revision should be real head {head!r}, got:\n{mig_text}"
    )
    assert 'down_revision: str = "0001_initial"' not in mig_text


# --- channels template branch (has_email True/False) ------------------------


def test_channels_stub_template_used_without_email_package():
    """Drives the has_email=False branch: with no app/email/ present the stub
    channels template is rendered (email channel is a stub)."""
    project = create_fixture_project(name="notif_ct_noemail")
    assert not (project / "app" / "email" / "__init__.py").exists()
    result = add_notifications(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    notes = " ".join(result.notes)
    assert "email channel stub" in notes, f"expected stub note, got: {notes}"


def test_channels_email_bridge_used_with_email_package():
    """Drives the has_email=True branch: when app/email/__init__.py exists the
    bridged email channel note is emitted instead of the stub note."""
    project = create_fixture_project(name="notif_ct_withemail")
    email_init = project / "app" / "email" / "__init__.py"
    email_init.parent.mkdir(parents=True, exist_ok=True)
    email_init.write_text('"""email package."""\n')
    result = add_notifications(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    notes = " ".join(result.notes)
    assert "email channel (bridged to app/email/)." in notes, f"expected bridged note, got: {notes}"
