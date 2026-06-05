"""Generic tool-contract mutation coverage for add_email_templates.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_email_templates.py in the mutation
runner: ``--tests test_add_email_templates.py test_add_email_templates_contract.py``.

The ``test_specific_*`` functions below target this tool's bespoke logic
(config-block placement, router import/include ordering, requirement and
env-file dedup, reply-to fallback, migration head wiring) that the generic
contract checks do not exercise.
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_email_templates import (
    _patch_config,
    _patch_env_example,
    _patch_models_init,
    _patch_requirements,
    _register_router,
    add_email_templates,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_email_templates import add_email_templates

    for check in SCAFFOLDABLE_CHECKS:
        check(add_email_templates, "add_email_templates")


# ---------------------------------------------------------------------------
# _patch_config — anchor / settings / fallback placement (L397, L401, L404)
# ---------------------------------------------------------------------------


def _patch_config_src(src: str, *, reply_to: str = "") -> str:
    d = Path(tempfile.mkdtemp())
    f = d / "config.py"
    f.write_text(src)
    _patch_config(
        f,
        provider="resend",
        from_address="a@b.com",
        from_name="N",
        reply_to=reply_to,
        default_locale="en",
    )
    return f.read_text()


def test_specific_config_block_lands_right_after_anchor():
    """L397 In->NotIn: when the ACCESS_TOKEN anchor exists, the EMAIL block is
    inserted directly after that anchor line (not bumped to the settings tail)."""
    src = (
        "class Settings:\n"
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n"
        "    OTHER: int = 1\n"
        "\n"
        "settings = Settings()\n"
    )
    out = _patch_config_src(src)
    lines = out.splitlines()
    anchor_idx = next(i for i, line in enumerate(lines) if "ACCESS_TOKEN_EXPIRE_MINUTES" in line)
    # The first line emitted after the anchor must be the tool's marker comment.
    assert "added by add_email_templates tool" in lines[anchor_idx + 1], (
        f"EMAIL block not placed immediately after anchor: {lines[anchor_idx + 1]!r}"
    )
    # And it must precede the pre-existing OTHER field that followed the anchor.
    assert out.index("EMAIL_PROVIDER") < out.index("OTHER: int = 1")


def test_specific_config_block_before_settings_when_no_anchor():
    """L401 In->NotIn: with no anchor but a ``settings = Settings()`` line, the
    block is inserted before that line (not appended after it)."""
    src = "class Settings:\n    FOO: int = 1\n\nsettings = Settings()\n"
    out = _patch_config_src(src)
    lines = out.splitlines()
    settings_idx = next(
        i for i, line in enumerate(lines) if line.strip() == "settings = Settings()"
    )
    assert any("EMAIL_PROVIDER" in line for line in lines[:settings_idx]), (
        "EMAIL block must appear before the settings = Settings() line"
    )
    assert not any("EMAIL_PROVIDER" in line for line in lines[settings_idx:]), (
        "EMAIL block must not appear after the settings = Settings() line"
    )


def test_specific_config_fallback_appends_block_at_end():
    """L404 Add->Sub: with neither anchor nor settings line, the block is
    appended at the end via string concatenation (Sub would raise TypeError)."""
    src = "class Settings:\n    FOO: int = 1\n"
    out = _patch_config_src(src)
    assert out.index("FOO") < out.index("EMAIL_PROVIDER"), (
        "pre-existing content must precede the appended block"
    )
    assert out.rstrip().endswith("EMAIL_PREVIEW_ENABLED_IN_PROD: bool = False"), (
        "EMAIL block must be appended at the very end of config.py"
    )


# ---------------------------------------------------------------------------
# _register_router — import/include ordering + fallback (L425, L430, L435, L440)
# ---------------------------------------------------------------------------


def test_specific_email_import_is_last_app_import():
    """L430 Add->Sub: the email import is inserted right after the last existing
    ``from app.`` import — i.e. it becomes the final app-import line."""
    project_dir = create_fixture_project(name="email_ct_imp")
    result = add_email_templates(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    app_import_idxs = [i for i, line in enumerate(lines) if line.startswith("from app.")]
    email_idx = next(
        i for i, line in enumerate(lines) if "email import router as email_router" in line
    )
    assert email_idx == max(app_import_idxs), (
        "email import must be the last from-app import line (Add->Sub would place it before)"
    )


def test_specific_email_include_is_last_include():
    """L440 Add->Sub: the email include is inserted right after the last existing
    ``api_router.include_router`` call — i.e. it becomes the final include."""
    project_dir = create_fixture_project(name="email_ct_inc")
    result = add_email_templates(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    include_idxs = [
        i for i, line in enumerate(lines) if line.startswith("api_router.include_router")
    ]
    email_idx = next(
        i
        for i, line in enumerate(lines)
        if line.strip() == "api_router.include_router(email_router)"
    )
    assert email_idx == max(include_idxs), (
        "email include must be the last include_router call (Add->Sub would place it before)"
    )


def test_specific_register_router_fallback_no_app_imports():
    """L425/L435 In/Eq guards: with no ``from app.`` imports and no existing
    includes, the import lands just before ``api_router = APIRouter()`` and the
    include just after it (the ``== -1`` fallback branches)."""
    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text("from fastapi import APIRouter\n\napi_router = APIRouter()\n")
    _register_router(ri, import_line="IMPORT_X", include_line="INCLUDE_Y")
    lines = ri.read_text().splitlines()
    apirouter_idx = next(i for i, line in enumerate(lines) if "APIRouter()" in line)
    assert lines[apirouter_idx - 1] == "IMPORT_X", (
        "fallback import must be inserted immediately before the APIRouter() line"
    )
    assert lines[apirouter_idx + 1] == "INCLUDE_Y", (
        "fallback include must be inserted immediately after the APIRouter() line"
    )


def test_specific_register_router_idempotent():
    """A second registration must not duplicate the import line."""
    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text(
        "from fastapi import APIRouter\n\n"
        "from app.api.routes.x import router as x_router\n\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(x_router)\n"
    )
    _register_router(
        ri,
        import_line="from app.api.routes.email import router as email_router",
        include_line="api_router.include_router(email_router)",
    )
    _register_router(
        ri,
        import_line="from app.api.routes.email import router as email_router",
        include_line="api_router.include_router(email_router)",
    )
    text = ri.read_text()
    assert text.count("import router as email_router") == 1
    assert text.count("api_router.include_router(email_router)") == 1


# ---------------------------------------------------------------------------
# _patch_models_init — trailing-newline guard (L361)
# ---------------------------------------------------------------------------


def test_specific_models_init_no_trailing_newline_stays_parseable():
    """L361 not->X: when the file has no trailing newline a newline must be
    added so the new import lands on its own line (flip would concatenate and
    break the AST)."""
    d = Path(tempfile.mkdtemp())
    mi = d / "__init__.py"
    mi.write_text("from app.models.base import Base")  # deliberately no trailing \n
    _patch_models_init(mi, [("email_delivery", "EmailDelivery")])
    text = mi.read_text()
    ast.parse(text)  # would raise if the two imports were concatenated
    lines = text.splitlines()
    assert lines[0] == "from app.models.base import Base", "original import line corrupted"
    assert any(
        "from app.models.email_delivery import EmailDelivery" in line for line in lines[1:]
    ), "new import must be on its own subsequent line"


# ---------------------------------------------------------------------------
# _patch_requirements / _patch_env_example — dedup guards (L446, L454)
# ---------------------------------------------------------------------------


def test_specific_requirements_adds_jinja_and_dedups():
    """L446 In->NotIn: jinja2 is added when absent and never duplicated on a
    second run (flip would never add it)."""
    d = Path(tempfile.mkdtemp())
    r = d / "requirements.txt"
    r.write_text("fastapi\n")
    _patch_requirements(r)
    assert "jinja2" in r.read_text().lower(), "jinja2 must be added when missing"
    _patch_requirements(r)
    assert r.read_text().lower().count("jinja2") == 1, "jinja2 must not be duplicated"


def test_specific_env_example_adds_block_and_dedups():
    """L454 In->NotIn: the EMAIL_PROVIDER env block is added when absent and not
    duplicated on a second run (flip would never add it)."""
    d = Path(tempfile.mkdtemp())
    e = d / ".env.example"
    e.write_text("SECRET=x\n")
    _patch_env_example(e)
    assert "EMAIL_PROVIDER" in e.read_text(), "env block must be added when missing"
    _patch_env_example(e)
    assert e.read_text().count("EMAIL_PROVIDER") == 1, "env block must not be duplicated"


# ---------------------------------------------------------------------------
# reply_to fallback + migration head wiring (L147, L246)
# ---------------------------------------------------------------------------


def test_specific_reply_to_none_renders_empty_string():
    """L147 Or->And: reply_to=None -> '' so config emits EMAIL_REPLY_TO = ""
    (And would propagate None and emit "None")."""
    out = _patch_config_src(
        "class Settings:\n    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n\nsettings = Settings()\n",
        reply_to="",  # the tool computes `reply_to or ""` before calling _patch_config
    )
    assert 'EMAIL_REPLY_TO: str = ""' in out, "empty reply_to must render as empty string"
    assert "None" not in out


def test_specific_reply_to_none_via_tool():
    """L147 Or->And end-to-end: reply_to defaults to None on the tool and must
    surface as an empty EMAIL_REPLY_TO field, never the literal 'None'."""
    project_dir = create_fixture_project(name="email_ct_reply")
    result = add_email_templates(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    config = (project_dir / "app" / "core" / "config.py").read_text()
    assert 'EMAIL_REPLY_TO: str = ""' in config, (
        "reply_to=None must render as empty string, not 'None'"
    )


def test_specific_migration_down_revision_uses_real_head():
    """L246 Or->And: down_revision wires to the actual migration head returned
    by find_migration_head (And would discard it and fall to the default)."""
    project_dir = create_fixture_project(name="email_ct_migr")
    from adapt.contracts.migration_helper import find_migration_head

    head = find_migration_head(project_dir / "alembic" / "versions")
    assert head, "fixture must have a migration head for this test to be meaningful"
    result = add_email_templates(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    migration = (project_dir / "alembic" / "versions" / "add_email_templates.py").read_text()
    assert f'down_revision = "{head}"' in migration, (
        f"down_revision must wire to the real head {head!r}"
    )
    assert 'down_revision = "0001_initial"' not in migration
