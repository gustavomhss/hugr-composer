"""Generator for async SQLAlchemy engine configuration."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_data_generate_engine',
    'description': 'Generate async database engine with pool_pre_ping, pool_recycle, and sized connection pool.',
    'tags': ['database', 'generator'],
    'entry': 'generate_engine',
}

import textwrap
from pathlib import Path


def generate_engine(
    output_dir: str,
    driver: str = "asyncpg",
    pool_size: int = 5,
    max_overflow: int = 10,
) -> dict:
    """Generate core/db.py with async engine, pool tuning, and init hook.

    Args:
        output_dir: Directory where core/db.py will be written.
        driver: Async database driver (asyncpg, aiosqlite).
        pool_size: Permanent connections kept in the pool.
        max_overflow: Extra connections allowed above pool_size under load.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "core"
    out.mkdir(parents=True, exist_ok=True)

    # Pre-compute the example pool total so it appears as a literal number
    # in the generated comment (no unrendered template placeholder).
    pool_total = 4 * 3 * (pool_size + max_overflow)

    content = textwrap.dedent(f'''\
        """Async SQLAlchemy engine and database initialisation."""

        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        # ---------------------------------------------------------------
        # Pool sizing rule of thumb:
        #
        #   workers x pods x (pool_size + max_overflow)  <=  max_connections - 20
        #
        # Example: 4 workers x 3 pods x ({pool_size} + {max_overflow}) = {pool_total} connections
        # Keep 20 connections free for migrations, monitoring, and ad-hoc queries.
        # ---------------------------------------------------------------

        engine = create_async_engine(
            str(settings.SQLALCHEMY_DATABASE_URI),
            pool_size={pool_size},
            max_overflow={max_overflow},
            pool_recycle=1800,
            pool_pre_ping=True,
            echo=False,
        )


        async def init_db() -> None:
            """Run startup checks (connection test, extension loading, etc.)."""
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))


        # Re-export for convenience (used by lifespan in main.py).
        __all__ = ["engine", "init_db"]
    ''')

    # Patch: add missing `text` import needed by init_db
    content = content.replace(
        "from sqlalchemy.ext.asyncio import create_async_engine",
        "from sqlalchemy import text\n"
        "from sqlalchemy.ext.asyncio import create_async_engine",
    )

    file_path = out / "db.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            f"Generated core/db.py with {driver} driver, pool_size={pool_size}, max_overflow={max_overflow}.",
            "Pool uses pool_pre_ping=True to discard stale connections and pool_recycle=1800 (30 min).",
        ],
    }
