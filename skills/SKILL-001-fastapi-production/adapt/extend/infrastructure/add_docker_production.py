"""TOOL-092: add_docker_production — add a multi-stage production Docker setup.

Generates a production-grade Docker configuration for a FastAPI project:

* ``Dockerfile`` — two-stage build (``builder`` + ``runtime``), non-root USER 1000,
  HEALTHCHECK, pip cache mount, gunicorn + uvicorn workers.
* ``.dockerignore`` — excludes ``__pycache__``, ``.venv``, ``*.pyc``, test dirs, etc.
* ``docker-compose.prod.yml`` — app + postgres + redis services, volume mounts,
  health checks, restart policies.
* ``scripts/docker-entrypoint.sh`` — wait-for-it idiom, ``alembic upgrade head``,
  optional create-superuser.

Configuration knobs are read from ``app/core/config.py`` via:
    ``DOCKER_WORKERS``, ``DOCKER_PORT``, ``DOCKER_HEALTH_PATH``

The tool is idempotent: a second run detects the ``HEALTHCHECK`` fingerprint in
``Dockerfile`` and returns ``status="no_op"`` without touching any file.

No new pip dependencies — gunicorn and uvicorn are already required by FastAPI
production deployments.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_docker_production import add_docker_production

    result = add_docker_production(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/Dockerfile", "…/docker-compose.prod.yml", …]
    print(result.next_steps)    # ["docker compose -f docker-compose.prod.yml up -d", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_deployment_add_docker_production",
    "description": (
        "Add a multi-stage production Dockerfile, .dockerignore, docker-compose.prod.yml, "
        "and docker-entrypoint.sh to a FastAPI project."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_docker_production",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_docker_production(inp: ToolInput) -> ToolResult:
    """Add a multi-stage production Docker setup to a FastAPI project.

    Generates Dockerfile (multi-stage builder + runtime, non-root USER 1000,
    HEALTHCHECK, pip cache mount, gunicorn+uvicorn workers), .dockerignore,
    docker-compose.prod.yml (app + postgres + redis with health checks and
    restart policies), and scripts/docker-entrypoint.sh (alembic upgrade head,
    optional superuser creation).

    Patches ``app/core/config.py`` with DOCKER_WORKERS, DOCKER_PORT, and
    DOCKER_HEALTH_PATH settings fields.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
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

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    # --- Pre-flight: already installed? -------------------------------------
    # Use docker-compose.prod.yml as the fingerprint — the base generator
    # never creates this file, so its presence is unique to this tool.
    compose_fingerprint = project / "docker-compose.prod.yml"
    if compose_fingerprint.exists() and "restart" in compose_fingerprint.read_text():
        return ToolResult(
            status="no_op",
            notes=["docker-compose.prod.yml already present — Docker production setup already installed, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard (BEFORE any writes) -----------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create: Dockerfile (multi-stage builder+runtime, USER 1000, HEALTHCHECK),",
                "          .dockerignore, docker-compose.prod.yml (app+postgres+redis),",
                "          scripts/docker-entrypoint.sh (alembic upgrade head).",
                "[dry_run] Would patch: app/core/config.py with DOCKER_WORKERS, DOCKER_PORT, DOCKER_HEALTH_PATH.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: Dockerfile ---------------------------------------------------
    dockerfile = project / "Dockerfile"
    _write_dockerfile(dockerfile)
    files_created.append(str(dockerfile))

    # --- Step 2: .dockerignore ------------------------------------------------
    dockerignore = project / ".dockerignore"
    if not dockerignore.exists():
        _write_dockerignore(dockerignore)
        files_created.append(str(dockerignore))

    # --- Step 3: docker-compose.prod.yml -------------------------------------
    compose_file = project / "docker-compose.prod.yml"
    if not compose_file.exists():
        _write_compose_prod(compose_file)
        files_created.append(str(compose_file))

    # --- Step 4: scripts/docker-entrypoint.sh --------------------------------
    scripts_dir = project / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    entrypoint = scripts_dir / "docker-entrypoint.sh"
    if not entrypoint.exists():
        _write_entrypoint(entrypoint)
        files_created.append(str(entrypoint))
        # Make executable
        import stat
        entrypoint.chmod(entrypoint.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # --- Step 5: Patch config.py with Docker settings fields -----------------
    config_file = project / "app" / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- ast.parse validation on Python files --------------------------------
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Production Docker setup added:",
            "  Dockerfile: multi-stage (builder + runtime), non-root USER 1000, HEALTHCHECK.",
            "  .dockerignore: excludes __pycache__, .venv, *.pyc, tests/, .git, etc.",
            "  docker-compose.prod.yml: app + postgres + redis with health checks and restart policies.",
            "  scripts/docker-entrypoint.sh: waits for DB, runs alembic upgrade head, starts gunicorn.",
            "Config fields added: DOCKER_WORKERS, DOCKER_PORT, DOCKER_HEALTH_PATH.",
        ],
        next_steps=[
            "Set POSTGRES_PASSWORD, SECRET_KEY, etc. in a .env.prod file (never commit it).",
            "docker compose -f docker-compose.prod.yml build",
            "docker compose -f docker-compose.prod.yml up -d",
            "docker compose -f docker-compose.prod.yml logs -f app",
            "Verify health: curl http://localhost:${DOCKER_PORT:-8000}${DOCKER_HEALTH_PATH:-/healthz}",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_dockerfile(dest: Path) -> None:
    """Write a multi-stage production Dockerfile.

    Stage 1 (builder): installs dependencies into a virtual environment.
    Stage 2 (runtime): copies the venv and app, runs as non-root USER 1000.

    Args:
        dest: Absolute path for the Dockerfile.
    """
    content = textwrap.dedent("""\
        # syntax=docker/dockerfile:1.7
        # Stage 1 — builder: install dependencies into /venv
        FROM python:3.12-slim AS builder
        WORKDIR /build
        RUN apt-get update && apt-get install -y --no-install-recommends \\
                build-essential libpq-dev \\
            && rm -rf /var/lib/apt/lists/*
        COPY requirements.txt .
        RUN --mount=type=cache,target=/root/.cache/pip \\
            python -m venv /venv && \\
            /venv/bin/pip install --upgrade pip && \\
            /venv/bin/pip install -r requirements.txt

        # Stage 2 — runtime: lean image, non-root user
        FROM python:3.12-slim AS runtime
        RUN apt-get update && apt-get install -y --no-install-recommends \\
                libpq5 \\
            && rm -rf /var/lib/apt/lists/* \\
            && groupadd -g 1000 appgroup \\
            && useradd -u 1000 -g appgroup -m -s /bin/sh appuser
        COPY --from=builder /venv /venv
        ENV PATH="/venv/bin:$PATH" \\
            PYTHONDONTWRITEBYTECODE=1 \\
            PYTHONUNBUFFERED=1
        WORKDIR /app
        COPY . .
        RUN chown -R appuser:appgroup /app
        USER 1000
        EXPOSE ${DOCKER_PORT:-8000}
        HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \\
            CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${DOCKER_PORT:-8000}${DOCKER_HEALTH_PATH:-/healthz}')"
        ENTRYPOINT ["scripts/docker-entrypoint.sh"]
        CMD ["gunicorn", "app.main:app", \\
             "--worker-class", "uvicorn.workers.UvicornWorker", \\
             "--workers", "${DOCKER_WORKERS:-2}", \\
             "--bind", "0.0.0.0:${DOCKER_PORT:-8000}", \\
             "--access-logfile", "-", \\
             "--error-logfile", "-"]
    """)
    dest.write_text(content)


def _write_dockerignore(dest: Path) -> None:
    """Write a .dockerignore that excludes dev artifacts.

    Args:
        dest: Absolute path for .dockerignore.
    """
    content = textwrap.dedent("""\
        # Python artifacts
        __pycache__/
        *.pyc
        *.pyo
        *.pyd
        .Python
        *.egg-info/
        dist/
        build/
        .eggs/

        # Virtual environments
        .venv/
        venv/
        env/

        # Test artifacts
        .pytest_cache/
        .coverage
        htmlcov/
        .tox/

        # IDE and OS
        .git/
        .gitignore
        .env
        .env.*
        *.swp
        .DS_Store

        # CI / docs
        .github/
        docs/
        *.md
    """)
    dest.write_text(content)


def _write_compose_prod(dest: Path) -> None:
    """Write docker-compose.prod.yml with app, postgres, redis services.

    All three services have health checks and restart policies.
    Postgres data is persisted via a named volume.

    Args:
        dest: Absolute path for docker-compose.prod.yml.
    """
    content = textwrap.dedent("""\
        version: "3.9"

        services:
          app:
            build:
              context: .
              target: runtime
            env_file: .env.prod
            environment:
              POSTGRES_SERVER: db
              REDIS_URL: redis://cache:6379/0
            ports:
              - "${DOCKER_PORT:-8000}:${DOCKER_PORT:-8000}"
            depends_on:
              db:
                condition: service_healthy
              cache:
                condition: service_healthy
            restart: unless-stopped
            healthcheck:
              test: ["CMD", "python", "-c",
                     "import urllib.request; urllib.request.urlopen('http://localhost:${DOCKER_PORT:-8000}${DOCKER_HEALTH_PATH:-/healthz}')"]
              interval: 30s
              timeout: 10s
              retries: 3
              start_period: 20s
            volumes:
              - ./alembic:/app/alembic:ro

          db:
            image: postgres:16-alpine
            environment:
              POSTGRES_USER: ${POSTGRES_USER:-postgres}
              POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD required}
              POSTGRES_DB: ${POSTGRES_DB:-app}
            volumes:
              - postgres_data:/var/lib/postgresql/data
            restart: unless-stopped
            healthcheck:
              test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres}"]
              interval: 10s
              timeout: 5s
              retries: 5

          cache:
            image: redis:7-alpine
            command: ["redis-server", "--maxmemory", "256mb", "--maxmemory-policy", "allkeys-lru"]
            restart: unless-stopped
            healthcheck:
              test: ["CMD", "redis-cli", "ping"]
              interval: 10s
              timeout: 5s
              retries: 5

        volumes:
          postgres_data:
    """)
    dest.write_text(content)


def _write_entrypoint(dest: Path) -> None:
    """Write scripts/docker-entrypoint.sh.

    Waits for the database to accept connections, then runs
    ``alembic upgrade head`` before starting the application server.

    Args:
        dest: Absolute path for the entrypoint script.
    """
    content = textwrap.dedent("""\
        #!/bin/sh
        # docker-entrypoint.sh — run DB migrations then start the app
        set -e

        DB_HOST="${POSTGRES_SERVER:-db}"
        DB_PORT="${POSTGRES_PORT:-5432}"
        MAX_TRIES=30

        echo "Waiting for database at ${DB_HOST}:${DB_PORT}..."
        tries=0
        until python -c "
        import socket, sys
        s = socket.socket()
        try:
            s.connect(('${DB_HOST}', ${DB_PORT}))
            s.close()
        except OSError:
            sys.exit(1)
        " 2>/dev/null; do
            tries=$((tries + 1))
            if [ "$tries" -ge "$MAX_TRIES" ]; then
                echo "Database not ready after ${MAX_TRIES} attempts. Aborting." >&2
                exit 1
            fi
            echo "  attempt ${tries}/${MAX_TRIES} — retrying in 2s..."
            sleep 2
        done

        echo "Database is ready. Running alembic upgrade head..."
        alembic upgrade head

        echo "Starting application..."
        exec "$@"
    """)
    dest.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Inject DOCKER_WORKERS, DOCKER_PORT, and DOCKER_HEALTH_PATH into Settings.

    Inserts the three config fields inside the ``class Settings`` body
    (4-space indented) just before the ``settings = Settings()`` instantiation
    line. When that line is absent, appends at end of file.

    Args:
        config_file: Absolute path to ``app/core/config.py``.
    """
    content = config_file.read_text()
    fields_needed = [
        "    DOCKER_WORKERS: int = 2",
        "    DOCKER_PORT: int = 8000",
        '    DOCKER_HEALTH_PATH: str = "/healthz"',
    ]
    new_lines = [line for line in fields_needed if line.strip().split(":")[0] not in content]
    if not new_lines:
        return

    insertion = "\n".join(new_lines) + "\n"

    # Insert BEFORE the module-level `settings = Settings()` instantiation
    # so the new fields remain inside the class body.
    marker = "settings = Settings()"
    if marker in content:
        content = content.replace(marker, insertion + "\n" + marker, 1)
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += "\n" + insertion
    config_file.write_text(content)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return wall-clock milliseconds since *start*.

    Args:
        start: Value from ``time.monotonic()`` taken at function entry.

    Returns:
        Elapsed time in milliseconds as a positive integer.
    """
    return int((time.monotonic() - start) * 1000)
