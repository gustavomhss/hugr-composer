"""SKILL-001 v3 -- Functional Proof (E2E Test Suite).

Generates a complete FastAPI project, patches it for SQLite (aiosqlite),
boots the app with TestClient, and validates every endpoint works correctly.

DISCOVERED GENERATOR BUGS (patched at runtime for this test):

  BUG-1: schemas/user.py -- UserCreate missing ``password`` field.
         The orchestrator generates UserCreate from model fields but
         excludes hashed_password. The signup route expects a ``password``
         field which it pops and hashes. Fix: add password to UserCreate.
         Generator: generators/orchestrator.py (_generate_package_inits)

  BUG-2: api/routes/users.py -- ``get_current_superuser = CurrentSuperuser``
         assigns an Annotated type alias, then uses it in
         ``dependencies=[Depends(get_current_superuser)]``. Depends()
         needs a callable, not an Annotated alias. Fix: import the actual
         function from deps.py.
         Generator: generators/endpoints/user_routes.py

  BUG-3: api/deps.py -- passes ``token_data.sub`` (str) to
         ``crud.get(session, id=...)`` which expects uuid.UUID. SQLAlchemy
         Uuid type can't process a raw string. Fix: wrap with uuid.UUID().
         Generator: generators/auth/deps.py

Usage:
    python benchmark/test_functional.py
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
import time
import traceback
import warnings
from pathlib import Path

# ---------------------------------------------------------------------------
# Silence noisy output so the test report is clean
# ---------------------------------------------------------------------------
warnings.filterwarnings("ignore")
os.environ.setdefault("ENVIRONMENT", "local")
# Suppress structlog request logs during tests
logging.getLogger("app.middleware.request_logging").setLevel(logging.CRITICAL)
logging.disable(logging.CRITICAL)

# ---------------------------------------------------------------------------
# Ensure generators are importable
# ---------------------------------------------------------------------------
SKILL_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from generators.orchestrator import generate_project


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------
SUPERUSER_EMAIL = "admin@test.com"
SUPERUSER_PASSWORD = "Admin1234!"
REGULAR_EMAIL = "user@test.com"
REGULAR_PASSWORD = "User1234!"
PREFIX = "/api/v1"

_results: list[dict] = []
_all_responses: list[dict] = []  # for hashed_password audit


def _record(
    test_id: str,
    section: str,
    description: str,
    *,
    passed: bool,
    status_code: int | None = None,
    duration_ms: float = 0.0,
    detail: str = "",
) -> None:
    _results.append({
        "test_id": test_id,
        "section": section,
        "description": description,
        "passed": passed,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 1),
        "detail": detail,
    })


# ---------------------------------------------------------------------------
# Phase 1: Generate project
# ---------------------------------------------------------------------------
def generate(tmp: Path) -> dict:
    """Generate the project with User + Item models."""
    return generate_project(
        output_dir=str(tmp),
        name="functional_test",
        prefix=PREFIX,
        models={
            "Item": {"title": "str", "description": "text"},
        },
        owner_models={"Item": "user"},
        with_auth=True,
        cors_origins=["http://localhost:3000"],
    )


# ---------------------------------------------------------------------------
# Phase 2: Patch for SQLite + aiosqlite
# ---------------------------------------------------------------------------
def patch_for_sqlite(tmp: Path) -> None:
    """Rewrite config.py and db.py to use SQLite with aiosqlite.

    Note: source code lives under tmp/app/ in the new package layout.
    """
    # The package layout puts source under app/. Some patches in this
    # function still hit "tmp/core/...". Switch to app/ root.
    app_root = tmp / "app" if (tmp / "app").exists() else tmp

    # --- Patch core/config.py ---
    # Replace the entire Postgres-based config with a simple one
    config_file = app_root / "core" / "config.py"
    config_file.write_text('''\
"""Application settings -- patched for functional test (SQLite)."""

from __future__ import annotations

import warnings
from enum import Enum
from typing import Annotated

from pydantic import AnyHttpUrl, BeforeValidator, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


def _parse_cors(v: str | list[str]) -> list[str]:
    if isinstance(v, str):
        return [origin.strip() for origin in v.split(",") if origin.strip()]
    return v


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    ENVIRONMENT: Environment = Environment.LOCAL
    PROJECT_NAME: str = "functional_test"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False

    SECRET_KEY: str = "test-secret-key-do-not-use-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    FIRST_SUPERUSER_EMAIL: str = "admin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = "changethis"

    FRONTEND_URL: str = "http://localhost:3000"
    # Empty REDIS_URL forces the rate limiter into in-memory mode
    # so the functional test doesn't require a running Redis instance.
    REDIS_URL: str = ""
    # Disable rate limiting entirely so back-to-back test calls don't 429.
    RATE_LIMITING_ENABLED: bool = False

    # Optional integration credentials — empty so integrations no-op cleanly.
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    SENDGRID_API_KEY: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str = ""
    ARQ_REDIS_URL: str = ""

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyHttpUrl],
        BeforeValidator(_parse_cors),
    ] = []

    # --- Database (SQLite for testing) ---
    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return "sqlite+aiosqlite://"

    # Alias so both settings.database_url and settings.SQLALCHEMY_DATABASE_URI work
    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return self.database_url

    # --- SMTP (disabled for tests) ---
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: str | None = None
    EMAILS_FROM_NAME: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)


settings = Settings()
''')

    # --- Patch core/db.py for SQLite (no pool_size/max_overflow) ---
    db_file = app_root / "core" / "db.py"
    db_file.write_text('''\
"""Async SQLAlchemy engine -- patched for SQLite (aiosqlite)."""

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

# SQLite does not support pool_size / max_overflow, so we omit them.
engine = create_async_engine(
    str(settings.database_url),
    echo=False,
)


# Enable WAL mode and foreign keys for SQLite
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def init_db() -> None:
    """Create all tables on startup."""
    from app.models.base import Base
    # Import models so they register with Base
    import app.models.user  # noqa: F401
    import app.models.item  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


__all__ = ["engine", "init_db"]
''')

    # NOTE: previous runtime patches for UserCreate password, get_current_superuser,
    # and deps.py UUID conversion are NO LONGER needed — those bugs are fixed at the
    # generator source. If they reappear, the audit will catch them.


# ---------------------------------------------------------------------------
# Phase 3: Import app, create client, seed superuser
# ---------------------------------------------------------------------------
def setup_app(tmp: Path):
    """Import the generated app and return a TestClient.

    With the new package layout, source code lives at tmp/app/ and is
    already a real Python package. We just need to add tmp to sys.path
    so `import app` resolves correctly. No symlinks needed.
    """
    # New layout: tmp/app/main.py — add tmp itself to path
    if str(tmp) not in sys.path:
        sys.path.insert(0, str(tmp))

    # Backward compat: if someone calls this with the old layout (no app/),
    # fall back to the symlink trick.
    if not (tmp / "app").exists():
        parent = tmp.parent
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        legacy_app_dir = parent / "app"
        if legacy_app_dir.exists() and legacy_app_dir.resolve() != tmp.resolve():
            shutil.rmtree(legacy_app_dir)
        if not legacy_app_dir.exists():
            legacy_app_dir.symlink_to(tmp)

    # Clear any cached 'app' modules
    for key in list(sys.modules.keys()):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]

    # Silence structlog before importing app (middleware uses structlog)
    import structlog
    structlog.configure(
        processors=[structlog.dev.ConsoleRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(50),
    )

    # Import the app
    from app.main import app  # type: ignore[import]
    from fastapi.testclient import TestClient

    client = TestClient(app)
    return client, app


def seed_superuser(tmp: Path) -> None:
    """Create a superuser directly in the database."""
    import asyncio

    async def _seed():
        # Import after app setup
        from app.core.db import engine, init_db  # type: ignore[import]
        from app.core.security import get_password_hash  # type: ignore[import]
        from app.models.user import User  # type: ignore[import]

        await init_db()

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            import uuid
            user = User(
                id=uuid.uuid4(),
                email=SUPERUSER_EMAIL,
                full_name="Admin User",
                hashed_password=get_password_hash(SUPERUSER_PASSWORD),
                is_active=True,
                is_superuser=True,
            )
            session.add(user)
            await session.commit()

    asyncio.run(_seed())


# ---------------------------------------------------------------------------
# Phase 4: Test functions
# ---------------------------------------------------------------------------
def login(client, email: str, password: str) -> tuple[int, dict]:
    """Perform login and return (status_code, response_json)."""
    t0 = time.perf_counter()
    r = client.post(
        f"{PREFIX}/login/access-token",
        data={"username": email, "password": password},
    )
    dt = (time.perf_counter() - t0) * 1000
    body = r.json()
    _all_responses.append(body)
    return r.status_code, body, dt


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def run_tests(client) -> None:
    """Execute all 25 test cases."""

    # ==================================================================
    # AUTH
    # ==================================================================
    section = "AUTH"

    # T01: Login with valid credentials
    code, body, dt = login(client, SUPERUSER_EMAIL, SUPERUSER_PASSWORD)
    admin_token = body.get("access_token", "")
    _record("T01", section, "Login with valid credentials",
            passed=(code == 200 and "access_token" in body),
            status_code=code, duration_ms=dt)

    # T02: Login with wrong password
    code, body, dt = login(client, SUPERUSER_EMAIL, "wrongpassword")
    _record("T02", section, "Login with wrong password",
            passed=(code == 401),
            status_code=code, duration_ms=dt)

    # T03: Login with non-existent user
    code, body, dt = login(client, "nobody@test.com", "any1234!")
    _record("T03", section, "Login with non-existent user",
            passed=(code == 401),
            status_code=code, duration_ms=dt)

    # T04: Test token (valid)
    t0 = time.perf_counter()
    r = client.post(f"{PREFIX}/login/test-token", headers=auth_header(admin_token))
    dt = (time.perf_counter() - t0) * 1000
    body = r.json()
    _all_responses.append(body)
    _record("T04", section, "Test token (valid token)",
            passed=(r.status_code == 200 and "email" in body),
            status_code=r.status_code, duration_ms=dt)

    # T05: Test token (no token)
    t0 = time.perf_counter()
    r = client.post(f"{PREFIX}/login/test-token")
    dt = (time.perf_counter() - t0) * 1000
    _all_responses.append(r.json())
    _record("T05", section, "Test token (no token)",
            passed=(r.status_code in (401, 403)),
            status_code=r.status_code, duration_ms=dt)

    # ==================================================================
    # USER SIGNUP
    # ==================================================================
    section = "USER SIGNUP"

    # T06: Signup valid user
    t0 = time.perf_counter()
    r = client.post(f"{PREFIX}/users/signup", json={
        "email": REGULAR_EMAIL,
        "full_name": "Regular User",
        "password": REGULAR_PASSWORD,
    })
    dt = (time.perf_counter() - t0) * 1000
    body = r.json()
    _all_responses.append(body)
    no_hash = "hashed_password" not in body
    _record("T06", section, "Signup valid user",
            passed=(r.status_code in (200, 201) and no_hash),
            status_code=r.status_code, duration_ms=dt,
            detail="" if no_hash else "LEAK: hashed_password in response!")

    # T07: Signup duplicate email
    t0 = time.perf_counter()
    r = client.post(f"{PREFIX}/users/signup", json={
        "email": REGULAR_EMAIL,
        "full_name": "Duplicate",
        "password": "Duplicate1234!",
    })
    dt = (time.perf_counter() - t0) * 1000
    _all_responses.append(r.json())
    _record("T07", section, "Signup duplicate email",
            passed=(r.status_code == 400),
            status_code=r.status_code, duration_ms=dt)

    # T08: Signup short password
    t0 = time.perf_counter()
    r = client.post(f"{PREFIX}/users/signup", json={
        "email": "short@test.com",
        "full_name": "Short Password",
        "password": "123",
    })
    dt = (time.perf_counter() - t0) * 1000
    _all_responses.append(r.json())
    _record("T08", section, "Signup short password",
            passed=(r.status_code == 422),
            status_code=r.status_code, duration_ms=dt)

    # ==================================================================
    # USER SELF-MANAGEMENT
    # ==================================================================
    section = "USER SELF-MGMT"

    # Login as regular user
    code, body, _ = login(client, REGULAR_EMAIL, REGULAR_PASSWORD)
    user_token = body.get("access_token", "")

    # T09: GET /users/me
    t0 = time.perf_counter()
    r = client.get(f"{PREFIX}/users/me", headers=auth_header(user_token))
    dt = (time.perf_counter() - t0) * 1000
    body = r.json()
    _all_responses.append(body)
    _record("T09", section, "GET /users/me",
            passed=(r.status_code == 200 and body.get("email") == REGULAR_EMAIL),
            status_code=r.status_code, duration_ms=dt)

    # T10: PATCH /users/me (update name)
    t0 = time.perf_counter()
    r = client.patch(f"{PREFIX}/users/me",
                     headers=auth_header(user_token),
                     json={"full_name": "Updated Name"})
    dt = (time.perf_counter() - t0) * 1000
    body = r.json()
    _all_responses.append(body)
    _record("T10", section, "PATCH /users/me (update name)",
            passed=(r.status_code == 200 and body.get("full_name") == "Updated Name"),
            status_code=r.status_code, duration_ms=dt)

    # T11: PATCH /users/me/password (valid change)
    t0 = time.perf_counter()
    r = client.patch(f"{PREFIX}/users/me/password",
                     headers=auth_header(user_token),
                     json={"current_password": REGULAR_PASSWORD, "new_password": "NewPass1234!"})
    dt = (time.perf_counter() - t0) * 1000
    body = r.json()
    _all_responses.append(body)
    _record("T11", section, "PATCH /users/me/password (valid)",
            passed=(r.status_code == 200),
            status_code=r.status_code, duration_ms=dt)

    # T12: PATCH /users/me/password (wrong current)
    t0 = time.perf_counter()
    r = client.patch(f"{PREFIX}/users/me/password",
                     headers=auth_header(user_token),
                     json={"current_password": "wrongpassword", "new_password": "Another1234!"})
    dt = (time.perf_counter() - t0) * 1000
    _all_responses.append(r.json())
    _record("T12", section, "PATCH /users/me/password (wrong current)",
            passed=(r.status_code in (400, 403)),
            status_code=r.status_code, duration_ms=dt)

    # ==================================================================
    # SUPERUSER
    # ==================================================================
    section = "SUPERUSER"

    # T13: GET /users/ (as superuser) -> list
    t0 = time.perf_counter()
    r = client.get(f"{PREFIX}/users/", headers=auth_header(admin_token))
    dt = (time.perf_counter() - t0) * 1000
    body = r.json()
    _all_responses.append(body)
    _record("T13", section, "GET /users/ (as superuser)",
            passed=(r.status_code == 200 and "data" in body and "count" in body),
            status_code=r.status_code, duration_ms=dt)

    # T14: GET /users/ (as regular user) -> 403
    # Re-login with new password
    code, body, _ = login(client, REGULAR_EMAIL, "NewPass1234!")
    user_token2 = body.get("access_token", "")

    t0 = time.perf_counter()
    r = client.get(f"{PREFIX}/users/", headers=auth_header(user_token2))
    dt = (time.perf_counter() - t0) * 1000
    _all_responses.append(r.json())
    _record("T14", section, "GET /users/ (as regular user)",
            passed=(r.status_code == 403),
            status_code=r.status_code, duration_ms=dt)

    # T15: GET /users/{id} (superuser fetches specific user)
    # First get user ID from /users/ list
    users_body = client.get(f"{PREFIX}/users/", headers=auth_header(admin_token)).json()
    # Find the regular user
    regular_user_id = None
    for u in users_body.get("data", []):
        if u.get("email") == REGULAR_EMAIL:
            regular_user_id = u["id"]
            break

    t0 = time.perf_counter()
    if regular_user_id:
        r = client.get(f"{PREFIX}/users/{regular_user_id}", headers=auth_header(admin_token))
    else:
        # Fallback: just try with any UUID
        r = client.get(f"{PREFIX}/users/00000000-0000-0000-0000-000000000000",
                       headers=auth_header(admin_token))
    dt = (time.perf_counter() - t0) * 1000
    _all_responses.append(r.json())
    _record("T15", section, "GET /users/{id} (superuser)",
            passed=(r.status_code == 200 and regular_user_id is not None),
            status_code=r.status_code, duration_ms=dt)

    # ==================================================================
    # ITEMS
    # ==================================================================
    section = "ITEMS"

    # T16: POST /items/ (create item)
    t0 = time.perf_counter()
    r = client.post(f"{PREFIX}/items/", headers=auth_header(admin_token),
                    json={"title": "Test Item", "description": "A test item"})
    dt = (time.perf_counter() - t0) * 1000
    body = r.json()
    _all_responses.append(body)
    item_id = body.get("id")
    _record("T16", section, "POST /items/ (create item)",
            passed=(r.status_code in (200, 201) and item_id is not None),
            status_code=r.status_code, duration_ms=dt)

    # T17: GET /items/ (list items)
    t0 = time.perf_counter()
    r = client.get(f"{PREFIX}/items/", headers=auth_header(admin_token))
    dt = (time.perf_counter() - t0) * 1000
    body = r.json()
    _all_responses.append(body)
    _record("T17", section, "GET /items/ (list own items)",
            passed=(r.status_code == 200 and "data" in body and "count" in body),
            status_code=r.status_code, duration_ms=dt)

    # T18: GET /items/{id}
    t0 = time.perf_counter()
    if item_id:
        r = client.get(f"{PREFIX}/items/{item_id}", headers=auth_header(admin_token))
    else:
        r = client.get(f"{PREFIX}/items/00000000-0000-0000-0000-000000000000",
                       headers=auth_header(admin_token))
    dt = (time.perf_counter() - t0) * 1000
    body = r.json()
    _all_responses.append(body)
    _record("T18", section, "GET /items/{id}",
            passed=(r.status_code == 200 and item_id is not None),
            status_code=r.status_code, duration_ms=dt)

    # T19: PATCH /items/{id} (partial update — was PUT, fixed to PATCH per REST semantics)
    t0 = time.perf_counter()
    if item_id:
        r = client.patch(f"{PREFIX}/items/{item_id}", headers=auth_header(admin_token),
                         json={"title": "Updated Item"})
    else:
        r = client.patch(f"{PREFIX}/items/00000000-0000-0000-0000-000000000000",
                         headers=auth_header(admin_token),
                         json={"title": "Updated Item"})
    dt = (time.perf_counter() - t0) * 1000
    body = r.json()
    _all_responses.append(body)
    _record("T19", section, "PATCH /items/{id} (update)",
            passed=(r.status_code == 200 and body.get("title") == "Updated Item"),
            status_code=r.status_code, duration_ms=dt)

    # T20: DELETE /items/{id}
    t0 = time.perf_counter()
    if item_id:
        r = client.delete(f"{PREFIX}/items/{item_id}", headers=auth_header(admin_token))
    else:
        r = client.delete(f"{PREFIX}/items/00000000-0000-0000-0000-000000000000",
                          headers=auth_header(admin_token))
    dt = (time.perf_counter() - t0) * 1000
    body = r.json()
    _all_responses.append(body)
    _record("T20", section, "DELETE /items/{id}",
            passed=(r.status_code == 200),
            status_code=r.status_code, duration_ms=dt)

    # ==================================================================
    # SECURITY
    # ==================================================================
    section = "SECURITY"

    # T21: hashed_password NEVER in any response
    leaked = False
    for resp in _all_responses:
        resp_str = json.dumps(resp)
        if "hashed_password" in resp_str:
            leaked = True
            break
    _record("T21", section, "hashed_password never in responses",
            passed=(not leaked),
            detail="VERIFIED" if not leaked else "LEAK DETECTED")

    # T22: Password recovery (existing email)
    t0 = time.perf_counter()
    r = client.post(f"{PREFIX}/password-recovery/{SUPERUSER_EMAIL}")
    dt = (time.perf_counter() - t0) * 1000
    body22 = r.json()
    _all_responses.append(body22)
    _record("T22", section, "Password recovery (existing email)",
            passed=(r.status_code == 200),
            status_code=r.status_code, duration_ms=dt,
            detail=body22.get("message", ""))

    # T23: Password recovery (non-existing email) -> same message
    t0 = time.perf_counter()
    r = client.post(f"{PREFIX}/password-recovery/nonexistent@test.com")
    dt = (time.perf_counter() - t0) * 1000
    body23 = r.json()
    _all_responses.append(body23)
    same_msg = body22.get("message") == body23.get("message")
    _record("T23", section, "Password recovery (non-existing email)",
            passed=(r.status_code == 200 and same_msg),
            status_code=r.status_code, duration_ms=dt,
            detail=("ENUMERATION SAFE" if same_msg else
                    f"VULNERABLE: messages differ: '{body22.get('message')}' vs '{body23.get('message')}'"))

    # ==================================================================
    # HEALTH
    # ==================================================================
    section = "HEALTH"

    # T24: GET /healthz — at ROOT (K8s convention), NOT under /api/v1
    t0 = time.perf_counter()
    r = client.get("/healthz")
    dt = (time.perf_counter() - t0) * 1000
    _record("T24", section, "GET /healthz (root)",
            passed=(r.status_code == 200),
            status_code=r.status_code, duration_ms=dt)

    # T25: GET /readyz — at ROOT (K8s convention)
    t0 = time.perf_counter()
    r = client.get("/readyz")
    dt = (time.perf_counter() - t0) * 1000
    _record("T25", section, "GET /readyz (root)",
            passed=(r.status_code in (200, 503)),
            status_code=r.status_code, duration_ms=dt)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def print_results(total_files: int) -> int:
    """Print results in professional format and return exit code."""
    print()
    print("\u2554" + "\u2550" * 62 + "\u2557")
    print("\u2551      SKILL-001 v3 -- FUNCTIONAL PROOF (E2E Test Suite)       \u2551")
    print("\u255a" + "\u2550" * 62 + "\u255d")
    print()

    current_section = ""
    passed_count = 0
    total_count = len(_results)

    for r in _results:
        if r["section"] != current_section:
            current_section = r["section"]
            print(f"  {current_section}")

        icon = "\u2705" if r["passed"] else "\u274c"
        status = ""
        if r["status_code"] is not None:
            status = f"{r['status_code']:>5d}"
        elif r["detail"]:
            status = r["detail"]

        duration = f"{r['duration_ms']:>6.0f}ms" if r["duration_ms"] > 0 else ""

        # Format: icon T01: Description              status  duration
        desc = f"{r['test_id']}: {r['description']}"
        line = f"  {icon} {desc:<45s} {status:>7s} {duration}"
        if r["detail"] and r["status_code"] is not None:
            line += f"  {r['detail']}"
        print(line)

        if r["passed"]:
            passed_count += 1

    print()
    print("  " + "\u2500" * 55)
    all_pass = passed_count == total_count
    result_text = "PASSED" if all_pass else "FAILED"
    print(f"  RESULT: {passed_count}/{total_count} {result_text}")
    print(f"  Generated project: {total_files} files")
    print(f"  All endpoints functional: {'YES' if all_pass else 'NO'}")
    print("  " + "\u2500" * 55)
    print()

    if not all_pass:
        print("  FAILURES:")
        for r in _results:
            if not r["passed"]:
                print(f"    {r['test_id']}: {r['description']}")
                if r["detail"]:
                    print(f"      Detail: {r['detail']}")
        print()

    return 0 if all_pass else 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="skill001_func_"))
    print(f"\n  Working directory: {tmp}")

    try:
        # Phase 1: Generate
        print("  [1/4] Generating project...")
        result = generate(tmp)
        total_files = result["total_files"]
        print(f"         Generated {total_files} files")

        # Phase 2: Patch for SQLite
        print("  [2/4] Patching for SQLite (aiosqlite)...")
        patch_for_sqlite(tmp)

        # Phase 3: Setup app + seed
        print("  [3/4] Booting FastAPI app + seeding superuser...")
        client, app = setup_app(tmp)
        seed_superuser(tmp)

        # Phase 4: Run tests
        print("  [4/4] Running 25 E2E tests...")
        run_tests(client)

        return print_results(total_files)

    except Exception as e:
        print(f"\n  FATAL ERROR: {e}")
        traceback.print_exc()
        return 1
    finally:
        # Cleanup: remove symlink but keep tmp for debugging on failure
        app_link = tmp.parent / "app"
        if app_link.is_symlink():
            app_link.unlink()

        # Clean up sys.modules
        for key in list(sys.modules.keys()):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]

        # Only remove tmp on success
        if _results and all(r["passed"] for r in _results):
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"  Project kept for inspection: {tmp}")


if __name__ == "__main__":
    sys.exit(main())
