"""ADAPT tool: add a background job (ARQ) to an existing FastAPI project.

Generates everything needed for async background job processing using ARQ
(async Redis queue) -- worker config, Redis pool dependency, and the job
function itself.  Optionally wires up cron scheduling.

Usage::

    from generators.tools.add_background_job import add_background_job

    result = add_background_job(
        project_dir="/path/to/existing-project",
        name="send_welcome_email",
        queue="emails",
        retry_max=5,
        cron="0 */6 * * *",
    )
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_add_background_job',
    'description': 'Add a background job using ARQ (async Redis queue).',
    'tags': ['adapt'],
    'entry': 'add_background_job',
    'annotations': {'readOnlyHint': False},
}

import re
import textwrap
from pathlib import Path

from generators.tools._layout import resolve_app_root


def add_background_job(
    project_dir: str,
    name: str,
    queue: str = "default",
    retry_max: int = 3,
    cron: str | None = None,
) -> dict:
    """Add a background job to an existing FastAPI project.

    This is a high-level tool that creates the ARQ worker infrastructure
    (if not already present) and then adds an individual job function.
    It is safe to run multiple times -- existing files are never
    overwritten, and duplicate registrations are detected and skipped.

    Args:
        project_dir: Root directory of the existing project (the folder
            that contains ``core/``, ``routes/``, etc.).
        name: Job function name in snake_case (e.g. ``send_welcome_email``).
        queue: Queue name for this job.  ARQ uses this to route jobs to
            specific workers.
        retry_max: Maximum number of retry attempts before the job is
            marked as failed.
        cron: Optional cron expression (e.g. ``"0 */6 * * *"``).  When
            provided the job is registered as a ``cron_job`` in the
            worker settings.

    Returns:
        Dict with ``files_created``, ``files_modified``, ``notes``, and
        ``commands``.
    """
    root = resolve_app_root(project_dir)
    lower = name.lower()

    files_created: list[str] = []
    files_modified: list[str] = []
    notes: list[str] = []
    commands: list[str] = []

    # ------------------------------------------------------------------
    # Guard: skip if job file already exists
    # ------------------------------------------------------------------
    job_file = root / "jobs" / f"{lower}.py"
    if job_file.exists():
        return {
            "files_created": [],
            "files_modified": [],
            "notes": [
                f"Job {lower} already exists at {job_file}. Skipped to avoid duplicates."
            ],
            "commands": [],
        }

    # ------------------------------------------------------------------
    # 1. Create ARQ infrastructure (if first job)
    # ------------------------------------------------------------------
    worker_file = root / "worker.py"
    first_job = not worker_file.exists()

    if first_job:
        _generate_arq_pool(root)
        files_created.append(str(root / "core" / "arq.py"))
        notes.append("Generated core/arq.py with ARQ pool factory and FastAPI dependency.")

        _generate_worker(root)
        files_created.append(str(worker_file))
        notes.append("Generated worker.py with ARQ WorkerSettings.")

        # Add arq to requirements.txt
        _ensure_requirement(root, "arq[watch]>=0.26", files_modified, notes)

        # Ensure ARQ_REDIS_URL in config
        _ensure_config_field(root, "ARQ_REDIS_URL", 'str = "redis://localhost:6379/0"', files_modified, notes)

    # ------------------------------------------------------------------
    # 2. Ensure jobs/ package exists
    # ------------------------------------------------------------------
    jobs_dir = root / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    jobs_init = jobs_dir / "__init__.py"
    if not jobs_init.exists():
        jobs_init.write_text('"""Background job functions."""\n')
        files_created.append(str(jobs_init))

    # ------------------------------------------------------------------
    # 3. Generate the job function
    # ------------------------------------------------------------------
    _generate_job_file(jobs_dir, lower, retry_max)
    files_created.append(str(job_file))
    notes.append(f"Generated jobs/{lower}.py with structured logging and retry_max={retry_max}.")

    # ------------------------------------------------------------------
    # 4. Register the job in worker.py
    # ------------------------------------------------------------------
    modified = _patch_worker_register(worker_file, lower, cron)
    if modified:
        files_modified.append(str(worker_file))
        notes.append(f"Registered {lower} in worker.py functions list.")
        if cron:
            notes.append(f"Added cron_job for {lower} with schedule '{cron}'.")
    else:
        notes.append(f"{lower} already registered in worker.py.")

    # ------------------------------------------------------------------
    # 5. Commands
    # ------------------------------------------------------------------
    commands.append("arq worker.WorkerSettings")
    if cron:
        notes.append(f"Cron schedule: {cron}")

    return {
        "files_created": files_created,
        "files_modified": files_modified,
        "notes": notes,
        "commands": commands,
    }


# ---------------------------------------------------------------------------
# Internal generators
# ---------------------------------------------------------------------------


def _generate_arq_pool(root: Path) -> None:
    """Generate ``core/arq.py`` with pool factory and FastAPI dependency."""
    out = root / "core"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent("""\
        \"\"\"ARQ Redis pool factory and FastAPI dependency.\"\"\"

        from __future__ import annotations

        from arq import create_pool
        from arq.connections import ArqRedis, RedisSettings

        from app.core.config import settings

        _pool: ArqRedis | None = None


        async def get_arq_pool() -> ArqRedis:
            \"\"\"Return a shared ARQ connection pool.

            Creates the pool lazily on first call.  Subsequent calls return the
            same instance.  Call ``close_arq_pool()`` during application shutdown.
            \"\"\"
            global _pool
            if _pool is None:
                _pool = await create_pool(
                    RedisSettings.from_dsn(settings.ARQ_REDIS_URL),
                )
            return _pool


        async def close_arq_pool() -> None:
            \"\"\"Close the shared ARQ pool (call during app shutdown).\"\"\"
            global _pool
            if _pool is not None:
                await _pool.aclose()
                _pool = None
    """)

    (out / "arq.py").write_text(content)


def _generate_worker(root: Path) -> None:
    """Generate ``worker.py`` with ARQ WorkerSettings."""
    content = textwrap.dedent("""\
        \"\"\"ARQ worker entry-point.

        Run with::

            arq worker.WorkerSettings
        \"\"\"

        from __future__ import annotations

        from arq.connections import RedisSettings

        from app.core.config import settings


        # --- Job function imports (managed by add_background_job) ---


        class WorkerSettings:
            \"\"\"ARQ worker configuration.\"\"\"

            redis_settings = RedisSettings.from_dsn(settings.ARQ_REDIS_URL)

            # Maximum seconds a job can run before being killed
            max_jobs = 10
            job_timeout = 300

            # Job functions registered with this worker
            functions = [
            ]

            # Cron jobs (periodic tasks)
            cron_jobs = [
            ]
    """)

    (root / "worker.py").write_text(content)


def _generate_job_file(jobs_dir: Path, name: str, retry_max: int) -> None:
    """Generate ``jobs/{name}.py`` with a job function skeleton."""
    content = textwrap.dedent("""\
        \"\"\"Background job: {name}.\"\"\"

        from __future__ import annotations

        import structlog

        logger = structlog.get_logger()


        async def {name}(ctx: dict, **kwargs) -> None:
            \"\"\"Execute the {name} background job.

            Args:
                ctx: ARQ worker context (contains Redis connection, job metadata).
                **kwargs: Job-specific arguments passed at enqueue time.
            \"\"\"
            logger.info("{name}_started", **kwargs)
            try:
                # TODO: Implement job logic
                pass
            finally:
                logger.info("{name}_completed")


        # ARQ metadata -- used by WorkerSettings.functions
        {name}.max_retries = {retry_max}  # type: ignore[attr-defined]
    """).format(name=name, retry_max=retry_max)

    (jobs_dir / f"{name}.py").write_text(content)


# ---------------------------------------------------------------------------
# Internal patchers
# ---------------------------------------------------------------------------


def _patch_worker_register(worker_file: Path, name: str, cron: str | None) -> bool:
    """Register a job function in ``worker.py``.

    Adds an import line and appends the function to the ``functions`` list.
    If *cron* is provided, also appends a ``cron_job(...)`` entry.

    Returns True if the file was modified, False if already registered.
    """
    content = worker_file.read_text()

    # Guard: already registered
    if f"from app.jobs.{name} import {name}" in content:
        return False

    lines = content.split("\n")

    # --- Insert import after the sentinel comment ---
    import_line = f"from app.jobs.{name} import {name}"
    sentinel = "# --- Job function imports (managed by add_background_job) ---"
    inserted_import = False
    for i, line in enumerate(lines):
        if sentinel in line:
            lines.insert(i + 1, import_line)
            inserted_import = True
            break

    if not inserted_import:
        # Fallback: insert after last import
        last_import_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("from ", "import ")):
                last_import_idx = i
        lines.insert(last_import_idx + 1, import_line)

    # --- Append to functions list ---
    for i, line in enumerate(lines):
        if "functions = [" in line:
            # Find the closing bracket
            for j in range(i + 1, len(lines)):
                if "]" in lines[j]:
                    lines.insert(j, f"        {name},")
                    break
            break

    # --- Append cron_job if cron is provided ---
    if cron:
        # Ensure cron_jobs import
        if "from arq.cron import cron" not in content:
            for i, line in enumerate(lines):
                if "from arq" in line:
                    lines.insert(i + 1, "from arq.cron import cron")
                    break

        for i, line in enumerate(lines):
            if "cron_jobs = [" in line:
                for j in range(i + 1, len(lines)):
                    if "]" in lines[j]:
                        cron_entry = (
                            f'        cron({name}, cron="{cron}"),'
                        )
                        lines.insert(j, cron_entry)
                        break
                break

    worker_file.write_text("\n".join(lines))
    return True


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _read_requirements(root: Path) -> tuple[Path | None, list[str]]:
    """Return (path, lines) for the first requirements*.txt found.

    Searches downward (rglob) AND upward (parent traversal) so it works
    whether `root` is the project root OR the app/ subdirectory.
    """
    for candidate in sorted(root.rglob("requirements*.txt")):
        return candidate, candidate.read_text().splitlines()
    for parent in root.parents:
        for fname in ("requirements.txt", "requirements-prod.txt"):
            cand = parent / fname
            if cand.exists():
                return cand, cand.read_text().splitlines()
        if parent == parent.parent:
            break
    return None, []


def _ensure_dep(lines: list[str], dep: str) -> list[str]:
    """Append *dep* if it is not already present (case-insensitive match)."""
    name = dep.split("[")[0].split("=")[0].split(">")[0].split("<")[0].strip().lower()
    for line in lines:
        if name in line.lower():
            return lines
    lines.append(dep)
    return lines


def _ensure_requirement(
    root: Path,
    dep: str,
    files_modified: list[str],
    notes: list[str],
) -> None:
    """Add a dependency to requirements.txt if not already present."""
    req_path, req_lines = _read_requirements(root)
    if req_path is not None:
        before = len(req_lines)
        req_lines[:] = _ensure_dep(req_lines, dep)
        if len(req_lines) > before:
            req_path.write_text("\n".join(req_lines) + "\n")
            files_modified.append(str(req_path))
            notes.append(f"Added {dep} to {req_path.name}.")


def _ensure_config_field(
    root: Path,
    field_name: str,
    field_def: str,
    files_modified: list[str],
    notes: list[str],
) -> None:
    """Add a field to ``core/config.py`` Settings class if not present."""
    config_path = root / "core" / "config.py"
    if not config_path.exists():
        notes.append(
            f"core/config.py not found -- add {field_name} to your settings manually."
        )
        return

    content = config_path.read_text()
    if field_name in content:
        return

    # Insert before the first @model_validator or at end of class body
    lines = content.split("\n")
    insert_idx = None
    for i, line in enumerate(lines):
        if "@model_validator" in line:
            insert_idx = i
            break

    if insert_idx is None:
        # Fallback: find last line in Settings class body (indented 4+)
        in_settings = False
        for i, line in enumerate(lines):
            if "class Settings" in line:
                in_settings = True
            if in_settings and line.strip() and not line.startswith((" ", "\t")) and i > 0:
                insert_idx = i
                break
        if insert_idx is None:
            insert_idx = len(lines)

    field_line = f"    {field_name}: {field_def}"
    lines.insert(insert_idx, "")
    lines.insert(insert_idx + 1, f"    # --- ARQ ---")
    lines.insert(insert_idx + 2, field_line)

    config_path.write_text("\n".join(lines))
    files_modified.append(str(config_path))
    notes.append(f"Added {field_name} to core/config.py Settings class.")
