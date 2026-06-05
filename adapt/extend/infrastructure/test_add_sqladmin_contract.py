"""Generic tool-contract mutation coverage for add_sqladmin.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_sqladmin.py in the mutation
runner: ``--tests test_add_sqladmin.py test_add_sqladmin_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_sqladmin import add_sqladmin
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_sqladmin import add_sqladmin

    for check in SCAFFOLDABLE_CHECKS:
        check(add_sqladmin, "add_sqladmin")


# ---------------------------------------------------------------------------
# Tool-specific survivor kills.
#
# The shared contract preamble (execution_time, idempotency, dry_run,
# auto-scaffold, exist_ok, prereq-error) is already covered by test_contract
# above and by SCAFFOLDABLE_CHECKS. The tests below target this tool's own
# logic: per-model view generation, config/main/env patching, and the
# require_superuser flag default.
# ---------------------------------------------------------------------------


def _minimal_project(
    *,
    config_src: str,
    main_src: str,
    models_init: str = "from app.models.user import User\n",
) -> Path:
    """Build a bare-but-valid project so config/main patch branches can run.

    Only the prerequisite markers are needed: a Base class, a Settings class,
    a models __init__ with an import, and a requirements.txt. Caller controls
    the exact config.py / main.py text so the patcher's anchor branches can be
    driven deterministically (something the full fixture cannot do because it
    always ships the ACCESS_TOKEN anchor + register_middleware call).
    """
    d = Path(tempfile.mkdtemp())
    (d / "app" / "models").mkdir(parents=True)
    (d / "app" / "core").mkdir(parents=True)
    (d / "app" / "models" / "base.py").write_text("class Base:\n    pass\n")
    (d / "app" / "models" / "__init__.py").write_text(models_init)
    (d / "app" / "core" / "config.py").write_text(config_src)
    (d / "app" / "main.py").write_text(main_src)
    (d / "requirements.txt").write_text("fastapi\n")
    return d


def _views(project: Path) -> str:
    return (project / "app" / "admin" / "views.py").read_text()


# --- L262 / L263: per-model can_delete + icon keyed on name == "User" -------


def test_user_view_cannot_delete_others_can():
    """can_delete = False for User, True for non-User models (L262 Eq)."""
    project = create_fixture_project(name="sqladmin_c_candelete")
    add_sqladmin(ToolInput(project_dir=str(project)))
    src = _views(project)
    # Default fixture ships Item + User.
    user_block = src.split("class UserAdmin")[1]
    item_block = src.split("class ItemAdmin")[1].split("class UserAdmin")[0]
    assert "can_delete = False" in user_block, "User must be delete-protected"
    assert "can_delete = True" in item_block, "non-User models must allow delete"


def test_user_icon_differs_from_other_models():
    """User gets the user icon, others the database icon (L263 Eq)."""
    project = create_fixture_project(name="sqladmin_c_icon")
    add_sqladmin(ToolInput(project_dir=str(project)))
    src = _views(project)
    user_block = src.split("class UserAdmin")[1]
    item_block = src.split("class ItemAdmin")[1].split("class UserAdmin")[0]
    assert 'icon = "fa-solid fa-user"' in user_block, "User icon wrong"
    assert 'icon = "fa-solid fa-database"' in item_block, "non-User icon wrong"


# --- L265 / L267: pluralisation BinOp Add ----------------------------------


def test_plural_for_name_ending_in_s():
    """A model ending in 's' pluralises with 'es' (L265 name + 'es')."""
    project = create_fixture_project(name="sqladmin_c_plural_s", models={"Bus": {"route": "str"}})
    add_sqladmin(ToolInput(project_dir=str(project)))
    src = _views(project)
    assert 'name_plural = "Buses"' in src, "Bus must pluralise to Buses"


def test_plural_for_name_ending_in_y():
    """A model ending in 'y' pluralises with 'ies' (L267 name[:-1] + 'ies')."""
    project = create_fixture_project(
        name="sqladmin_c_plural_y", models={"Category": {"label": "str"}}
    )
    add_sqladmin(ToolInput(project_dir=str(project)))
    src = _views(project)
    assert 'name_plural = "Categories"' in src, "Category must pluralise to Categories"


# --- L35: require_superuser default True -----------------------------------


def test_require_superuser_default_true():
    """Default require_superuser=True flows to config + auth (L35 BoolLiteral)."""
    project = create_fixture_project(name="sqladmin_c_super_default")
    add_sqladmin(ToolInput(project_dir=str(project)))
    config = (project / "app" / "core" / "config.py").read_text()
    assert "ADMIN_REQUIRE_SUPERUSER: bool = True" in config, (
        "default require_superuser must render True in config"
    )
    auth = (project / "app" / "admin" / "auth.py").read_text()
    assert "require_superuser = True" in auth, "default must render True in auth.py"
    assert "require_superuser = False" not in auth, "default must not render False"


def test_require_superuser_false_renders_false():
    """require_superuser=False renders False in config + auth (kills L35)."""
    project = create_fixture_project(name="sqladmin_c_super_false")
    add_sqladmin(ToolInput(project_dir=str(project)), require_superuser=False)
    config = (project / "app" / "core" / "config.py").read_text()
    assert "ADMIN_REQUIRE_SUPERUSER: bool = False" in config, (
        "require_superuser=False must render False in config"
    )
    auth = (project / "app" / "admin" / "auth.py").read_text()
    assert "require_superuser = False" in auth, "explicit False must render in auth.py"


# --- L305 / L312: _patch_config anchor branches ----------------------------


def test_config_block_inserted_right_after_anchor():
    """With the ACCESS_TOKEN anchor present, the admin block lands directly
    after it (L305 'anchor in src' + the +block ordering)."""
    project = create_fixture_project(name="sqladmin_c_cfg_anchor")
    add_sqladmin(ToolInput(project_dir=str(project)))
    config = (project / "app" / "core" / "config.py").read_text()
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    assert anchor in config
    after = config.split(anchor, 1)[1]
    # The admin block must be the next thing after the anchor, before any
    # other field declaration creeps in.
    idx_block = after.index("# --- Admin panel")
    assert idx_block < 200, "admin block not anchored right after ACCESS_TOKEN line"
    # Idempotent: a re-run inserts nothing new.
    assert config.count("ADMIN_PATH: str") == 1, "config field duplicated"


def test_config_no_anchor_no_settings_appends_at_end():
    """No anchor and no 'settings = Settings()' line -> block appended at the
    tail (L309 settings_line branch false, L312 rstrip+block)."""
    project = _minimal_project(
        config_src="class Settings:\n    API_V1_STR: str = '/api'\n",
        main_src="from fastapi import FastAPI\napp = FastAPI()\n",
    )
    r = add_sqladmin(ToolInput(project_dir=str(project)))
    assert r.status == "success", r.error
    config = (project / "app" / "core" / "config.py").read_text()
    assert "ADMIN_PATH: str" in config, "admin block not written"
    # Block must be at the END (after the original class body), not spliced in
    # the middle, since neither anchor nor settings line exists.
    assert config.rstrip().endswith("ADMIN_REQUIRE_SUPERUSER: bool = True"), (
        "with no anchor/settings line the block must be appended last"
    )


def test_config_settings_line_branch_inserts_before_settings():
    """No anchor but a 'settings = Settings()' line -> block inserted BEFORE
    that line (L309 settings_line in src true)."""
    project = _minimal_project(
        config_src=("class Settings:\n    API_V1_STR: str = '/api'\n\n\nsettings = Settings()\n"),
        main_src="from fastapi import FastAPI\napp = FastAPI()\n",
    )
    r = add_sqladmin(ToolInput(project_dir=str(project)))
    assert r.status == "success", r.error
    config = (project / "app" / "core" / "config.py").read_text()
    assert config.index("ADMIN_PATH: str") < config.index("settings = Settings()"), (
        "admin block must precede the settings = Settings() instantiation"
    )


# --- L322 / L323 / L333 / L338 / L339 / L344: _patch_main ------------------


def test_main_setup_after_register_middleware():
    """With register_middleware(app present, setup_admin(app) lands right after
    that call (L333 And + register_middleware anchor)."""
    project = create_fixture_project(name="sqladmin_c_main_mw")
    add_sqladmin(ToolInput(project_dir=str(project)))
    main = (project / "app" / "main.py").read_text()
    assert "from app.admin.setup import setup_admin" in main, "admin import missing"
    assert "setup_admin(app)" in main, "setup_admin(app) call missing"
    lines = main.splitlines()
    mw_idx = next(i for i, ln in enumerate(lines) if "register_middleware(app" in ln)
    setup_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "setup_admin(app)")
    assert setup_idx > mw_idx, "setup_admin must come after register_middleware"
    # The SQLAdmin comment marker proves the in-loop (not fallback) branch ran.
    assert "# --- SQLAdmin panel ---" in main, "in-loop insertion marker missing"


def test_main_import_inserted_after_last_app_import():
    """The admin import is added once, right after the run of 'from app.'
    imports (L322 flag init False; flip True would skip it)."""
    project = create_fixture_project(name="sqladmin_c_main_import")
    add_sqladmin(ToolInput(project_dir=str(project)))
    main = (project / "app" / "main.py").read_text()
    assert main.count("from app.admin.setup import setup_admin") == 1, (
        "admin import must be added exactly once"
    )


def test_main_fallback_appends_when_no_anchor():
    """main with neither a 'from app.' import nor register_middleware: import is
    prepended (L339 not admin_import_added true) and setup appended via the
    fallback (L338 not admin_setup_added true)."""
    project = _minimal_project(
        config_src="class Settings:\n    API_V1_STR: str = '/api'\n",
        main_src="from fastapi import FastAPI\napp = FastAPI()\n",
    )
    r = add_sqladmin(ToolInput(project_dir=str(project)))
    assert r.status == "success", r.error
    main = (project / "app" / "main.py").read_text()
    lines = main.splitlines()
    assert lines[0] == "from app.admin.setup import setup_admin", (
        "fallback must prepend the admin import when none existed"
    )
    assert lines[-1].strip() == "setup_admin(app)", (
        "fallback must append setup_admin(app) at the tail"
    )
    # No in-loop marker: this confirms the fallback path, not the anchored one.
    assert "# --- SQLAdmin panel ---" not in main, "should not use in-loop marker"


def test_main_fallback_no_double_import_when_app_import_exists():
    """main with a 'from app.' import but no register_middleware: the import is
    added in-loop, and the fallback must NOT prepend a second one
    (L339 not admin_import_added false)."""
    project = _minimal_project(
        config_src="class Settings:\n    API_V1_STR: str = '/api'\n",
        main_src=(
            "from fastapi import FastAPI\nfrom app.core.config import settings\n\napp = FastAPI()\n"
        ),
    )
    r = add_sqladmin(ToolInput(project_dir=str(project)))
    assert r.status == "success", r.error
    main = (project / "app" / "main.py").read_text()
    assert main.count("from app.admin.setup import setup_admin") == 1, (
        "import must appear exactly once (no fallback duplicate)"
    )
    assert main.splitlines()[0] != "from app.admin.setup import setup_admin", (
        "import should be added after the existing app import, not prepended"
    )


def test_main_preserves_trailing_newline():
    """Source ending in a newline keeps its trailing newline (L344 And)."""
    project = _minimal_project(
        config_src="class Settings:\n    API_V1_STR: str = '/api'\n",
        main_src="from fastapi import FastAPI\napp = FastAPI()\n",
    )
    add_sqladmin(ToolInput(project_dir=str(project)))
    main = (project / "app" / "main.py").read_text()
    assert main.endswith("\n"), "trailing newline must be preserved"


# --- L364: _patch_env_example idempotency guard ----------------------------


def test_env_example_block_added_when_absent():
    """On a fresh project the env.example admin block is written exactly once."""
    project = create_fixture_project(name="sqladmin_c_env")
    add_sqladmin(ToolInput(project_dir=str(project)))
    env = (project / ".env.example").read_text()
    assert "# ADMIN_PATH=/admin" in env, "env.example admin block not added"
    assert env.count("# ADMIN_PATH=/admin") == 1, "env.example block duplicated"


def test_env_example_guard_skips_when_marker_present():
    """If 'ADMIN_PATH' already appears in .env.example the patcher leaves it
    untouched (L364 'ADMIN_PATH' in src guard). Flipping In->NotIn would append
    the admin block, producing a second ADMIN_PATH occurrence."""
    project = _minimal_project(
        config_src="class Settings:\n    API_V1_STR: str = '/api'\n",
        main_src="from fastapi import FastAPI\napp = FastAPI()\n",
    )
    original = "SECRET_KEY=x\n# ADMIN_PATH=/existing\n"
    (project / ".env.example").write_text(original)
    r = add_sqladmin(ToolInput(project_dir=str(project)))
    assert r.status == "success", r.error
    env = (project / ".env.example").read_text()
    assert env == original, "guard must leave .env.example byte-for-byte unchanged"
    assert env.count("ADMIN_PATH") == 1, "guard must not append a second block"
