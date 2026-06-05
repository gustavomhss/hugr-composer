"""Generic tool-contract mutation coverage for add_runtime_sentinel.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_runtime_sentinel.py in the mutation
runner: ``--tests test_add_runtime_sentinel.py test_add_runtime_sentinel_contract.py``.

The ``test_kill_*`` functions below target this tool's bespoke logic
(survivors the generic preamble checks leave alive):

* L103 ``if not middleware_init.exists():`` — only writes the middleware
  package ``__init__.py`` when it is absent (UnaryNot flip).
* L125 ``elif patch_outcome is PatchResult.TARGET_MISSING:`` — emits the
  "no class Settings shape" note and keeps config.py out of
  files_modified (Compare Is flip).
* L130 ``elif patch_outcome is PatchResult.SYNTAX_ERROR:`` — returns
  status="error" when config.py is unparseable (Compare Is flip).
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_runtime_sentinel import add_runtime_sentinel
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_runtime_sentinel, "add_runtime_sentinel")


# ---------------------------------------------------------------------------
# Bare-project builders (no fixture_factory: we need precise control over
# whether app/middleware/__init__.py and the Settings class shape exist).
# ---------------------------------------------------------------------------


def _bare_project(config_body: str) -> Path:
    """Build a minimal project that satisfies the tool's prerequisites.

    ``config_body`` is written verbatim to ``app/core/config.py``.
    A ``requirements.txt`` is supplied so prereqs pass without scaffolding.
    """
    root = Path(tempfile.mkdtemp())
    (root / "app" / "core").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "core" / "__init__.py").write_text("")
    (root / "app" / "core" / "config.py").write_text(config_body)
    (root / "requirements.txt").write_text("fastapi\n")
    return root


_VALID_SETTINGS = 'class Settings:\n    APP_NAME: str = "x"\n'


# ---------------------------------------------------------------------------
# L103: UnaryNot — `if not middleware_init.exists():`
# ---------------------------------------------------------------------------


def test_kill_l103_creates_middleware_init_when_absent():
    """L103 (not X->X): a fresh project gets the middleware package __init__.py.

    The tool must WRITE app/middleware/__init__.py (with its package
    docstring) and list it in files_created when it does not yet exist.
    Flipping ``not`` would skip writing → the file would be absent and
    missing from files_created.
    """
    root = _bare_project(_VALID_SETTINGS)
    result = add_runtime_sentinel(ToolInput(project_dir=str(root)))

    assert result.status == "success", result.error
    init_path = root / "app" / "middleware" / "__init__.py"
    assert init_path.exists(), "middleware/__init__.py was not created"
    assert init_path.read_text() == '"""Middleware package."""\n'
    assert any(p.endswith("app/middleware/__init__.py") for p in result.files_created)


def test_kill_l103_preserves_existing_middleware_init():
    """L103 (not X->X): a pre-existing __init__.py is left untouched.

    With ``not`` the guard is False when the file exists, so the tool must
    NOT overwrite custom content nor re-add it to files_created. Flipping
    ``not`` would clobber the file with the package docstring.
    """
    root = _bare_project(_VALID_SETTINGS)
    mw = root / "app" / "middleware"
    mw.mkdir()
    sentinel_marker = "# CUSTOM MIDDLEWARE INIT — DO NOT CLOBBER\n"
    (mw / "__init__.py").write_text(sentinel_marker)

    result = add_runtime_sentinel(ToolInput(project_dir=str(root)))

    assert result.status == "success", result.error
    assert (mw / "__init__.py").read_text() == sentinel_marker
    assert not any(p.endswith("app/middleware/__init__.py") for p in result.files_created)


# ---------------------------------------------------------------------------
# L125: Compare Is — `elif patch_outcome is PatchResult.TARGET_MISSING:`
# ---------------------------------------------------------------------------


def test_kill_l125_target_missing_emits_note_and_skips_modified():
    """L125 (Is->IsNot): no real Settings class -> TARGET_MISSING note path.

    The prereq check only substring-matches ``class Settings``; a config
    with that text in a COMMENT passes prereqs but the AST patcher finds
    no ClassDef, returning TARGET_MISSING. The tool must then add the
    "no `class Settings` shape found" note and must NOT list config.py in
    files_modified. Flipping ``is`` to ``is not`` skips the note.
    """
    root = _bare_project("# class Settings placeholder\nFOO = 1\n")
    result = add_runtime_sentinel(ToolInput(project_dir=str(root)))

    assert result.status == "success", result.error
    assert any("no `class Settings` shape found" in n for n in result.notes), result.notes
    assert not any(p.endswith("app/core/config.py") for p in result.files_modified)


def test_kill_l125_applied_path_has_no_target_missing_note():
    """L125 companion: a real Settings class -> APPLIED, no TARGET_MISSING note.

    Drives the opposite branch so the IsNot flip (which would emit the
    note here) is also caught: with a real class the note must be absent
    and config.py must be in files_modified.
    """
    root = _bare_project(_VALID_SETTINGS)
    result = add_runtime_sentinel(ToolInput(project_dir=str(root)))

    assert result.status == "success", result.error
    assert not any("no `class Settings` shape found" in n for n in result.notes)
    assert any(p.endswith("app/core/config.py") for p in result.files_modified)


# ---------------------------------------------------------------------------
# L130: Compare Is — `elif patch_outcome is PatchResult.SYNTAX_ERROR:`
# ---------------------------------------------------------------------------


def test_kill_l130_syntax_error_in_config_returns_error():
    """L130 (Is->IsNot): an unparseable config.py -> status='error'.

    The config contains ``class Settings`` (prereq passes) but is not
    valid Python, so the AST patcher returns SYNTAX_ERROR and the tool
    must refuse to patch with a specific error. Flipping ``is`` to
    ``is not`` would skip this branch and not surface the error.
    """
    root = _bare_project("class Settings:\n    APP =  (((\n")
    result = add_runtime_sentinel(ToolInput(project_dir=str(root)))

    assert result.status == "error"
    assert result.error is not None
    assert "syntax error" in result.error.lower()
    assert "config.py" in result.error
