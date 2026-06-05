"""Generic tool-contract mutation coverage for add_response_armor.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_response_armor.py in the mutation
runner: ``--tests test_add_response_armor.py test_add_response_armor_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_response_armor import add_response_armor
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_response_armor import add_response_armor

    for check in SCAFFOLDABLE_CHECKS:
        check(add_response_armor, "add_response_armor")


def _bare_project(config_src: str, main_src: str) -> Path:
    """Build a minimal project that satisfies prereqs but has caller-chosen
    config.py / main.py so the *else* branches of the patchers are exercised.

    Returns the project root (a fresh tempdir)."""
    root = Path(tempfile.mkdtemp())
    (root / "app" / "core").mkdir(parents=True)
    (root / "app" / "core" / "config.py").write_text(config_src)
    (root / "app" / "main.py").write_text(main_src)
    (root / "requirements.txt").write_text("fastapi\n")
    return root


# ---------------------------------------------------------------------------
# L181 (Compare In->NotIn) — import lands directly AFTER the FastAPI import
# ---------------------------------------------------------------------------


def test_armor_import_inserted_directly_after_fastapi_import() -> None:
    """When ``from fastapi import FastAPI`` is present, the armor import must be
    spliced immediately after it (the In-branch). Flipping In->NotIn diverts to
    the else-branch which prepends the import at the top of the file, breaking
    this adjacency."""
    project = create_fixture_project(name="ra_ctr_l181")
    result = add_response_armor(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    main = (project / "app" / "main.py").read_text()
    assert (
        "from fastapi import FastAPI\n"
        "from app.middleware.response_armor import register_response_armor"
    ) in main, "armor import must immediately follow the FastAPI import"
    # And it must NOT have been prepended to the very top of the file.
    assert not main.lstrip().startswith(
        "from app.middleware.response_armor import register_response_armor"
    ), "armor import was prepended instead of spliced after FastAPI import"


# ---------------------------------------------------------------------------
# L187 (BinOp Add->Sub, else-branch) — no FastAPI import => import is prepended
# ---------------------------------------------------------------------------


def test_armor_import_prepended_when_no_fastapi_import() -> None:
    """A main.py WITHOUT ``from fastapi import FastAPI`` must take the else-branch
    that prepends ``import_line + src``. Add->Sub there raises TypeError
    (str - str), so a successful run with the import at the top kills it."""
    project = _bare_project(
        "class Settings:\n    DEBUG: bool = False\n",
        "import os\n\napp = make_app()\n",
    )
    result = add_response_armor(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    main = (project / "app" / "main.py").read_text()
    assert main.lstrip().startswith(
        "from app.middleware.response_armor import register_response_armor"
    ), "armor import must be prepended when FastAPI import is absent"
    assert "import os" in main, "original main.py body must be preserved"


# ---------------------------------------------------------------------------
# L190 (Compare In->NotIn) — register call lands right after app = FastAPI(...)
# ---------------------------------------------------------------------------


def test_register_call_inserted_after_fastapi_app_not_at_eof() -> None:
    """With the ``app = FastAPI(`` marker present, the register call is inserted
    immediately after the constructor's closing paren (mid-file, before the
    router includes). Flipping In->NotIn diverts to the else-branch which appends
    the call at EOF — after the router includes."""
    project = create_fixture_project(name="ra_ctr_l190")
    result = add_response_armor(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    main = (project / "app" / "main.py").read_text()
    reg_idx = main.find("register_response_armor(app)")
    include_idx = main.find("app.include_router(api_router")
    assert reg_idx >= 0, "register call not inserted"
    assert include_idx >= 0, "fixture should include the api_router include"
    assert reg_idx < include_idx, (
        "register call must be spliced right after app = FastAPI(...), "
        "before the router includes — not appended at EOF"
    )


# ---------------------------------------------------------------------------
# L205 (BinOp Add->Sub, else-branch) — no FastAPI() marker => call appended
# ---------------------------------------------------------------------------


def test_register_call_appended_when_no_fastapi_marker() -> None:
    """A main.py without ``app = FastAPI(`` takes the else-branch that appends
    ``register_response_armor(app)`` at the end. Add->Sub there raises TypeError,
    so a successful run with the call appended kills it."""
    project = _bare_project(
        "class Settings:\n    DEBUG: bool = False\n",
        "from fastapi import FastAPI\n\napp = build()\n",
    )
    result = add_response_armor(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    main = (project / "app" / "main.py").read_text()
    assert main.rstrip().endswith("register_response_armor(app)"), (
        "register call must be appended at EOF when no FastAPI() marker exists"
    )
    assert "app = build()" in main, "original main.py body must be preserved"


# ---------------------------------------------------------------------------
# L167 (BinOp Add->Sub, else-branch) — config without the anchor
# ---------------------------------------------------------------------------


def test_config_fields_appended_when_anchor_absent() -> None:
    """A config.py without the ``ACCESS_TOKEN_EXPIRE_MINUTES`` anchor takes the
    else-branch that appends the RESPONSE_ARMOR_* fields. Add->Sub there raises
    TypeError, so a successful run with all three fields present kills it."""
    project = _bare_project(
        "class Settings:\n    DEBUG: bool = False\n",
        "from fastapi import FastAPI\n\napp = FastAPI()\n",
    )
    result = add_response_armor(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    config = (project / "app" / "core" / "config.py").read_text()
    for field in (
        "RESPONSE_ARMOR_ENABLED",
        "RESPONSE_ARMOR_SANITIZE_ERRORS",
        "RESPONSE_ARMOR_TIMING_SAFE",
    ):
        assert field in config, f"missing {field} when anchor absent"
    assert "DEBUG: bool = False" in config, "original config body must be preserved"


# ---------------------------------------------------------------------------
# L110 (UnaryNot) — middleware/__init__.py created only when it does NOT exist
# ---------------------------------------------------------------------------


def test_middleware_init_created_when_absent() -> None:
    """The ``if not mw_init.exists()`` guard writes app/middleware/__init__.py
    only when it is missing. Flipping ``not X`` -> ``X`` inverts the guard so the
    file is never written on a fresh project. Assert it gets created."""
    project = _bare_project(
        "class Settings:\n    DEBUG: bool = False\n",
        "from fastapi import FastAPI\n\napp = FastAPI()\n",
    )
    init_file = project / "app" / "middleware" / "__init__.py"
    assert not init_file.exists(), "precondition: middleware/__init__.py absent"
    result = add_response_armor(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert init_file.exists(), "middleware/__init__.py must be created when absent"
    assert any(p.endswith("app/middleware/__init__.py") for p in result.files_created), (
        "middleware/__init__.py must be reported in files_created"
    )


# ---------------------------------------------------------------------------
# L98 (BoolLiteral True->False) — app/core mkdir uses exist_ok=True
# ---------------------------------------------------------------------------


def test_succeeds_when_app_core_dir_already_exists() -> None:
    """The fixture project already has app/core/. The core mkdir uses
    ``exist_ok=True``; flipping True->False raises FileExistsError. A successful
    run (core files created in the pre-existing dir) kills it."""
    project = create_fixture_project(name="ra_ctr_l98")
    assert (project / "app" / "core").is_dir(), "precondition: app/core exists"
    result = add_response_armor(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert (project / "app" / "core" / "response_armor.py").exists()
    assert (project / "app" / "core" / "timing_safe.py").exists()


# ---------------------------------------------------------------------------
# L108 (BoolLiteral True->False) — middleware mkdir uses exist_ok=True
# ---------------------------------------------------------------------------


def test_succeeds_when_middleware_dir_already_exists() -> None:
    """Pre-create app/middleware/ before running. The middleware mkdir uses
    ``exist_ok=True``; flipping True->False raises FileExistsError on the
    pre-existing directory. A successful run kills it."""
    project = _bare_project(
        "class Settings:\n    DEBUG: bool = False\n",
        "from fastapi import FastAPI\n\napp = FastAPI()\n",
    )
    (project / "app" / "middleware").mkdir(parents=True)
    assert (project / "app" / "middleware").is_dir()
    result = add_response_armor(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert (project / "app" / "middleware" / "response_armor.py").exists()


# ---------------------------------------------------------------------------
# L211 (BoolLiteral True->False) — tests/ mkdir uses exist_ok=True
# ---------------------------------------------------------------------------


def test_succeeds_when_tests_dir_already_exists() -> None:
    """The fixture project already has tests/. ``_emit_project_test`` does
    ``(project / "tests").mkdir(parents=True, exist_ok=True)``; flipping
    exist_ok True->False raises FileExistsError on the pre-existing tests/ dir.
    A successful run that emits the project test kills it."""
    project = create_fixture_project(name="ra_ctr_l211")
    assert (project / "tests").is_dir(), "precondition: tests/ exists"
    result = add_response_armor(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert (project / "tests" / "test_add_response_armor_emitted.py").exists(), (
        "project-level emitted test must be created"
    )
