"""Generator for .gitignore with Python + FastAPI defaults."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_generate_gitignore',
    'description': 'Generate .gitignore with Python, virtualenv, IDE, .env, database, testing, Docker exclusions.',
    'tags': ['generator', 'infra'],
    'entry': 'generate_gitignore',
}

import textwrap
from pathlib import Path


def generate_gitignore(output_dir: str) -> dict:
    """Generate a ``.gitignore`` tailored for Python + FastAPI projects.

    Covers: Python bytecode, virtual environments, IDE files,
    environment secrets, databases, testing artifacts, Docker
    overrides, and OS-specific files.

    Args:
        output_dir: Directory where ``.gitignore`` will be written.

    Returns:
        Dict with ``files_created`` and ``notes``.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent("""\
        # Python
        __pycache__/
        *.py[cod]
        *.egg-info/
        dist/
        build/
        .eggs/
        *.egg

        # Virtual environments
        .venv/
        venv/
        env/

        # IDE
        .vscode/
        .idea/
        *.swp
        *.swo

        # Environment
        .env
        .env.local
        .env.*.local

        # Database
        *.db
        *.sqlite3

        # Testing
        .pytest_cache/
        .coverage
        htmlcov/
        .mypy_cache/

        # Docker
        docker-compose.override.yml

        # OS
        .DS_Store
        Thumbs.db
    """)

    file_path = out / ".gitignore"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            "Generated .gitignore with Python, virtualenv, IDE, .env, database, "
            "testing, Docker, and OS exclusions.",
        ],
    }
