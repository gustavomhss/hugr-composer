"""Generic + tool-specific mutation coverage for add_celery_beat.

The generic half applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. The tool-specific half targets the
``_patch_config`` branch selection / string-concat mutants and the
``list(scaffolded or [])`` BoolOp that the generic checks cannot reach.

Run alongside test_add_celery_beat.py in the mutation runner:
``--tests test_add_celery_beat.py test_add_celery_beat_contract.py``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_celery_beat import (
    _patch_config,
    add_celery_beat,
)
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS

_CELERY_BLOCK_MARKER = "# --- Celery settings — added by add_celery_beat tool ---"


def _tmp_config(body: str) -> Path:
    """Write a throwaway config.py with *body* and return its path."""
    d = Path(tempfile.mkdtemp())
    f = d / "config.py"
    f.write_text(body)
    return f


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_celery_beat, "add_celery_beat")


# ---------------------------------------------------------------------------
# _patch_config branch selection
# ---------------------------------------------------------------------------


def test_patch_config_anchor_branch_inserts_after_anchor() -> None:
    """When the ACCESS_TOKEN anchor is present, the Celery block is inserted
    IMMEDIATELY after the anchor line — kills ``if anchor in src`` In→NotIn
    (the flip falls through to the settings-line branch, so the block no
    longer follows the anchor line)."""
    f = _tmp_config(
        "class Settings(BaseSettings):\n"
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n"
        "    OTHER: int = 1\n"
        "\n"
        "settings = Settings()\n"
    )
    _patch_config(f)
    lines = f.read_text().splitlines()
    anchor_idx = next(
        i for i, ln in enumerate(lines) if "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30" in ln
    )
    # The very next line must be the Celery block marker.
    assert _CELERY_BLOCK_MARKER in lines[anchor_idx + 1], (
        "Celery block was not inserted directly after the anchor line; "
        f"line after anchor was: {lines[anchor_idx + 1]!r}"
    )


def test_patch_config_settings_branch_inserts_before_settings_line() -> None:
    """With no anchor but a ``settings = Settings()`` line, the block is
    inserted BEFORE that line — kills ``if settings_line in src`` In→NotIn
    (the flip appends at the end, after the settings line) AND the
    ``block + "\\n\\n" + settings_line`` Add→Sub (str - str raises)."""
    f = _tmp_config("class Settings(BaseSettings):\n    FOO: int = 1\n\nsettings = Settings()\n")
    _patch_config(f)
    text = f.read_text()
    assert _CELERY_BLOCK_MARKER in text, "Celery block missing"
    block_pos = text.index(_CELERY_BLOCK_MARKER)
    settings_pos = text.index("settings = Settings()")
    assert block_pos < settings_pos, (
        "Celery block must be inserted before the 'settings = Settings()' line"
    )


def test_patch_config_final_else_appends_block() -> None:
    """With neither anchor nor settings line, the block is appended at the
    end of the file — exercises the final ``src.rstrip + "\\n" + block``
    branch and kills its Add→Sub (str - str raises)."""
    f = _tmp_config("class Settings(BaseSettings):\n    FOO: int = 1\n")
    _patch_config(f)
    text = f.read_text()
    assert _CELERY_BLOCK_MARKER in text, "Celery block not appended in final-else branch"
    assert 'CELERY_BROKER_URL: str = ""' in text
    # The block is at the tail — nothing of the original body follows it.
    assert text.rstrip().endswith("CELERY_TASK_ALWAYS_EAGER: bool = False"), (
        "Celery block must be appended at the end in the final-else branch"
    )


# ---------------------------------------------------------------------------
# list(scaffolded or []) — auto-scaffold reporting
# ---------------------------------------------------------------------------


def test_bare_project_reports_scaffolded_files_in_created() -> None:
    """On a bare project, the auto-scaffolded files (e.g. app/core/config.py)
    are seeded into ``files_created`` via ``list(scaffolded or [])`` — kills
    the BoolOp Or→And (``scaffolded and []`` evaluates to ``[]``, dropping
    every scaffolded path from files_created)."""
    d = Path(tempfile.mkdtemp()) / "bare_scaffold"
    d.mkdir(parents=True)
    result = add_celery_beat(ToolInput(project_dir=str(d)))
    assert result.status == "success", result.error
    created_resolved = {str(Path(p).resolve()) for p in result.files_created}
    scaffolded_config = str((d / "app" / "core" / "config.py").resolve())
    assert scaffolded_config in created_resolved, (
        "auto-scaffolded app/core/config.py must appear in files_created "
        "(BoolOp Or→And drops the scaffolded prefix)"
    )
