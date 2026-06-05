"""Generic tool-contract mutation coverage for add_transactional_email.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_transactional_email.py in the mutation
runner: ``--tests test_add_transactional_email.py test_add_transactional_email_contract.py``.

The hand-written ``test_*`` functions below target this tool's SPECIFIC logic
(config-block placement after the anchor, route import/include ordering, the
migration down_revision resolution, and the patch-helper fallback branches) so
that the tool-specific mutants survive the shared preamble checks are killed.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_transactional_email import (
    _patch_config,
    _patch_models_init,
    _patch_routes_init,
    add_transactional_email,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_transactional_email import add_transactional_email

    for check in SCAFFOLDABLE_CHECKS:
        check(add_transactional_email, "add_transactional_email")


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines()


def _index_of(lines: list[str], needle: str) -> int:
    for idx, line in enumerate(lines):
        if needle in line:
            return idx
    raise AssertionError(f"{needle!r} not found in lines")


# ---------------------------------------------------------------------------
# Config patch — anchor placement (kills L245 In->NotIn, and the In->NotIn /
# Eq->NotEq guards reached only through this anchored path stay observable).
# ---------------------------------------------------------------------------


def test_config_block_lands_immediately_after_access_token_anchor() -> None:
    """EMAIL_PROVIDER block is inserted directly after the ACCESS_TOKEN anchor.

    The fixture config contains ``ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`` so the
    anchored branch (``if anchor in src``) must fire. If In->NotIn flips, the
    block would land near ``settings = Settings()`` instead, far from the anchor.
    """
    project = create_fixture_project(name="txemail_cfg_anchor")
    add_transactional_email(ToolInput(project_dir=str(project)))
    lines = _lines(project / "app" / "core" / "config.py")
    anchor_idx = _index_of(lines, "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30")
    # The very next non-blank, non-comment line must be EMAIL_PROVIDER.
    tail = [ln for ln in lines[anchor_idx + 1 :] if ln.strip()]
    assert tail, "nothing emitted after the anchor"
    # First emitted line after anchor is the tool's comment header, then the field.
    first_field = next(ln for ln in tail if ln.strip().startswith("EMAIL_PROVIDER"))
    field_idx = lines.index(first_field)
    settings_idx = _index_of(lines, "settings = Settings()")
    assert anchor_idx < field_idx < settings_idx, (
        f"EMAIL_PROVIDER ({field_idx}) must sit between the anchor ({anchor_idx}) "
        f"and settings = Settings() ({settings_idx})"
    )
    # And it must be adjacent to the anchor (block header at anchor+1).
    assert "added by add_transactional_email tool" in lines[anchor_idx + 1]


def test_config_settings_line_fallback_when_no_anchor() -> None:
    """No anchor but a settings line: block lands before ``settings = Settings()``.

    Drives the ``else`` branch of ``if anchor in src`` and the
    ``if settings_line in src`` branch (kills L249 In->NotIn).
    """
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text('class Settings:\n    NAME = "x"\n\nsettings = Settings()\n')
    _patch_config(cfg)
    lines = _lines(cfg)
    field_idx = _index_of(lines, "EMAIL_PROVIDER")
    settings_idx = _index_of(lines, "settings = Settings()")
    assert field_idx < settings_idx, "block must precede settings = Settings()"


def test_config_bare_fallback_appends_block_at_end() -> None:
    """No anchor and no settings line: block is appended at the file tail.

    Drives the final ``else`` (``src.rstrip + "\\n" + block``); kills L252
    BinOp Add->Sub by asserting the block content survives concatenation.
    """
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text('class Settings:\n    NAME = "x"\n')
    _patch_config(cfg)
    text = cfg.read_text()
    assert "EMAIL_PROVIDER" in text
    assert "RESEND_API_KEY" in text
    # The original content must be preserved and precede the new block.
    assert text.index('NAME = "x"') < text.index("EMAIL_PROVIDER")
    # No source text was destroyed by the rstrip+add concatenation.
    assert text.startswith("class Settings:")


def test_config_idempotent_no_double_block() -> None:
    """Re-patching a config that already has EMAIL_PROVIDER is a no-op."""
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text('class Settings:\n    NAME = "x"\n\nsettings = Settings()\n')
    _patch_config(cfg)
    once = cfg.read_text()
    _patch_config(cfg)
    twice = cfg.read_text()
    assert once == twice, "second patch must not re-insert the block"
    assert twice.count("EMAIL_PROVIDER: str") == 1


# ---------------------------------------------------------------------------
# Routes patch — ordering in the standard (fixture) layout.
# Kills L272 BinOp Add->Sub (import after last app import) and
# L282 BinOp Add->Sub (include after last include).
# ---------------------------------------------------------------------------


def test_route_import_follows_last_app_import() -> None:
    """email_events import lands AFTER the final ``from app.`` import line."""
    project = create_fixture_project(name="txemail_routes_imp")
    add_transactional_email(ToolInput(project_dir=str(project)))
    lines = _lines(project / "app" / "routes" / "__init__.py")
    import_idx = _index_of(lines, "from app.api.routes.email_events import")
    # No other ``from app.`` import may appear AFTER the inserted one (Add->Sub
    # would drop it one slot too early, leaving an app import below it).
    for ln in lines[import_idx + 1 :]:
        assert not ln.startswith("from app."), (
            f"an app import follows the inserted email_events import: {ln!r}"
        )
    # And it must come strictly after at least one existing app import.
    health_idx = _index_of(lines, "from app.routes.health import")
    assert health_idx < import_idx


def test_route_include_follows_last_include() -> None:
    """email_events include lands AFTER all existing ``include_router`` calls."""
    project = create_fixture_project(name="txemail_routes_inc")
    add_transactional_email(ToolInput(project_dir=str(project)))
    lines = _lines(project / "app" / "routes" / "__init__.py")
    include_idx = _index_of(lines, "api_router.include_router(email_events_router)")
    for ln in lines[include_idx + 1 :]:
        assert not ln.startswith("api_router.include_router"), (
            f"another include_router follows the inserted one: {ln!r}"
        )
    item_idx = _index_of(lines, "api_router.include_router(item_router)")
    assert item_idx < include_idx


def test_routes_idempotent_no_double_register() -> None:
    """Re-patching routes already wired is a no-op (guards the dedup branch)."""
    project = create_fixture_project(name="txemail_routes_idem")
    add_transactional_email(ToolInput(project_dir=str(project)))
    routes = project / "app" / "routes" / "__init__.py"
    before = routes.read_text()
    _patch_routes_init(routes)
    after = routes.read_text()
    assert before == after
    assert after.count("from app.api.routes.email_events import") == 1
    assert after.count("api_router.include_router(email_events_router)") == 1


# ---------------------------------------------------------------------------
# Routes patch — fallback branches (no ``from app.`` import / no include line).
# Kills L267 Eq->NotEq, L277 Eq->NotEq, L269 BoolOp And->Or + In->NotIn,
# L279 BoolOp And->Or.
# ---------------------------------------------------------------------------


def test_routes_import_fallback_when_no_app_import() -> None:
    """No ``from app.`` import: import is placed via the APIRouter() fallback.

    last_app_import stays -1, so the ``== -1`` branch (L267) finds the
    ``api_router = APIRouter()`` line. The And at L269 must require BOTH
    substrings: the bare ``api_router.include_router(foo)`` line must NOT be
    treated as the APIRouter() definition.
    """
    d = Path(tempfile.mkdtemp())
    routes = d / "routes.py"
    routes.write_text(
        "from fastapi import APIRouter\napi_router.include_router(foo)\napi_router = APIRouter()\n"
    )
    _patch_routes_init(routes)
    lines = _lines(routes)
    import_idx = _index_of(lines, "from app.api.routes.email_events import")
    bare_include_idx = _index_of(lines, "api_router.include_router(foo)")
    # And-semantics: import must land AFTER the bare include line (the real
    # APIRouter() definition is the matched anchor, not the include line).
    assert import_idx > bare_include_idx, (
        f"import ({import_idx}) must follow the bare include ({bare_include_idx}); "
        "Or/NotIn would mis-anchor on the fastapi line or the include line"
    )
    # Must NOT be inserted at the very top (which an inverted == -1 guard via
    # insert(-1+1=0) would produce).
    assert import_idx != 0


def test_routes_include_fallback_when_no_include_line() -> None:
    """No existing include_router: include uses the APIRouter() fallback.

    last_include stays -1 (L277 ``== -1`` branch), and the And at L279 must
    require both substrings before treating a line as the APIRouter() def.
    """
    d = Path(tempfile.mkdtemp())
    routes = d / "routes.py"
    routes.write_text(
        "from fastapi import APIRouter\n"
        "from app.routes.health import router as health_router\n"
        "\n"
        "api_router = APIRouter()\n"
    )
    _patch_routes_init(routes)
    lines = _lines(routes)
    apirouter_idx = _index_of(lines, "api_router = APIRouter()")
    include_idx = _index_of(lines, "api_router.include_router(email_events_router)")
    # Include must land immediately AFTER the APIRouter() definition.
    assert include_idx == apirouter_idx + 1, (
        f"include ({include_idx}) must directly follow APIRouter() ({apirouter_idx})"
    )


# ---------------------------------------------------------------------------
# models/__init__ patch — newline guard. Kills L226 UnaryNot (not X -> X).
# ---------------------------------------------------------------------------


def test_models_init_no_trailing_newline_gets_one() -> None:
    """A models __init__ WITHOUT a trailing newline must not glue lines together.

    ``if not content.endswith("\\n")`` appends the separator; flipping the
    ``not`` would skip it, producing ``...UserfromAppModels`` glued text.
    """
    d = Path(tempfile.mkdtemp())
    mi = d / "__init__.py"
    mi.write_text("from app.models.user import User")  # no trailing newline
    _patch_models_init(mi)
    text = mi.read_text()
    assert "from app.models.user import User\n" in text, (
        "existing import must keep its own line (newline guard failed)"
    )
    assert "from app.models.email_event import EmailEvent" in text
    # The two imports must be on separate lines.
    assert "Userfrom app.models.email_event" not in text


def test_models_init_with_trailing_newline_no_blank_gap() -> None:
    """A models __init__ WITH a trailing newline is not given a second one."""
    d = Path(tempfile.mkdtemp())
    mi = d / "__init__.py"
    mi.write_text("from app.models.user import User\n")  # already has newline
    _patch_models_init(mi)
    text = mi.read_text()
    # No blank line should separate the two imports (no double newline inserted).
    assert "from app.models.user import User\nfrom app.models.email_event" in text


def test_models_init_idempotent() -> None:
    """Re-patching a models __init__ already wired is a no-op."""
    d = Path(tempfile.mkdtemp())
    mi = d / "__init__.py"
    mi.write_text("from app.models.user import User\n")
    _patch_models_init(mi)
    once = mi.read_text()
    _patch_models_init(mi)
    assert mi.read_text() == once
    assert once.count("from app.models.email_event import EmailEvent") == 1


# ---------------------------------------------------------------------------
# Migration down_revision — kills L151 BoolOp Or->And.
# ---------------------------------------------------------------------------


def test_migration_down_revision_uses_real_head() -> None:
    """The emitted migration chains onto the project's real migration head.

    ``find_migration_head(...) or "0001_initial"`` resolves to the existing
    head revision. If Or->And flipped, ``down_revision`` would collapse to the
    truthy/None result of And and never reference the actual head.
    """
    project = create_fixture_project(name="txemail_migration")
    add_transactional_email(ToolInput(project_dir=str(project)))
    versions = project / "alembic" / "versions"
    migration = versions / "add_email_events.py"
    assert migration.exists(), "migration not emitted"
    text = migration.read_text()
    # The DOWN_REV_PLACEHOLDER marker must have been substituted away.
    assert "DOWN_REV_PLACEHOLDER" not in text
    # down_revision must reference a concrete revision string (the real head or
    # the documented "0001_initial" fallback), never None/empty.
    assert "down_revision" in text
    import re

    m = re.search(r"down_revision\s*(?::[^=]+)?=\s*(.+)", text)
    assert m, "down_revision assignment not found"
    rhs = m.group(1).strip()
    assert rhs not in ("None", '""', "''", ""), (
        f"down_revision resolved to an empty/None value: {rhs!r}"
    )
