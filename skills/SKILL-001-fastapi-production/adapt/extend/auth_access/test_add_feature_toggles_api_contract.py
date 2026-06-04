"""Generic tool-contract mutation coverage for add_feature_toggles_api.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_feature_toggles_api.py in the mutation
runner: ``--tests test_add_feature_toggles_api.py test_add_feature_toggles_api_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_feature_toggles_api import add_feature_toggles_api
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_feature_toggles_api, "add_feature_toggles_api")


def test_scaffolded_prereq_files_tracked_in_files_created():
    """Kills L71 BoolOp Or->And on ``list(scaffolded or [])``.

    On a bare project (no config/requirements) the prerequisite layer
    auto-scaffolds ``app/core/config.py`` etc. and returns them. The tool seeds
    ``files_created`` with ``scaffolded or []`` so those files are reported back
    to the caller. The mutant ``scaffolded and []`` evaluates to ``[]`` whenever
    ``scaffolded`` is truthy, silently dropping every auto-scaffolded file from
    the result.
    """
    d = Path(tempfile.mkdtemp())
    r = add_feature_toggles_api(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error
    files = r.files_created or []
    # The auto-scaffolded config prerequisite must be reported.
    assert any(f.endswith("config.py") for f in files), (
        f"auto-scaffolded prereq dropped from files_created: {files}"
    )
    # And the bare-project run still scaffolds more than just the tool's own glue.
    assert len(files) >= 3, files


def test_existing_glue_without_adapter_marker_is_rewired():
    """Kills the no_op-guard BoolOp And->Or.

    The no_op guard is ``glue_file.exists() and "FeatureToggleAdapter" in
    glue_file.read_text()`` — it short-circuits to ``no_op`` ONLY when the glue
    file both exists *and* already references the adapter. If a stale/placeholder
    ``app/feature_toggles.py`` exists *without* the adapter marker, the tool must
    proceed and wire it. The mutant ``exists() or "...marker..." in text`` would
    treat any pre-existing glue file as already-wired and bail out with no_op,
    leaving the placeholder unwired.
    """
    p = create_fixture_project(name="ft_guard_and")
    app = p / "app"
    app.mkdir(parents=True, exist_ok=True)
    glue = app / "feature_toggles.py"
    glue.write_text("# placeholder, adapter not wired yet\n")

    r = add_feature_toggles_api(ToolInput(project_dir=str(p)))

    assert r.status == "success", r.error
    body = glue.read_text()
    assert "FeatureToggleAdapter" in body, "tool failed to rewire marker-less glue"


def test_fully_wired_glue_is_no_op():
    """Kills the no_op-guard Compare NotIn variant on the adapter marker.

    Once the glue exists *and* already contains ``FeatureToggleAdapter`` the tool
    must report ``no_op`` (idempotent re-run). The ``in`` -> ``not in`` mutant
    would invert the membership test so an already-wired project would be
    re-processed instead of short-circuiting.
    """
    p = create_fixture_project(name="ft_guard_in")
    first = add_feature_toggles_api(ToolInput(project_dir=str(p)))
    assert first.status == "success", first.error
    assert "FeatureToggleAdapter" in (p / "app" / "feature_toggles.py").read_text()

    second = add_feature_toggles_api(ToolInput(project_dir=str(p)))
    assert second.status == "no_op", second.status
