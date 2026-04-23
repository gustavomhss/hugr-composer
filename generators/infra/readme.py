"""Generator for project README.md."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_deployment_generate_readme',
    'description': 'Generate README.md with quick start, env reference, project structure, and deployment guide.',
    'tags': ['generator', 'infra'],
    'entry': 'generate_readme',
}

import textwrap
from pathlib import Path


def generate_readme(
    output_dir: str,
    name: str = "app",
    prefix: str = "/api/v1",
) -> dict:
    """Generate a production-grade README.md for the generated project.

    Includes quick-start, env-var reference, project structure,
    development workflow, and deployment instructions.

    Args:
        output_dir: Directory where README.md will be written.
        name: Project / application name.
        prefix: API route prefix (e.g. ``/api/v1``).

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    title = name.replace("-", " ").replace("_", " ").title()

    content = textwrap.dedent(f"""\
        # {title}

        Production-ready FastAPI backend with async SQLAlchemy, JWT auth,
        structured logging, and Docker support.

        ## Quick Start

        ### With Docker (recommended)

        ```bash
        # 1. Copy and configure environment variables
        cp .env.example .env
        # Edit .env — at minimum change SECRET_KEY and POSTGRES_PASSWORD

        # 2. Start all services
        docker compose up -d

        # 3. Run database migrations
        docker compose exec app alembic upgrade head

        # 4. Open API docs
        open http://localhost:8000/docs
        ```

        ### Without Docker

        ```bash
        # 1. Create and activate a virtual environment
        python -m venv .venv
        source .venv/bin/activate

        # 2. Install dependencies
        pip install -r requirements.txt

        # 3. Copy and configure environment variables
        cp .env.example .env

        # 4. Make sure PostgreSQL is running, then apply migrations
        alembic upgrade head

        # 5. Seed the first superuser
        python initial_data.py

        # 6. Start the development server
        uvicorn app.main:app --reload
        ```

        ## Environment Variables

        All configuration is driven by environment variables (or a `.env` file).
        See **`.env.example`** for the full list with descriptions.

        | Variable | Required | Description |
        |----------|----------|-------------|
        | `SECRET_KEY` | **Yes** | JWT signing key — **must be ≥ 32 chars in every environment**, fail-fast at boot. Generate once: `openssl rand -hex 32` |
        | `ENVIRONMENT` | No | `local` / `staging` / `production` (default: `local`) |
        | `POSTGRES_*` | Yes | Database connection parameters |
        | `FIRST_SUPERUSER_EMAIL` | Opt-in | Email for the initial admin. Leave empty to skip seeding. If set, `FIRST_SUPERUSER_PASSWORD` must also be set. |
        | `FIRST_SUPERUSER_PASSWORD` | Opt-in | Must be ≥ 12 chars and not a known-weak value (`changethis`, `admin`, `password`, …). |

        **Security contract.** `app/core/config.py` refuses to boot when
        `SECRET_KEY` is empty, shorter than 32 chars, or matches a
        known-weak value — in every environment including `local`.
        Superuser seeding is opt-in: leave both `FIRST_SUPERUSER_*`
        empty to skip. Setting only one raises at boot.

        ## API Documentation

        Once the server is running:

        | URL | Description |
        |-----|-------------|
        | [`/docs`](http://localhost:8000/docs) | Swagger UI (interactive) |
        | [`/redoc`](http://localhost:8000/redoc) | ReDoc (read-only) |
        | [`/healthz`](http://localhost:8000/healthz) | Health check |
        | [`/healthz/ready`](http://localhost:8000/healthz/ready) | Readiness probe (includes DB) |

        ## Project Structure

        ```
        .
        ├── app/
        │   ├── main.py              # Application entry point + lifespan
        │   ├── core/
        │   │   ├── config.py         # Pydantic settings (env parsing)
        │   │   ├── db.py             # Async SQLAlchemy engine + session
        │   │   └── security.py       # Password hashing + JWT helpers
        │   ├── models/               # SQLAlchemy ORM models
        │   ├── schemas/              # Pydantic request/response schemas
        │   ├── crud/                 # Data-access layer
        │   ├── api/
        │   │   ├── deps.py           # Dependency injection (auth, DB session)
        │   │   └── routes/           # Route modules
        │   ├── routes/               # Route assembly (api_router)
        │   └── middleware/           # CORS, security headers, logging
        ├── alembic/                  # Database migrations
        ├── tests/                    # Test suite
        ├── initial_data.py           # Superuser seeder
        ├── backend_pre_start.py      # DB readiness check
        ├── Dockerfile                # Multi-stage production image
        ├── docker-compose.yml        # Local development stack
        ├── .env.example              # Environment variable template
        └── requirements.txt          # Pinned dependencies
        ```

        ## Development

        ### Running Tests

        ```bash
        # Run the full test suite
        pytest -v

        # With coverage report
        pytest --cov=app --cov-report=term-missing
        ```

        ### Database Migrations

        ```bash
        # Create a new migration after changing models
        alembic revision --autogenerate -m "describe the change"

        # Apply all pending migrations
        alembic upgrade head

        # Rollback one migration
        alembic downgrade -1
        ```

        ### Code Quality

        ```bash
        # Lint + format (requires pre-commit or ruff installed)
        ruff check .
        ruff format .
        ```

        ## Deployment

        ### Docker

        ```bash
        # Build the production image
        docker build -t {name}:latest .

        # Run with environment variables
        docker run -p 8000:8000 --env-file .env {name}:latest
        ```

        ### Kubernetes

        Use the manifests in `k8s/` (if generated) or adapt the Dockerfile
        for your orchestrator.  Key points:

        - Set `ENVIRONMENT=production` and a strong `SECRET_KEY`.
        - Use the `/healthz` endpoint for liveness probes.
        - Use `/healthz/ready` for readiness probes.
        - Run `alembic upgrade head` as an init container.

        ---

        *Generated with SKILL-001 FastAPI Production.*
    """)

    file_path = out / "README.md"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            f"Generated README.md for '{title}' with quick-start, env reference, and project structure.",
        ],
    }
