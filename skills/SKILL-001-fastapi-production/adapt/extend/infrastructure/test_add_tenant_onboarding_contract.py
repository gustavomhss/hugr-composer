"""Generic tool-contract mutation coverage for add_tenant_onboarding.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_tenant_onboarding.py in the mutation
runner: ``--tests test_add_tenant_onboarding.py test_add_tenant_onboarding_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_tenant_onboarding import add_tenant_onboarding
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_tenant_onboarding import add_tenant_onboarding

    for check in SCAFFOLDABLE_CHECKS:
        check(add_tenant_onboarding, "add_tenant_onboarding")


# ---------------------------------------------------------------------------
# L123 UnaryNot: `if not onboarding_init.exists():` guards writing the
# onboarding package __init__.py. Flipping `not X -> X` means the file is
# only written when it ALREADY exists (never, on a fresh project) — so the
# package __init__ would be absent. Assert it is created with its docstring.
# ---------------------------------------------------------------------------


def test_onboarding_package_init_written() -> None:
    project_dir = create_fixture_project(name="ob_ct_initguard")
    result = add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error

    init_file = project_dir / "app" / "onboarding" / "__init__.py"
    assert init_file.exists(), "onboarding package __init__.py not written"
    assert init_file.read_text() == '"""Tenant onboarding package."""\n'

    # The created file must be reported in files_created (resolve both sides
    # to survive the /var -> /private/var symlink on macOS CI).
    created_resolved = {str(Path(p).resolve()) for p in result.files_created}
    assert str(init_file.resolve()) in created_resolved


# ---------------------------------------------------------------------------
# L204 Compare In->NotIn: `if anchor in content:` selects the anchor branch
# that inserts the config block IMMEDIATELY AFTER
# `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`. The fixture config HAS that
# anchor. Flipping In->NotIn would skip to the settings-line fallback and
# drop the block at the end of the file (right before `settings = Settings()`)
# instead. Assert the block lands directly after the anchor line.
# ---------------------------------------------------------------------------


def test_config_block_inserted_after_anchor() -> None:
    project_dir = create_fixture_project(name="ob_ct_anchor")
    result = add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error

    config = (project_dir / "app" / "core" / "config.py").read_text()
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    assert anchor in config
    assert "ONBOARDING_STEPS" in config

    # Between the end of the anchor line and ONBOARDING_STEPS there must be
    # only the injected comment block — i.e. the block lands right after the
    # anchor, NOT down by `settings = Settings()`.
    anchor_end = config.index(anchor) + len(anchor)
    onboarding_at = config.index("ONBOARDING_STEPS")
    settings_at = config.index("settings = Settings()")
    assert anchor_end < onboarding_at < settings_at
    between = config[anchor_end:onboarding_at]
    assert "settings = Settings()" not in between
    assert "Tenant Onboarding" in between, (
        "config block not placed directly after ACCESS_TOKEN_EXPIRE_MINUTES anchor"
    )


# ---------------------------------------------------------------------------
# Helper: a minimal project whose config.py has NO anchor line but DOES have
# `settings = Settings()` — drives the _patch_config fallback branch (L207-212).
# ---------------------------------------------------------------------------


def _project_without_config_anchor() -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "app" / "core").mkdir(parents=True)
    (d / "app" / "routes").mkdir(parents=True)
    (d / "app" / "api" / "routes").mkdir(parents=True)
    (d / "app" / "__init__.py").write_text("")
    (d / "requirements.txt").write_text("fastapi\n")
    (d / "app" / "core" / "config.py").write_text(
        "from pydantic_settings import BaseSettings\n"
        "\n"
        "\n"
        "class Settings(BaseSettings):\n"
        '    PROJECT_NAME: str = "app"\n'
        "\n"
        "\n"
        "settings = Settings()\n"
    )
    (d / "app" / "routes" / "__init__.py").write_text(
        "from fastapi import APIRouter\n\napi_router = APIRouter()\n"
    )
    return d


# ---------------------------------------------------------------------------
# L208 Compare In->NotIn: in the fallback (no anchor) branch,
# `if settings_line in content:` guards inserting the block before
# `settings = Settings()`. The fixture config HAS that line. Flipping
# In->NotIn would skip insertion entirely, leaving ONBOARDING_STEPS absent.
# Assert the block IS present in a no-anchor config.
# ---------------------------------------------------------------------------


def test_config_fallback_inserts_before_settings() -> None:
    project_dir = _project_without_config_anchor()
    result = add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error

    config = (project_dir / "app" / "core" / "config.py").read_text()
    assert "ACCESS_TOKEN_EXPIRE_MINUTES" not in config  # confirm fallback path
    assert "ONBOARDING_STEPS" in config, "fallback branch did not insert config block"

    # L211 BinOp Add->Sub: the block is concatenated BEFORE the settings line
    # (`block + "\n\n" + settings_line`). Order must be block-then-settings;
    # a Sub mutation would raise TypeError (str - str) and never reach here.
    onboarding_at = config.index("ONBOARDING_STEPS")
    settings_at = config.index("settings = Settings()")
    assert onboarding_at < settings_at, (
        "config block must precede `settings = Settings()` in fallback branch"
    )


# ---------------------------------------------------------------------------
# L211 BinOp Add->Sub (explicit): exercising the fallback branch must yield a
# successful run AND the exact `\n\n` separator between the block and the
# settings line. A `-` operator on the str concat would crash the tool.
# ---------------------------------------------------------------------------


def test_config_fallback_block_separator() -> None:
    project_dir = _project_without_config_anchor()
    result = add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error

    config = (project_dir / "app" / "core" / "config.py").read_text()
    assert (
        'ONBOARDING_WELCOME_EMAIL_TEMPLATE: str = "welcome"\n\n\nsettings = Settings()' in config
    ), "fallback block must be joined to settings line with a blank-line separator"
