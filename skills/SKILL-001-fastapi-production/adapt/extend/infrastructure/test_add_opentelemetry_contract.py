"""Generic tool-contract mutation coverage for add_opentelemetry.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_opentelemetry.py in the mutation
runner: ``--tests test_add_opentelemetry.py test_add_opentelemetry_contract.py``.

Hand-added tool-specific tests below target the remaining survivors in
``_patch_config`` (anchor / settings-line / end-of-file insertion ordering) and
``_patch_requirements`` (per-package dedup) which the generic preamble checks
do not exercise.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_opentelemetry import (
    _patch_config,
    _patch_requirements,
    add_opentelemetry,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS

_OTEL_BLOCK_HEAD = "# --- OpenTelemetry — added by add_opentelemetry tool ---"


def test_contract():
    from adapt.extend.infrastructure.add_opentelemetry import add_opentelemetry

    for check in SCAFFOLDABLE_CHECKS:
        check(add_opentelemetry, "add_opentelemetry")


# ---------------------------------------------------------------------------
# _patch_config — anchor branch (L201-203)
#   if anchor in src:  (In->NotIn)
#   src.replace(anchor, anchor + "\n" + block...)  (ordering)
# ---------------------------------------------------------------------------


def test_patch_config_inserts_after_anchor_line() -> None:
    """OTEL block lands immediately AFTER the ACCESS_TOKEN_EXPIRE_MINUTES anchor.

    Kills L202 In->NotIn (anchor branch must be taken when anchor present) and
    L203 ordering (block goes after, not before, the anchor).
    """
    d = Path(tempfile.mkdtemp())
    config = d / "config.py"
    config.write_text(
        "class Settings:\n"
        '    SECRET_KEY: str = ""\n'
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n"
        '    FRONTEND_URL: str = "x"\n\n'
        "settings = Settings()\n"
    )
    _patch_config(config)
    out = config.read_text()
    assert "OTEL_ENABLED: bool = False" in out
    anchor_idx = out.index("ACCESS_TOKEN_EXPIRE_MINUTES: int = 30")
    block_idx = out.index(_OTEL_BLOCK_HEAD)
    # Block must appear AFTER the anchor line, not before it.
    assert block_idx > anchor_idx, "OTEL block must be inserted after the anchor"
    # And it must sit directly after the anchor line, before FRONTEND_URL.
    frontend_idx = out.index("FRONTEND_URL")
    assert anchor_idx < block_idx < frontend_idx


def test_patch_config_anchor_block_directly_follows_anchor() -> None:
    """The line right after the anchor is the OTEL block start (Add ordering).

    Kills L203 Add->Sub: replacement is ``anchor + "\\n" + block`` so the very
    next non-empty line after the anchor is the OTEL comment header.
    """
    d = Path(tempfile.mkdtemp())
    config = d / "config.py"
    config.write_text(
        "class Settings:\n    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\nsettings = Settings()\n"
    )
    _patch_config(config)
    lines = config.read_text().splitlines()
    anchor_line = next(
        i for i, ln in enumerate(lines) if "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30" in ln
    )
    # Next line is the OTEL comment header.
    assert _OTEL_BLOCK_HEAD in lines[anchor_line + 1], (
        f"Expected OTEL header right after anchor, got: {lines[anchor_line + 1]!r}"
    )


def test_patch_config_anchor_idempotent() -> None:
    """Second _patch_config is a no-op (OTEL_ENABLED guard)."""
    d = Path(tempfile.mkdtemp())
    config = d / "config.py"
    config.write_text(
        "class Settings:\n    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\nsettings = Settings()\n"
    )
    _patch_config(config)
    once = config.read_text()
    _patch_config(config)
    twice = config.read_text()
    assert once == twice, "config patch must be idempotent"
    assert twice.count("OTEL_ENABLED: bool = False") == 1


# ---------------------------------------------------------------------------
# _patch_config — settings-line fallback (L205-207)
#   if settings_line in src:  (In->NotIn)
#   block + "\n\n" + settings_line  (Add ordering: block BEFORE settings)
# ---------------------------------------------------------------------------


def test_patch_config_fallback_inserts_before_settings_line() -> None:
    """With no anchor, block is inserted BEFORE ``settings = Settings()``.

    Kills L206 In->NotIn (settings-line branch taken when anchor absent) and
    L207 Add->Sub (block precedes the settings instantiation line).
    """
    d = Path(tempfile.mkdtemp())
    config = d / "config.py"
    # No ACCESS_TOKEN_EXPIRE_MINUTES anchor on purpose.
    config.write_text('class Settings:\n    SECRET_KEY: str = ""\nsettings = Settings()\n')
    _patch_config(config)
    out = config.read_text()
    assert "OTEL_ENABLED: bool = False" in out
    block_idx = out.index(_OTEL_BLOCK_HEAD)
    settings_idx = out.index("settings = Settings()")
    assert block_idx < settings_idx, "OTEL block must be inserted before settings = Settings()"


# ---------------------------------------------------------------------------
# _patch_config — end-of-file fallback (L209)
#   src.rstrip("\n") + "\n" + block  (Add ordering: block appended at end)
# ---------------------------------------------------------------------------


def test_patch_config_appends_at_end_when_no_anchor_no_settings() -> None:
    """With neither anchor nor settings line, block is appended at the END.

    Kills L209 Add->Sub: the source is preserved and the block follows it.
    """
    d = Path(tempfile.mkdtemp())
    config = d / "config.py"
    config.write_text('class Settings:\n    SECRET_KEY: str = ""\n')
    _patch_config(config)
    out = config.read_text()
    assert "OTEL_ENABLED: bool = False" in out
    # Original content must still precede the appended block.
    secret_idx = out.index("SECRET_KEY")
    block_idx = out.index(_OTEL_BLOCK_HEAD)
    assert secret_idx < block_idx, "OTEL block must be appended after original source"
    # Block sits at the tail of the file.
    assert out.rstrip().endswith("OTEL_TRACES_SAMPLER_ARG: float = 1.0"), (
        f"OTEL block should be at end of file, tail was: {out[-120:]!r}"
    )


# ---------------------------------------------------------------------------
# _patch_requirements — per-package dedup (L221, L223, L225)
#   if "opentelemetry-sdk" not in src:           (NotIn->In)
#   if "opentelemetry-exporter-otlp" not in src: (NotIn->In)
#   if not additions: return                     (UnaryNot)
# ---------------------------------------------------------------------------


def test_patch_requirements_adds_both_when_absent() -> None:
    """Both OTEL packages appended when neither present (L221/L223 NotIn)."""
    d = Path(tempfile.mkdtemp())
    req = d / "requirements.txt"
    req.write_text("fastapi>=0.110\n")
    _patch_requirements(req)
    out = req.read_text()
    assert "opentelemetry-sdk>=1.23.0" in out
    assert "opentelemetry-exporter-otlp>=1.23.0" in out
    assert "fastapi>=0.110" in out


def test_patch_requirements_skips_sdk_when_present() -> None:
    """opentelemetry-sdk is NOT re-added when already present (L221 NotIn->In).

    Only the exporter gets appended; sdk line count stays at 1.
    """
    d = Path(tempfile.mkdtemp())
    req = d / "requirements.txt"
    req.write_text("fastapi>=0.110\nopentelemetry-sdk>=1.23.0\n")
    _patch_requirements(req)
    out = req.read_text()
    assert out.count("opentelemetry-sdk") == 1, "sdk must not be duplicated"
    assert "opentelemetry-exporter-otlp>=1.23.0" in out


def test_patch_requirements_skips_exporter_when_present() -> None:
    """exporter is NOT re-added when already present (L223 NotIn->In).

    Only the sdk gets appended; exporter line count stays at 1.
    """
    d = Path(tempfile.mkdtemp())
    req = d / "requirements.txt"
    req.write_text("fastapi>=0.110\nopentelemetry-exporter-otlp>=1.23.0\n")
    _patch_requirements(req)
    out = req.read_text()
    assert out.count("opentelemetry-exporter-otlp") == 1, "exporter must not be duplicated"
    assert "opentelemetry-sdk>=1.23.0" in out


def test_patch_requirements_noop_when_both_present() -> None:
    """File untouched when both packages already present (L225 UnaryNot).

    If ``not additions`` were flipped, the empty additions list would be joined
    and a stray newline appended; assert byte-for-byte identity instead.
    """
    d = Path(tempfile.mkdtemp())
    req = d / "requirements.txt"
    original = "fastapi>=0.110\nopentelemetry-sdk>=1.23.0\nopentelemetry-exporter-otlp>=1.23.0\n"
    req.write_text(original)
    _patch_requirements(req)
    assert req.read_text() == original, "no-op when both packages already present"


# ---------------------------------------------------------------------------
# End-to-end: real fixture exercises the anchor branch + requirements add.
# ---------------------------------------------------------------------------


def test_end_to_end_config_and_requirements_patched() -> None:
    """Full run patches config after the anchor and adds OTEL to requirements."""
    project_dir = create_fixture_project(name="otel_contract_e2e")
    result = add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"

    config = (project_dir / "app" / "core" / "config.py").read_text()
    anchor_idx = config.index("ACCESS_TOKEN_EXPIRE_MINUTES: int = 30")
    block_idx = config.index(_OTEL_BLOCK_HEAD)
    assert block_idx > anchor_idx, "real config: OTEL block must follow the anchor"

    req = (project_dir / "requirements.txt").read_text()
    assert "opentelemetry-sdk>=1.23.0" in req
    assert "opentelemetry-exporter-otlp>=1.23.0" in req
