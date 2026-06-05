"""Generic + tool-specific mutation coverage for add_stripe_subscription.

The generic block applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests.

The bespoke block below targets the operators the generic checks cannot
reach: the anchor-relative config insertion (``_patch_config``), the
import/include insertion positions and fallbacks in ``_patch_routes_init``,
and the trailing-newline guard in ``_patch_models_init``. Run alongside
test_add_stripe_subscription.py in the mutation runner:
``--tests test_add_stripe_subscription.py test_add_stripe_subscription_contract.py``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from adapt.extend.infrastructure.add_stripe_subscription import (
    _patch_config,
    _patch_models_init,
    _patch_routes_init,
)
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_stripe_subscription import add_stripe_subscription

    for check in SCAFFOLDABLE_CHECKS:
        check(add_stripe_subscription, "add_stripe_subscription")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmpfile(text: str) -> Path:
    d = Path(tempfile.mkdtemp())
    f = d / "config.py"
    f.write_text(text)
    return f


# ---------------------------------------------------------------------------
# _patch_config — anchor-relative insertion (L237 / L239 / L240 / L242)
# ---------------------------------------------------------------------------


def test_config_block_inserted_right_after_anchor() -> None:
    """L237 In->NotIn: when the ACCESS_TOKEN anchor is present, the Stripe
    block is inserted DIRECTLY after the anchor line (not at EOF / before
    settings). Flipping ``anchor in src`` skips this branch and the block
    lands elsewhere, so its position relative to the anchor changes."""
    src = (
        "class Settings:\n"
        '    SECRET_KEY: str = "x"\n'
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n"
        '    OTHER_FIELD: str = "keep"\n'
        "\n"
        "settings = Settings()\n"
    )
    f = _tmpfile(src)
    _patch_config(f)
    lines = f.read_text().splitlines()
    anchor_idx = next(
        i for i, ln in enumerate(lines) if "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30" in ln
    )
    secret_idx = next(i for i, ln in enumerate(lines) if "STRIPE_SECRET_KEY" in ln)
    # The block follows the anchor immediately (a comment line then the field),
    # and crucially is BEFORE the OTHER_FIELD line that came after the anchor.
    other_idx = next(i for i, ln in enumerate(lines) if "OTHER_FIELD" in ln)
    assert anchor_idx < secret_idx < other_idx, (
        f"Stripe block must sit between anchor and the following field; "
        f"anchor={anchor_idx} secret={secret_idx} other={other_idx}"
    )


def test_config_settings_branch_inserts_before_settings_call() -> None:
    """L239 In->NotIn + L240 Add->Sub: with NO anchor but a
    ``settings = Settings()`` line, the block is inserted immediately BEFORE
    that line. Flipping the elif Compare or the string-concat reorders /
    corrupts the result so the block no longer precedes the settings call."""
    src = 'class Settings:\n    SECRET_KEY: str = "x"\n\nsettings = Settings()\n'
    f = _tmpfile(src)
    _patch_config(f)
    out = f.read_text()
    lines = out.splitlines()
    secret_idx = next(i for i, ln in enumerate(lines) if "STRIPE_SECRET_KEY" in ln)
    settings_idx = next(i for i, ln in enumerate(lines) if "settings = Settings()" in ln)
    assert secret_idx < settings_idx, (
        "block must be inserted before the `settings = Settings()` call"
    )
    # L240 Add->Sub would drop the trailing "\n\nsettings = Settings()" suffix;
    # assert the settings call survives exactly once after the block.
    assert out.count("settings = Settings()") == 1


def test_config_else_branch_appends_block_at_end() -> None:
    """L242 Add->Sub: with neither the anchor nor a settings call, the block
    is appended at the END of the file. Flipping the ``rstrip + '\\n' + block``
    concat (Sub) raises a TypeError instead of appending."""
    src = 'class Settings:\n    SECRET_KEY: str = "x"\n'
    f = _tmpfile(src)
    _patch_config(f)
    out = f.read_text()
    assert "STRIPE_SECRET_KEY" in out
    # Original content preserved AND block lands after it.
    assert out.index("SECRET_KEY: str") < out.index("STRIPE_SECRET_KEY")
    assert out.rstrip().endswith(
        'STRIPE_BILLING_PORTAL_RETURN_URL: str = "http://localhost:8000/billing"'
    )


# ---------------------------------------------------------------------------
# _patch_routes_init — import insertion (L257 / L262)
# ---------------------------------------------------------------------------


def _routes_with_app_imports() -> Path:
    d = Path(tempfile.mkdtemp())
    f = d / "__init__.py"
    f.write_text(
        '"""Route registration."""\n'
        "\n"
        "from fastapi import APIRouter\n"
        "\n"
        "from app.api.routes.item import router as item_router\n"
        "from app.api.routes.users import router as users_router\n"
        "\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(item_router)\n"
        "api_router.include_router(users_router)\n"
    )
    return f


def test_routes_import_inserted_after_last_app_import() -> None:
    """L257 Eq->NotEq + L262 Add->Sub: when there ARE ``from app.`` imports,
    the fallback is skipped and the subscriptions import is inserted on the
    line immediately AFTER the last ``from app.`` import (idx+1). Flipping the
    ``== -1`` Compare runs the fallback (wrong anchor); flipping ``idx + 1``
    inserts one line too early (above the last app import)."""
    f = _routes_with_app_imports()
    _patch_routes_init(f)
    lines = f.read_text().splitlines()
    last_app_idx = max(
        i for i, ln in enumerate(lines) if ln.startswith("from app.") and "subscriptions" not in ln
    )
    import_idx = next(
        i for i, ln in enumerate(lines) if "import router as subscriptions_router" in ln
    )
    assert import_idx == last_app_idx + 1, (
        f"subscriptions import must be exactly after the last app import; "
        f"last_app={last_app_idx} import={import_idx}"
    )


def test_routes_include_inserted_after_last_include() -> None:
    """L267 Eq->NotEq + L272 Add->Sub: when there ARE existing
    ``api_router.include_router`` lines, the include for subscriptions is
    inserted on the line immediately AFTER the last existing include (idx+1).
    Flipping ``== -1`` runs the fallback; flipping ``idx + 1`` mis-positions
    the inserted include."""
    f = _routes_with_app_imports()
    _patch_routes_init(f)
    lines = f.read_text().splitlines()
    include_indices = [
        i for i, ln in enumerate(lines) if ln.startswith("api_router.include_router")
    ]
    sub_include_idx = next(
        i
        for i, ln in enumerate(lines)
        if ln.startswith("api_router.include_router(subscriptions_router)")
    )
    # The subscriptions include is the LAST include, sitting right after the
    # previous one (users_router).
    prev_includes = [i for i in include_indices if i != sub_include_idx]
    assert sub_include_idx == max(prev_includes) + 1, (
        f"subscriptions include must be right after the last existing include; "
        f"got {sub_include_idx}, prev_max={max(prev_includes)}"
    )


# ---------------------------------------------------------------------------
# _patch_routes_init — fallback branches (L259 / L260 / L269)
# ---------------------------------------------------------------------------


def _routes_no_app_imports() -> Path:
    """routes_init that has NO ``from app.`` imports and NO existing
    include_router lines — forces both fallback branches."""
    d = Path(tempfile.mkdtemp())
    f = d / "__init__.py"
    f.write_text(
        '"""Route registration."""\nfrom fastapi import APIRouter\n\napi_router = APIRouter()\n'
    )
    return f


def test_routes_import_fallback_inserts_before_apirouter_line() -> None:
    """L259 (In->NotIn / And->Or) + L260 (Sub->Add): with no ``from app.``
    imports, the fallback locates the ``api_router = APIRouter()`` line and
    sets the import-anchor to ``idx - 1``, so the import is inserted just
    BEFORE that line. Flipping the And->Or / In->NotIn breaks line detection;
    flipping ``idx - 1`` to ``idx + 1`` would place the import AFTER the
    APIRouter() line instead of before it."""
    f = _routes_no_app_imports()
    _patch_routes_init(f)
    lines = f.read_text().splitlines()
    apirouter_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    import_idx = next(
        i for i, ln in enumerate(lines) if "import router as subscriptions_router" in ln
    )
    assert import_idx < apirouter_idx, (
        f"fallback import must be inserted before the APIRouter() line; "
        f"import={import_idx} apirouter={apirouter_idx}"
    )


def test_routes_include_fallback_inserts_after_apirouter_line() -> None:
    """L269 (And->Or / In->NotIn): with no existing ``include_router`` lines,
    the include fallback locates ``api_router = APIRouter()`` and inserts the
    subscriptions include right AFTER it. Flipping And->Or makes the condition
    match the wrong line; flipping In->NotIn skips the only candidate so no
    include lands."""
    f = _routes_no_app_imports()
    _patch_routes_init(f)
    out = f.read_text()
    lines = out.splitlines()
    assert "api_router.include_router(subscriptions_router)" in out, (
        "fallback must still emit the include line"
    )
    apirouter_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    include_idx = next(
        i
        for i, ln in enumerate(lines)
        if ln.startswith("api_router.include_router(subscriptions_router)")
    )
    assert include_idx > apirouter_idx, (
        f"fallback include must come after the APIRouter() line; "
        f"include={include_idx} apirouter={apirouter_idx}"
    )


# ---------------------------------------------------------------------------
# _patch_models_init — trailing-newline guard (L220)
# ---------------------------------------------------------------------------


def test_models_init_marker_on_own_line_when_no_trailing_newline() -> None:
    """L220 UnaryNot: when the existing __init__ does NOT end in a newline,
    the guard appends one so the new import sits on its OWN line. Flipping
    ``not content.endswith('\\n')`` skips that, fusing the new import onto the
    last existing line and producing a broken statement."""
    d = Path(tempfile.mkdtemp())
    f = d / "__init__.py"
    f.write_text("from app.models.user import User  # noqa: F401")  # no trailing \n
    _patch_models_init(f, [("subscription", "Subscription")])
    lines = f.read_text().splitlines()
    # The Subscription import must be a standalone line, not glued to User.
    sub_lines = [ln for ln in lines if "Subscription" in ln]
    assert sub_lines, "Subscription import not added"
    assert sub_lines[0].startswith("from app.models.subscription import Subscription"), (
        f"Subscription import fused onto previous line: {sub_lines[0]!r}"
    )
    # The original User import line must remain intact (not corrupted).
    assert any(ln.strip() == "from app.models.user import User  # noqa: F401" for ln in lines)
