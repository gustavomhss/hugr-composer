"""Generic tool-contract mutation coverage for add_secret_rotation.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_secret_rotation.py in the mutation
runner: ``--tests test_add_secret_rotation.py test_add_secret_rotation_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_secret_rotation import add_secret_rotation
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_secret_rotation import add_secret_rotation

    for check in SCAFFOLDABLE_CHECKS:
        check(add_secret_rotation, "add_secret_rotation")


def _bare_project_with_config(body: str) -> Path:
    """Make a minimal project whose app/core/config.py has the given Settings body.

    All four prerequisites are satisfied with valid marker tokens so the tool
    proceeds without auto-scaffold clobbering the custom config body.
    """
    root = Path(tempfile.mkdtemp()) / "proj"
    (root / "app" / "core").mkdir(parents=True)
    (root / "app" / "models").mkdir(parents=True)
    (root / "app" / "routes").mkdir(parents=True)
    (root / "app" / "models" / "base.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\n\n\nclass Base(DeclarativeBase):\n    pass\n"
    )
    (root / "app" / "routes" / "__init__.py").write_text(
        'from fastapi import APIRouter\n\napi_router = APIRouter()\n__all__ = ["api_router"]\n'
    )
    (root / "app" / "core" / "config.py").write_text(body)
    (root / "requirements.txt").write_text("fastapi>=0.115.0\n")
    return root


# --- L184 (anchor In→NotIn): block lands directly after the anchor line -------


def test_config_block_inserted_immediately_after_anchor():
    """L184 In->NotIn / anchor path: rotation block must follow the anchor line.

    If `anchor in src` flips to NotIn, the tool takes the `settings = Settings()`
    fallback and the block lands somewhere else (not glued to the anchor).
    """
    project = create_fixture_project(name="anchor_after")
    result = add_secret_rotation(ToolInput(project_dir=str(project)))
    assert result.status == "success"

    cfg = (project / "app" / "core" / "config.py").read_text()
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    expected = anchor + "\n    # --- Secret rotation"
    assert expected in cfg, "rotation block must be inserted directly after the anchor line"


# --- L188 (settings_line In→NotIn) + L189 (Add→Sub): no-anchor fallback -------


def test_config_block_before_settings_when_no_anchor():
    """L188 In->NotIn + L189 Add->Sub: with no anchor, block precedes `settings = Settings()`.

    The block must be inserted *before* the `settings = Settings()` line and that
    line must still be present afterwards (L189 concatenation order).
    """
    body = (
        "from pydantic_settings import BaseSettings\n\n\n"
        "class Settings(BaseSettings):\n"
        '    PROJECT_NAME: str = "demo"\n\n\n'
        "settings = Settings()\n"
    )
    project = _bare_project_with_config(body)
    result = add_secret_rotation(ToolInput(project_dir=str(project)))
    assert result.status == "success"

    cfg = (project / "app" / "core" / "config.py").read_text()
    assert "SECRET_PROVIDER" in cfg
    assert "settings = Settings()" in cfg, "L189: settings line must survive the rewrite"
    # block must appear before the settings assignment
    assert cfg.index("SECRET_PROVIDER") < cfg.index("settings = Settings()"), (
        "L188/L189: rotation block must be inserted before `settings = Settings()`"
    )
    # the block must be glued right before the settings line (L189 ordering)
    assert "SECRET_ROTATION_INTERVAL_H: int = 24\n\n\nsettings = Settings()" in cfg


# --- L191 (Add→Sub): no anchor and no settings line -> append at end ----------


def test_config_block_appended_when_no_anchor_no_settings_line():
    """L191 Add->Sub: with neither anchor nor settings line, block is appended at EOF.

    The fallback path `src.rstrip("\\n") + "\\n" + block` must keep the original
    body intact and append the rotation block after it.
    """
    body = (
        "from pydantic_settings import BaseSettings\n\n\n"
        "class Settings(BaseSettings):\n"
        '    PROJECT_NAME: str = "demo"\n'
    )
    project = _bare_project_with_config(body)
    result = add_secret_rotation(ToolInput(project_dir=str(project)))
    assert result.status == "success"

    cfg = (project / "app" / "core" / "config.py").read_text()
    assert 'PROJECT_NAME: str = "demo"' in cfg, "L191: original body must be preserved"
    assert "SECRET_PROVIDER" in cfg
    # block appended after the original content
    assert cfg.index('PROJECT_NAME: str = "demo"') < cfg.index("SECRET_PROVIDER")


# --- L99 (scaffolded Or→And): auto-scaffolded prereqs carried into files_created


def test_autoscaffolded_prereqs_included_in_files_created():
    """L99 `list(scaffolded or [])` Or->And: scaffolded prereq files survive.

    With a bare project the prereq scaffolder emits files; `scaffolded or []`
    must yield those files. The And-mutant collapses to `[]`, dropping them.
    """
    project = _bare_project_with_config(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class Settings(BaseSettings):\n"
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n\n\n"
        "settings = Settings()\n"
    )
    # remove a prereq file so the scaffolder must (re)generate it, leaving the
    # valid config/routes intact → `scaffolded` is non-empty.
    (project / "requirements.txt").unlink()
    result = add_secret_rotation(ToolInput(project_dir=str(project)))
    assert result.status == "success"

    created = result.files_created or []
    assert any(p.endswith("app/__init__.py") for p in created), (
        "L99: auto-scaffolded prereq files must appear in files_created"
    )


# --- requirements + idempotency sanity (anchor path) --------------------------


def test_requirements_get_provider_stubs_and_idempotent():
    """Second run is a no_op and does not double-append the rotation block."""
    project = create_fixture_project(name="idem_rot")
    first = add_secret_rotation(ToolInput(project_dir=str(project)))
    assert first.status == "success"

    req = (project / "requirements.txt").read_text()
    assert "hvac" in req and "boto3" in req

    second = add_secret_rotation(ToolInput(project_dir=str(project)))
    assert second.status == "no_op"

    cfg = (project / "app" / "core" / "config.py").read_text()
    assert cfg.count("SECRET_PROVIDER") == 1, "config block must not be duplicated"
