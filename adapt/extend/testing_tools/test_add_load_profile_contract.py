"""Generic tool-contract mutation coverage for add_load_profile.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_load_profile.py in the mutation
runner: ``--tests test_add_load_profile.py test_add_load_profile_contract.py``.

The ``test_kill_*`` functions below target this tool's *bespoke* logic — the
arithmetic that derives smoke/baseline/peak user counts and spawn rates for the
generated Locust shapes, CI workflow, and result notes, plus the
emitted-test-file idempotency guard. These survive the generic preamble checks.
"""

from __future__ import annotations

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_load_profile import add_load_profile
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_load_profile import add_load_profile

    for check in SCAFFOLDABLE_CHECKS:
        check(add_load_profile, "add_load_profile")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Distinct config so every arithmetic op produces a unique number:
#   users=100   -> //10=10  //5=20  //2=50  *2=200  *3=300
#   spawn=10    -> *2=20  *3=30
_USERS = 100
_SPAWN = 10
_DURATION = 60


def _run(name: str):
    """Generate a fresh project, run the tool with the canonical config."""
    project = create_fixture_project(name=name)
    result = add_load_profile(
        ToolInput(project_dir=str(project)),
        users=_USERS,
        spawn_rate=_SPAWN,
        duration_seconds=_DURATION,
    )
    assert result.status == "success", result.error
    return project, result


def _read(project: Path, *parts: str) -> str:
    return (project.joinpath(*parts)).read_text()


# ---------------------------------------------------------------------------
# Arithmetic in the result notes (L167)
# ---------------------------------------------------------------------------


def test_kill_notes_peak_users_is_users_times_3():
    """L167 ``users * 3``: the success notes advertise the peak profile size.

    Mult->FloorDiv would print ``peak (33 users)`` instead of ``peak (300 users)``.
    """
    _project, result = _run("loadprof_notes_peak")
    notes = "\n".join(result.notes)
    assert f"peak ({_USERS * 3} users)" in notes
    # The floor-div mutant value must NOT appear.
    assert f"peak ({_USERS // 3} users)" not in notes


def test_kill_notes_smoke_and_baseline_counts():
    """The notes also state the smoke (10 users) and baseline (100 users) sizes."""
    _project, result = _run("loadprof_notes_counts")
    notes = "\n".join(result.notes)
    assert f"smoke ({_DURATION}s / 10 users)" in notes
    assert f"baseline ({_USERS} users)" in notes


# ---------------------------------------------------------------------------
# Arithmetic in shapes.py (L199, L200, L201, L202, L240, L241)
# ---------------------------------------------------------------------------


def test_kill_shapes_smoke_users_floordiv_10():
    """L199 ``max(5, users // 10)``: SmokeShape uses 10 users for users=100.

    FloorDiv->Mult would yield 1000 smoke users.
    """
    project, _ = _run("loadprof_shape_smoke")
    shapes = _read(project, "tests", "load", "shapes.py")
    expected = max(5, _USERS // 10)  # 10
    assert f"Minimal smoke profile: {expected} users" in shapes
    assert f"'users': {expected}," in shapes
    # The mutant value (users * 10 == 1000) must be absent.
    assert f"'users': {_USERS * 10}," not in shapes


def test_kill_shapes_peak_users_mult_3():
    """L200 ``peak_users = users * 3``: PeakShape envelope is 300 users.

    Mult->FloorDiv would make peak_users == 33.
    """
    project, _ = _run("loadprof_shape_peak")
    shapes = _read(project, "tests", "load", "shapes.py")
    peak = _USERS * 3  # 300
    assert f"Step-load up to {peak} users" in shapes
    assert f"'users': {peak}," in shapes
    assert f"'users': {_USERS // 3}," not in shapes


def test_kill_shapes_baseline_fifth_floordiv_5():
    """L201 ``users_fifth = max(1, users // 5)``: BaselineShape stage 1 = 20 users.

    FloorDiv->Mult would yield 500.
    """
    project, _ = _run("loadprof_shape_fifth")
    shapes = _read(project, "tests", "load", "shapes.py")
    fifth = max(1, _USERS // 5)  # 20
    assert f"'duration': 30,  'users': {fifth}," in shapes
    assert f"'users': {_USERS * 5}," not in shapes


def test_kill_shapes_baseline_half_floordiv_2():
    """L202 ``users_half = users // 2``: BaselineShape stage 2 = 50 users.

    FloorDiv->Mult would yield 200.
    """
    project, _ = _run("loadprof_shape_half")
    shapes = _read(project, "tests", "load", "shapes.py")
    half = _USERS // 2  # 50
    assert f"'duration': 90,  'users': {half}," in shapes


def test_kill_shapes_peak_stage2_users_and_spawn_mult_2():
    """L240 ``users * 2`` and ``spawn_rate * 2``: PeakShape stage 2.

    For users=100 / spawn=10 the stage is users=200, spawn_rate=20.
    Mult->FloorDiv would give users=50 (100//2) / spawn=5 (10//2).
    """
    project, _ = _run("loadprof_shape_stage2")
    shapes = _read(project, "tests", "load", "shapes.py")
    line = f"'duration': 120, 'users': {_USERS * 2},     'spawn_rate': {_SPAWN * 2}}}"
    assert line in shapes
    # Mutated values must not appear together on a peak stage line.
    assert f"'duration': 120, 'users': {_USERS // 2}," not in shapes


def test_kill_shapes_peak_stage3_users_and_spawn_mult_3():
    """L241 ``peak_users`` (==users*3) and ``spawn_rate * 3``: PeakShape stage 3.

    For users=100 / spawn=10 the stage is users=300, spawn_rate=30.
    Mult->FloorDiv on spawn_rate*3 would give spawn_rate=3.
    """
    project, _ = _run("loadprof_shape_stage3")
    shapes = _read(project, "tests", "load", "shapes.py")
    line = f"'duration': 200, 'users': {_USERS * 3},    'spawn_rate': {_SPAWN * 3}}}"
    assert line in shapes
    assert f"'spawn_rate': {_SPAWN // 3}}}" not in shapes


# ---------------------------------------------------------------------------
# Arithmetic in the CI workflow (L296)
# ---------------------------------------------------------------------------


def test_kill_ci_smoke_users_floordiv_10():
    """L296 ``smoke_users = max(5, users // 10)`` in the CI workflow.

    The generated load-tests.yml runs ``--users 10`` for users=100.
    FloorDiv->Mult would emit ``--users 1000``.
    """
    project, _ = _run("loadprof_ci_smoke")
    ci = _read(project, ".github", "workflows", "load-tests.yml")
    expected = max(5, _USERS // 10)  # 10
    assert f"--users {expected} " in ci
    assert f"--users {_USERS * 10} " not in ci


# ---------------------------------------------------------------------------
# Emitted-test idempotency guard (L157 UnaryNot)
# ---------------------------------------------------------------------------


def test_kill_emitted_test_guard_not_exists():
    """L157 ``if not emitted.exists():`` guards the emitted regression test.

    Pre-seed tests/test_add_load_profile_emitted.py with a sentinel. Because the
    locustfile fingerprint is absent the tool runs fully, but it must NOT
    overwrite the pre-existing emitted file (guard = ``not exists``). Flipping
    to ``if emitted.exists():`` would render over our sentinel.
    """
    project = create_fixture_project(name="loadprof_emitted_guard")
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_load_profile_emitted.py"
    sentinel = "# SENTINEL — must not be overwritten\n"
    emitted.write_text(sentinel)

    result = add_load_profile(
        ToolInput(project_dir=str(project)),
        users=_USERS,
        spawn_rate=_SPAWN,
        duration_seconds=_DURATION,
    )
    assert result.status == "success", result.error
    # Guard intact: sentinel preserved, and the emitted path is NOT reported as
    # newly created.
    assert emitted.read_text() == sentinel
    assert not any(
        p.endswith("tests/test_add_load_profile_emitted.py") for p in result.files_created
    )


def test_kill_emitted_test_rendered_when_absent():
    """Companion to L157: on a clean project the emitted file IS rendered.

    This pins the true branch (``not exists`` -> render) so a mutant that
    short-circuits the render is caught from the other side.
    """
    project, result = _run("loadprof_emitted_render")
    emitted = project / "tests" / "test_add_load_profile_emitted.py"
    assert emitted.is_file()
    assert any(p.endswith("tests/test_add_load_profile_emitted.py") for p in result.files_created)
    # The bespoke emitted file is a real generated test, not our sentinel.
    assert "SENTINEL" not in emitted.read_text()


# ---------------------------------------------------------------------------
# scaffolded-fallback fold (L76 BoolOp Or->And)
# ---------------------------------------------------------------------------


def test_kill_scaffolded_prereq_files_included():
    """L76 ``files_created = list(scaffolded or [])``.

    On a bare project (no app/models/base.py) the BASE_MODEL prereq
    auto-scaffolds files; those paths must seed files_created. Flipping ``or``
    to ``and`` would discard the scaffolded list (``list([])``), dropping the
    auto-created base-model files from the report.
    """
    project = create_fixture_project(name="loadprof_scaffold_base")
    # Remove the base-model so the prereq must auto-scaffold it on this run.
    base_model = project / "app" / "models" / "base.py"
    if not base_model.exists():
        # Nothing to remove → this fixture can't exercise the path; skip body.
        return
    base_model.unlink()

    result = add_load_profile(
        ToolInput(project_dir=str(project)),
        users=_USERS,
        spawn_rate=_SPAWN,
        duration_seconds=_DURATION,
    )
    assert result.status == "success", result.error
    # The auto-scaffolded base model must be reported as created.
    assert any(p.endswith("app/models/base.py") for p in result.files_created)
