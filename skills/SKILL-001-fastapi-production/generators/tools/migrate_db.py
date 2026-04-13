"""ADAPT tool: generate an Alembic migration helper for pending model changes.

Since Alembic's ``--autogenerate`` requires a live database connection,
this tool takes a practical approach: it generates a helper script and
returns the exact commands the user needs to run.

Usage::

    from generators.tools.migrate_db import generate_migration

    result = generate_migration(
        project_dir="/path/to/existing-project",
        message="add orders table",
    )
    # result["commands"] -> ["bash scripts/create_migration.sh 'add orders table'"]
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from generators.tools._layout import resolve_app_root


def generate_migration(
    project_dir: str,
    message: str | None = None,
) -> dict:
    """Generate an Alembic migration helper and return run instructions.

    This tool does NOT require a running database.  Instead it:

    1. Verifies the Alembic scaffolding exists (``alembic/`` directory
       and ``alembic.ini``).
    2. Generates ``scripts/create_migration.sh`` — a self-contained
       shell script that sets up ``PYTHONPATH``, activates the venv
       (if present), and runs ``alembic revision --autogenerate``.
    3. Returns the exact commands the user should execute to create
       and apply the migration.

    If the Alembic scaffolding is missing, the tool returns an error
    note directing the user to run the project generator first.

    Args:
        project_dir: Root directory of the existing project.
        message: Migration message (e.g. ``"add orders table"``).
            Defaults to ``"auto migration"``.

    Returns:
        Dict with ``files_created``, ``commands``, and ``notes``.
    """
    # Alembic config + versions live at the project root (not under app/)
    # so that `alembic upgrade head` runs from the same dir as alembic.ini.
    root = Path(project_dir)
    msg = message or "auto migration"

    files_created: list[str] = []
    commands: list[str] = []
    notes: list[str] = []

    # ------------------------------------------------------------------
    # 1. Verify Alembic scaffolding
    # ------------------------------------------------------------------
    alembic_dir = root / "alembic"
    alembic_ini = root / "alembic.ini"
    env_py = alembic_dir / "env.py"

    missing: list[str] = []
    if not alembic_dir.is_dir():
        missing.append("alembic/")
    if not alembic_ini.exists():
        missing.append("alembic.ini")
    if not env_py.exists():
        missing.append("alembic/env.py")

    if missing:
        notes.append(
            f"Alembic scaffolding is incomplete (missing: {', '.join(missing)}). "
            "Run the project generator first or use: "
            "from generators.database.alembic import generate_alembic; "
            f"generate_alembic('{project_dir}')"
        )
        return {
            "files_created": [],
            "commands": [],
            "notes": notes,
        }

    # ------------------------------------------------------------------
    # 2. Ensure alembic/versions/ exists
    # ------------------------------------------------------------------
    versions_dir = alembic_dir / "versions"
    if not versions_dir.is_dir():
        versions_dir.mkdir(parents=True, exist_ok=True)
        notes.append("Created alembic/versions/ directory.")

    # ------------------------------------------------------------------
    # 3. Generate helper script
    # ------------------------------------------------------------------
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    script_path = scripts_dir / "create_migration.sh"

    script_content = textwrap.dedent("""\
        #!/usr/bin/env bash
        # Create an Alembic autogenerate migration.
        #
        # Usage:
        #   bash scripts/create_migration.sh "add orders table"
        #   bash scripts/create_migration.sh              # defaults to "auto migration"
        #
        # Prerequisites:
        #   - A running PostgreSQL database matching DATABASE_URL in .env
        #   - All model files imported in alembic/env.py (via models/__init__.py)

        set -euo pipefail

        MESSAGE="${1:-auto migration}"

        # Activate venv if present
        if [ -f ".venv/bin/activate" ]; then
            source .venv/bin/activate
        fi

        # Ensure PYTHONPATH includes the project root so "from app.xxx" works
        export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}."

        echo "Creating migration: $MESSAGE"
        alembic revision --autogenerate -m "$MESSAGE"

        echo ""
        echo "Migration created. Review the file in alembic/versions/ then run:"
        echo "  alembic upgrade head"
    """)

    script_path.write_text(script_content)
    script_path.chmod(0o755)
    files_created.append(str(script_path))
    notes.append("Generated scripts/create_migration.sh (chmod +x).")

    # ------------------------------------------------------------------
    # 4. Build commands for the user
    # ------------------------------------------------------------------
    # Escaped message for shell
    escaped_msg = msg.replace("'", "'\\''")

    commands.extend([
        f"bash scripts/create_migration.sh '{escaped_msg}'",
        "# Review the generated file in alembic/versions/",
        "alembic upgrade head",
    ])

    notes.extend([
        "Step 1: Run the create_migration.sh script (requires a running database).",
        "Step 2: Review the generated migration in alembic/versions/ — "
        "autogenerate is not perfect; check indexes, constraints, and data migrations.",
        "Step 3: Apply with 'alembic upgrade head'.",
        "Step 4: Commit the migration file to version control.",
    ])

    return {
        "files_created": files_created,
        "commands": commands,
        "notes": notes,
    }
