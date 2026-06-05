"""Generic tool-contract mutation coverage for add_ml_model_registry.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_ml_model_registry.py in the mutation
runner: ``--tests test_add_ml_model_registry.py test_add_ml_model_registry_contract.py``.

Bespoke tests below target this tool's specific logic (config patching,
routes-init ordering, models-init dedup, migration head chaining, ML
subpackage creation) to kill tool-specific mutation survivors.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_ml_model_registry import (
    _patch_config,
    _patch_models_init,
    _patch_routes_init,
    add_ml_model_registry,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_ml_model_registry import add_ml_model_registry

    for check in SCAFFOLDABLE_CHECKS:
        check(add_ml_model_registry, "add_ml_model_registry")


# ---------------------------------------------------------------------------
# _patch_config — anchor branch + fallback branches
# ---------------------------------------------------------------------------


def test_config_block_inserted_right_after_anchor():
    """ML block lands immediately after the ACCESS_TOKEN anchor line.

    Kills L242/L243 (anchor `in` check + `replace` placement): if the
    anchor branch is skipped/flipped the block would not sit directly
    below the anchor.
    """
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text(
        "class Settings:\n"
        "    PROJECT_NAME: str = 'x'\n"
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n"
        "    OTHER: int = 1\n"
        "\n"
        "settings = Settings()\n"
    )
    _patch_config(cfg)
    lines = cfg.read_text().splitlines()
    anchor_idx = next(i for i, ln in enumerate(lines) if "ACCESS_TOKEN_EXPIRE_MINUTES" in ln)
    fw_idx = next(i for i, ln in enumerate(lines) if "ML_REGISTRY_DEFAULT_FRAMEWORK" in ln)
    # The framework field must come AFTER the anchor, before the next real field.
    assert fw_idx > anchor_idx
    other_idx = next(i for i, ln in enumerate(lines) if "OTHER: int" in ln)
    assert anchor_idx < fw_idx < other_idx, (
        "ML block must be inserted directly after the anchor, before OTHER"
    )
    # Indentation preserved (inside the class body).
    assert lines[fw_idx].startswith("    ML_REGISTRY_DEFAULT_FRAMEWORK")


def test_config_fallback_before_settings_instantiation():
    """Without the anchor, block is injected before `settings = Settings()`.

    Kills L247 (`settings_line in src`) and L248 (`block + "\\n\\n" +
    settings_line`): drives the second branch (no anchor present).
    """
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text("class Settings:\n    PROJECT_NAME: str = 'x'\n\nsettings = Settings()\n")
    _patch_config(cfg)
    text = cfg.read_text()
    assert "ML_REGISTRY_DEFAULT_FRAMEWORK" in text
    fw_pos = text.index("ML_REGISTRY_DEFAULT_FRAMEWORK")
    settings_pos = text.index("settings = Settings()")
    assert fw_pos < settings_pos, "fallback must inject block BEFORE settings = Settings()"
    # block then blank line(s) then settings — the Add at L248 wires this gap.
    between = text[text.index("ML_REGISTRY_ARTIFACT_BASE_PATH") : settings_pos]
    assert "\n\n" in between, "expected blank-line separation before settings line"


def test_config_fallback_append_when_no_anchor_no_settings():
    """With neither anchor nor settings line, block is appended at EOF.

    Drives the final L250 else branch (rstrip + append).
    """
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text("class Settings:\n    PROJECT_NAME: str = 'x'\n")
    _patch_config(cfg)
    text = cfg.read_text()
    assert "ML_REGISTRY_DEFAULT_FRAMEWORK" in text
    # appended after the original content.
    assert text.index("PROJECT_NAME") < text.index("ML_REGISTRY_DEFAULT_FRAMEWORK")


def test_config_idempotent_no_double_insert():
    """Re-patching a config that already has the field is a no-op."""
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text(
        "class Settings:\n    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n\nsettings = Settings()\n"
    )
    _patch_config(cfg)
    once = cfg.read_text()
    _patch_config(cfg)
    twice = cfg.read_text()
    assert once == twice, "second patch must not change config"
    assert twice.count("ML_REGISTRY_DEFAULT_FRAMEWORK") == 1


# ---------------------------------------------------------------------------
# _patch_routes_init — insertion ordering (import before include, anchors)
# ---------------------------------------------------------------------------


def _routes_init_src() -> str:
    return (
        '"""Route registration."""\n'
        "\n"
        "from fastapi import APIRouter\n"
        "\n"
        "from app.api.routes.item import router as item_router\n"
        "from app.routes.health import router as health_router\n"
        "\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(item_router)\n"
        "\n"
        '__all__ = ["api_router"]\n'
    )


def test_routes_import_inserted_after_last_from_app():
    """ml_registry import goes right after the LAST `from app.` line.

    Kills L262 (Eq check / max default) and L268 BinOp Add (`+ 1`): a
    Sub would drop the import before the last from-app line (before
    health), an Eq->NotEq flip on `last_from_app == -1` would route into
    the fallback scan.
    """
    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text(_routes_init_src())
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()
    health_idx = next(i for i, ln in enumerate(lines) if "health import" in ln)
    import_idx = next(i for i, ln in enumerate(lines) if "ml_registry import router" in ln)
    # import must come directly after the last from-app line (health).
    assert import_idx == health_idx + 1, (
        f"import at {import_idx}, expected directly after last from-app {health_idx}"
    )


def test_routes_include_inserted_after_last_include():
    """include_router(ml_registry_router) goes after the LAST include line.

    Kills L273 (Eq check) and L278 BinOp Add (`+ 1`): a Sub would place
    the include before the existing include_router(item_router).
    """
    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text(_routes_init_src())
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()
    item_inc_idx = next(i for i, ln in enumerate(lines) if "include_router(item_router)" in ln)
    ml_inc_idx = next(i for i, ln in enumerate(lines) if "include_router(ml_registry_router)" in ln)
    assert ml_inc_idx == item_inc_idx + 1, (
        f"include at {ml_inc_idx}, expected directly after last include {item_inc_idx}"
    )


def test_routes_import_precedes_include():
    """The import line must appear before the include line in the output."""
    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text(_routes_init_src())
    _patch_routes_init(ri)
    text = ri.read_text()
    assert text.index("ml_registry import router") < text.index(
        "include_router(ml_registry_router)"
    )


def test_routes_fallback_when_no_from_app_lines():
    """No `from app.` lines -> import anchored relative to APIRouter() line.

    Drives L263/L264 fallback (last_from_app == -1) and L265 BoolOp
    And (`api_router` and `APIRouter()`): both substrings must be present
    on the same line for the fallback anchor to fire. Result must parse.
    """
    import ast

    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text(
        "from fastapi import APIRouter\n"
        "\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(other_router)\n"
    )
    _patch_routes_init(ri)
    text = ri.read_text()
    assert "ml_registry import router" in text
    assert "include_router(ml_registry_router)" in text
    # Fallback anchors last_from_app to (decl_idx - 1); the import is then
    # inserted at decl_idx, i.e. directly BEFORE the APIRouter() declaration.
    lines = text.splitlines()
    decl_idx = next(i for i, ln in enumerate(lines) if "api_router" in ln and "APIRouter()" in ln)
    import_idx = next(i for i, ln in enumerate(lines) if "ml_registry import router" in ln)
    assert import_idx == decl_idx - 1, (
        f"fallback import at {import_idx}, expected directly before APIRouter() line {decl_idx}"
    )
    ast.parse(text)  # emitted module still valid


def test_routes_idempotent_no_double_register():
    """Re-patching already-registered routes init is a no-op (L259 guard)."""
    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text(_routes_init_src())
    _patch_routes_init(ri)
    once = ri.read_text()
    _patch_routes_init(ri)
    twice = ri.read_text()
    assert once == twice
    assert twice.count("ml_registry import router") == 1
    assert twice.count("include_router(ml_registry_router)") == 1


# ---------------------------------------------------------------------------
# _patch_models_init — dedup / append guards
# ---------------------------------------------------------------------------


def test_models_init_appends_import():
    """MLModel import appended; ends with newline (L225 guard)."""
    d = Path(tempfile.mkdtemp())
    mi = d / "__init__.py"
    mi.write_text('"""models."""\nfrom app.models.item import Item  # noqa: F401')
    _patch_models_init(mi, [("ml_model", "MLModel")])
    text = mi.read_text()
    assert "from app.models.ml_model import MLModel" in text
    assert text.endswith("\n"), "L225 newline guard must terminate file with newline"
    # original content preserved before the appended line.
    assert text.index("item import Item") < text.index("ml_model import MLModel")


def test_models_init_already_present_is_noop():
    """If the marker is present, nothing is appended (the `continue` path)."""
    d = Path(tempfile.mkdtemp())
    mi = d / "__init__.py"
    original = '"""models."""\nfrom app.models.ml_model import MLModel  # noqa: F401\n'
    mi.write_text(original)
    _patch_models_init(mi, [("ml_model", "MLModel")])
    assert mi.read_text() == original, "no change when import already present"
    assert mi.read_text().count("ml_model import MLModel") == 1


# ---------------------------------------------------------------------------
# Migration head chaining (L151 BoolOp Or) + ML subpackage (L134 UnaryNot)
# ---------------------------------------------------------------------------


def test_migration_chains_to_real_head_not_fallback():
    """down_revision chains to the actual migration head, not the fallback.

    The fixture ships 0002_baseline_schema as HEAD, so
    find_migration_head() returns a truthy value and the `or "0001_initial"`
    fallback (L151) must NOT be used. Or->And would yield "0001_initial".
    """
    project = create_fixture_project(name="ml_ctr_mig")
    add_ml_model_registry(ToolInput(project_dir=str(project)))
    mig = (project / "alembic" / "versions" / "add_ml_model_registry.py").read_text()
    assert "0002_baseline_schema" in mig, "migration must chain to real head 0002_baseline_schema"
    assert '"0001_initial"' not in mig, "must not fall back to 0001_initial when a head exists"


def test_ml_init_created_when_absent():
    """app/ml/__init__.py is created on a fresh project (L134 `not exists`).

    not X->X would invert the guard and skip creating the subpackage init.
    """
    project = create_fixture_project(name="ml_ctr_init")
    result = add_ml_model_registry(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    ml_init = project / "app" / "ml" / "__init__.py"
    assert ml_init.exists(), "app/ml/__init__.py must be created"
    assert any(p.endswith("app/ml/__init__.py") for p in result.files_created), (
        "ml/__init__.py must be reported in files_created"
    )
    # registry_service sits alongside the package init.
    assert (project / "app" / "ml" / "registry_service.py").exists()


def test_ml_init_preserved_when_already_present():
    """If app/ml/__init__.py exists, the tool must not overwrite it.

    Drives the false side of the L134 guard: existing init kept verbatim,
    not reported in files_created.
    """
    project = create_fixture_project(name="ml_ctr_init2")
    ml_dir = project / "app" / "ml"
    ml_dir.mkdir(parents=True, exist_ok=True)
    sentinel = '"""pre-existing ml pkg."""\nMARKER = 1\n'
    (ml_dir / "__init__.py").write_text(sentinel)
    result = add_ml_model_registry(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    assert (ml_dir / "__init__.py").read_text() == sentinel, (
        "existing ml/__init__.py must be left untouched"
    )
    assert not any(p.endswith("app/ml/__init__.py") for p in result.files_created), (
        "pre-existing ml/__init__.py must NOT be re-reported as created"
    )
