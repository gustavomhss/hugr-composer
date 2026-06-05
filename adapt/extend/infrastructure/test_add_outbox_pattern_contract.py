"""Generic tool-contract mutation coverage for add_outbox_pattern.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_outbox_pattern.py in the mutation
runner: ``--tests test_add_outbox_pattern.py test_add_outbox_pattern_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_outbox_pattern import (
    _patch_models_init,
    add_outbox_pattern,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_outbox_pattern import add_outbox_pattern

    for check in SCAFFOLDABLE_CHECKS:
        check(add_outbox_pattern, "add_outbox_pattern")


# ---------------------------------------------------------------------------
# Tool-specific mutation kills (survivors not covered by the generic preamble).
# ---------------------------------------------------------------------------


def test_scaffolded_prereqs_carried_into_files_created() -> None:
    """L89 BoolOp Or->And: ``list(scaffolded or [])`` must keep prereq files.

    On a bare project the prerequisite step auto-scaffolds app/core/config.py,
    app/models/base.py, etc. and returns them as ``scaffolded``. ``Or->And``
    flips ``scaffolded or []`` -> ``scaffolded and []`` which evaluates to the
    empty list, silently dropping every auto-scaffolded file from the result.
    """
    bare = Path(tempfile.mkdtemp())
    result = add_outbox_pattern(ToolInput(project_dir=str(bare)))
    assert result.status == "success", result.error
    # These come ONLY from the scaffolded prereq list, not from the outbox body.
    assert any(p.endswith("app/core/config.py") for p in result.files_created), (
        "auto-scaffolded config.py must survive into files_created"
    )
    assert any(p.endswith("app/models/base.py") for p in result.files_created), (
        "auto-scaffolded base model must survive into files_created"
    )


def test_events_init_written_on_fresh_project() -> None:
    """L123 UnaryNot ``not events_init.exists()``: package init must be created.

    Flipping the guard to ``if events_init.exists()`` would only write the
    file when it already exists, so on a fresh project the events package
    ``__init__.py`` would never be emitted.
    """
    project = create_fixture_project(name="obx_ctr_init")
    result = add_outbox_pattern(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    events_init = project / "app" / "events" / "__init__.py"
    assert events_init.exists(), "events/__init__.py must be created on a fresh project"
    assert any(p.endswith("app/events/__init__.py") for p in result.files_created), (
        "events/__init__.py must be reported in files_created"
    )


def test_succeeds_when_events_dir_preexists() -> None:
    """L121 BoolLiteral True->False on ``events_dir.mkdir(exist_ok=True)``.

    With ``exist_ok=False`` the mkdir raises FileExistsError when app/events
    already exists, breaking the run. Pre-creating the dir and asserting
    success kills the flip.
    """
    project = create_fixture_project(name="obx_ctr_evdir")
    (project / "app" / "events").mkdir(parents=True, exist_ok=True)
    result = add_outbox_pattern(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert (project / "app" / "events" / "outbox.py").exists()


def test_succeeds_when_models_dir_preexists() -> None:
    """L135 BoolLiteral True->False on ``models.mkdir(exist_ok=True)``.

    A standard fixture already has app/models; with ``exist_ok=False`` the
    mkdir raises FileExistsError. Asserting success + that the model file
    landed kills the flip.
    """
    project = create_fixture_project(name="obx_ctr_mdir")
    assert (project / "app" / "models").exists(), "fixture should ship app/models"
    result = add_outbox_pattern(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert (project / "app" / "models" / "outbox.py").exists()


def test_succeeds_when_services_dir_preexists() -> None:
    """L144 BoolLiteral True->False on ``services.mkdir(exist_ok=True)``.

    Pre-create app/services so that an ``exist_ok=False`` flip raises
    FileExistsError; success + emitted service file kills the flip.
    """
    project = create_fixture_project(name="obx_ctr_sdir")
    (project / "app" / "services").mkdir(parents=True, exist_ok=True)
    result = add_outbox_pattern(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert (project / "app" / "services" / "outbox.py").exists()


def test_models_init_gets_both_outbox_imports() -> None:
    """L238/L244/L247 — _patch_models_init must append both class imports.

    - L238 UnaryNot ``not models_init.exists()``: flip returns early when the
      file DOES exist, so nothing is patched.
    - L244 Compare In->NotIn ``if marker in content``: flip ``not in`` makes
      every absent marker ``continue``, so no import is ever appended.
    - L247 UnaryNot ``not new_lines``: flip returns when there ARE new lines,
      so the file is never written.
    Asserting both imports are present after a single run kills all three.
    """
    project = create_fixture_project(name="obx_ctr_mi")
    add_outbox_pattern(ToolInput(project_dir=str(project)))
    content = (project / "app" / "models" / "__init__.py").read_text()
    assert "from app.models.outbox import OutboxEvent" in content
    assert "from app.models.outbox import OutboxDlq" in content


def test_models_init_imports_not_duplicated_on_second_run() -> None:
    """L244 Compare In->NotIn dedup: a second run must not double the imports.

    The ``if marker in content: continue`` guard dedups. Idempotency means the
    OutboxEvent import appears exactly once even after running twice.
    """
    project = create_fixture_project(name="obx_ctr_mi2")
    add_outbox_pattern(ToolInput(project_dir=str(project)))
    add_outbox_pattern(ToolInput(project_dir=str(project)))
    content = (project / "app" / "models" / "__init__.py").read_text()
    assert content.count("from app.models.outbox import OutboxEvent") == 1
    assert content.count("from app.models.outbox import OutboxDlq") == 1


def test_patch_models_init_handles_missing_trailing_newline() -> None:
    """L249 UnaryNot ``not content.endswith()``: new import must be on its own line.

    When the existing __init__ has no trailing newline, the tool prepends one
    before appending. The flip ``if content.endswith("\\n")`` would only add a
    newline when one already exists, gluing the new import onto the previous
    line. Asserting the original line stays intact kills the flip.
    """
    d = Path(tempfile.mkdtemp())
    models_init = d / "__init__.py"
    original = "from app.models.user import User  # noqa: F401"  # no trailing \n
    models_init.write_text(original)
    _patch_models_init(models_init, [("outbox", "OutboxEvent")])
    lines = models_init.read_text().splitlines()
    assert lines[0] == original, "existing import line must not be mangled"
    assert any(line.startswith("from app.models.outbox import OutboxEvent") for line in lines), (
        "new import must land on its own line"
    )


def test_patch_models_init_noop_when_file_missing() -> None:
    """L238 UnaryNot ``not models_init.exists()``: missing file is a clean no-op.

    The guard returns early when the file is absent. With the flip the function
    would attempt ``models_init.read_text()`` on a non-existent path and raise.
    """
    d = Path(tempfile.mkdtemp())
    missing = d / "__init__.py"
    assert not missing.exists()
    _patch_models_init(missing, [("outbox", "OutboxEvent")])  # must not raise
    assert not missing.exists(), "missing file must stay absent (clean return)"
