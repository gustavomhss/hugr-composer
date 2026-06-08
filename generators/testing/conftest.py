"""Generator for test infrastructure (conftest.py + tests/__init__.py)."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_test_infrastructure(
    output_dir: str,
    with_auth: bool = True,
) -> dict:
    """Generate a complete test infrastructure: conftest.py and tests/__init__.py.

    Provides fixtures for:
    - Async test engine (SQLite + aiosqlite for isolation)
    - Per-test session that creates/drops tables
    - ``httpx.AsyncClient`` wired to the app
    - ``superuser_token`` — creates admin user and returns Authorization header
    - ``normal_user_token`` — creates regular user and returns Authorization header

    Args:
        output_dir: Project root directory. Files are written to ``tests/``.
        with_auth: Include auth-related fixtures (superuser/normal user tokens).

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "tests"
    out.mkdir(parents=True, exist_ok=True)

    # --- tests/__init__.py ---
    init_path = out / "__init__.py"
    init_path.write_text("")

    # --- Build auth fixtures ---
    auth_imports = ""
    auth_fixtures = ""

    if with_auth:
        auth_imports = textwrap.dedent("""\
            from app.core.config import settings
            from app.core.security import get_password_hash
            from app.models.user import User
        """)

        auth_fixtures = textwrap.dedent('''\

            @pytest_asyncio.fixture()
            async def superuser_token(
                session: AsyncSession,
                client: AsyncClient,
            ) -> dict[str, str]:
                """Create a superuser and return an Authorization header dict."""
                user = User(
                    email=settings.FIRST_SUPERUSER_EMAIL or "admin@test.com",
                    hashed_password=get_password_hash("testpassword123"),
                    full_name="Test Admin",
                    is_active=True,
                    is_superuser=True,
                )
                session.add(user)
                await session.commit()

                login_data = {
                    "username": user.email,
                    "password": "testpassword123",
                }
                resp = await client.post(
                    f"{settings.API_V1_STR}/login/access-token",
                    data=login_data,
                )
                token = resp.json()["access_token"]
                return {"Authorization": f"Bearer {token}"}


            @pytest_asyncio.fixture()
            async def normal_user_token(
                session: AsyncSession,
                client: AsyncClient,
            ) -> dict[str, str]:
                """Create a regular (non-superuser) user and return an Authorization header."""
                user = User(
                    email="user@test.com",
                    hashed_password=get_password_hash("testpassword123"),
                    full_name="Test User",
                    is_active=True,
                    is_superuser=False,
                )
                session.add(user)
                await session.commit()

                login_data = {
                    "username": user.email,
                    "password": "testpassword123",
                }
                resp = await client.post(
                    f"{settings.API_V1_STR}/login/access-token",
                    data=login_data,
                )
                token = resp.json()["access_token"]
                return {"Authorization": f"Bearer {token}"}
        ''')

    # --- conftest.py ---
    conftest_content = textwrap.dedent('''\
        """Shared test fixtures — async engine, session, client, and auth helpers.

        Uses SQLite + aiosqlite for fast, isolated tests.  Each test gets its
        own set of tables (created in ``session`` fixture, dropped on teardown).
        """

        from __future__ import annotations

        # CRITICAL: the order of these env defaults is load-bearing —
        # every one of them MUST run before ``from app.main import app``
        # because the generated Settings() validates at import time and
        # raises on a missing/weak SECRET_KEY (Codex 3 F-006).
        #
        # - SECRET_KEY: deterministic 64-char hex placeholder. Real
        #   deployments override via .env / Secret manager; the value is
        #   long enough to clear the production-grade length check
        #   without ever shipping as a real credential (clearly marked
        #   test-only).
        # - RATE_LIMITING_ENABLED: off so sequential async test calls do
        #   not get 429-throttled by the production limiter.
        # - ENVIRONMENT: "local" so the strict prod-only validators
        #   relax.
        # - FIRST_SUPERUSER_EMAIL / FIRST_SUPERUSER_PASSWORD: the scaffold
        #   ships EMPTY defaults (no baked-in credentials, by design) and its
        #   Settings validator requires the pair to be set TOGETHER or both
        #   empty. The auth fixtures and the /login tests read
        #   ``settings.FIRST_SUPERUSER_EMAIL`` as the superuser's email, so it
        #   MUST be a non-empty, valid address here: posting an empty
        #   ``username`` to the OAuth2 form endpoint yields HTTP 422 ("field
        #   required"). The password is set to the same value the fixtures
        #   hash for the seeded user; it clears the ≥12-char / non-weak
        #   checks. Both are clearly test-only and never ship.
        import os
        os.environ.setdefault(
            "SECRET_KEY",
            "test-only-secret-key-not-for-production-"
            "0000000000000000000000000000",
        )
        os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
        os.environ.setdefault("ENVIRONMENT", "local")
        os.environ.setdefault("FIRST_SUPERUSER_EMAIL", "admin@test.com")
        os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "testpassword123")

        from collections.abc import AsyncGenerator

        import pytest
        import pytest_asyncio
        from httpx import ASGITransport, AsyncClient
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from app.core.session import get_session
        from app.main import app
        from app.models.base import Base
        {auth_imports}

        # ---------------------------------------------------------------------------
        # Async test engine — in-memory SQLite (no external DB required)
        # ---------------------------------------------------------------------------
        TEST_DATABASE_URL = "sqlite+aiosqlite://"

        engine_test = create_async_engine(
            TEST_DATABASE_URL,
            echo=False,
            future=True,
        )

        async_session_test = async_sessionmaker(
            engine_test,
            class_=AsyncSession,
            expire_on_commit=False,
        )


        # ---------------------------------------------------------------------------
        # Fixtures
        # ---------------------------------------------------------------------------
        @pytest_asyncio.fixture()
        async def session() -> AsyncGenerator[AsyncSession, None]:
            """Provide a clean database session for each test.

            Creates all tables before the test and drops them after.
            """
            async with engine_test.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with async_session_test() as sess:
                yield sess

            async with engine_test.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)


        @pytest_asyncio.fixture()
        async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
            """Provide an ``httpx.AsyncClient`` wired to the FastAPI app.

            Overrides the ``get_session`` dependency so the app uses the
            test database instead of the real one.
            """

            async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
                yield session

            app.dependency_overrides[get_session] = _override_get_session

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac

            app.dependency_overrides.clear()
        {auth_fixtures}
    ''').format(
        auth_imports=auth_imports,
        auth_fixtures=auth_fixtures,
    )

    conftest_path = out / "conftest.py"
    conftest_path.write_text(conftest_content)

    # pytest.ini for asyncio mode
    pytest_ini = Path(output_dir) / "pytest.ini"
    if not pytest_ini.exists():
        pytest_ini.write_text("[pytest]\nasyncio_mode = auto\n")

    # Add test deps to requirements.txt
    req_file = Path(output_dir) / "requirements.txt"
    if req_file.exists():
        req_content = req_file.read_text()
        test_deps = [
            "pytest>=8.0.0",
            "pytest-asyncio>=0.24.0",
            "httpx>=0.28.0",
            "aiosqlite>=0.20.0",
        ]
        added = []
        for dep in test_deps:
            pkg = dep.split(">=")[0].split("[")[0]
            if pkg not in req_content:
                req_content += f"{dep}\n"
                added.append(dep)
        if added:
            req_file.write_text(req_content)

    files = [str(init_path), str(conftest_path)]
    notes = [
        "Generated tests/conftest.py with async SQLite engine, session, and client fixtures.",
        "Tests are fully isolated — tables created/dropped per test.",
    ]
    if with_auth:
        notes.append("Auth fixtures included: superuser_token and normal_user_token.")

    return {"files_created": files, "notes": notes}
