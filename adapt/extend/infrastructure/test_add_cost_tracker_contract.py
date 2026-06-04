"""Generic tool-contract mutation coverage for add_cost_tracker.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_cost_tracker.py in the mutation
runner: ``--tests test_add_cost_tracker.py test_add_cost_tracker_contract.py``.
"""

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_cost_tracker import add_cost_tracker
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def _resolved(paths) -> set[str]:
    """Resolve every path so macOS /var -> /private/var symlinks compare equal."""
    return {str(Path(p).resolve()) for p in paths}


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_cost_tracker, "add_cost_tracker")


def test_scaffolded_prereq_lands_in_files_created() -> None:
    """L69 ``list(scaffolded or [])``: Or->And would drop auto-scaffolded prereqs.

    When ``app/core/config.py`` is missing, the CONFIG_SETTINGS prereq
    regenerates it and ``ensure_prerequisites`` returns its path in
    ``scaffolded``. The tool seeds ``files_created`` from that list, so the
    regenerated config must surface in ``files_created``. The And-mutant
    seeds an empty list (``scaffolded and []`` -> ``[]``) and the path
    disappears.
    """
    d = create_fixture_project(name="ct_ct_l69")
    config = d / "app" / "core" / "config.py"
    assert config.exists()
    config.unlink()

    r = add_cost_tracker(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error

    created = _resolved(r.files_created)
    assert str(config.resolve()) in created, r.files_created


def test_config_not_remodified_when_marker_present() -> None:
    """L106 guard ``exists() and "COST_DB_QUERY_RATE" not in ...``.

    And->Or flips the second clause from a gate into a fallback: when the
    config already carries the COST_DB_QUERY_RATE marker, And short-circuits
    (no re-patch, config absent from files_modified) while Or would patch
    again and append the path. Asserting the marker-present config is NOT in
    files_modified kills the Or-mutant.
    """
    d = create_fixture_project(name="ct_ct_l106")
    config = d / "app" / "core" / "config.py"
    config.write_text(config.read_text() + "\n    COST_DB_QUERY_RATE: float = 0.5\n")

    r = add_cost_tracker(ToolInput(project_dir=str(d)))
    assert r.status == "success", r.error

    modified = _resolved(r.files_modified)
    assert str(config.resolve()) not in modified, r.files_modified
