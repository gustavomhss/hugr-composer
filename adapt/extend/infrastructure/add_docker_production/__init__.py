"""TOOL-092: add_docker_production — add a multi-stage production Docker setup.

Generates a production-grade Docker configuration for a FastAPI project:

* ``Dockerfile`` — two-stage build (``builder`` + ``runtime``), non-root USER 1000,
  HEALTHCHECK, pip cache mount, gunicorn + uvicorn workers.
* ``.dockerignore`` — excludes ``__pycache__``, ``.venv``, ``*.pyc``, test dirs, etc.
* ``docker-compose.prod.yml`` — app + postgres + redis services, volume mounts,
  health checks, restart policies.
* ``scripts/docker-entrypoint.sh`` — wait-for-it idiom, ``alembic upgrade head``,
  optional create-superuser.

The tool is idempotent: a second run detects the ``restart`` fingerprint in
``docker-compose.prod.yml`` and returns ``status="no_op"``.

Warnings:
    - This Dockerfile runs as USER 1000, providing standard non-root isolation.
      It does NOT enforce a read-only filesystem or drop Linux capabilities.
    - The docker-compose.prod.yml uses shell-style ${VAR} references that are
      expanded by docker compose at runtime from environment variables or .env.prod.
    - No securityContext is set in Dockerfile; see add_kubernetes_manifests for k8s.
"""

from __future__ import annotations

import ast
import stat
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_deployment_add_docker_production",
    "description": (
        "Add a multi-stage production Dockerfile, .dockerignore, docker-compose.prod.yml, "
        "and docker-entrypoint.sh to a FastAPI project."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_docker_production",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_docker_production(inp: ToolInput) -> ToolResult:
    """Add a multi-stage production Docker setup to a FastAPI project.

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
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

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

    compose_fingerprint = project / "docker-compose.prod.yml"
    if compose_fingerprint.exists() and "restart" in compose_fingerprint.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "docker-compose.prod.yml already present — Docker production setup already installed, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

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

    # Step 1: Dockerfile (mixed-language — read verbatim, no template substitution)
    dockerfile = project / "Dockerfile"
    _write_from_tmpl("Dockerfile.tmpl", dockerfile)
    files_created.append(str(dockerfile))

    # Step 2: .dockerignore
    dockerignore = project / ".dockerignore"
    if not dockerignore.exists():
        _write_from_tmpl(".dockerignore.tmpl", dockerignore)
        files_created.append(str(dockerignore))

    # Step 3: docker-compose.prod.yml (mixed-language — read verbatim)
    compose_file = project / "docker-compose.prod.yml"
    if not compose_file.exists():
        _write_from_tmpl("docker-compose.prod.yml.tmpl", compose_file)
        files_created.append(str(compose_file))

    # Step 4: scripts/docker-entrypoint.sh (mixed-language — read verbatim)
    scripts_dir = project / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    entrypoint = scripts_dir / "docker-entrypoint.sh"
    if not entrypoint.exists():
        _write_from_tmpl("docker-entrypoint.sh.tmpl", entrypoint)
        files_created.append(str(entrypoint))
        entrypoint.chmod(entrypoint.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Step 5: Patch config.py
    config_file = project / "app" / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 6: Emit project test
    _emit_project_test(project, files_created)

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
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _write_from_tmpl(tmpl_name: str, dest: Path) -> None:
    """Write a mixed-language template verbatim (no substitution)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = (_HERE / "templates" / tmpl_name).read_text()
    dest.write_text(content)


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_docker_production_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_docker_production_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_config(config_file: Path) -> None:
    """Inject DOCKER_WORKERS, DOCKER_PORT, and DOCKER_HEALTH_PATH into Settings."""
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
    marker = "settings = Settings()"
    if marker in content:
        content = content.replace(marker, insertion + "\n" + marker, 1)
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += "\n" + insertion
    config_file.write_text(content)


