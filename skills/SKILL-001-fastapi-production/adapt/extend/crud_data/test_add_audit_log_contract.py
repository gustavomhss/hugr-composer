"""Generic tool-contract mutation coverage for add_audit_log.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_audit_log.py in the mutation
runner: ``--tests test_add_audit_log.py test_add_audit_log_contract.py``.

The ``test_*_kills_*`` functions below target add_audit_log's TOOL-SPECIFIC
logic (config patch ordering / idempotency, the emitted-file ast.parse guard).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_audit_log import (
    _patch_config,
    add_audit_log,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_audit_log import add_audit_log

    for check in SCAFFOLDABLE_CHECKS:
        check(add_audit_log, "add_audit_log")


def test_patch_config_returns_true_and_inserts_field() -> None:
    """L197 return True: a fresh config gets the durable field and reports True.

    BoolLiteral True->False would make the caller skip recording config.py in
    files_modified even though it was changed.
    """
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text("class Settings:\n    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n")
    changed = _patch_config(cfg)
    assert changed is True
    assert "AUDIT_LOG_DURABLE: bool = False" in cfg.read_text()


def test_patch_config_idempotent_returns_false_no_double_insert() -> None:
    """L189 return False: a config already carrying the field is left untouched.

    BoolLiteral False->True would re-report a modification (and a paired naive
    impl could double-insert). We assert the second call reports no change and
    the field appears exactly once.
    """
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text("class Settings:\n    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n")
    assert _patch_config(cfg) is True
    text_after_first = cfg.read_text()
    assert _patch_config(cfg) is False
    assert cfg.read_text() == text_after_first
    assert cfg.read_text().count("AUDIT_LOG_DURABLE") == 1


def test_patch_config_field_lands_right_after_anchor() -> None:
    """Anchor-present branch: the durable field is inserted directly after
    ACCESS_TOKEN_EXPIRE_MINUTES, not somewhere else."""
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text(
        "class Settings:\n    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n    OTHER_FIELD: int = 7\n"
    )
    _patch_config(cfg)
    text = cfg.read_text()
    anchor_end = text.index("ACCESS_TOKEN_EXPIRE_MINUTES: int = 30") + len(
        "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    )
    durable_at = text.index("AUDIT_LOG_DURABLE")
    other_at = text.index("OTHER_FIELD")
    # Durable field sits between the anchor and the next existing field.
    assert anchor_end < durable_at < other_at


def test_patch_config_fallback_appends_when_no_anchor() -> None:
    """L195 BinOp Add->Sub: with NO anchor the field is appended to the source.

    The fallback rebuilds the file via string concatenation; flipping Add to Sub
    breaks the concatenation so the field never lands. We drive the
    anchor-absent branch and assert the field is appended and present exactly
    once.
    """
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text("class Settings:\n    SOME_FIELD: int = 1\n")
    assert "ACCESS_TOKEN_EXPIRE_MINUTES" not in cfg.read_text()
    changed = _patch_config(cfg)
    assert changed is True
    text = cfg.read_text()
    assert "AUDIT_LOG_DURABLE: bool = False" in text
    assert text.count("AUDIT_LOG_DURABLE") == 1
    # Original content is preserved (append, not replace).
    assert "SOME_FIELD: int = 1" in text


def test_emitted_file_parse_guard_skips_non_python_manifest() -> None:
    """L131 (Eq->NotEq and And->Or): the ast.parse guard must only parse real
    .py FILES in files_created.

    add_audit_log appends a ``.venous_manifest.json`` to files_created. The
    guard ``p.suffix == '.py' and p.is_file()`` skips it; flipping ``==`` to
    ``!=`` (parse everything that is NOT .py) or ``and`` to ``or`` (parse
    anything that is a file) would feed the JSON manifest to ast.parse, raising
    SyntaxError and turning the result into status='error'. A clean success on
    a full fixture (whose files_created includes that .json) kills both flips.
    """
    project = create_fixture_project(name="al_guard")
    result = add_audit_log(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    # Confirm the non-.py manifest really is among files_created (so the guard
    # was genuinely exercised on a non-python path).
    assert any(p.endswith(".json") for p in result.files_created)


def test_full_run_succeeds_over_preexisting_app_and_tests_dirs() -> None:
    """L107 / L202 mkdir exist_ok=True: the fixture already contains app/ and
    tests/ directories.

    Flipping ``exist_ok=True`` to ``False`` for ``app_dir.mkdir(...)`` (L107) or
    ``(project / 'tests').mkdir(...)`` (L202) would raise FileExistsError on a
    real project. Asserting a clean success over a fixture that already has both
    dirs kills both literal flips.
    """
    project = create_fixture_project(name="al_existdirs")
    assert (project / "app").is_dir()
    assert (project / "tests").is_dir()
    result = add_audit_log(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert any(p.endswith("app/audit_log.py") for p in result.files_created)
    assert any(p.endswith("tests/test_add_audit_log_emitted.py") for p in result.files_created)
