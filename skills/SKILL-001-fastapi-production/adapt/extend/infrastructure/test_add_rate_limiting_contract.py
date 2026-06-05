"""Generic tool-contract mutation coverage for add_rate_limiting.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_rate_limiting.py in the mutation
runner: ``--tests test_add_rate_limiting.py test_add_rate_limiting_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_rate_limiting import add_rate_limiting
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_rate_limiting, "add_rate_limiting")


def _endswith_any(paths: list[str], suffix: str) -> bool:
    return any(p.replace("\\", "/").endswith(suffix) for p in paths)


def test_scaffolded_prereqs_reported_in_files_created() -> None:
    """L67 ``list(scaffolded or [])`` — the auto-scaffolded prerequisite
    files must be carried into ``files_created``.

    On a bare project the tool scaffolds CONFIG_SETTINGS + REQUIREMENTS_TXT,
    so ``scaffolded`` is a NON-empty list. The ``or`` fallback keeps that
    list; flipping it to ``and`` (``[...] and []``) would drop every
    scaffolded path, so the generated ``app/core/config.py`` would vanish
    from ``files_created``.
    """
    bare = Path(tempfile.mkdtemp())
    r = add_rate_limiting(ToolInput(project_dir=str(bare)))
    assert r.status == "success", r.error
    # The scaffolded config.py is only ever recorded via L67's `scaffolded`.
    assert _endswith_any(r.files_created, "app/core/config.py"), r.files_created


def test_app_dir_mkdir_exist_ok_on_existing_app() -> None:
    """L98 ``app_dir.mkdir(..., exist_ok=True)`` — the full fixture already
    has an ``app/`` directory.

    Flipping ``exist_ok`` to ``False`` raises ``FileExistsError`` instead of
    succeeding, so a clean success run over a project whose ``app/`` already
    exists pins the literal.
    """
    d = create_fixture_project(name="rl_c_appdir")
    assert (d / "app").is_dir()
    r = add_rate_limiting(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error
    assert (d / "app" / "rate_limit.py").is_file()


def test_tests_dir_mkdir_exist_ok_on_existing_tests() -> None:
    """L139 ``(project / "tests").mkdir(..., exist_ok=True)`` — the full
    fixture already has a ``tests/`` directory.

    Flipping ``exist_ok`` to ``False`` raises ``FileExistsError`` while
    emitting the project test, so a success run that writes
    ``tests/test_add_rate_limiting_emitted.py`` over an existing ``tests/``
    dir pins the literal.
    """
    d = create_fixture_project(name="rl_c_testsdir")
    assert (d / "tests").is_dir()
    r = add_rate_limiting(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error
    assert (d / "tests" / "test_add_rate_limiting_emitted.py").is_file()


def test_config_not_repatched_when_field_already_present() -> None:
    """L104 ``config.exists() and "RATE_LIMIT_PER_SECOND" not in text`` —
    And→Or guard against double-patching.

    Pre-seed ``RATE_LIMIT_PER_SECOND`` into an existing config (config.py is
    present, glue file is absent so we don't short-circuit to no_op). With
    ``and`` the second operand is False → config is NOT re-patched, so the
    config file must be ABSENT from ``files_modified``. Flipping to ``or``
    short-circuits True on ``config.exists()`` → it would re-patch and report
    the config in ``files_modified``.
    """
    d = create_fixture_project(name="rl_c_cfgguard")
    config_file = d / "app" / "core" / "config.py"
    text = config_file.read_text()
    assert "RATE_LIMIT_PER_SECOND" not in text
    # Seed the field as a top-of-class attribute right after the class line
    # so the guard's second operand is False, keeping the file valid Python.
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    injected = False
    for line in lines:
        out.append(line)
        if not injected and line.lstrip().startswith("class Settings"):
            out.append("    RATE_LIMIT_PER_SECOND: float = 100.0\n")
            injected = True
    assert injected, "could not locate Settings class to seed"
    config_file.write_text("".join(out))
    assert "RATE_LIMIT_PER_SECOND" in config_file.read_text()

    # Glue file must not exist yet, else the tool returns no_op before L104.
    assert not (d / "app" / "rate_limit.py").exists()

    r = add_rate_limiting(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error
    assert not _endswith_any(r.files_modified, "app/core/config.py"), r.files_modified
