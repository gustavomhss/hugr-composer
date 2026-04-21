"""Generator for async session factory and FastAPI dependency."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_data_generate_session',
    'description': 'Generate async session factory with commit/rollback/close and SessionDep dependency.',
    'tags': ['database', 'generator'],
    'entry': 'generate_session',
}

import textwrap
from pathlib import Path


def generate_session(output_dir: str) -> dict:
    """Generate core/session.py with async session factory and get_session dependency.

    Args:
        output_dir: Directory where core/session.py will be written.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "core"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent('''\
        """Async session factory and FastAPI dependency."""

        from collections.abc import AsyncGenerator
        from typing import Annotated

        from fastapi import Depends
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from app.core.db import engine

        # ---------------------------------------------------------------
        # expire_on_commit=False is MANDATORY for async sessions.
        #
        # Without it, every attribute access after commit triggers a
        # lazy load — which raises MissingGreenlet in async context
        # because SQLAlchemy cannot implicitly perform I/O in an
        # awaitable that has already been committed.
        # ---------------------------------------------------------------
        async_session = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )


        async def get_session() -> AsyncGenerator[AsyncSession, None]:
            """FastAPI dependency that yields an async session.

            Commits on success, rolls back on unhandled exception,
            and always closes the session.
            """
            async with async_session() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    await session.close()


        SessionDep = Annotated[AsyncSession, Depends(get_session)]
    ''')

    file_path = out / "session.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            "Generated core/session.py with async_sessionmaker (expire_on_commit=False).",
            "SessionDep annotated dependency ready for use in route signatures.",
        ],
    }
