"""Prerequisite checker for adapt tools.

Every adapt tool calls ``check_prerequisites()`` before modifying a project.
The checker validates that required files and patterns exist, returning
clear error messages instead of silently generating broken code.

Example::

    from adapt.contracts.prerequisites import check_prerequisites, Prereq

    errors = check_prerequisites(
        project_dir,
        Prereq.BASE_MODEL,       # app/models/base.py with Base class
        Prereq.CONFIG_SETTINGS,   # app/core/config.py with Settings class
        Prereq.ROUTES_INIT,       # app/routes/__init__.py with api_router
        Prereq.MODELS_INIT,       # app/models/__init__.py
    )
    if errors:
        return ToolResult(
            status="error",
            error=f"Missing prerequisites: {'; '.join(errors)}",
            notes=[
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='minimal', ...)",
            ],
        )
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class Prereq(str, Enum):
    """Prerequisites that adapt tools may require."""

    BASE_MODEL = "base_model"
    CONFIG_SETTINGS = "config_settings"
    ROUTES_INIT = "routes_init"
    MODELS_INIT = "models_init"
    AUTH_DEPS = "auth_deps"
    AUTH_SECURITY = "auth_security"
    SESSION_DEP = "session_dep"
    REQUIREMENTS_TXT = "requirements_txt"
    ALEMBIC_VERSIONS = "alembic_versions"


_CHECKS: dict[Prereq, tuple[str, str, str]] = {
    # (relative_path, content_marker, human_description)
    Prereq.BASE_MODEL: (
        "app/models/base.py",
        "class Base",
        "SQLAlchemy Base declarative class (app/models/base.py)",
    ),
    Prereq.CONFIG_SETTINGS: (
        "app/core/config.py",
        "class Settings",
        "Pydantic Settings class (app/core/config.py)",
    ),
    Prereq.ROUTES_INIT: (
        "app/routes/__init__.py",
        "api_router",
        "API router assembly (app/routes/__init__.py)",
    ),
    Prereq.MODELS_INIT: (
        "app/models/__init__.py",
        "import",
        "Model registration file (app/models/__init__.py)",
    ),
    Prereq.AUTH_DEPS: (
        "app/api/deps.py",
        "CurrentUser",
        "Auth dependencies with CurrentUser (app/api/deps.py)",
    ),
    Prereq.AUTH_SECURITY: (
        "app/core/security.py",
        "verify_password",
        "Password verification (app/core/security.py)",
    ),
    Prereq.SESSION_DEP: (
        "app/core/session.py",
        "get_session",
        "Database session dependency (app/core/session.py)",
    ),
    Prereq.REQUIREMENTS_TXT: (
        "requirements.txt",
        "",  # just needs to exist
        "Python dependencies file (requirements.txt)",
    ),
    Prereq.ALEMBIC_VERSIONS: (
        "alembic/versions",
        "",  # directory, not file
        "Alembic versions directory (alembic/versions/)",
    ),
}


def check_prerequisites(project_dir: str | Path, *prereqs: Prereq) -> list[str]:
    """Check that all required prerequisites are present in the project.

    Args:
        project_dir: Root of the FastAPI project.
        *prereqs: One or more ``Prereq`` enum values to check.

    Returns:
        List of human-readable error strings for missing prerequisites.
        Empty list means all prerequisites are satisfied.
    """
    errors: list[str] = []
    root = Path(project_dir)

    for prereq in prereqs:
        rel_path, marker, description = _CHECKS[prereq]
        target = root / rel_path

        if prereq == Prereq.ALEMBIC_VERSIONS:
            if not target.is_dir():
                errors.append(f"Missing: {description}")
            continue

        if not target.is_file():
            errors.append(f"Missing: {description}")
            continue

        if marker:
            content = target.read_text(errors="replace")
            if marker not in content:
                errors.append(
                    f"Found {rel_path} but missing '{marker}' — "
                    f"expected: {description}"
                )

    return errors
