"""Generic tool-contract mutation coverage for add_anomaly_detector.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_anomaly_detector.py in the mutation
runner: ``--tests test_add_anomaly_detector.py test_add_anomaly_detector_contract.py``.

The per-tool tests below target the mutants the generic preamble does NOT
cover: the idempotency content guard (``exists() and marker in text``) and
the ``parents=True`` mkdir in ``_emit_project_test`` (the only non-equivalent
``True``->``False`` literal — its parents are not guaranteed to pre-exist when
the helper is called directly). The routes/config insertion branches and the
defensive ast.parse guard are exercised here too, though the mutation runner
finds no mutable operators in those bare ``if x.exists():`` lines.
"""

from __future__ import annotations

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_anomaly_detector import (
    _emit_project_test,
    add_anomaly_detector,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def _resolved(paths: list[str]) -> set[str]:
    """Resolve paths so macOS /var -> /private/var symlinks compare equal."""
    return {str(Path(p).resolve()) for p in paths}


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_anomaly_detector, "add_anomaly_detector")


# ---------------------------------------------------------------------------
# L35: idempotency content guard
#   ``detector_file.exists() and 'AnomalyDetector' in detector_file.read_text()``
# Kills the ``and``->``or`` BoolOp flip and the ``in``->``not in`` Compare flip.
# A stale detector.py that lacks the marker must NOT short-circuit to no_op.
# ---------------------------------------------------------------------------


def test_stale_detector_without_marker_is_not_no_op() -> None:
    """detector.py present but missing 'AnomalyDetector' -> tool proceeds.

    With the real guard (``exists() AND marker in text``) the marker is
    absent, so the guard is False and the tool writes. An ``and``->``or``
    flip would short-circuit on ``exists()`` alone and return no_op; an
    ``in``->``not in`` flip would also trip the guard.
    """
    project = create_fixture_project(name="anomaly_stale")
    detector_file = project / "app" / "anomaly" / "detector.py"
    detector_file.parent.mkdir(parents=True, exist_ok=True)
    detector_file.write_text("# placeholder, no marker here\n")

    result = add_anomaly_detector(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert "AnomalyDetector" in detector_file.read_text(), (
        "stale detector.py should have been overwritten with real content"
    )


def test_marker_present_is_no_op() -> None:
    """detector.py WITH the marker -> no_op (anchors the True branch)."""
    project = create_fixture_project(name="anomaly_marker")
    detector_file = project / "app" / "anomaly" / "detector.py"
    detector_file.parent.mkdir(parents=True, exist_ok=True)
    detector_file.write_text("class AnomalyDetector:\n    pass\n")

    result = add_anomaly_detector(ToolInput(project_dir=str(project)))
    assert result.status == "no_op", f"expected no_op, got {result.status}"
    assert not result.files_created


# ---------------------------------------------------------------------------
# L60: ``if routes_dir.exists():`` controls whether routes/anomaly.py is written
# Kills flipping this branch — full fixture HAS routes/, bare project does not.
# ---------------------------------------------------------------------------


def test_routes_dir_present_emits_route_file() -> None:
    """When app/api/routes/ exists, the anomaly route file is created."""
    project = create_fixture_project(name="anomaly_routes_yes")
    assert (project / "app" / "api" / "routes").exists()
    result = add_anomaly_detector(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    route_file = project / "app" / "api" / "routes" / "anomaly.py"
    assert route_file.exists(), "route file must be created when routes/ exists"
    assert str(route_file.resolve()) in _resolved(result.files_created)


def test_routes_dir_absent_skips_route_file() -> None:
    """When app/api/routes/ is absent, no route file is emitted.

    A bare project auto-scaffolds config + requirements but has no
    api/routes/ tree, so the routes branch is False. Flipping the branch
    would attempt to write into a non-existent dir.
    """
    import tempfile

    bare = Path(tempfile.mkdtemp()) / "anomaly_routes_no"
    bare.mkdir(parents=True)
    result = add_anomaly_detector(ToolInput(project_dir=str(bare)))
    assert result.status == "success", result.error
    route_file = bare / "app" / "api" / "routes" / "anomaly.py"
    assert not route_file.exists(), "no route file without a routes/ dir"
    assert not any(p.endswith("api/routes/anomaly.py") for p in result.files_created)


# ---------------------------------------------------------------------------
# L65: ``if config_file.exists():`` controls config patch + files_modified.
# Kills flipping this branch — full fixture HAS config.py; bare project does
# (auto-scaffolded). A False fixture: a project with app/ but no core/config.py.
# ---------------------------------------------------------------------------


def test_config_present_is_patched_and_reported() -> None:
    """config.py present -> ANOMALY_* injected and listed in files_modified."""
    project = create_fixture_project(name="anomaly_cfg_yes")
    config_file = project / "app" / "core" / "config.py"
    assert config_file.exists()
    result = add_anomaly_detector(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert "ANOMALY_ENABLED" in config_file.read_text()
    assert str(config_file.resolve()) in _resolved(result.files_modified)


# ---------------------------------------------------------------------------
# L86 (in _emit_project_test): ``if emitted.exists(): return`` dedup guard.
# Kills flipping the guard — a pre-existing emitted test must be left intact
# and NOT re-appended to files_created.
# ---------------------------------------------------------------------------


def test_emitted_test_dedup_preserves_existing() -> None:
    """A pre-existing emitted test is neither overwritten nor re-listed."""
    project = create_fixture_project(name="anomaly_emit_dedup")
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_anomaly_detector_emitted.py"
    sentinel = "# SENTINEL: pre-existing, must survive\n"
    emitted.write_text(sentinel)

    created: list[str] = []
    _emit_project_test(project, created)

    assert emitted.read_text() == sentinel, "existing emitted test was overwritten"
    assert not any(p.endswith("test_add_anomaly_detector_emitted.py") for p in created)


def test_emitted_test_written_when_absent() -> None:
    """When the emitted test is absent it is created and appended (False branch)."""
    project = create_fixture_project(name="anomaly_emit_new")
    emitted = project / "tests" / "test_add_anomaly_detector_emitted.py"
    if emitted.exists():
        emitted.unlink()

    created: list[str] = []
    _emit_project_test(project, created)

    assert emitted.exists(), "emitted test should be created when absent"
    assert str(emitted.resolve()) in _resolved(created)


def test_emitted_test_mkdir_creates_missing_parents() -> None:
    """``(project / 'tests').mkdir(parents=True, ...)`` must create missing
    intermediate dirs. Project sits under not-yet-existing ancestors, so
    ``parents=True`` is load-bearing — a ``True``->``False`` flip would raise
    FileNotFoundError instead of writing the emitted test.
    """
    import tempfile

    base = Path(tempfile.mkdtemp())
    project = base / "missing_a" / "missing_b" / "proj"  # ancestors absent

    created: list[str] = []
    _emit_project_test(project, created)

    emitted = project / "tests" / "test_add_anomaly_detector_emitted.py"
    assert emitted.exists(), "emitted test should be written through missing parents"
    assert str(emitted.resolve()) in _resolved(created)
