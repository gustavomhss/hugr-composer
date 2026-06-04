"""Generic tool-contract mutation coverage for add_file_upload.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_file_upload.py in the mutation
runner: ``--tests test_add_file_upload.py test_add_file_upload_contract.py``.

The ``test_kill_*`` functions below target this tool's BESPOKE logic — the
patch helpers that splice imports/includes/config/requirements into existing
project files. Each asserts the exact emitted ordering / dedup / fallback that a
specific surviving mutant would break.
"""

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_file_upload import add_file_upload
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_file_upload import add_file_upload

    for check in SCAFFOLDABLE_CHECKS:
        check(add_file_upload, "add_file_upload")


# ---------------------------------------------------------------------------
# Tool-specific kills
# ---------------------------------------------------------------------------


def _run(name: str) -> Path:
    project_dir = create_fixture_project(name=name)
    result = add_file_upload(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"setup failed: {result.status}: {result.error}"
    return project_dir


def test_kill_tasks_init_created_when_absent() -> None:
    """L102 True / L104 not: tasks/__init__.py is written when it does not exist.

    The fixture has no app/tasks package. The tool must mkdir it and, because
    __init__.py is absent, write the package marker. Flipping ``not
    tasks_init.exists()`` would skip the write entirely.
    """
    project_dir = _run("fu_k_tasks_init")
    tasks_init = project_dir / "app" / "tasks" / "__init__.py"
    assert tasks_init.exists(), "tasks/__init__.py must be created when absent"
    assert tasks_init.read_text() == '"""Task modules."""\n'


def test_kill_models_init_import_added() -> None:
    """L210 not / L219 not: FileMetadata import spliced into models/__init__.py.

    The models package exists, so the early ``if not models_init.exists():
    return`` must NOT fire, and ``if not new_lines: return`` must NOT fire
    (a new import IS pending). Flipping either suppresses the write.
    """
    project_dir = _run("fu_k_models_init")
    content = (project_dir / "app" / "models" / "__init__.py").read_text()
    assert "from app.models.file import FileMetadata" in content


def test_kill_models_init_import_not_duplicated() -> None:
    """L216 In: the marker dedup guard prevents a second FileMetadata import.

    Running twice (second run no_ops on the model guard, but the marker dedup
    is what guarantees single insertion on the first pass and the idempotency
    of any re-entry). Flipping ``if marker in content: continue`` to NotIn
    would re-add the import. Assert exactly one occurrence.
    """
    project_dir = create_fixture_project(name="fu_k_models_dedup")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "models" / "__init__.py").read_text()
    assert content.count("from app.models.file import FileMetadata") == 1


def test_kill_routes_import_added_once() -> None:
    """L239 In: files_router import dedup guard.

    Flipping ``if import_line in src: return`` (In -> NotIn) would invert the
    dedup. After two runs the import must appear exactly once.
    """
    project_dir = create_fixture_project(name="fu_k_routes_dedup")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "routes" / "__init__.py").read_text()
    line = "from app.api.routes.files import router as files_router"
    assert content.count(line) == 1


def test_kill_routes_import_inserted_after_last_app_import() -> None:
    """L247 Eq / L252 Add: import lands immediately after the last app import.

    The fixture HAS ``from app.`` imports, so ``last_app_import_idx == -1`` is
    False and the fallback block is skipped (L247). The new import is inserted
    at ``last_app_import_idx + 1`` (L252), i.e. directly after the final
    existing ``from app.`` import and before the APIRouter()/include lines.
    """
    project_dir = _run("fu_k_import_order")
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    import_line = "from app.api.routes.files import router as files_router"
    assert import_line in lines
    new_idx = lines.index(import_line)
    # Every "from app." import must be at or before the inserted import: the
    # tool appends after the LAST one. Sub (L252) would place it before.
    app_import_idxs = [i for i, ln in enumerate(lines) if ln.startswith("from app.")]
    last_existing = max(i for i in app_import_idxs if i != new_idx)
    assert new_idx == last_existing + 1, "import must follow the last app import"
    # And it must precede the APIRouter() construction line.
    router_ctor = next(i for i, ln in enumerate(lines) if "APIRouter()" in ln)
    assert new_idx < router_ctor, "import must precede api_router construction"


def test_kill_routes_include_inserted_after_last_include() -> None:
    """L258 Eq / L263 Add: include_router lands after the last existing include.

    The fixture HAS ``api_router.include_router(...)`` lines, so the
    ``last_include_idx == -1`` fallback (L258) is skipped, and the new include
    is inserted at ``last_include_idx + 1`` (L263) — right after the final
    existing include. Sub would place it before an existing include.
    """
    project_dir = _run("fu_k_include_order")
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    include_line = "api_router.include_router(files_router)"
    assert include_line in lines
    new_idx = lines.index(include_line)
    other_includes = [
        i
        for i, ln in enumerate(lines)
        if ln.startswith("api_router.include_router") and i != new_idx
    ]
    assert other_includes, "fixture must have existing includes"
    assert new_idx == max(other_includes) + 1, "include must follow the last existing include"


def test_kill_config_storage_backend_appended() -> None:
    """L269 In: config additions are appended when STORAGE_BACKEND is absent.

    The fixture config has no STORAGE_BACKEND, so ``if "STORAGE_BACKEND" in
    src: return`` (In) is False and the additions are appended. Flipping to
    NotIn would early-return and skip the append.
    """
    project_dir = _run("fu_k_config")
    content = (project_dir / "app" / "core" / "config.py").read_text()
    assert "STORAGE_BACKEND" in content
    assert "MAX_UPLOAD_SIZE_MB" in content
    assert "QUOTA_MB_PER_USER" in content


def test_kill_requirements_redis_not_duplicated() -> None:
    """L282 NotIn: redis dep guard skips re-adding an already-present redis.

    The baseline requirements already pin ``redis[hiredis]``. The guard
    ``if "redis" not in src`` (NotIn) is therefore False, so no bare
    ``redis>=5.0.0`` line is appended. Flipping to In would append a duplicate
    redis requirement.
    """
    project_dir = _run("fu_k_req_redis")
    lines = (project_dir / "requirements.txt").read_text().splitlines()
    assert any("redis" in ln for ln in lines), "baseline already has redis"
    assert "redis>=5.0.0" not in lines, "must not duplicate redis (already present)"


def test_kill_requirements_magic_and_boto3_added() -> None:
    """L278/L280 NotIn companions: python-magic and boto3 ARE appended.

    Neither dep is in the baseline, so both bare-pin lines are appended.
    Guards against a regression that would skip the genuinely-missing deps.
    """
    project_dir = _run("fu_k_req_add")
    content = (project_dir / "requirements.txt").read_text()
    assert "python-magic>=0.4.27" in content
    assert "boto3>=1.34.0" in content


def test_kill_migration_down_revision_is_head() -> None:
    """L133 Or: migration down_revision chains to the real head, not the literal.

    ``find_migration_head(versions_dir) or "0001_initial"`` resolves to the
    actual head (``0002_baseline_schema`` in the fixture). Flipping Or -> And
    would yield ``"0001_initial"`` instead, breaking the migration chain.
    """
    project_dir = _run("fu_k_migration")
    versions_dir = project_dir / "alembic" / "versions"
    migration = next(versions_dir.glob("*create_files*"))
    content = migration.read_text()
    assert 'down_revision = "0002_baseline_schema"' in content
    assert 'down_revision = "0001_initial"' not in content


def test_kill_routes_init_fallback_anchors_on_apirouter_ctor(tmp_path):
    """When routes/__init__.py has no ``from app.`` imports, the import +
    include must anchor on the ``api_router = APIRouter()`` line.

    Kills the fallback In->NotIn guards (L249/L260) and the idx-1 offset
    (L250 Sub->Add): an In->NotIn flip pushes the insert to file top; a
    Sub->Add flip shifts it past the anchor.
    """
    from adapt.extend.crud_data.add_file_upload import _register_router_in_routes_init

    ri = tmp_path / "__init__.py"
    ri.write_text("from fastapi import APIRouter\n\napi_router = APIRouter()\n")
    _register_router_in_routes_init(
        ri,
        import_line="from app.api.routes.files import router as files_router",
        include_line="api_router.include_router(files_router)",
    )
    lines = ri.read_text().splitlines()
    ctor = next(i for i, ln in enumerate(lines) if "api_router" in ln and "APIRouter()" in ln)
    assert lines[ctor - 1] == "from app.api.routes.files import router as files_router"
    inc = lines.index("api_router.include_router(files_router)")
    assert inc == ctor + 1
