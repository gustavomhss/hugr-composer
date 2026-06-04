"""Generic + tool-specific mutation coverage for add_compliance_engine.

The generic block applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests.

The tool-specific block below targets the orchestration helpers
(``_patch_config``, ``_patch_routes_init``, ``_patch_models_init``) and the
Alembic ``down_rev`` resolution — the operator-controlled insertion
positions / anchors / branch selection / dedup that the generic checks and
the bespoke structural tests do not pin down. Run alongside
test_add_compliance_engine.py in the mutation runner.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_compliance_engine import (
    _patch_config,
    _patch_models_init,
    _patch_routes_init,
    add_compliance_engine,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS

_COMPLIANCE_BLOCK_FIELD = "COMPLIANCE_ENABLED"


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_compliance_engine, "add_compliance_engine")


# ---------------------------------------------------------------------------
# _patch_config — anchor branch (L248: `anchor in src`)
# ---------------------------------------------------------------------------


def test_config_block_inserted_immediately_after_anchor() -> None:
    """The compliance block must be injected right AFTER the anchor line.

    Kills `anchor in src` -> `not in`: that flip would route to the
    `settings = Settings()` fallback (the real config has both), placing the
    block at the bottom of the class instead of after the anchor.
    """
    project_dir = create_fixture_project(name="comp_cfg_anchor")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    config = (project_dir / "app" / "core" / "config.py").read_text()
    lines = config.splitlines()
    anchor_idx = next(
        i for i, ln in enumerate(lines) if "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30" in ln
    )
    field_idx = next(i for i, ln in enumerate(lines) if _COMPLIANCE_BLOCK_FIELD in ln and ":" in ln)
    # comment line then COMPLIANCE_ENABLED right after the anchor.
    assert field_idx - anchor_idx <= 2, (
        f"compliance block not anchored to ACCESS_TOKEN_EXPIRE_MINUTES "
        f"(anchor L{anchor_idx}, field L{field_idx})"
    )


# ---------------------------------------------------------------------------
# _patch_config — settings_line fallback (L252: `settings_line in src`)
# ---------------------------------------------------------------------------


def test_config_fallback_inserts_before_settings_instance() -> None:
    """With no anchor present, the block goes BEFORE `settings = Settings()`.

    Kills `settings_line in src` -> `not in`: that flip would route to the
    final append-at-EOF branch, dropping the block after the instantiation.
    """
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "config.py"
    cfg.write_text("class Settings:\n    FOO: int = 1\n\nsettings = Settings()\n")
    _patch_config(cfg)
    out = cfg.read_text()
    assert _COMPLIANCE_BLOCK_FIELD in out
    assert out.index(_COMPLIANCE_BLOCK_FIELD) < out.index("settings = Settings()"), (
        "compliance block must precede the settings instantiation"
    )


# ---------------------------------------------------------------------------
# _patch_config — final fallback (L255: `src.rstrip("\n") + "\n" + block`)
# ---------------------------------------------------------------------------


def test_config_final_fallback_appends_block() -> None:
    """With neither anchor nor settings instance, append the block at EOF.

    Kills the `+` -> `-` mutant on the string concatenation (string
    subtraction raises TypeError) and verifies the block actually lands.
    """
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "config.py"
    cfg.write_text("class Settings:\n    FOO: int = 1")
    _patch_config(cfg)
    out = cfg.read_text()
    assert _COMPLIANCE_BLOCK_FIELD in out, "block not appended in the final fallback branch"
    assert out.startswith("class Settings:\n    FOO: int = 1\n"), (
        "original config body must be preserved before the appended block"
    )


# ---------------------------------------------------------------------------
# _patch_models_init — leading-newline guard (L229: `not content.endswith("\\n")`)
# ---------------------------------------------------------------------------


def test_models_init_separates_imports_without_trailing_newline() -> None:
    """When the file lacks a trailing newline, a separator must be added.

    Kills `not content.endswith("\\n")` -> `content.endswith(...)`: that flip
    would skip the separator and glue the new import onto the last line.
    """
    tmp = Path(tempfile.mkdtemp())
    mi = tmp / "__init__.py"
    mi.write_text("from app.models.user import User")  # no trailing newline
    _patch_models_init(mi, [("compliance_event", "ComplianceEvent")])
    lines = mi.read_text().splitlines()
    assert lines[0] == "from app.models.user import User", "existing import was mangled"
    assert any("ComplianceEvent" in ln for ln in lines[1:]), (
        "new import not placed on its own line (separator dropped)"
    )
    assert "UserFrom" not in mi.read_text(), "imports were concatenated (missing separator)"


def test_models_init_dedup_is_noop_when_already_present() -> None:
    """A second patch with the same import must not duplicate it."""
    tmp = Path(tempfile.mkdtemp())
    mi = tmp / "__init__.py"
    mi.write_text("from app.models.compliance_event import ComplianceEvent  # noqa: F401\n")
    before = mi.read_text()
    _patch_models_init(mi, [("compliance_event", "ComplianceEvent")])
    assert mi.read_text() == before, "already-present import must be a no-op (dedup guard)"


# ---------------------------------------------------------------------------
# _patch_routes_init — import position in the normal branch (L276: `idx + 1`)
# ---------------------------------------------------------------------------


def test_routes_init_import_after_last_app_import() -> None:
    """The compliance import lands immediately after the last `from app.` line.

    Kills `last_app_import_idx + 1` -> `- 1`: that flip would insert the import
    one line too early (before the last existing app import).
    """
    project_dir = create_fixture_project(name="comp_ri_imp")
    ri = project_dir / "app" / "routes" / "__init__.py"
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()
    comp_idx = next(i for i, ln in enumerate(lines) if "import router as compliance_router" in ln)
    app_import_idxs = [
        i for i, ln in enumerate(lines) if ln.startswith("from app.") and i != comp_idx
    ]
    assert comp_idx == max(app_import_idxs) + 1, (
        f"compliance import not directly after last app import "
        f"(comp L{comp_idx}, last app L{max(app_import_idxs)})"
    )


# ---------------------------------------------------------------------------
# _patch_routes_init — include position in the normal branch (L286: `idx + 1`)
# ---------------------------------------------------------------------------


def test_routes_init_include_after_last_include() -> None:
    """The compliance include lands immediately after the last include line.

    Kills `last_include_idx + 1` -> `- 1`.
    """
    project_dir = create_fixture_project(name="comp_ri_inc")
    ri = project_dir / "app" / "routes" / "__init__.py"
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()
    comp_idx = next(i for i, ln in enumerate(lines) if "include_router(compliance_router)" in ln)
    other_incl = [
        i
        for i, ln in enumerate(lines)
        if ln.startswith("api_router.include_router") and i != comp_idx
    ]
    assert comp_idx == max(other_incl) + 1, (
        f"compliance include not directly after last include "
        f"(comp L{comp_idx}, last incl L{max(other_incl)})"
    )


# ---------------------------------------------------------------------------
# _patch_routes_init — no-`from app.` fallback (L271/L274/L283)
# ---------------------------------------------------------------------------


def test_routes_init_fallback_no_app_imports() -> None:
    """When no `from app.` import exists, import is anchored to APIRouter().

    Kills:
      * `last_app_import_idx == -1` -> `!= -1`: skipping the fallback would
        insert the import at the very top (index 0) instead of before the
        `api_router = APIRouter()` line.
      * `idx - 1` -> `idx + 1`: shifts the anchor.
      * the `"api_router" in line and "APIRouter()" in line` guard mutants in
        the fallback loop.
    """
    tmp = Path(tempfile.mkdtemp())
    ri = tmp / "__init__.py"
    ri.write_text(
        "from fastapi import APIRouter\n\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(foo_router)\n"
    )
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()
    assert lines[0] == "from fastapi import APIRouter", (
        "import wrongly inserted at the top (fallback branch not taken)"
    )
    apirouter_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    comp_idx = next(i for i, ln in enumerate(lines) if "import router as compliance_router" in ln)
    assert comp_idx == apirouter_idx - 1, (
        f"compliance import not directly before APIRouter() "
        f"(comp L{comp_idx}, apirouter L{apirouter_idx})"
    )


# ---------------------------------------------------------------------------
# _patch_routes_init — include fallback when no include lines exist (L281/L283)
# ---------------------------------------------------------------------------


def test_routes_init_include_fallback_no_existing_includes() -> None:
    """With no existing include lines, the include is anchored after APIRouter().

    Kills `last_include_idx == -1` -> `!= -1` (the fallback loop would be
    skipped, and `lines.insert(-1 + 1, ...)` would push the include to the top).
    """
    tmp = Path(tempfile.mkdtemp())
    ri = tmp / "__init__.py"
    ri.write_text("from fastapi import APIRouter\n\napi_router = APIRouter()\n")
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()
    apirouter_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    incl_idx = next(i for i, ln in enumerate(lines) if "include_router(compliance_router)" in ln)
    assert incl_idx == apirouter_idx + 1, (
        f"compliance include not directly after APIRouter() "
        f"(incl L{incl_idx}, apirouter L{apirouter_idx})"
    )


def test_routes_init_dedup_is_noop_when_already_present() -> None:
    """A second patch must not re-register the compliance router."""
    project_dir = create_fixture_project(name="comp_ri_dedup")
    ri = project_dir / "app" / "routes" / "__init__.py"
    _patch_routes_init(ri)
    once = ri.read_text()
    _patch_routes_init(ri)
    assert ri.read_text() == once, "second patch must be a no-op (import-present guard)"
    assert once.count("import router as compliance_router") == 1


# ---------------------------------------------------------------------------
# Alembic down_rev resolution (L144: `find_migration_head(...) or "0001_initial"`)
# ---------------------------------------------------------------------------


def test_migration_down_rev_uses_real_head() -> None:
    """The emitted migration chains onto the real head, not the static default.

    Kills `find_migration_head(...) or "0001_initial"` -> `and`: the `and`
    flip would set down_revision to "0001_initial" whenever a real head was
    found, silently corrupting the migration chain.
    """
    project_dir = create_fixture_project(name="comp_mig")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    migration = project_dir / "alembic" / "versions" / "add_compliance_engine.py"
    content = migration.read_text()
    down_line = next(ln for ln in content.splitlines() if "down_revision" in ln)
    assert "0002_baseline_schema" in down_line, (
        f"down_revision must chain onto the real head, got: {down_line!r}"
    )
    assert '"0001_initial"' not in down_line, (
        "down_revision fell back to the static default despite a real head"
    )
