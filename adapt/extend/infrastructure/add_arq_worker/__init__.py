from __future__ import annotations
"""TOOL-022: add_arq_worker — add an arq (Redis-backed async) job queue to a FastAPI project.

Writes an ``app/workers/`` package containing the arq ``WorkerSettings`` runtime,
a task registry with 3 example tasks (``send_email_task``, ``cleanup_task``,
``webhook_retry_task``), a FastAPI-friendly ``enqueue()`` helper backed by a
pool cached on ``app.state.arq_pool``, HTTP companion routes
(``GET /jobs/{job_id}/status`` and ``GET /jobs/active``), an optional
``Job`` SQLAlchemy model + CRUD + Pydantic schemas for durable audit of
critical jobs (in addition to Redis), an Alembic migration (tenant-aware when
``app/models/tenant.py`` exists), a dedicated ``Dockerfile.worker`` for the
worker process, and every required ``settings`` key.

The tool is idempotent: a second run detects the ``WorkerSettings``
fingerprint in ``app/workers/arq_worker.py`` and returns ``status="no_op"``
without touching any file.
"""

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_arq_worker",
    "description": "Add an arq (Redis-backed async) job queue with worker, task registry, and HTTP status routes.",
    "tags": ["extend", "infrastructure"],
    "entry": "add_arq_worker",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_arq_worker(
    inp: ToolInput,
    *,
    max_jobs: int = 10,
    job_timeout_seconds: int = 300,
    max_tries: int = 3,
    keep_results_seconds: int = 86400,
) -> ToolResult:
    """Add an arq (async Redis-backed) background job queue to a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.
        max_jobs: Maximum concurrent jobs a single worker process will run.
        job_timeout_seconds: Per-job hard wall-clock timeout in seconds.
        max_tries: Maximum number of attempts for a job before permanent failure.
        keep_results_seconds: How long arq keeps completed job results in Redis.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/workers/ package (arq_worker.py, tasks.py, enqueue.py),",
                "         GET /jobs/{job_id}/status + GET /jobs/active HTTP routes,",
                "         Job model + schemas + CRUD + Alembic migration"
                + (" (tenant-aware)" if has_tenants else "")
                + ", Dockerfile.worker.",
                f"         max_jobs={max_jobs}, job_timeout_seconds={job_timeout_seconds}, "
                f"max_tries={max_tries}, keep_results_seconds={keep_results_seconds}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    workers_dir = app_dir / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)
    workers_init = workers_dir / "__init__.py"
    if not workers_init.exists():
        workers_init.write_text('"""Async background job queue (arq) sub-package."""\n')
        files_created.append(str(workers_init))

    tasks_file = workers_dir / "tasks.py"
    render_to(_HERE, "tasks.py.tmpl", dest=tasks_file, substitutions={})
    files_created.append(str(tasks_file))

    render_to(_HERE, "arq_worker.py.tmpl", dest=worker_file, substitutions={})
    files_created.append(str(worker_file))

    enqueue_file = workers_dir / "enqueue.py"
    render_to(_HERE, "enqueue.py.tmpl", dest=enqueue_file, substitutions={})
    files_created.append(str(enqueue_file))

    job_model_file = app_dir / "models" / "job.py"
    model_tmpl = "job_model_tenanted.py.tmpl" if has_tenants else "job_model.py.tmpl"
    render_to(_HERE, model_tmpl, dest=job_model_file, substitutions={})
    files_created.append(str(job_model_file))

    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("job", "Job")])
        files_modified.append(str(models_init))

    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    job_schema_file = schemas_dir / "job.py"
    render_to(_HERE, "job_schemas.py.tmpl", dest=job_schema_file, substitutions={})
    files_created.append(str(job_schema_file))

    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    job_crud_file = crud_dir / "job.py"
    render_to(_HERE, "job_crud.py.tmpl", dest=job_crud_file, substitutions={})
    files_created.append(str(job_crud_file))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    jobs_route_file = routes_dir / "jobs.py"
    render_to(_HERE, "jobs_routes.py.tmpl", dest=jobs_route_file, substitutions={})
    files_created.append(str(jobs_route_file))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_tmpl = "migration_tenanted.py.tmpl" if has_tenants else "migration.py.tmpl"
        migration_file = versions_dir / "add_arq_worker.py"
        render_to(_HERE, mig_tmpl, dest=migration_file, substitutions={"down_rev": down_rev})
        files_created.append(str(migration_file))

    dockerfile_worker = project / "Dockerfile.worker"
    if not dockerfile_worker.exists():
        render_to(
            _HERE,
            "Dockerfile.worker.tmpl",
            dest=dockerfile_worker,
            substitutions={},
        )
        files_created.append(str(dockerfile_worker))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(
            config_file,
            max_jobs,
            job_timeout_seconds,
            max_tries,
            keep_results_seconds,
        )
        files_modified.append(str(config_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    main_file = app_dir / "main.py"
    if main_file.exists() and _patch_main(main_file):
        files_modified.append(str(main_file))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    _emit_project_test(project, files_created)

    import ast
    for fpath in files_created:
        if fpath.endswith(".py"):
            try:
                ast.parse(Path(fpath).read_text())
            except SyntaxError as e:
                return ToolResult(
                    status="error",
                    error=f"Syntax error in {fpath}: {e}",
                    files_created=[],
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "arq worker added: WorkerSettings runtime, task registry, enqueue helpers,",
            "Job audit model + schemas + CRUD + Alembic migration"
            + (" (tenant-aware)" if has_tenants else "")
            + ".",
            f"max_jobs={max_jobs}, job_timeout={job_timeout_seconds}s, "
            f"max_tries={max_tries}, keep_result={keep_results_seconds}s.",
            "HTTP companion routes: GET /jobs/{job_id}/status, GET /jobs/active.",
            "arq pool is created in FastAPI lifespan on app.state.arq_pool — multi-worker safe.",
            "Dockerfile.worker generated for running the worker as a separate process "
            "(runs as non-root USER 1000).",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set REDIS_URL in .env — the worker and enqueue helpers require Redis.",
            "Start the worker: docker build -f Dockerfile.worker -t myapp-worker . && "
            "docker run --rm --env-file .env myapp-worker",
            "Or locally: python -m app.workers.arq_worker",
            "Restart the FastAPI app so the /jobs/* routes and pool lifespan are active.",
            "Verify: POST an enqueue-triggering endpoint, then GET /jobs/<job_id>/status.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_arq_worker_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_arq_worker_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_arq_worker_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently."""
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker in content:
            continue
        new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _patch_config(
    config_file: Path,
    max_jobs: int,
    job_timeout_seconds: int,
    max_tries: int,
    keep_results_seconds: int,
) -> None:
    """Inject arq worker settings into the ``Settings`` class body."""
    src = config_file.read_text()
    if "ARQ_MAX_JOBS" in src:
        return

    block = (
        "\n"
        "    # --- arq worker settings — added by add_arq_worker tool ---\n"
        f"    ARQ_MAX_JOBS: int = {max_jobs}\n"
        f"    ARQ_JOB_TIMEOUT_SECONDS: int = {job_timeout_seconds}\n"
        f"    ARQ_MAX_TRIES: int = {max_tries}\n"
        f"    ARQ_KEEP_RESULTS_SECONDS: int = {keep_results_seconds}\n"
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the jobs HTTP router in ``app/routes/__init__.py`` idempotently."""
    _register_router(
        routes_init,
        import_line="from app.api.routes.jobs import router as jobs_router",
        include_line="api_router.include_router(jobs_router)",
    )


def _register_router(
    routes_init: Path,
    *,
    import_line: str,
    include_line: str,
) -> None:
    """Idempotently add an import + ``api_router.include_router`` call."""
    src = routes_init.read_text()
    if import_line in src:
        return

    lines = src.splitlines()

    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)

    last_include_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include_idx = idx
    if last_include_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include_idx = idx
                break
    lines.insert(last_include_idx + 1, include_line)

    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _patch_main(main_file: Path) -> bool:
    """Wire the arq pool startup/shutdown into ``app/main.py``'s lifespan."""
    src = main_file.read_text()
    if "arq_pool" in src:
        return False
    lines = src.splitlines()
    last_from_app = max(
        (i for i, ln in enumerate(lines) if ln.startswith("from app.")),
        default=-1,
    )
    if last_from_app == -1:
        return False
    lines.insert(
        last_from_app + 1,
        "from app.workers.enqueue import close_arq_pool, create_arq_pool",
    )
    yield_idx = next((i for i, ln in enumerate(lines) if ln.strip() == "yield"), -1)
    if yield_idx != -1:
        indent = lines[yield_idx][: len(lines[yield_idx]) - len(lines[yield_idx].lstrip())]
        lines.insert(yield_idx, f"{indent}app.state.arq_pool = await create_arq_pool()")
        lines.insert(yield_idx + 2, f"{indent}await close_arq_pool(app.state.arq_pool)")
    main_file.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))
    return True


def _patch_requirements(requirements_file: Path) -> None:
    """Ensure ``arq`` and ``redis[hiredis]`` are in ``requirements.txt``."""
    src = requirements_file.read_text()
    additions: list[str] = []
    if "arq" not in src:
        additions.append("arq>=0.25.0")
    if "redis" not in src:
        additions.append("redis[hiredis]>=5.0.0")
    if not additions:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "\n".join(additions) + "\n")





    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"

    worker_file = app_dir / "workers" / "arq_worker.py"
    if worker_file.exists() and "WorkerSettings" in worker_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["WorkerSettings already present — arq worker is already installed, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    has_tenants = (app_dir / "models" / "tenant.py").exists()

"""TOOL-022: add_arq_worker — add an arq (Redis-backed async) job queue to a FastAPI project.

Writes an ``app/workers/`` package containing the arq ``WorkerSettings`` runtime,
a task registry with 3 example tasks (``send_email_task``, ``cleanup_task``,
``webhook_retry_task``), a FastAPI-friendly ``enqueue()`` helper backed by a
pool cached on ``app.state.arq_pool``, HTTP companion routes
(``GET /jobs/{job_id}/status`` and ``GET /jobs/active``), an optional
``Job`` SQLAlchemy model + CRUD + Pydantic schemas for durable audit of
critical jobs (in addition to Redis), an Alembic migration (tenant-aware when
``app/models/tenant.py`` exists), a dedicated ``Dockerfile.worker`` for the
worker process, and every required ``settings`` key.

The tool is idempotent: a second run detects the ``WorkerSettings``
fingerprint in ``app/workers/arq_worker.py`` and returns ``status="no_op"``
without touching any file.
"""

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_arq_worker",
    "description": "Add an arq (Redis-backed async) job queue with worker, task registry, and HTTP status routes.",
    "tags": ["extend", "infrastructure"],
    "entry": "add_arq_worker",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_arq_worker(
    inp: ToolInput,
    *,
    max_jobs: int = 10,
    job_timeout_seconds: int = 300,
    max_tries: int = 3,
    keep_results_seconds: int = 86400,
) -> ToolResult:
    """Add an arq (async Redis-backed) background job queue to a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.
        max_jobs: Maximum concurrent jobs a single worker process will run.
        job_timeout_seconds: Per-job hard wall-clock timeout in seconds.
        max_tries: Maximum number of attempts for a job before permanent failure.
        keep_results_seconds: How long arq keeps completed job results in Redis.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"

    worker_file = app_dir / "workers" / "arq_worker.py"
    if worker_file.exists() and "WorkerSettings" in worker_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["WorkerSettings already present — arq worker is already installed, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    has_tenants = (app_dir / "models" / "tenant.py").exists()

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/workers/ package (arq_worker.py, tasks.py, enqueue.py),",
                "         GET /jobs/{job_id}/status + GET /jobs/active HTTP routes,",
                "         Job model + schemas + CRUD + Alembic migration"
                + (" (tenant-aware)" if has_tenants else "")
                + ", Dockerfile.worker.",
                f"         max_jobs={max_jobs}, job_timeout_seconds={job_timeout_seconds}, "
                f"max_tries={max_tries}, keep_results_seconds={keep_results_seconds}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    workers_dir = app_dir / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)
    workers_init = workers_dir / "__init__.py"
    if not workers_init.exists():
        workers_init.write_text('"""Async background job queue (arq) sub-package."""\n')
        files_created.append(str(workers_init))

    tasks_file = workers_dir / "tasks.py"
    render_to(_HERE, "tasks.py.tmpl", dest=tasks_file, substitutions={})
    files_created.append(str(tasks_file))

    render_to(_HERE, "arq_worker.py.tmpl", dest=worker_file, substitutions={})
    files_created.append(str(worker_file))

    enqueue_file = workers_dir / "enqueue.py"
    render_to(_HERE, "enqueue.py.tmpl", dest=enqueue_file, substitutions={})
    files_created.append(str(enqueue_file))

    job_model_file = app_dir / "models" / "job.py"
    model_tmpl = "job_model_tenanted.py.tmpl" if has_tenants else "job_model.py.tmpl"
    render_to(_HERE, model_tmpl, dest=job_model_file, substitutions={})
    files_created.append(str(job_model_file))

    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("job", "Job")])
        files_modified.append(str(models_init))

    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    job_schema_file = schemas_dir / "job.py"
    render_to(_HERE, "job_schemas.py.tmpl", dest=job_schema_file, substitutions={})
    files_created.append(str(job_schema_file))

    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    job_crud_file = crud_dir / "job.py"
    render_to(_HERE, "job_crud.py.tmpl", dest=job_crud_file, substitutions={})
    files_created.append(str(job_crud_file))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    jobs_route_file = routes_dir / "jobs.py"
    render_to(_HERE, "jobs_routes.py.tmpl", dest=jobs_route_file, substitutions={})
    files_created.append(str(jobs_route_file))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_tmpl = "migration_tenanted.py.tmpl" if has_tenants else "migration.py.tmpl"
        migration_file = versions_dir / "add_arq_worker.py"
        render_to(_HERE, mig_tmpl, dest=migration_file, substitutions={"down_rev": down_rev})
        files_created.append(str(migration_file))

    dockerfile_worker = project / "Dockerfile.worker"
    if not dockerfile_worker.exists():
        render_to(
            _HERE,
            "Dockerfile.worker.tmpl",
            dest=dockerfile_worker,
            substitutions={},
        )
        files_created.append(str(dockerfile_worker))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(
            config_file,
            max_jobs,
            job_timeout_seconds,
            max_tries,
            keep_results_seconds,
        )
        files_modified.append(str(config_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    main_file = app_dir / "main.py"
    if main_file.exists() and _patch_main(main_file):
        files_modified.append(str(main_file))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    _emit_project_test(project, files_created)

    import ast
    for fpath in files_created:
        if fpath.endswith(".py"):
            try:
                ast.parse(Path(fpath).read_text())
            except SyntaxError as e:
                return ToolResult(
                    status="error",
                    error=f"Syntax error in {fpath}: {e}",
                    files_created=[],
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "arq worker added: WorkerSettings runtime, task registry, enqueue helpers,",
            "Job audit model + schemas + CRUD + Alembic migration"
            + (" (tenant-aware)" if has_tenants else "")
            + ".",
            f"max_jobs={max_jobs}, job_timeout={job_timeout_seconds}s, "
            f"max_tries={max_tries}, keep_result={keep_results_seconds}s.",
            "HTTP companion routes: GET /jobs/{job_id}/status, GET /jobs/active.",
            "arq pool is created in FastAPI lifespan on app.state.arq_pool — multi-worker safe.",
            "Dockerfile.worker generated for running the worker as a separate process "
            "(runs as non-root USER 1000).",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set REDIS_URL in .env — the worker and enqueue helpers require Redis.",
            "Start the worker: docker build -f Dockerfile.worker -t myapp-worker . && "
            "docker run --rm --env-file .env myapp-worker",
            "Or locally: python -m app.workers.arq_worker",
            "Restart the FastAPI app so the /jobs/* routes and pool lifespan are active.",
            "Verify: POST an enqueue-triggering endpoint, then GET /jobs/<job_id>/status.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_arq_worker_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_arq_worker_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_arq_worker_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently."""
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker in content:
            continue
        new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _patch_config(
    config_file: Path,
    max_jobs: int,
    job_timeout_seconds: int,
    max_tries: int,
    keep_results_seconds: int,
) -> None:
    """Inject arq worker settings into the ``Settings`` class body."""
    src = config_file.read_text()
    if "ARQ_MAX_JOBS" in src:
        return

    block = (
        "\n"
        "    # --- arq worker settings — added by add_arq_worker tool ---\n"
        f"    ARQ_MAX_JOBS: int = {max_jobs}\n"
        f"    ARQ_JOB_TIMEOUT_SECONDS: int = {job_timeout_seconds}\n"
        f"    ARQ_MAX_TRIES: int = {max_tries}\n"
        f"    ARQ_KEEP_RESULTS_SECONDS: int = {keep_results_seconds}\n"
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the jobs HTTP router in ``app/routes/__init__.py`` idempotently."""
    _register_router(
        routes_init,
        import_line="from app.api.routes.jobs import router as jobs_router",
        include_line="api_router.include_router(jobs_router)",
    )


def _register_router(
    routes_init: Path,
    *,
    import_line: str,
    include_line: str,
) -> None:
    """Idempotently add an import + ``api_router.include_router`` call."""
    src = routes_init.read_text()
    if import_line in src:
        return

    lines = src.splitlines()

    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)

    last_include_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include_idx = idx
    if last_include_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include_idx = idx
                break
    lines.insert(last_include_idx + 1, include_line)

    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _patch_main(main_file: Path) -> bool:
    """Wire the arq pool startup/shutdown into ``app/main.py``'s lifespan."""
    src = main_file.read_text()
    if "arq_pool" in src:
        return False
    lines = src.splitlines()
    last_from_app = max(
        (i for i, ln in enumerate(lines) if ln.startswith("from app.")),
        default=-1,
    )
    if last_from_app == -1:
        return False
    lines.insert(
        last_from_app + 1,
        "from app.workers.enqueue import close_arq_pool, create_arq_pool",
    )
    yield_idx = next((i for i, ln in enumerate(lines) if ln.strip() == "yield"), -1)
    if yield_idx != -1:
        indent = lines[yield_idx][: len(lines[yield_idx]) - len(lines[yield_idx].lstrip())]
        lines.insert(yield_idx, f"{indent}app.state.arq_pool = await create_arq_pool()")
        lines.insert(yield_idx + 2, f"{indent}await close_arq_pool(app.state.arq_pool)")
    main_file.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))
    return True


def _patch_requirements(requirements_file: Path) -> None:
    """Ensure ``arq`` and ``redis[hiredis]`` are in ``requirements.txt``."""
    src = requirements_file.read_text()
    additions: list[str] = []
    if "arq" not in src:
        additions.append("arq>=0.25.0")
    if "redis" not in src:
        additions.append("redis[hiredis]>=5.0.0")
    if not additions:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "\n".join(additions) + "\n")


