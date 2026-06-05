"""Generic tool-contract mutation coverage for add_dlp_shield.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_dlp_shield.py in the mutation
runner: ``--tests test_add_dlp_shield.py test_add_dlp_shield_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_dlp_shield import _patch_config, add_dlp_shield
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS

_DLP_FIELDS = (
    "    DLP_ENABLED: bool = True\n"
    '    DLP_REDACTION_MODE: str = "full"\n'
    "    DLP_SENSITIVE_PATTERNS: list[str] = []\n"
    "    DLP_BYPASS_ROLES: list[str] = []\n"
)


def test_contract():
    from adapt.extend.infrastructure.add_dlp_shield import add_dlp_shield

    for check in SCAFFOLDABLE_CHECKS:
        check(add_dlp_shield, "add_dlp_shield")


# ---------------------------------------------------------------------------
# Tool-specific survivors. The shared preamble mutants (execution_time,
# idempotency, dry_run, auto-scaffold, exist_ok, prereq-error) live in
# SCAFFOLDABLE_CHECKS above; the tests below target the bespoke logic of
# _patch_config (config-field insertion position / branch selection) and the
# auto-scaffold accumulation in add_dlp_shield.
# ---------------------------------------------------------------------------


def test_patch_config_inserts_after_anchor_line() -> None:
    """L159 `if anchor in src`: when the ACCESS_TOKEN_EXPIRE anchor is present,
    DLP fields must be injected directly after that anchor line — not down by
    `settings = Settings()`. NotIn-flip would route to the settings branch and
    place the fields elsewhere.
    """
    project_dir = create_fixture_project(name="dlp_anchor")
    add_dlp_shield(ToolInput(project_dir=str(project_dir)))
    config = (project_dir / "app" / "core" / "config.py").read_text()
    lines = config.splitlines()
    anchor_idx = next(
        i for i, ln in enumerate(lines) if "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30" in ln
    )
    # The very next line after the anchor must be the first DLP field.
    assert lines[anchor_idx + 1] == "    DLP_ENABLED: bool = True", (
        f"DLP fields not directly after anchor; got: {lines[anchor_idx + 1]!r}"
    )
    # The fields must precede `settings = Settings()` in source order.
    assert config.index("DLP_ENABLED") < config.index("settings = Settings()")


def test_patch_config_settings_target_branch() -> None:
    """L163 `if target in src` + L164 `fields + "\\n" + target`: with NO anchor
    but a `settings = Settings()` target, fields are inserted immediately before
    that target line (NotIn-flip would fall through to the append fallback;
    Add->Sub would raise TypeError on str subtraction).
    """
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text("class Settings:\n    FOO: int = 1\n\nsettings = Settings()\n")
    _patch_config(cfg)
    out = cfg.read_text()
    assert "DLP_ENABLED" in out
    # Fields land before the target (settings branch), proving In-branch taken.
    assert out.index("DLP_ENABLED") < out.index("settings = Settings()")
    # The exact `fields + "\n" + target` glue: blank line then the target.
    assert _DLP_FIELDS + "\nsettings = Settings()" in out


def test_patch_config_fallback_append_branch() -> None:
    """L166 `src.rstrip("\\n") + "\\n" + fields`: with neither the anchor nor the
    `settings = Settings()` target, fields are appended to the end of the file.
    Add->Sub would raise TypeError; this drives the fallback to completion and
    asserts the fields are appended last.
    """
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text("class Settings:\n    FOO: int = 1\n")
    _patch_config(cfg)
    out = cfg.read_text()
    assert "DLP_ENABLED" in out
    # Appended at the tail — the DLP block is the final content.
    assert out.rstrip("\n").endswith(_DLP_FIELDS.rstrip("\n"))
    # Exactly one newline separates the original tail from the fields.
    assert "    FOO: int = 1\n    DLP_ENABLED: bool = True" in out


def test_scaffolded_config_included_in_files_created() -> None:
    """L82 `list(scaffolded or [])`: on a bare project the prerequisite check
    auto-scaffolds app/core/config.py; those paths must be carried into
    files_created. And-flip (`scaffolded and []`) would drop them since a
    non-empty list is truthy and returns the empty list.
    """
    d = Path(tempfile.mkdtemp())
    (d / "app").mkdir()
    (d / "app" / "main.py").write_text("app = None\n")
    result = add_dlp_shield(ToolInput(project_dir=str(d)))
    assert result.status == "success", result.error
    assert any(p.endswith("app/core/config.py") for p in result.files_created), (
        f"auto-scaffolded config.py missing from files_created: {result.files_created}"
    )
