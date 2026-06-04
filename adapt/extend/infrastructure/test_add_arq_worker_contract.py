"""Generic + tool-specific mutation coverage for add_arq_worker.

The generic block applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests.

The tool-specific block below targets the *positional / anchor / dedup /
branch* mutants that the presence-only bespoke test cannot detect:

  * ``_patch_config`` anchor branch (block must follow the
    ``ACCESS_TOKEN_EXPIRE_MINUTES`` anchor, not the ``settings =`` fallback).
  * ``_register_router`` index math + fallback ``and`` (import must precede
    ``api_router = APIRouter()``; include must follow the include block).
  * ``_patch_main`` lifespan wiring (pool create BEFORE ``yield``, pool close
    AFTER ``yield`` — not just the import line that mentions both names).
  * migration ``down_rev or '0001_initial'`` fallback (must resolve to the
    real head).
  * ``_patch_requirements`` redis dedup (``not in`` guard must not duplicate
    the already-present redis pin).
  * ``_patch_models_init`` dedup + formatting (no duplicate import, no blank
    line wedged between the existing imports and the new one).
  * workers ``__init__.py`` creation guard.
"""

from __future__ import annotations

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_arq_worker import (
    _patch_config,
    _patch_main,
    _patch_models_init,
    _register_router,
    add_arq_worker,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def _resolved_set(paths: list[str]) -> set[str]:
    return {str(Path(p).resolve()) for p in paths}


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_arq_worker, "add_arq_worker")


# ---------------------------------------------------------------------------
# _patch_config — anchor branch (L158-160)
# ---------------------------------------------------------------------------


def test_config_block_follows_access_token_anchor():
    """The ARQ block is injected right after the ACCESS_TOKEN anchor.

    Kills the ``anchor in src`` In->NotIn flip, which would fall through to
    the ``settings = Settings()`` fallback and place the block elsewhere.
    """
    project = create_fixture_project(name="arq_c_anchor")
    result = add_arq_worker(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    content = (project / "app" / "core" / "config.py").read_text()
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    assert anchor in content
    after = content.split(anchor, 1)[1]
    # The very next non-empty content after the anchor must be the arq block,
    # not the rest of the Settings class (CORS/etc.).
    head = after.lstrip("\n")
    assert head.startswith("    # --- arq worker settings"), (
        f"ARQ block not anchored after ACCESS_TOKEN line; got: {head[:80]!r}"
    )
    assert "ARQ_MAX_JOBS: int = 10" in after.split("# --- CORS ---")[0]


# ---------------------------------------------------------------------------
# _register_router — positional insertion (L179-198)
# ---------------------------------------------------------------------------


def test_jobs_import_is_last_app_import_and_last_include():
    """jobs import is appended right after the last ``from app.`` import, and
    the jobs include right after the last existing ``include_router``.

    Kills the ``last_app_import_idx == -1`` Eq->NotEq flip AND the
    ``insert(idx + 1)`` Add->Sub flips: with ``- 1`` the new lines would land
    one slot too early (not the last import / not the last include).
    """
    project = create_fixture_project(name="arq_c_router")
    add_arq_worker(ToolInput(project_dir=str(project)))
    lines = (project / "app" / "routes" / "__init__.py").read_text().splitlines()
    import_idx = next(i for i, ln in enumerate(lines) if "from app.api.routes.jobs import" in ln)
    construct_idx = next(
        i for i, ln in enumerate(lines) if ln.strip() == "api_router = APIRouter()"
    )
    include_idx = next(i for i, ln in enumerate(lines) if "include_router(jobs_router)" in ln)
    assert import_idx < construct_idx, "jobs import must precede api_router = APIRouter()"
    assert include_idx > construct_idx, "jobs include must follow api_router construction"

    # The jobs import must be the LAST ``from app.`` import line (it is appended
    # after the previous last one). Add->Sub would make it not the last.
    app_import_idxs = [i for i, ln in enumerate(lines) if ln.startswith("from app.")]
    assert import_idx == max(app_import_idxs), (
        f"jobs import not appended after the last app import: {import_idx} vs {app_import_idxs}"
    )
    # The jobs include must be the LAST ``api_router.include_router`` line.
    include_idxs = [i for i, ln in enumerate(lines) if ln.startswith("api_router.include_router")]
    assert include_idx == max(include_idxs), (
        f"jobs include not appended after the last include: {include_idx} vs {include_idxs}"
    )


def test_register_router_fallback_anchors_on_apirouter_line(tmp_path: Path):
    """No ``from app.`` imports + no ``include_router`` lines -> anchor search.

    The fixture deliberately mentions ``api_router`` in a COMMENT line above
    the construction, so the ``'api_router' in line and 'APIRouter()' in line``
    And->Or flip is killable: ``and`` matches only the real construction line
    (``api_router = APIRouter()``), while ``or`` would match the earlier
    comment line and misplace BOTH the import and the include.
    """
    ri = tmp_path / "routes_init.py"
    ri.write_text(
        "from fastapi import APIRouter\n# configure api_router below\napi_router = APIRouter()\n"
    )
    _register_router(
        ri,
        import_line="from app.api.routes.jobs import router as jobs_router",
        include_line="api_router.include_router(jobs_router)",
    )
    lines = ri.read_text().splitlines()
    import_idx = next(i for i, ln in enumerate(lines) if "jobs import" in ln)
    construct_idx = next(
        i for i, ln in enumerate(lines) if ln.strip() == "api_router = APIRouter()"
    )
    include_idx = next(i for i, ln in enumerate(lines) if "include_router(jobs_router)" in ln)
    # Import inserted on the line immediately before the construction line.
    assert import_idx == construct_idx - 1, (
        f"fallback import misplaced: import@{import_idx} construct@{construct_idx}"
    )
    # Include inserted immediately after the construction line.
    assert include_idx == construct_idx + 1, (
        f"fallback include misplaced: include@{include_idx} construct@{construct_idx}"
    )


def test_register_router_idempotent(tmp_path: Path):
    """A second call adds nothing (kills the ``import_line in src`` In->NotIn flip)."""
    ri = tmp_path / "routes_init.py"
    ri.write_text(
        "from fastapi import APIRouter\n"
        "from app.api.routes.users import router as users_router\n\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(users_router)\n"
    )
    import_line = "from app.api.routes.jobs import router as jobs_router"
    include_line = "api_router.include_router(jobs_router)"
    _register_router(ri, import_line=import_line, include_line=include_line)
    first = ri.read_text()
    _register_router(ri, import_line=import_line, include_line=include_line)
    second = ri.read_text()
    assert first == second, "second register_router call must be a no-op"
    assert second.count(import_line) == 1
    assert second.count(include_line) == 1


# ---------------------------------------------------------------------------
# _patch_main — lifespan wiring (L201-217)
# ---------------------------------------------------------------------------


def test_main_pool_wired_around_yield():
    """Pool create sits BEFORE ``yield``, pool close AFTER it.

    The import line names both create_arq_pool and close_arq_pool, so a
    presence check survives the ``yield_idx != -1`` NotEq->Eq flip (which
    drops the actual wiring). This asserts the wiring statements + ordering.
    """
    project = create_fixture_project(name="arq_c_main")
    result = add_arq_worker(ToolInput(project_dir=str(project)))
    main_file = project / "app" / "main.py"
    lines = main_file.read_text().splitlines()
    yield_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "yield")
    create_idx = next(
        i
        for i, ln in enumerate(lines)
        if ln.strip() == "app.state.arq_pool = await create_arq_pool()"
    )
    close_idx = next(
        i for i, ln in enumerate(lines) if ln.strip() == "await close_arq_pool(app.state.arq_pool)"
    )
    assert create_idx < yield_idx, "pool create must run before yield (startup)"
    assert close_idx > yield_idx, "pool close must run after yield (shutdown)"
    # _patch_main returns True after wiring -> main.py must be reported modified.
    # Kills the ``return True`` -> ``return False`` BoolLiteral flip.
    assert str(main_file.resolve()) in _resolved_set(result.files_modified), (
        "main.py was patched but not reported in files_modified"
    )


# ---------------------------------------------------------------------------
# migration head fallback (L98)
# ---------------------------------------------------------------------------


def test_migration_down_revision_is_real_head():
    """down_revision points at the real migration head, not the literal fallback.

    The fixture ships heads 0001_initial -> 0002_baseline_schema; the new
    migration must chain onto 0002. Kills the ``head or '0001_initial'``
    Or->And flip (which would resolve to '0001_initial').
    """
    project = create_fixture_project(name="arq_c_mig")
    add_arq_worker(ToolInput(project_dir=str(project)))
    mig = (project / "alembic" / "versions" / "add_arq_worker.py").read_text()
    assert 'down_revision = "0002_baseline_schema"' in mig, (
        "migration must chain onto the real head, not the 0001 fallback"
    )


# ---------------------------------------------------------------------------
# _patch_requirements — redis dedup (L225)
# ---------------------------------------------------------------------------


def test_requirements_no_duplicate_redis():
    """redis is already pinned in the fixture; the tool must not duplicate it.

    Kills the ``'redis' not in src`` NotIn->In flip, which would re-add a
    second redis line.
    """
    project = create_fixture_project(name="arq_c_req")
    add_arq_worker(ToolInput(project_dir=str(project)))
    req = (project / "requirements.txt").read_text()
    redis_lines = [ln for ln in req.splitlines() if ln.startswith("redis")]
    assert len(redis_lines) == 1, f"expected exactly one redis pin, got {redis_lines}"
    # arq IS new and must be added exactly once.
    arq_lines = [ln for ln in req.splitlines() if ln.startswith("arq")]
    assert len(arq_lines) == 1, f"expected exactly one arq pin, got {arq_lines}"


# ---------------------------------------------------------------------------
# _patch_models_init — dedup + formatting (L134-150)
# ---------------------------------------------------------------------------


def test_models_init_no_duplicate_and_no_blank_gap(tmp_path: Path):
    """Job import added once, directly after existing imports (no blank gap).

    Kills:
      * ``marker in content`` In->NotIn (would skip / mis-handle the dedup),
      * ``not new_lines`` UnaryNot (would early-return without writing),
      * ``not content.endswith`` UnaryNot (would wedge a blank line in).
    """
    mi = tmp_path / "models_init.py"
    mi.write_text('"""models."""\nfrom app.models.user import User  # noqa: F401\n')
    _patch_models_init(mi, [("job", "Job")])
    content = mi.read_text()
    marker = "from app.models.job import Job"
    assert marker in content, "Job import must be added"
    assert content.count(marker) == 1
    # The new import must sit directly under the User import — no blank gap.
    assert (
        "from app.models.user import User  # noqa: F401\n"
        "from app.models.job import Job  # noqa: F401\n" in content
    ), f"unexpected gap/format: {content!r}"


def test_models_init_idempotent(tmp_path: Path):
    """A second patch adds nothing (dedup guard)."""
    mi = tmp_path / "models_init.py"
    mi.write_text("from app.models.user import User  # noqa: F401\n")
    _patch_models_init(mi, [("job", "Job")])
    first = mi.read_text()
    _patch_models_init(mi, [("job", "Job")])
    assert mi.read_text() == first


# ---------------------------------------------------------------------------
# workers/__init__.py creation guard (L62)
# ---------------------------------------------------------------------------


def test_workers_package_init_created():
    """app/workers/__init__.py is created and reported in files_created.

    Kills the ``not workers_init.exists()`` UnaryNot flip, which would skip
    creating the package marker on a fresh project.
    """
    project = create_fixture_project(name="arq_c_pkg")
    result = add_arq_worker(ToolInput(project_dir=str(project)))
    init_file = project / "app" / "workers" / "__init__.py"
    assert init_file.exists(), "workers/__init__.py must be created"
    target = str(init_file.resolve())
    assert target in _resolved_set(result.files_created), (
        "workers/__init__.py must be reported in files_created"
    )


# ---------------------------------------------------------------------------
# auto-scaffold seed of files_created (L89)
# ---------------------------------------------------------------------------


def test_scaffolded_prereq_seeded_into_files_created():
    """Auto-scaffolded prerequisites seed the files_created list.

    A missing ``app/core/config.py`` is auto-created by the prereq pass and
    returned in ``scaffolded``; ``files_created`` is initialised from it via
    ``list(scaffolded or [])``. Kills the ``scaffolded or []`` Or->And flip,
    which (scaffolded being truthy) would evaluate to ``[]`` and drop the
    scaffolded file from the report.
    """
    project = create_fixture_project(name="arq_c_scaffold")
    (project / "app" / "core" / "config.py").unlink()
    result = add_arq_worker(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    config_path = str((project / "app" / "core" / "config.py").resolve())
    assert config_path in _resolved_set(result.files_created), (
        "auto-scaffolded config.py must be reported in files_created"
    )


# ---------------------------------------------------------------------------
# _patch_main — direct-call branch coverage (L356-375)
# ---------------------------------------------------------------------------


def test_patch_main_idempotent_when_pool_present(tmp_path: Path):
    """When ``arq_pool`` is already wired, _patch_main is a no-op returning False.

    Kills the ``if 'arq_pool' in src: return False`` BoolLiteral False->True
    flip (True would falsely report a modification on an already-wired file).
    """
    mf = tmp_path / "main.py"
    mf.write_text("from app.x import y\napp.state.arq_pool = 1\n")
    before = mf.read_text()
    assert _patch_main(mf) is False
    assert mf.read_text() == before, "already-wired main must be left untouched"


def test_patch_main_returns_false_without_app_imports(tmp_path: Path):
    """No ``from app.`` anchor -> _patch_main bails out returning False.

    Kills the ``if last_from_app == -1: return False`` BoolLiteral False->True
    flip (True would claim a modification despite writing nothing useful).
    """
    mf = tmp_path / "main.py"
    mf.write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    before = mf.read_text()
    assert _patch_main(mf) is False
    assert mf.read_text() == before, "main without app imports must be untouched"


def test_patch_main_import_after_last_app_import(tmp_path: Path):
    """The enqueue import is inserted directly after the last ``from app.`` line.

    Kills the ``insert(last_from_app + 1, ...)`` Add->Sub flip (which would
    wedge the import before the last existing app import) and confirms
    _patch_main returns True on a real patch.
    """
    mf = tmp_path / "main.py"
    mf.write_text(
        "from fastapi import FastAPI\n"
        "from app.a import A\n"
        "from app.b import B\n"
        "\n"
        "async def lifespan(app):\n"
        "    yield\n"
    )
    assert _patch_main(mf) is True
    lines = mf.read_text().splitlines()
    enqueue_idx = next(i for i, ln in enumerate(lines) if "from app.workers.enqueue import" in ln)
    last_other_app = max(
        i
        for i, ln in enumerate(lines)
        if ln.startswith("from app.") and "workers.enqueue" not in ln
    )
    assert enqueue_idx == last_other_app + 1, (
        f"enqueue import not directly after last app import: {enqueue_idx} vs {last_other_app}"
    )


# ---------------------------------------------------------------------------
# _patch_config — no-anchor fallback branch (L298-300)
# ---------------------------------------------------------------------------


def test_patch_config_fallback_before_settings_instance(tmp_path: Path):
    """Without the ACCESS_TOKEN anchor, the block precedes ``settings = Settings()``.

    Kills the ``if settings_line in src`` In->NotIn flip in the no-anchor
    branch, which would skip the settings-relative insert and dump the block
    at end-of-file (after the ``settings = Settings()`` instantiation).
    """
    cf = tmp_path / "config.py"
    cf.write_text("class Settings:\n    FOO: int = 1\n\nsettings = Settings()\n")
    _patch_config(cf, 10, 300, 3, 86400)
    content = cf.read_text()
    assert "ARQ_MAX_JOBS: int = 10" in content
    block_idx = content.index("ARQ_MAX_JOBS")
    settings_idx = content.index("settings = Settings()")
    assert block_idx < settings_idx, (
        "ARQ block must be injected before the settings = Settings() instantiation"
    )


def test_patch_config_append_fallback_no_anchor_no_settings(tmp_path: Path):
    """No anchor AND no ``settings = Settings()`` -> block appended at EOF.

    Exercises the final fallback ``src.rstrip("\\n") + "\\n" + block`` so the
    Add->Sub flip (``str - str`` TypeError) is killed: the call must succeed
    and append the ARQ fields.
    """
    cf = tmp_path / "config.py"
    cf.write_text("class Settings:\n    FOO: int = 1\n")
    _patch_config(cf, 10, 300, 3, 86400)
    content = cf.read_text()
    assert "ARQ_MAX_JOBS: int = 10" in content
    assert "ARQ_KEEP_RESULTS_SECONDS: int = 86400" in content
