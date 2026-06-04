"""Generic tool-contract mutation coverage for add_bola_guard.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_bola_guard.py in the mutation
runner: ``--tests test_add_bola_guard.py test_add_bola_guard_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_bola_guard import add_bola_guard
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS

_VALID_SETTINGS_CONFIG = (
    '"""Config."""\n\n\nclass Settings:\n    SECRET_KEY: str = "x"\n\n\nsettings = Settings()\n'
)


def _bare_project(extra_config: str | None = None) -> Path:
    """A minimal on-disk project: requirements.txt + a config.py we control.

    No ``app/auth/`` dir exists, so the tool's auth-package creation branch
    (L136 ``if not auth_init.exists():``) is exercised. When *extra_config*
    is given it is written as ``app/core/config.py`` BEFORE the run so the
    prereq auto-scaffolder leaves it untouched (it only creates missing
    files), letting us drive the config-patch branch outcomes.
    """
    root = Path(tempfile.mkdtemp())
    (root / "requirements.txt").write_text("fastapi>=0.115.0\n")
    core = root / "app" / "core"
    core.mkdir(parents=True, exist_ok=True)
    config = extra_config if extra_config is not None else _VALID_SETTINGS_CONFIG
    (core / "config.py").write_text(config)
    return root


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_bola_guard, "add_bola_guard")


def test_auth_init_created_when_missing():
    """L136 UnaryNot (``not auth_init.exists()`` -> ``auth_init.exists()``).

    On a project that has NO ``app/auth/`` package, the tool must WRITE
    ``app/auth/__init__.py`` (the "Auth package." stub) and report it in
    files_created. If the ``not`` is dropped, the write is skipped on the
    one path where the file is missing, so the file never appears.
    """
    root = _bare_project()
    auth_init = root / "app" / "auth" / "__init__.py"
    assert not auth_init.exists()

    result = add_bola_guard(ToolInput(project_dir=str(root)))

    assert result.status == "success", result.error
    assert auth_init.exists(), "app/auth/__init__.py must be created when missing"
    assert "Auth package." in auth_init.read_text()
    assert str(Path(auth_init).resolve()) in {str(Path(p).resolve()) for p in result.files_created}


def test_config_applied_branch_marks_modified():
    """L162/L164 baseline: a real Settings class yields APPLIED, not the
    TARGET_MISSING fallback note.

    When ``patch_config`` returns APPLIED the tool records config.py in
    files_modified AND does not emit the "no `class Settings` shape found"
    note. This anchors the ``is PatchResult.APPLIED`` / ``is
    PatchResult.TARGET_MISSING`` discrimination.
    """
    root = _bare_project(_VALID_SETTINGS_CONFIG)
    config = root / "app" / "core" / "config.py"

    result = add_bola_guard(ToolInput(project_dir=str(root)))

    assert result.status == "success", result.error
    assert str(config) in result.files_modified
    assert "BOLA_GUARD_ENABLED" in config.read_text()
    assert not any("no `class Settings` shape found" in n for n in result.notes), (
        "APPLIED outcome must not emit the TARGET_MISSING fallback note"
    )


def test_config_target_missing_emits_fallback_note():
    """L164 Compare Is->IsNot (``is PatchResult.TARGET_MISSING``).

    A config.py that PARSES but has no top-level ``Settings`` class (the
    marker text lives only in the docstring so the prereq check still
    passes) makes ``patch_config`` return TARGET_MISSING. The tool must
    then append the "no `class Settings` shape found" note. Flipping the
    ``is`` to ``is not`` routes a genuine TARGET_MISSING outcome past this
    branch, so the note disappears.
    """
    config_src = '"""Config with the marker class Settings only in this docstring."""\n\nFOO = 1\n'
    root = _bare_project(config_src)
    config = root / "app" / "core" / "config.py"

    result = add_bola_guard(ToolInput(project_dir=str(root)))

    assert result.status == "success", result.error
    assert any("no `class Settings` shape found" in n for n in result.notes), (
        "TARGET_MISSING outcome must emit the fallback note"
    )
    # Fallback path appends fields at module level, so it is NOT counted as
    # an APPLIED modification.
    assert str(config) not in result.files_modified


def test_config_syntax_error_returns_error():
    """L170 Compare Is->IsNot (``is PatchResult.SYNTAX_ERROR``).

    A config.py whose text contains ``class Settings`` (prereq passes) but
    which does NOT parse makes ``patch_config`` return SYNTAX_ERROR. The
    tool must refuse and return status="error". Flipping the ``is`` to
    ``is not`` skips this branch for a real SYNTAX_ERROR outcome, so the
    tool would fall through to success instead.
    """
    broken = "class Settings:\n    SECRET_KEY: str =\n"  # trailing = -> SyntaxError
    root = _bare_project(broken)

    result = add_bola_guard(ToolInput(project_dir=str(root)))

    assert result.status == "error"
    assert result.error and "config.py" in result.error
