"""Generic tool-contract mutation coverage for add_feature_flags.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_feature_flags.py in the mutation
runner: ``--tests test_add_feature_flags.py test_add_feature_flags_contract.py``.

The ``test_kill_*`` functions below target this tool's *specific* logic
(the survivors the generic preamble checks leave alive): the models/__init__
patcher, the main.py lifespan patcher, the migration down-revision fallback,
and the prerequisite-error message builder.
"""

import ast
import tempfile

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_feature_flags import add_feature_flags
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_feature_flags import add_feature_flags

    for check in UNIVERSAL_CHECKS:
        check(add_feature_flags, "add_feature_flags")


# ---------------------------------------------------------------------------
# Tool-specific survivor kills
# ---------------------------------------------------------------------------


def test_kill_emit_creates_into_existing_parent_dirs():
    """L40 exist_ok=True->False: the emitted modules land in pre-existing
    package dirs (app/models, app/core, app/crud, ...). If mkdir lost
    exist_ok the tool would raise FileExistsError on the fixture, so a clean
    success here pins the literal."""
    project = create_fixture_project(name="ff_kill_emit")
    result = add_feature_flags(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    for rel in (
        "app/models/feature_flag.py",
        "app/core/feature_flag_cache.py",
        "app/core/feature_flag_evaluator.py",
        "app/core/feature_flag_deps.py",
        "app/crud/feature_flag.py",
        "app/schemas/feature_flag.py",
        "app/api/routes/feature_flags.py",
    ):
        assert (project / rel).is_file(), f"missing emitted file: {rel}"


def test_kill_prereq_error_message_is_concatenated():
    """L65 Add->Sub: the prereq-error path builds
    ``"Prerequisites not met:\\n" + "\\n".join(...)``. Sub would TypeError
    on str-minus-str, so a bare project must return a clean error whose
    body contains BOTH the header and the joined detail lines."""
    bare = tempfile.mkdtemp()
    result = add_feature_flags(ToolInput(project_dir=bare))
    assert result.status == "error"
    assert result.error is not None
    assert result.error.startswith("Prerequisites not met:\n")
    # The joined ("\n".join) detail lines must be appended after the header.
    assert "  - " in result.error
    assert result.error.count("\n") >= 1


def test_kill_models_init_patched_with_both_imports():
    """L237 (not exists guard), L243 (In dedup), L246 (not new_lines guard):
    after a run, models/__init__.py must import BOTH FeatureFlag and
    FeatureFlagAudit. NotIn would never add an absent marker; a flipped
    early-return would skip patching entirely; an inverted ``not new_lines``
    would bail before writing."""
    project = create_fixture_project(name="ff_kill_models_init")
    result = add_feature_flags(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    body = (project / "app" / "models" / "__init__.py").read_text()
    assert "from app.models.feature_flag import FeatureFlag  # noqa: F401" in body
    assert "from app.models.feature_flag import FeatureFlagAudit  # noqa: F401" in body
    # Each import appears exactly once (no double-insert) — the In dedup.
    assert body.count("from app.models.feature_flag import FeatureFlag ") == 1
    assert body.count("from app.models.feature_flag import FeatureFlagAudit") == 1


def test_kill_models_init_dedup_on_preseeded_marker():
    """L243 In->NotIn: pre-seed models/__init__.py with one of the two
    markers; the tool must skip the present one (dedup) yet still add the
    absent one. NotIn inverts both decisions: it would re-append the present
    marker (duplicate) and drop the absent one."""
    project = create_fixture_project(name="ff_kill_models_dedup")
    init_path = project / "app" / "models" / "__init__.py"
    seeded = init_path.read_text()
    seeded += "from app.models.feature_flag import FeatureFlag  # noqa: F401\n"
    init_path.write_text(seeded)

    result = add_feature_flags(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    body = init_path.read_text()
    # Present marker stays single (dedup'd), absent marker gets added.
    assert body.count("from app.models.feature_flag import FeatureFlag ") == 1
    assert "from app.models.feature_flag import FeatureFlagAudit  # noqa: F401" in body


def test_kill_models_init_separator_newline_when_no_trailing_nl():
    """L248 ``not content.endswith("\\n")``: when the existing
    models/__init__.py has NO trailing newline, the tool must insert one
    before appending so imports do not concatenate onto the last line.
    Flipping the guard would glue the new import onto the previous line,
    producing an unparseable file."""
    project = create_fixture_project(name="ff_kill_models_nonl")
    init_path = project / "app" / "models" / "__init__.py"
    init_path.write_text(init_path.read_text().rstrip("\n"))  # strip trailing nl

    result = add_feature_flags(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    body = init_path.read_text()
    # The new import must be on its own line (start-of-line), not glued.
    assert "\nfrom app.models.feature_flag import FeatureFlag  # noqa: F401" in body
    ast.parse(body)  # would raise if the import was concatenated


def test_kill_main_lifespan_patched_with_listener_stub():
    """L269 ``"feature_flag" in src`` (idempotency guard) and L278
    ``marker in src`` (anchor): the fixture main.py has ``await init_db()``
    and no ``feature_flag`` text, so the tool must inject the commented
    invalidation-listener stub right where the anchor is. NotIn on either
    compare would skip the injection on this exact project shape."""
    project = create_fixture_project(name="ff_kill_main")
    main_path = project / "app" / "main.py"
    before = main_path.read_text()
    assert "await init_db()" in before
    assert "feature_flag" not in before

    result = add_feature_flags(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    after = main_path.read_text()
    assert "start Redis invalidation listener" in after
    assert "start_invalidation_listener" in after
    # The stub is anchored to the init_db() call.
    anchor = "await init_db()"
    note_pos = after.find("start Redis invalidation listener")
    anchor_pos = after.find(anchor)
    assert anchor_pos != -1 and note_pos > anchor_pos
    assert str(main_path) in result.files_modified


def test_kill_migration_down_revision_uses_current_head():
    """L256 ``find_migration_head(...) or "0001_initial"``: the fixture has a
    real migration head, so down_revision must equal that head — NOT the
    fallback. ``and`` would coerce the truthy head to the literal
    ``"0001_initial"``."""
    project = create_fixture_project(name="ff_kill_migration")
    result = add_feature_flags(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    versions = project / "alembic" / "versions"
    migration = next(iter(versions.glob("*feature_flags*")))
    content = migration.read_text()
    # Real head present in fixture is 0002_baseline_schema (not the fallback).
    assert 'down_revision = "0002_baseline_schema"' in content
    assert 'down_revision = "0001_initial"' not in content
