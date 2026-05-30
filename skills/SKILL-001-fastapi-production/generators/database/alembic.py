"""Generator for Alembic async migration scaffolding."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_data_generate_alembic',
    'description': 'Generate complete Alembic migration setup (alembic.ini + env.py + script template).',
    'tags': ['database', 'generator'],
    'entry': 'generate_alembic',
}

import textwrap
from pathlib import Path


def generate_alembic(output_dir: str) -> dict:
    """Generate Alembic configuration files for async PostgreSQL migrations.

    Creates:
        - ``alembic.ini`` (project root config)
        - ``alembic/env.py`` (async migration runner)
        - ``alembic/script.mako`` (revision template)
        - ``alembic/versions/`` (empty directory for migration scripts)

    Args:
        output_dir: Project root directory.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir)
    alembic_dir = out / "alembic"
    versions_dir = alembic_dir / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)

    files_created: list[str] = []

    # --- alembic.ini ------------------------------------------------------
    ini_content = textwrap.dedent("""\
        # Alembic configuration — async PostgreSQL
        [alembic]
        script_location = alembic
        prepend_sys_path = .

        # sqlalchemy.url is set programmatically in env.py from app settings.
        # Do NOT put credentials here.
        # sqlalchemy.url =

        [post_write_hooks]

        [loggers]
        keys = root,sqlalchemy,alembic

        [handlers]
        keys = console

        [formatters]
        keys = generic

        [logger_root]
        level = WARN
        handlers = console

        [logger_sqlalchemy]
        level = WARN
        handlers =
        qualname = sqlalchemy.engine

        [logger_alembic]
        level = INFO
        handlers =
        qualname = alembic

        [handler_console]
        class = StreamHandler
        args = (sys.stderr,)
        level = NOTSET
        formatter = generic

        [formatter_generic]
        format = %(levelname)-5.5s [%(name)s] %(message)s
        datefmt = %H:%M:%S
    """)

    ini_path = out / "alembic.ini"
    ini_path.write_text(ini_content)
    files_created.append(str(ini_path))

    # --- alembic/env.py ---------------------------------------------------
    env_content = textwrap.dedent("""\
        \"\"\"Alembic environment — async migration runner.\"\"\"

        import asyncio
        from logging.config import fileConfig

        from alembic import context
        from sqlalchemy import pool
        from sqlalchemy.ext.asyncio import async_engine_from_config

        from app.core.config import settings

        # Import ALL models so Alembic sees them in target_metadata.
        from app.models import *  # noqa: F401, F403
        from app.models.base import Base

        config = context.config

        # Logging
        if config.config_file_name is not None:
            fileConfig(config.config_file_name)

        target_metadata = Base.metadata

        # Inject the real database URL (never stored in alembic.ini).
        config.set_main_option("sqlalchemy.url", str(settings.SQLALCHEMY_DATABASE_URI))


        def run_migrations_offline() -> None:
            \"\"\"Run migrations in 'offline' mode — emit SQL to stdout.\"\"\"
            url = config.get_main_option("sqlalchemy.url")
            context.configure(
                url=url,
                target_metadata=target_metadata,
                literal_binds=True,
                dialect_opts={"paramstyle": "named"},
            )

            with context.begin_transaction():
                context.run_migrations()


        def do_run_migrations(connection):
            \"\"\"Configure context and run migrations synchronously.\"\"\"
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()


        async def run_async_migrations() -> None:
            \"\"\"Run migrations inside an async engine.\"\"\"
            connectable = async_engine_from_config(
                config.get_section(config.config_ini_section, {}),
                prefix="sqlalchemy.",
                poolclass=pool.NullPool,
            )

            async with connectable.connect() as connection:
                await connection.run_sync(do_run_migrations)

            await connectable.dispose()


        def run_migrations_online() -> None:
            \"\"\"Run migrations in 'online' mode — connect to the database.\"\"\"
            asyncio.run(run_async_migrations())


        if context.is_offline_mode():
            run_migrations_offline()
        else:
            run_migrations_online()
    """)

    env_path = alembic_dir / "env.py"
    env_path.write_text(env_content)
    files_created.append(str(env_path))

    # --- alembic/script.mako ----------------------------------------------
    mako_content = textwrap.dedent("""\
        \"\"\"${message}

        Revision ID: ${up_revision}
        Revises: ${down_revision | comma,n}
        Create Date: ${create_date}
        \"\"\"

        from typing import Sequence, Union

        import sqlalchemy as sa
        from alembic import op
        ${imports if imports else ""}

        # revision identifiers, used by Alembic.
        revision: str = ${repr(up_revision)}
        down_revision: Union[str, None] = ${repr(down_revision)}
        branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
        depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


        def upgrade() -> None:
            ${upgrades if upgrades else "pass"}


        def downgrade() -> None:
            ${downgrades if downgrades else "pass"}
    """)

    mako_path = alembic_dir / "script.mako"
    mako_path.write_text(mako_content)
    files_created.append(str(mako_path))

    # --- alembic/versions/0001_initial.py (chain root) --------------------
    # Closes R6-O4-A1: every extend tool emits migrations chained off
    # ``down_revision = "0001_initial"`` (see adapt/contracts/migration_helper
    # fallback).  Without an actual ``0001_initial`` revision on disk,
    # ``alembic upgrade head`` errors with "Can't locate revision identified by
    # '0001_initial'".  Emit a no-op baseline here so the chain root always
    # exists, regardless of whether ``generate_baseline_migration`` runs.
    initial_path = versions_dir / "0001_initial.py"
    if not initial_path.exists():
        initial_content = textwrap.dedent('''\
            """initial revision — chain root (no-op).

            Revision ID: 0001_initial
            Revises:
            Create Date: scaffold

            This is the empty root of the Alembic chain emitted by
            ``generators.database.alembic.generate_alembic``.  It exists so that
            extend tools which chain off ``down_revision = "0001_initial"``
            always have a valid parent revision to attach to.

            Real schema is created by ``0002_baseline_schema`` (if models are
            scaffolded) or by subsequent extend-tool migrations.
            """
            from __future__ import annotations

            from typing import Sequence, Union


            # revision identifiers, used by Alembic.
            revision: str = "0001_initial"
            down_revision: Union[str, None] = None
            branch_labels: Union[str, Sequence[str], None] = None
            depends_on: Union[str, Sequence[str], None] = None


            def upgrade() -> None:
                """No-op: chain root exists solely so downstream migrations chain."""
                pass


            def downgrade() -> None:
                """No-op: nothing to undo at the chain root."""
                pass
        ''')
        initial_path.write_text(initial_content)
    files_created.append(str(initial_path))

    return {
        "files_created": files_created,
        "notes": [
            "Generated alembic.ini, alembic/env.py (async), alembic/script.mako, and versions/0001_initial.py.",
            "Database URL is injected from app.core.config.settings — never hardcoded in alembic.ini.",
            "Import all model modules in env.py so autogenerate detects schema changes.",
            "0001_initial.py is the no-op chain root; baseline schema (when models exist) is 0002_baseline_schema.",
        ],
    }
