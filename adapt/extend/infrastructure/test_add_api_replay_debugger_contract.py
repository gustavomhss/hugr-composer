"""Generic + tool-specific mutation coverage for add_api_replay_debugger.

The generic fleet checks (tests/common/tool_contract.py) kill the shared
preamble mutants (execution_time, idempotency, dry_run, auto-scaffold,
exist_ok-on-fresh, prereq-error). The bespoke tests below target the
survivors the generic suite cannot reach:

  * L219  ``if "init_recorder" in src`` dedup guard in ``_patch_main``
  * L236  ``if "from fastapi import FastAPI" in src`` branch selection
  * L242  ``recorder_import + src`` (else / no-FastAPI-import branch)
  * L129  ``debug_dir.mkdir(exist_ok=True)``     (dir already exists)
  * L144  ``middleware_dir.mkdir(exist_ok=True)`` (dir already exists)
  * L182  ``(project / "tests").mkdir(exist_ok=True)`` (dir already exists)
"""

from __future__ import annotations

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_api_replay_debugger import (
    _patch_main,
    add_api_replay_debugger,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_api_replay_debugger, "add_api_replay_debugger")


# ---------------------------------------------------------------------------
# L219: ``if "init_recorder" in src: return`` — dedup guard in _patch_main.
# Flipping In→NotIn makes a *fresh* main short-circuit and never get patched.
# ---------------------------------------------------------------------------


def test_patch_main_patches_fresh_file() -> None:
    """_patch_main must inject init_recorder import into a fresh main.py.

    Kills L219 In->NotIn: with the flip, a main.py that does NOT yet contain
    'init_recorder' would early-return and stay unpatched.
    """
    project_dir = create_fixture_project(name="replay_c_dedup_fresh")
    main_file = project_dir / "app" / "main.py"
    assert "init_recorder" not in main_file.read_text()
    _patch_main(main_file)
    patched = main_file.read_text()
    assert "init_recorder" in patched, "fresh main.py must be patched"
    assert "from app.debug.recorder import init_recorder" in patched


def test_patch_main_idempotent_no_duplicate() -> None:
    """Calling _patch_main twice must not duplicate the recorder import.

    Reinforces L219: the dedup guard returns early on the already-patched
    file, so the import line count stays at exactly one.
    """
    project_dir = create_fixture_project(name="replay_c_dedup_twice")
    main_file = project_dir / "app" / "main.py"
    _patch_main(main_file)
    once = main_file.read_text()
    _patch_main(main_file)
    twice = main_file.read_text()
    assert once == twice, "second _patch_main must be a no-op"
    assert twice.count("from app.debug.recorder import init_recorder") == 1


# ---------------------------------------------------------------------------
# L236: ``if "from fastapi import FastAPI" in src`` — branch selection.
# True branch injects the recorder import *right after* the FastAPI import.
# Flipping In->NotIn drops into the else branch and prepends at the top.
# ---------------------------------------------------------------------------


def test_patch_main_inserts_after_fastapi_import() -> None:
    """recorder import is anchored immediately after the FastAPI import.

    Kills L236 In->NotIn: the else branch would prepend the recorder import
    at the very top of the file instead of after 'from fastapi import FastAPI'.
    """
    project_dir = create_fixture_project(name="replay_c_anchor")
    main_file = project_dir / "app" / "main.py"
    assert "from fastapi import FastAPI" in main_file.read_text()
    _patch_main(main_file)
    patched = main_file.read_text()
    anchor = "from fastapi import FastAPI"
    idx = patched.index(anchor)
    after = patched[idx + len(anchor) : idx + len(anchor) + 120]
    assert "from app.debug.recorder import init_recorder" in after, (
        "recorder import must directly follow the FastAPI import"
    )
    # And it must NOT have been prepended to the very top of the file.
    assert not patched.lstrip().startswith("from app.debug.recorder import init_recorder")


# ---------------------------------------------------------------------------
# L242: ``src = recorder_import + src`` — else branch (no FastAPI import).
# Flipping Add->Sub on strings raises TypeError; only exercised when the
# main file lacks 'from fastapi import FastAPI'.
# ---------------------------------------------------------------------------


def test_patch_main_prepends_when_no_fastapi_import(tmp_path: Path) -> None:
    """_patch_main prepends the recorder import when no FastAPI import exists.

    Kills L242 Add->Sub: the else branch does ``recorder_import + src``; the
    Sub mutant would TypeError, and we assert the import lands at the top.
    """
    main_file = tmp_path / "main.py"
    main_file.write_text('"""no fastapi import here."""\napp = object()\n')
    _patch_main(main_file)
    patched = main_file.read_text()
    assert "from app.debug.recorder import init_recorder" in patched
    # Prepended before the original first line.
    assert patched.index("init_recorder") < patched.index("app = object()")


# ---------------------------------------------------------------------------
# L129 / L144 / L182: mkdir(exist_ok=True) on pre-existing directories.
# Flipping True->False raises FileExistsError when the dir already exists.
# ---------------------------------------------------------------------------


def test_succeeds_when_debug_dir_already_exists() -> None:
    """Tool succeeds when app/debug/ already exists (empty).

    Kills L129 exist_ok True->False: a pre-existing debug_dir would raise
    FileExistsError on mkdir. The dir is created empty so the RequestRecorder
    fingerprint is absent and the tool does not no_op.
    """
    project_dir = create_fixture_project(name="replay_c_debugdir")
    (project_dir / "app" / "debug").mkdir(parents=True, exist_ok=True)
    result = add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"got {result.status}: {result.error}"
    recorder = project_dir / "app" / "debug" / "recorder.py"
    assert recorder.exists()


def test_succeeds_when_middleware_dir_already_exists() -> None:
    """Tool succeeds when app/middleware/ already exists.

    Kills L144 exist_ok True->False on the middleware dir mkdir.
    """
    project_dir = create_fixture_project(name="replay_c_mwdir")
    (project_dir / "app" / "middleware").mkdir(parents=True, exist_ok=True)
    result = add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"got {result.status}: {result.error}"
    mw = project_dir / "app" / "middleware" / "request_recorder.py"
    assert mw.exists()


def test_succeeds_when_tests_dir_already_exists() -> None:
    """Tool succeeds when tests/ already exists.

    Kills L182 exist_ok True->False on the project tests dir mkdir in
    _emit_project_test.
    """
    project_dir = create_fixture_project(name="replay_c_testsdir")
    (project_dir / "tests").mkdir(parents=True, exist_ok=True)
    result = add_api_replay_debugger(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"got {result.status}: {result.error}"
    emitted = project_dir / "tests" / "test_add_api_replay_debugger_emitted.py"
    assert emitted.exists()
