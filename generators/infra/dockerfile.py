"""Generator for Dockerfile and .dockerignore."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_generate_dockerfile',
    'description': 'Generate multi-stage Dockerfile with non-root user and HEALTHCHECK.',
    'tags': ['generator', 'infra'],
    'entry': 'generate_dockerfile',
}

import textwrap
from pathlib import Path


def generate_dockerfile(
    output_dir: str,
    python_version: str = "3.12",
    port: int = 8000,
    workers: int = 4,
) -> dict:
    """Generate a production-grade multi-stage Dockerfile and .dockerignore.

    Args:
        output_dir: Directory where Dockerfile and .dockerignore will be written.
        python_version: Python version for the base image.
        port: Port the application listens on.
        workers: Number of uvicorn workers.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    dockerfile_content = textwrap.dedent(f"""\
        # ---- Builder stage ----
        FROM python:{python_version}-slim AS builder

        WORKDIR /build

        RUN apt-get update && \\
            apt-get install -y --no-install-recommends gcc libpq-dev && \\
            rm -rf /var/lib/apt/lists/*

        COPY requirements.txt .
        RUN pip install --no-cache-dir --upgrade pip && \\
            pip install --no-cache-dir --prefix=/install -r requirements.txt

        # ---- Runtime stage ----
        FROM python:{python_version}-slim AS runtime

        WORKDIR /project

        # Install only runtime libs (no compiler)
        RUN apt-get update && \\
            apt-get install -y --no-install-recommends libpq5 curl && \\
            rm -rf /var/lib/apt/lists/*

        # Copy installed packages from builder
        COPY --from=builder /install /usr/local

        # Non-root user
        RUN groupadd --gid 1000 appuser && \\
            useradd --uid 1000 --gid appuser --shell /bin/sh --create-home appuser

        # Copy source tree.  The real ``app/`` package lives under the
        # project root, so ``from app.xxx`` imports resolve naturally
        # once WORKDIR is /project -- no smuggling tricks needed.
        COPY . /project/

        # Own the workdir
        RUN chown -R appuser:appuser /project

        USER appuser

        EXPOSE {port}

        HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \\
            CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:{port}/healthz')"

        # Pre-start: wait for DB, run Alembic migrations, seed superuser, then start uvicorn
        CMD ["sh", "-c", "python -m app.backend_pre_start && alembic upgrade head && python -m app.initial_data && uvicorn app.main:app --host 0.0.0.0 --port {port} --workers {workers}"]
    """)

    dockerignore_content = textwrap.dedent("""\
        .git
        .gitignore
        .github/
        .env
        .env.*
        .venv
        venv
        __pycache__
        *.pyc
        *.pyo
        *.md
        *.rst
        .mypy_cache
        .pytest_cache
        .ruff_cache
        .coverage
        htmlcov
        dist
        build
        *.egg-info
        docker-compose*.yml
        docker-compose.yml
        Makefile
        tests/
        docs/
        .pre-commit-config.yaml
    """)

    dockerfile_path = out / "Dockerfile"
    dockerfile_path.write_text(dockerfile_content)

    dockerignore_path = out / ".dockerignore"
    dockerignore_path.write_text(dockerignore_content)

    return {
        "files_created": [str(dockerfile_path), str(dockerignore_path)],
        "notes": [
            f"Multi-stage Dockerfile: python:{python_version}-slim, {workers} workers on port {port}.",
            "Non-root user (appuser:1000), HEALTHCHECK on /healthz, .dockerignore included.",
        ],
    }
