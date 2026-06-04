"""Generic + bespoke mutation coverage for add_chaos_testing.

Auto-generated header: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_chaos_testing.py in the mutation
runner: ``--tests test_add_chaos_testing.py test_add_chaos_testing_contract.py``.

The hand-written tests below target tool-specific survivors that the generic
preamble checks do not reach: the ``_patch_main`` insertion anchor / position,
the ``ChaosMiddleware`` idempotency guard, and the FastAPI-import branch.
"""

from __future__ import annotations

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_chaos_testing import (
    _patch_main,
    add_chaos_testing,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_chaos_testing import add_chaos_testing

    for check in SCAFFOLDABLE_CHECKS:
        check(add_chaos_testing, "add_chaos_testing")


# ---------------------------------------------------------------------------
# L171: ``if "ChaosMiddleware" in src: return`` — idempotency guard in
# _patch_main. Flip In->NotIn makes _patch_main bail BEFORE wiring on a
# fresh main.py. Assert a fresh main.py is actually wired with the
# middleware + router.
# ---------------------------------------------------------------------------


def test_patch_main_wires_fresh_main(tmp_path: Path) -> None:
    main_file = tmp_path / "main.py"
    main_file.write_text(
        "from fastapi import FastAPI\n\napp = FastAPI()\n",
        encoding="utf-8",
    )
    _patch_main(main_file)
    out = main_file.read_text()
    assert "app.add_middleware(ChaosMiddleware)" in out, (
        "fresh main.py must be wired with ChaosMiddleware"
    )
    assert "app.include_router(_chaos_router)" in out, "fresh main.py must include the chaos router"
    assert "from app.chaos.middleware import ChaosMiddleware" in out


# ---------------------------------------------------------------------------
# L171 (the other half): guard must be a no-op when ChaosMiddleware already
# present — a second _patch_main call must NOT append the wire snippet twice.
# Flip In->NotIn would re-run the body and duplicate the wiring.
# ---------------------------------------------------------------------------


def test_patch_main_idempotent_no_duplicate(tmp_path: Path) -> None:
    main_file = tmp_path / "main.py"
    main_file.write_text(
        "from fastapi import FastAPI\n\napp = FastAPI()\n",
        encoding="utf-8",
    )
    _patch_main(main_file)
    _patch_main(main_file)
    out = main_file.read_text()
    assert out.count("app.add_middleware(ChaosMiddleware)") == 1, (
        "_patch_main must be idempotent (no duplicate middleware wiring)"
    )
    assert out.count("app.include_router(_chaos_router)") == 1


# ---------------------------------------------------------------------------
# L184: ``if "from fastapi import FastAPI" in src:`` — when the import is
# present, the chaos imports are inserted IMMEDIATELY AFTER the FastAPI
# import line, not prepended at the very top of the file. Flip In->NotIn
# would prepend instead. Assert the chaos import lands after the FastAPI
# import (i.e. the file does NOT start with the chaos import).
# ---------------------------------------------------------------------------


def test_patch_main_inserts_after_fastapi_import(tmp_path: Path) -> None:
    main_file = tmp_path / "main.py"
    main_file.write_text(
        "from fastapi import FastAPI\n\napp = FastAPI()\n",
        encoding="utf-8",
    )
    _patch_main(main_file)
    out = main_file.read_text()
    fastapi_pos = out.index("from fastapi import FastAPI")
    chaos_pos = out.index("from app.chaos.middleware import ChaosMiddleware")
    assert fastapi_pos < chaos_pos, (
        "chaos import must be inserted AFTER the FastAPI import, not before"
    )
    assert not out.lstrip().startswith("from app.chaos.middleware"), (
        "with a FastAPI import present the file must not begin with the chaos import"
    )


# ---------------------------------------------------------------------------
# L184 + L190: else-branch (no FastAPI import). The chaos import is
# PREPENDED to the file. Flip In->NotIn (L184) would skip the else; flip
# Add->Sub (L190, ``import_snippet + src``) would raise TypeError. Assert the
# else branch prepends the chaos import to the top of the file successfully.
# ---------------------------------------------------------------------------


def test_patch_main_prepends_when_no_fastapi_import(tmp_path: Path) -> None:
    main_file = tmp_path / "main.py"
    main_file.write_text(
        "import os\n\napp = make_app()\n",
        encoding="utf-8",
    )
    _patch_main(main_file)
    out = main_file.read_text()
    assert out.lstrip().startswith("from app.chaos.middleware import ChaosMiddleware"), (
        "without a FastAPI import the chaos import must be prepended at the top"
    )
    # original content is preserved (Add not Sub — string concatenation, not error)
    assert "import os" in out
    assert "app.add_middleware(ChaosMiddleware)" in out


# ---------------------------------------------------------------------------
# Integration: a fully-generated fixture project gets main.py patched with
# the chaos middleware + router (covers the main_file.exists() branch and the
# end-to-end _patch_main wiring on a real generated main.py).
# ---------------------------------------------------------------------------


def test_generated_main_is_patched() -> None:
    project_dir = create_fixture_project(name="ct_contract_main")
    result = add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    main_file = project_dir / "app" / "main.py"
    assert main_file.exists()
    out = main_file.read_text()
    assert "app.add_middleware(ChaosMiddleware)" in out
    assert "app.include_router(_chaos_router)" in out
    # main.py must be reported as modified (resolve both sides for macOS symlink)
    modified = {str(Path(p).resolve()) for p in result.files_modified}
    assert str(main_file.resolve()) in modified
