"""Generic + tool-specific mutation coverage for add_stripe_refund_flow.

The generic block applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests.

The tool-specific block below targets the orchestration-only mutants that the
shared checks and the bespoke ``test_add_stripe_refund_flow.py`` leave
surviving: the config/route insertion *position* and *anchor* selection, the
migration ``down_revision`` seeding, the ``models/__init__`` newline guard, and
the per-branch fallbacks in ``_patch_config`` / ``_patch_routes_init``. We call
the module-level helpers directly for precise branch coverage where a fixture
project cannot reach the fallback branch (the fixture always carries the canonical
anchor + ``from app.`` imports).

Run alongside test_add_stripe_refund_flow.py in the mutation runner:
``--tests test_add_stripe_refund_flow.py test_add_stripe_refund_flow_contract.py``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_stripe_refund_flow import (
    _patch_config,
    _patch_models_init,
    _patch_routes_init,
    add_stripe_refund_flow,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_stripe_refund_flow, "add_stripe_refund_flow")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_file(content: str, name: str = "f.py") -> Path:
    d = Path(tempfile.mkdtemp())
    f = d / name
    f.write_text(content)
    return f


def _run_on_fixture(name: str) -> Path:
    project_dir = create_fixture_project(name=name)
    result = add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"tool failed: {result.error}"
    return project_dir


# ---------------------------------------------------------------------------
# L121 — files_created seed: ``list(scaffolded or [])``
# Or→And flips ``False or []`` (→ []) to ``False and []`` (→ False), and
# ``list(False)`` raises TypeError → the tool errors instead of succeeding.
# (scaffolded is falsy on a fully-formed fixture: nothing to auto-scaffold.)
# ---------------------------------------------------------------------------


def test_files_created_seed_succeeds_when_nothing_scaffolded() -> None:
    # scaffolded is falsy on a fully-formed fixture: `False or []` → []; the And
    # mutant yields `False`, and `list(False)` raises TypeError → tool errors and
    # files_created would never be a populated list.
    project_dir = create_fixture_project(name="refund_ct_seed")
    res = add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    assert res.status == "success", f"seed branch must succeed: {res.error}"
    assert isinstance(res.files_created, list)
    assert len(res.files_created) >= 5


# ---------------------------------------------------------------------------
# L155 — migration down_revision: ``find_migration_head(...) or "0001_initial"``
# Or→And flips a real head ("0002_...") to the literal "0001_initial", so the
# generated migration would chain off the wrong (stale) revision.
# ---------------------------------------------------------------------------


def test_migration_down_revision_is_actual_head() -> None:
    from adapt.contracts.migration_helper import find_migration_head

    project_dir = create_fixture_project(name="refund_ct_downrev")
    versions = project_dir / "alembic" / "versions"
    head = find_migration_head(versions)
    assert head and head != "0001_initial", (
        "fixture must have a real migration head distinct from the fallback"
    )
    add_stripe_refund_flow(ToolInput(project_dir=str(project_dir)))
    migration = (versions / "add_stripe_refund_flow.py").read_text()
    assert f'down_revision = "{head}"' in migration, (
        f"migration must chain off the actual head {head!r}, not the '0001_initial' fallback"
    )


# ---------------------------------------------------------------------------
# L211 — _patch_models_init newline guard: ``if not content.endswith("\n")``
# UnaryNot ``not X``→``X`` inverts the guard: a file NOT ending in a newline
# would skip the appended "\n", concatenating the new import onto the last line.
# ---------------------------------------------------------------------------


def test_models_init_appends_on_own_line_when_no_trailing_newline() -> None:
    # No trailing newline: original adds "\n" first; mutant (X) skips it.
    f = _tmp_file("from app.models.user import User  # noqa: F401", name="__init__.py")
    _patch_models_init(f, [("refund", "Refund")])
    lines = f.read_text().splitlines()
    assert lines[0] == "from app.models.user import User  # noqa: F401", (
        "existing import must remain on its own line (not have Refund glued on)"
    )
    assert any(line == "from app.models.refund import Refund  # noqa: F401" for line in lines), (
        "Refund import must be on its own line after the newline guard"
    )


def test_models_init_does_not_double_glue_imports() -> None:
    # The exact failure the mutant causes: no line should contain BOTH imports.
    f = _tmp_file("from app.models.user import User  # noqa: F401", name="__init__.py")
    _patch_models_init(f, [("refund", "Refund")])
    for line in f.read_text().splitlines():
        assert not ("User" in line and "Refund" in line), (
            f"imports glued onto one line (newline guard inverted): {line!r}"
        )


# ---------------------------------------------------------------------------
# L228 — _patch_config anchor branch: ``if anchor in src``
# In→NotIn flips the anchor-present project onto the settings/else branch, so
# the refund block is no longer inserted directly after ACCESS_TOKEN_EXPIRE.
# ---------------------------------------------------------------------------


def test_config_block_inserted_right_after_anchor() -> None:
    src = (
        "class Settings:\n"
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n"
        "    OTHER: int = 1\n\n"
        "settings = Settings()\n"
    )
    f = _tmp_file(src, name="config.py")
    _patch_config(f)
    out = f.read_text()
    anchor = "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n"
    assert anchor in out
    after_anchor = out[out.index(anchor) + len(anchor) :]
    assert after_anchor.lstrip().startswith("# --- Stripe refunds"), (
        "block must be inserted immediately after the ACCESS_TOKEN anchor line"
    )
    # And it must precede `settings = Settings()` (proves NOT the else/append path).
    assert out.index("STRIPE_REFUND_WEBHOOK_SECRET") < out.index("settings = Settings()")


# ---------------------------------------------------------------------------
# L230/L231/L233 — _patch_config no-anchor branches
# L230 In→NotIn flips the settings-present config onto the else (append) branch;
# L231/L233 Add→Sub break the string concatenation (TypeError) for each branch.
# ---------------------------------------------------------------------------


def test_config_settings_branch_inserts_before_settings_line() -> None:
    # No anchor, has `settings = Settings()` → settings branch (L230/L231).
    src = "class Settings:\n    FOO: int = 1\n\nsettings = Settings()\n"
    f = _tmp_file(src, name="config.py")
    _patch_config(f)
    out = f.read_text()
    assert "STRIPE_REFUND_WEBHOOK_SECRET" in out
    # Block must be BEFORE the settings instantiation, not appended at EOF.
    assert out.index("STRIPE_REFUND_WEBHOOK_SECRET") < out.index("settings = Settings()"), (
        "no-anchor+settings config must insert block before `settings = Settings()`"
    )
    # The settings line must survive exactly once (L231 Sub would have crashed).
    assert out.count("settings = Settings()") == 1


def test_config_else_branch_appends_at_end() -> None:
    # No anchor, no settings line → else branch (L233 Add→Sub would crash).
    src = "class Settings:\n    FOO: int = 1\n"
    f = _tmp_file(src, name="config.py")
    _patch_config(f)
    out = f.read_text()
    assert out.startswith("class Settings:\n    FOO: int = 1\n"), (
        "original content must be preserved at the top"
    )
    assert out.rstrip().endswith("REFUND_AUTO_APPROVE_THRESHOLD_CENTS: int = 5_000"), (
        "else branch must append the refund block at the end of the file"
    )


# ---------------------------------------------------------------------------
# L248/L250/L251/L253 — _patch_routes_init import insertion
# Standard path: import lands right after the last `from app.` import.
# Fallback (no `from app.`): import lands right before `api_router = APIRouter()`.
# ---------------------------------------------------------------------------


def test_routes_import_after_last_app_import_in_fixture() -> None:
    # Standard path (L253 Add→Sub would mis-place the insert by one line).
    project_dir = _run_on_fixture("refund_ct_routes_std")
    out = (project_dir / "app" / "routes" / "__init__.py").read_text()
    lines = out.splitlines()
    imp_idx = next(i for i, line in enumerate(lines) if "import router as refunds_router" in line)
    # The line immediately above must be the LAST pre-existing `from app.` import.
    assert lines[imp_idx - 1].startswith("from app."), (
        f"refunds import must follow the last `from app.` import; "
        f"got prev line {lines[imp_idx - 1]!r}"
    )
    # The block of `from app.` imports must be contiguous (no foreign line wedged
    # in by an off-by-one insert from L253 Sub).
    assert lines[imp_idx].startswith("from app.api.routes.refunds")


def test_routes_import_fallback_before_apirouter_def() -> None:
    # Fallback path: no `from app.` imports (L248 Eq→NotEq, L251 Sub→Add,
    # L250 and→or / in→notin all change this insert position).
    content = (
        "# api_router is configured here\n"
        "from fastapi import APIRouter\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(other_router)\n"
    )
    f = _tmp_file(content, name="__init__.py")
    _patch_routes_init(f)
    lines = f.read_text().splitlines()
    imp_idx = next(i for i, line in enumerate(lines) if "import router as refunds_router" in line)
    def_idx = next(i for i, line in enumerate(lines) if line == "api_router = APIRouter()")
    # Import must sit immediately before the `api_router = APIRouter()` line, and
    # NOT at the very top (which is what the Eq→NotEq / and→or mutants produce).
    assert imp_idx == def_idx - 1, (
        f"fallback import must be right before APIRouter() def: "
        f"import@{imp_idx} def@{def_idx} lines={lines}"
    )
    assert imp_idx != 0, "fallback import must not be wedged at file top"
    # The leading comment (contains 'api_router' but not 'APIRouter()') must NOT
    # be chosen as the anchor — that is exactly what and→or would do.
    assert lines[0].startswith("# api_router"), "leading comment must be untouched"


# ---------------------------------------------------------------------------
# L258/L260/L263 — _patch_routes_init include insertion
# Standard path: include lands right after the last `include_router` line.
# Fallback (no include_router): include lands right after `api_router = APIRouter()`.
# ---------------------------------------------------------------------------


def test_routes_include_after_last_include_in_fixture() -> None:
    # Standard path (L263 Add→Sub mis-places the include insert).
    project_dir = _run_on_fixture("refund_ct_include_std")
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    inc_idx = next(i for i, line in enumerate(lines) if "include_router(refunds_router)" in line)
    assert lines[inc_idx - 1].startswith("api_router.include_router("), (
        f"refunds include must follow the last existing include_router line; "
        f"got prev {lines[inc_idx - 1]!r}"
    )


def test_routes_include_fallback_after_apirouter_def() -> None:
    # Fallback path: no `include_router` line at all (L258 Eq→NotEq,
    # L260 and→or / in→notin change this insert position).
    content = "# api_router lives here\nfrom fastapi import APIRouter\napi_router = APIRouter()\n"
    f = _tmp_file(content, name="__init__.py")
    _patch_routes_init(f)
    lines = f.read_text().splitlines()
    inc_idx = next(i for i, line in enumerate(lines) if "include_router(refunds_router)" in line)
    def_idx = next(i for i, line in enumerate(lines) if line == "api_router = APIRouter()")
    assert inc_idx == def_idx + 1, (
        f"fallback include must sit right after APIRouter() def: "
        f"include@{inc_idx} def@{def_idx} lines={lines}"
    )
    # The leading comment must not be chosen by an and→or relaxed match.
    assert lines[0].startswith("# api_router"), "leading comment must be untouched"
