"""Generator for initial_data.py — creates first superuser on startup."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_generate_initial_data',
    'description': 'Generate initial_data.py -- idempotent superuser seeding script for first boot.',
    'tags': ['generator', 'infra'],
    'entry': 'generate_initial_data',
}

import textwrap
from pathlib import Path


def generate_initial_data(output_dir: str) -> dict:
    """Generate initial_data.py that seeds the first superuser from env vars.

    Creates two files:
    - ``initial_data.py`` — idempotent script that creates the superuser
      if it does not already exist.  Called from the app lifespan or
      as a standalone ``python initial_data.py``.

    Args:
        output_dir: Directory where initial_data.py will be written.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent('''\
        """Create initial data (first superuser) on application startup.

        This script is idempotent — it checks whether the superuser already
        exists before attempting to create it.  Safe to run on every boot.

        Usage:
            # As standalone script (e.g. in Docker entrypoint):
            python initial_data.py

            # Or called programmatically from the app lifespan:
            from initial_data import init_db
            await init_db()
        """

        from __future__ import annotations

        import asyncio
        import logging

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.config import settings, Environment
        from app.core.db import engine
        from app.core.session import async_session
        from app.core.security import get_password_hash
        # Import via the package so all models register with Base.metadata.
        # Alembic discovers the same package via app/models/__init__.py.
        import app.models  # noqa: F401
        from app.models.base import Base
        from app.models.user import User

        logger = logging.getLogger(__name__)


        async def init_db() -> None:
            """Seed the first superuser.

            Schema creation:
              - In ``local`` environment, falls back to ``Base.metadata.create_all``
                so newly added models work without requiring a manual
                ``alembic revision --autogenerate``.
              - In ``staging`` and ``production``, Alembic is the source of truth;
                ``alembic upgrade head`` runs in the Docker entrypoint BEFORE
                this script.  ``create_all`` is skipped.
            """
            if settings.ENVIRONMENT == Environment.LOCAL:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)

            async with async_session() as session:
                await _create_first_superuser(session)


        async def _create_first_superuser(session: AsyncSession) -> None:
            """Create the first superuser if it does not already exist."""
            email = settings.FIRST_SUPERUSER_EMAIL
            password = settings.FIRST_SUPERUSER_PASSWORD

            if not email or not password:
                logger.warning(
                    "FIRST_SUPERUSER_EMAIL or FIRST_SUPERUSER_PASSWORD not set — "
                    "skipping superuser creation."
                )
                return

            result = await session.execute(
                select(User).where(User.email == email).limit(1)
            )
            existing = result.scalars().first()

            if existing is not None:
                logger.info("Superuser %s already exists — skipping.", email)
                return

            try:
                superuser = User(
                    email=email,
                    hashed_password=get_password_hash(password),
                    full_name="Initial Admin",
                    is_active=True,
                    is_superuser=True,
                )
                session.add(superuser)
                await session.commit()
                logger.info("Created first superuser: %s", email)
            except Exception:
                await session.rollback()
                logger.info("Superuser %s already exists (concurrent creation) — skipping.", email)


        if __name__ == "__main__":
            logging.basicConfig(level=logging.INFO)
            asyncio.run(init_db())
    ''')

    file_path = out / "initial_data.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            "Generated initial_data.py — idempotent superuser seeding script.",
            "Checks for existing superuser by email before creating.",
            "Can be called from lifespan or as standalone: python initial_data.py.",
        ],
    }
