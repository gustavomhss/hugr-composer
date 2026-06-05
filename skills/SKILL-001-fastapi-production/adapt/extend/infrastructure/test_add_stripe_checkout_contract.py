"""Generic tool-contract mutation coverage for add_stripe_checkout.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_stripe_checkout.py in the mutation
runner: ``--tests test_add_stripe_checkout.py test_add_stripe_checkout_contract.py``.
"""

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_stripe_checkout import add_stripe_checkout
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_stripe_checkout, "add_stripe_checkout")


# ---------------------------------------------------------------------------
# Tool-specific mutation kills (logic NOT covered by the generic preamble).
# ---------------------------------------------------------------------------


def _config_lines(project_dir):
    return (project_dir / "app" / "core" / "config.py").read_text().splitlines()


def test_config_block_lands_right_after_access_token_anchor():
    """L276 (In), L301-ish placement: the STRIPE block is inserted directly
    after the ACCESS_TOKEN_EXPIRE_MINUTES anchor, inside the Settings class.

    A NotIn flip would skip the anchor branch entirely (block appended at EOF,
    outside the class), so STRIPE_SECRET_KEY would NOT immediately follow the
    anchor line.
    """
    project_dir = create_fixture_project(name="stripe_c_anchor")
    result = add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    lines = _config_lines(project_dir)
    anchor_idx = next(
        i for i, ln in enumerate(lines) if "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30" in ln
    )
    # The very next non-empty line introduces the Stripe block (comment),
    # and STRIPE_SECRET_KEY appears within the next few lines, still indented
    # as a class attribute (4-space indent).
    following = lines[anchor_idx + 1 : anchor_idx + 8]
    assert any("Stripe payments" in ln for ln in following), (
        f"Stripe block not placed immediately after anchor: {following!r}"
    )
    secret_line = next(ln for ln in following if "STRIPE_SECRET_KEY" in ln and ":" in ln)
    assert secret_line.startswith("    "), (
        f"STRIPE_SECRET_KEY must stay inside Settings class body: {secret_line!r}"
    )


def test_config_block_omitted_when_already_present():
    """L325-twin (_patch_config L263 guard): second run is a no_op and never
    duplicates the STRIPE_SECRET_KEY field in config.py.
    """
    project_dir = create_fixture_project(name="stripe_c_dup")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    config_text = (project_dir / "app" / "core" / "config.py").read_text()
    # Exactly one declaration of the Stripe block.
    assert config_text.count("STRIPE_SECRET_KEY: str") == 1
    r2 = add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op"
    after = (project_dir / "app" / "core" / "config.py").read_text()
    assert after.count("STRIPE_SECRET_KEY: str") == 1, "Stripe config block duplicated"


def test_config_block_appended_when_anchor_and_settings_marker_absent():
    """L276 (In→NotIn) + L278 (In→NotIn): when neither the ACCESS_TOKEN anchor
    nor 'settings = Settings()' exist, the block is appended at EOF.

    Drives the final ``else`` branch and asserts the field still lands.
    """
    project_dir = create_fixture_project(name="stripe_c_else")
    config_file = project_dir / "app" / "core" / "config.py"
    # Strip both the anchor and the settings marker so only the else path runs.
    src = config_file.read_text()
    src = src.replace("ACCESS_TOKEN_EXPIRE_MINUTES: int = 30", "ATEM_PLACEHOLDER = 30")
    src = src.replace("settings = Settings()", "_settings_obj = None  # marker removed")
    config_file.write_text(src)
    result = add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    text = config_file.read_text()
    assert "STRIPE_SECRET_KEY" in text
    # No anchor / marker present, so the block is appended at the tail.
    assert text.rstrip().endswith(
        'STRIPE_CHECKOUT_CANCEL_URL: str = "http://localhost:8000/cancel"'
    )


def test_config_block_placed_before_settings_instantiation_fallback():
    """L278 (In→NotIn): with the anchor removed but 'settings = Settings()'
    present, the block is inserted *before* the instantiation, not appended
    after it. A NotIn flip skips this branch (falls through to else / EOF),
    placing the block AFTER ``settings = Settings()``.
    """
    project_dir = create_fixture_project(name="stripe_c_pre_settings")
    config_file = project_dir / "app" / "core" / "config.py"
    src = config_file.read_text()
    src = src.replace("ACCESS_TOKEN_EXPIRE_MINUTES: int = 30", "ATEM_PLACEHOLDER = 30")
    config_file.write_text(src)
    result = add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    text = config_file.read_text()
    stripe_idx = text.index("STRIPE_SECRET_KEY")
    settings_idx = text.index("settings = Settings()")
    assert stripe_idx < settings_idx, (
        "Stripe block must precede `settings = Settings()` in the fallback branch"
    )


def test_payments_import_after_last_app_import_and_before_router():
    """L296/L298 (Eq/And/In), L301 (Add→Sub): the payments import is inserted
    right after the LAST ``from app.`` import (so before ``api_router =
    APIRouter()``), and the include is appended after the existing includes.

    Add→Sub at L301 would shift the import one line up (before the last app
    import); the Eq/-1 fallback only triggers when no app imports exist.
    """
    project_dir = create_fixture_project(name="stripe_routes_order")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    import_idx = next(i for i, ln in enumerate(lines) if "payments_router" in ln and "import" in ln)
    apirouter_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    # Import must precede the APIRouter() construction.
    assert import_idx < apirouter_idx
    # The import directly follows the last 'from app.' import (no other line
    # between the payments import and the previous app import).
    prev = lines[import_idx - 1]
    assert prev.startswith("from app."), (
        f"payments import not placed right after last app import; prev={prev!r}"
    )


def test_payments_include_appended_after_existing_includes():
    """L311 (Add→Sub) + L306/L308: the include line lands right after the LAST
    existing ``api_router.include_router(...)`` call. Add→Sub would insert it
    before the last include (or atop the block).
    """
    project_dir = create_fixture_project(name="stripe_include_order")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    include_idxs = [i for i, ln in enumerate(lines) if "include_router(" in ln]
    payments_idx = next(i for i, ln in enumerate(lines) if "include_router(payments_router)" in ln)
    # The payments include is the LAST include line.
    assert payments_idx == max(include_idxs), "payments include must be the last include"
    # And the line directly above it is another include (item_router), proving
    # it was appended after the existing includes, not before them.
    assert "include_router(" in lines[payments_idx - 1], (
        f"payments include not appended after existing includes: prev={lines[payments_idx - 1]!r}"
    )


def test_routes_fallback_branches_when_no_app_imports():
    """L296 (Eq→NotEq) + L298 (And/In) + L306 (Eq→NotEq) + L308 (And/In):
    a routes __init__ with NO ``from app.`` imports and NO existing includes
    forces both ``-1`` sentinel branches, which anchor on the
    ``api_router = APIRouter()`` line.

    Eq→NotEq would skip the fallback (leaving last_*_idx at -1 → insert at
    index 0); And→Or / In→NotIn would mis-locate or fail to find the anchor.
    We assert the import precedes the APIRouter line and the include follows it.
    """
    project_dir = create_fixture_project(name="stripe_routes_fallback")
    ri = project_dir / "app" / "routes" / "__init__.py"
    ri.write_text("from fastapi import APIRouter\n\napi_router = APIRouter()\n")
    result = add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    lines = ri.read_text().splitlines()
    import_idx = next(i for i, ln in enumerate(lines) if "import router as payments_router" in ln)
    apirouter_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    include_idx = next(i for i, ln in enumerate(lines) if "include_router(payments_router)" in ln)
    assert import_idx < apirouter_idx, "import must come before APIRouter() in fallback"
    assert include_idx == apirouter_idx + 1, (
        f"include must come right after APIRouter() in fallback; lines={lines!r}"
    )


def test_routes_init_idempotent_no_double_register():
    """_patch_routes_init L289 guard: a second run must NOT re-import or
    re-include the payments router.
    """
    project_dir = create_fixture_project(name="stripe_routes_idem")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    text = (project_dir / "app" / "routes" / "__init__.py").read_text()
    assert text.count("import router as payments_router") == 1
    assert text.count("include_router(payments_router)") == 1
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))  # no_op
    text2 = (project_dir / "app" / "routes" / "__init__.py").read_text()
    assert text2.count("import router as payments_router") == 1
    assert text2.count("include_router(payments_router)") == 1


def test_models_init_import_on_own_line():
    """L256 (UnaryNot not X→X): _patch_models_init ensures the file ends with a
    newline before appending, so the Payment import lands on its OWN line.

    Flipping ``not content.endswith(...)`` to ``content.endswith(...)`` would
    skip the newline-normalisation, gluing the import onto the previous line
    when the source did not already end in a newline.
    """
    project_dir = create_fixture_project(name="stripe_models_nl")
    mi = project_dir / "app" / "models" / "__init__.py"
    # Force a source WITHOUT a trailing newline to exercise the guard.
    mi.write_text(mi.read_text().rstrip("\n"))
    result = add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    lines = mi.read_text().splitlines()
    payment_line = next(ln for ln in lines if "from app.models.payment import Payment" in ln)
    # The import must be a clean standalone line, not concatenated onto the
    # previous import.
    assert payment_line.strip().startswith("from app.models.payment import Payment")
    # No other code glued onto the same physical line.
    assert payment_line.count("import") == 1, f"import glued onto another line: {payment_line!r}"


def test_models_init_idempotent_no_duplicate_import():
    """_patch_models_init dedup (L252 marker check): second run does not add a
    duplicate Payment import.
    """
    project_dir = create_fixture_project(name="stripe_models_idem")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    text = (project_dir / "app" / "models" / "__init__.py").read_text()
    assert text.count("from app.models.payment import Payment") == 1
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    text2 = (project_dir / "app" / "models" / "__init__.py").read_text()
    assert text2.count("from app.models.payment import Payment") == 1


def test_migration_down_revision_is_real_head_not_default():
    """L187 (Or→And): down_rev = find_migration_head(...) or "0001_initial".

    On a real fixture the alembic versions dir already has a head migration,
    so down_revision MUST be that real head, NOT the "0001_initial" literal.
    Or→And would force the literal even when a head exists.
    """
    project_dir = create_fixture_project(name="stripe_mig_head")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    mig = project_dir / "alembic" / "versions" / "add_stripe_checkout.py"
    assert mig.exists()
    down_line = next(
        ln for ln in mig.read_text().splitlines() if ln.strip().startswith("down_revision")
    )
    assert "0001_initial" not in down_line, (
        f"down_revision fell back to default despite a real head: {down_line!r}"
    )
    assert "0002" in down_line or "baseline" in down_line, (
        f"down_revision did not pin to the real migration head: {down_line!r}"
    )


def test_env_example_idempotent_no_double_block():
    """L325 (In→NotIn): the .env.example guard `if STRIPE_SECRET_KEY in src`
    prevents a duplicate Stripe block on re-run.
    """
    project_dir = create_fixture_project(name="stripe_env_idem")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    env = project_dir / ".env.example"
    text = env.read_text()
    assert text.count("STRIPE_SECRET_KEY=") == 1
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))  # no_op
    assert env.read_text().count("STRIPE_SECRET_KEY=") == 1


def test_requirements_idempotent_single_stripe_entry():
    """_patch_requirements L317 guard (`if "stripe" in src`): only one stripe
    pin is ever appended.
    """
    project_dir = create_fixture_project(name="stripe_req_idem")
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    req = project_dir / "requirements.txt"
    assert req.read_text().count("stripe>=") == 1
    add_stripe_checkout(ToolInput(project_dir=str(project_dir)))
    assert req.read_text().count("stripe>=") == 1
