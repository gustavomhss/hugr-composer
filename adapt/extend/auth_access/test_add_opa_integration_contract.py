"""Generic tool-contract mutation coverage for add_opa_integration.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_opa_integration.py in the mutation
runner: ``--tests test_add_opa_integration.py test_add_opa_integration_contract.py``.
"""

import time
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_opa_integration import (
    _elapsed_ms,
    _patch_config,
    _patch_requirements,
    _patch_routes_init,
    add_opa_integration,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_opa_integration import add_opa_integration

    for check in SCAFFOLDABLE_CHECKS:
        check(add_opa_integration, "add_opa_integration")


# ---------------------------------------------------------------------------
# Tool-specific survivors (logic the generic contract does NOT cover)
# ---------------------------------------------------------------------------


def test_elapsed_ms_scales_to_milliseconds() -> None:
    """L38 Mult->FloorDiv: elapsed must be reported in milliseconds, not seconds.

    A start ~2s in the past must yield ~2000ms. The mutant ``// 1000`` would
    floor a 2s span to 0 (then clamped to 1), so anything >= 1000 kills it.
    """
    two_seconds_ago = time.monotonic() - 2.0
    assert _elapsed_ms(two_seconds_ago) >= 1000


def test_patch_config_else_branch_appends_without_marker(tmp_path: Path) -> None:
    """L209 BinOp Add->Sub: config WITHOUT the ``settings = Settings()`` marker.

    Drives the else-branch (string concatenation). The mutant flips ``+`` to
    ``-`` on str operands, which raises TypeError; the original appends the
    OPA fields to the end of the file.
    """
    cfg = tmp_path / "config.py"
    original = "class Settings:\n    DEBUG: bool = True\n"
    cfg.write_text(original)
    _patch_config(cfg)
    patched = cfg.read_text()
    assert "settings = Settings()" not in patched  # confirm else-branch was taken
    assert patched.startswith(original.rstrip())
    for field in ("OPA_URL", "OPA_ENABLED", "OPA_POLICY_PATH", "OPA_TIMEOUT_MS", "OPA_FAIL_OPEN"):
        assert field in patched


def test_patch_routes_init_adds_missing_include_only(tmp_path: Path) -> None:
    """L217 BoolOp And->Or and Compare In->NotIn.

    File already has the import but NOT the include. The original must NOT
    early-return (both conditions required via ``and``) and must append the
    missing include line. The And->Or mutant would early-return on the import
    alone and leave the include absent.
    """
    ri = tmp_path / "__init__.py"
    ri.write_text("from app.api.routes.opa import router as opa_router\napi_router = APIRouter()\n")
    _patch_routes_init(ri)
    content = ri.read_text()
    assert "api_router.include_router(opa_router)" in content
    # import was already present — must not be duplicated
    assert content.count("from app.api.routes.opa import router as opa_router") == 1


def test_patch_routes_init_idempotent_when_both_present(tmp_path: Path) -> None:
    """L217 In->NotIn: when BOTH lines exist the helper must early-return.

    NotIn would invert the guard and re-append both lines (a double-insert).
    """
    ri = tmp_path / "__init__.py"
    ri.write_text(
        "from app.api.routes.opa import router as opa_router\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(opa_router)\n"
    )
    before = ri.read_text()
    _patch_routes_init(ri)
    after = ri.read_text()
    assert before == after
    assert after.count("api_router.include_router(opa_router)") == 1


def test_patch_routes_init_no_trailing_newline(tmp_path: Path) -> None:
    """L224 UnaryNot ``not content.endswith`` on a file lacking a trailing newline.

    The original adds a separating newline before the additions. The mutant
    (``if content.endswith``) would glue the import onto the last line, e.g.
    ``APIRouter()from app...``.
    """
    ri = tmp_path / "__init__.py"
    ri.write_text("api_router = APIRouter()")  # no trailing newline
    _patch_routes_init(ri)
    content = ri.read_text()
    assert "APIRouter()from" not in content
    assert "from app.api.routes.opa import router as opa_router" in content
    assert "\nfrom app.api.routes.opa import router as opa_router" in content


def test_patch_requirements_adds_httpx_when_absent(tmp_path: Path) -> None:
    """L232 Compare In->NotIn: requirements WITHOUT httpx must gain it.

    The mutant inverts the guard and early-returns, never adding httpx.
    """
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.110.0\n")
    _patch_requirements(req)
    content = req.read_text()
    assert "httpx" in content
    assert "fastapi>=0.110.0" in content


def test_patch_requirements_idempotent_when_httpx_present(tmp_path: Path) -> None:
    """L232 In->NotIn (other direction): existing httpx must NOT be duplicated."""
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.110.0\nhttpx>=0.27.0\n")
    before = req.read_text()
    _patch_requirements(req)
    assert req.read_text() == before


def test_patch_requirements_no_trailing_newline(tmp_path: Path) -> None:
    """L234 UnaryNot: requirements without a trailing newline must not glue lines.

    The mutant would produce ``fastapi>=0.110.0httpx>=0.28.0``.
    """
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.110.0")  # no trailing newline
    _patch_requirements(req)
    content = req.read_text()
    assert "fastapi>=0.110.0httpx" not in content
    assert "httpx" in content


def test_full_run_routes_init_import_precedes_include() -> None:
    """End-to-end: on a fresh project both patch lines are added exactly once."""
    project_dir = create_fixture_project(name="opa_contract_e2e")
    result = add_opa_integration(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    content = (project_dir / "app" / "routes" / "__init__.py").read_text()
    assert content.count("from app.api.routes.opa import router as opa_router") == 1
    assert content.count("api_router.include_router(opa_router)") == 1
