"""Generator for PostgreSQL Row-Level Security (multi-tenancy) support.

Extracted from modules/database/tools/scaffold_db.py (_tenancy_py / _engine_py)
during Phase 0.5 of SKILL-001.

Generates two files:
- database/tenancy.py  -- FastAPI dependency + tenant-ID extractor
- (engine snippet)     -- get_tenant_session() using SET LOCAL app.current_tenant
"""

from __future__ import annotations

import textwrap
from pathlib import Path

MCP_TOOL = {
    "name": "fastapi_generate_rls",
    "description": "Generate PostgreSQL Row-Level Security policies for multi-tenant table isolation.",
    "tags": ["database", "security", "generator"],
    "entry": "generate_rls",
}


def generate_rls(output_dir: str) -> dict:
    """Generate database/tenancy.py for PostgreSQL Row-Level Security.

    Creates a FastAPI dependency that:
    1. Extracts a tenant ID from the incoming request (X-Tenant-ID header
       by default — override for JWT-claim or subdomain strategies).
    2. Yields an AsyncSession that has executed
       ``SET LOCAL app.current_tenant = :tid`` so that PostgreSQL RLS
       policies can enforce row-level isolation without any application-layer
       filtering.

    The ``SET LOCAL`` call is transaction-scoped: it is automatically
    cleared when the transaction ends, preventing tenant context from
    leaking across pooled connections.

    Args:
        output_dir: Parent directory where ``database/tenancy.py`` will
            be written (and ``database/`` will be created if absent).

    Returns:
        Dict with ``files_created`` (list of paths) and ``notes`` (list
        of implementation hints).

    Example::

        result = generate_rls("/tmp/myproject")
        print(result["files_created"])
        # ['/tmp/myproject/database/tenancy.py']

    SQL setup (run once per tenant table)::

        ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
        ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON <table>
            USING (tenant_id = current_setting('app.current_tenant')::text);
    """
    out = Path(output_dir) / "database"
    out.mkdir(parents=True, exist_ok=True)

    tenancy_content = textwrap.dedent('''\
        """Multi-tenancy support via PostgreSQL Row-Level Security.

        Architecture:
        - Each request sets ``app.current_tenant`` via ``SET LOCAL``
          (transaction-scoped — never leaks across pooled connections).
        - PostgreSQL RLS policies enforce isolation at the database level.
        - The application also filters by ``tenant_id`` (defense in depth).

        Setup SQL (run once per tenant table)::

            ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
            ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON <table>
                USING (tenant_id = current_setting(\'app.current_tenant\')::text);

        Usage in routes::

            from database.tenancy import TenantSession

            @app.get("/documents")
            async def list_docs(session: TenantSession):
                # RLS automatically filters rows to the current tenant
                result = await session.execute(select(Document))
                return result.scalars().all()
        """

        from collections.abc import AsyncGenerator
        from typing import Annotated

        from fastapi import Depends, HTTPException, Request
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from app.core.db import engine  # adjust import to match your project layout

        # Session factory (reuse from engine module if already created there)
        _async_session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )


        async def _get_tenant_session(
            tenant_id: str,
        ) -> AsyncGenerator[AsyncSession, None]:
            """Yield an AsyncSession with RLS tenant context.

            Uses ``SET LOCAL`` so the setting is scoped to the current
            transaction and does not leak across pooled connections.
            Commits on success, rolls back on any exception.
            """
            async with _async_session_factory() as session:
                try:
                    await session.execute(
                        text("SET LOCAL app.current_tenant = :tid"),
                        {"tid": tenant_id},
                    )
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise


        def get_tenant_id_from_request(request: Request) -> str:
            """Extract tenant ID from the incoming request.

            Default strategy: read the ``X-Tenant-ID`` header.

            Override this function to match your auth strategy:
            - JWT claim:  ``request.state.user["tenant_id"]``
            - Subdomain:  ``request.url.hostname.split(".")[0]``
            - Path param: injected via route dependency
            """
            tenant_id = request.headers.get("X-Tenant-ID")
            if not tenant_id:
                raise HTTPException(
                    status_code=400,
                    detail="X-Tenant-ID header required",
                )
            return tenant_id


        async def get_session_with_tenant(
            request: Request,
        ) -> AsyncGenerator[AsyncSession, None]:
            """FastAPI dependency providing a tenant-scoped database session.

            Combines tenant-ID extraction with RLS session setup in one
            dependency so routes only need to declare ``TenantSession``.
            """
            tenant_id = get_tenant_id_from_request(request)
            async for session in _get_tenant_session(tenant_id):
                yield session


        # Annotated type alias — use this in route signatures
        TenantSession = Annotated[AsyncSession, Depends(get_session_with_tenant)]
    ''')

    tenancy_path = out / "tenancy.py"
    tenancy_path.write_text(tenancy_content)

    return {
        "files_created": [str(tenancy_path)],
        "notes": [
            "Generated database/tenancy.py with PostgreSQL RLS support via SET LOCAL.",
            "TenantSession type alias ready for use in FastAPI route signatures.",
            "Default tenant extraction: X-Tenant-ID header — override "
            "get_tenant_id_from_request() for JWT-claim or subdomain strategies.",
            "SET LOCAL is transaction-scoped: tenant context never leaks across "
            "pooled connections (safe with pgBouncer in transaction mode).",
            "Phase 0.5 nugget: extracted from scaffold_db.py (_tenancy_py / "
            "_engine_py.get_tenant_session) and adapted to v3 generator style.",
            "Required SQL per table: ENABLE ROW LEVEL SECURITY + CREATE POLICY "
            "tenant_isolation USING (tenant_id = current_setting('app.current_tenant')::text).",
        ],
    }
