# TOOL-056: add_sqladmin

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_sqladmin` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Source LOC | 785 |
| Dependencies | FastAPI, SQLAlchemy 2.0, `sqladmin>=0.19.0`, `itsdangerous>=2.2.0` (both lazy-loaded at runtime), existing `app.core.security.verify_password`, existing `app.core.jwt.verify_access_token`, existing `User` model with `hashed_password` and `is_superuser` fields, existing `app.core.db.engine`, existing `app.core.config.settings` |
| Signature | `add_sqladmin(inp: ToolInput, *, admin_path: str = "/admin", admin_title: str = "Admin Panel", require_superuser: bool = True) -> ToolResult` |
| Parameters | `inp`: `ToolInput` containing `project_dir` (absolute FastAPI project root) and `dry_run` flag<br>`admin_path`: URL path where the admin panel is mounted — maps to `settings.ADMIN_PATH` (default: `"/admin"`)<br>`admin_title`: Title rendered in the admin panel header — maps to `settings.ADMIN_TITLE` (default: `"Admin Panel"`)<br>`require_superuser`: Whether only users with `is_superuser=True` can authenticate — maps to `settings.ADMIN_REQUIRE_SUPERUSER` (default: `True`) |
| Files created | `app/admin/__init__.py`, `app/admin/setup.py`, `app/admin/auth.py`, `app/admin/views.py` |
| Files modified | `app/core/config.py`, `app/main.py`, `requirements.txt`, `.env.example` |
| Idempotency | Detects `setup_admin` in `app/admin/setup.py` and returns `status="no_op"` without touching any file |

## 2. Purpose

Every serious FastAPI deployment eventually hits the same wall: operations, support, finance, and compliance all need to **look at and edit production data** without filing a developer ticket. Support wants to reset a password. Finance wants to refund a subscription. Compliance wants to redact a user on GDPR request. An on-call engineer wants to flip a feature flag at 03:00. The "correct" answer is always "build an internal tool" — but building an internal React dashboard for every entity in your schema is a **multi-month project** that rots on contact with schema change, has its own auth, its own audit trail, its own paging logic, its own test suite, and its own deploy cadence. Teams either drag a freelancer in for three weeks, open a psql tunnel to production (auditors hate this), or give support staff a broad read-write role on the primary database (auditors hate this more). Meanwhile, their engineers burn cycles on CRUD screens instead of shipping product.

The `fastapi_add_sqladmin` tool solves this by dropping **SQLAdmin** — the de facto admin panel for SQLAlchemy — into an existing FastAPI project in under 5 seconds. SQLAdmin is the right choice here for four structural reasons: (1) it **reads the existing SQLAlchemy metadata**, so no new models, no migrations, no schema churn; (2) it auto-generates list / detail / create / edit / delete views for every model with search, sort, and pagination already wired; (3) its authentication is pluggable, so it **reuses the existing JWT + `verify_password` scaffold** instead of introducing a second auth system; and (4) it is a **Starlette-native mount**, so it composes with FastAPI middleware, dependency injection, and OpenTelemetry instrumentation that already exist in the project. The alternative — Flask-Admin, Django-admin, Retool, Forest Admin, hand-rolled React — costs 10x to 1000x more and multiplies the surface area auditors have to review.

The tool generates a production-grade integration that is **safe by default**: (a) the `AdminAuthBackend` delegates login to the existing `verify_password` helper and the existing `User` model, so there is exactly one source of truth for credentials; (b) access is gated behind `is_superuser=True` via the `require_superuser=True` default — a support agent without the flag cannot reach `/admin` even if they know the URL; (c) **sensitive columns** (`hashed_password`, `secret_enc`, `entry_hash`, `prev_hash`) are excluded from list views so they do not appear in screenshots, screen-recordings, or over-the-shoulder lookups; (d) `can_delete = False` is set on the `User` ModelView to prevent "click the wrong row and nuke the customer" incidents; (e) no secrets are logged — `settings.SECRET_KEY` is read via `getattr` but never echoed to stdout. Every generated function is kept under 50 LOC (enforced by AST walking in the tool's self-verification step), which keeps the surface small enough for a security reviewer to read the entire admin package in one sitting.

The **single most important design decision** in this tool — and the one that distinguishes it from a naive "just import sqladmin and call it" implementation — is the **lazy `SessionMiddleware` import inside `setup_admin()`**. SQLAdmin requires Starlette's `SessionMiddleware` (backed by `itsdangerous`) for its cookie-based login flow. A naive implementation would add `from starlette.middleware.sessions import SessionMiddleware` at the top of `app/main.py`. This was the first implementation, and it **broke the application boot** on environments where `itsdangerous` was not installed (CI runners, health-check images, local laptops that had not yet run `pip install -r requirements.txt`). The fix is to move the `SessionMiddleware` import **inside** `setup_admin()`, wrapped in `try/except ImportError` — the application imports `app.main`, calls `setup_admin(app)`, the inner import fails gracefully, a warning is logged, and the app continues booting without an admin panel. This matches the equally-lazy `from sqladmin import Admin` import at the top of `setup_admin()`: **both hard dependencies are loaded at call time, never at import time**, so the app always boots whether the admin package is installed or not. This is the pattern this spec enforces, and it is the pattern every test in `test_add_sqladmin.py` verifies.

The tool is also **idempotent**: a second invocation detects `setup_admin` in `app/admin/setup.py` and returns `status="no_op"` with zero file writes. This matters for CI pipelines that re-run `fastapi_add_*` tools on every commit — the second run is a no-op, not a crash. It is also safe under `dry_run=True`: the tool returns `status="success"` with a preview of what would be written, but touches nothing on disk.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5s | Must complete during deployment without extending downtime window |
| Files created | = 4 | `__init__.py`, `setup.py`, `auth.py`, `views.py` — complete and minimal |
| Files modified | ≥ 2 | `config.py` + `main.py` at minimum; `requirements.txt` and `.env.example` when present |
| Max function LOC (generated) | ≤ 50 | Enforced by AST walking — every helper must fit on one screen for review |
| Admin panel boot overhead | < 100 ms | Single `Admin(app, engine, ...)` call + view registration |
| App boot without `sqladmin` installed | Successful | Lazy import at call time guarantees graceful degradation |
| App boot without `itsdangerous` installed | Successful | Lazy `SessionMiddleware` import inside `setup_admin()` |
| Migration runtime | 0s | No schema changes — SQLAdmin reads existing SQLAlchemy metadata |
| Idempotent re-run | < 50 ms | Single file stat + substring check; returns `no_op` before any write |
| Admin login latency | < 200 ms | Single `SELECT` on `users` by email + one `verify_password` call |
| Model list view first paint | < 500 ms | SQLAdmin query is `SELECT ... LIMIT 25` with server-side pagination |

---

## 4. Code Examples (Before / After)

### 4.1 `app/main.py`: BEFORE

```python
# app/main.py
from fastapi import FastAPI

from app.api.main import api_router
from app.core.config import settings
from app.core.middleware import register_middleware


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

register_middleware(app, settings)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

Nothing admin-aware. The app boots, serves the API, and passes health checks — but operations staff have no UI.

### 4.2 `app/main.py`: AFTER

```python
# app/main.py
from fastapi import FastAPI

from app.admin.setup import setup_admin
from app.api.main import api_router
from app.core.config import settings
from app.core.middleware import register_middleware


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

register_middleware(app, settings)

# --- SQLAdmin panel ---
setup_admin(app)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

**Only two lines added**: the import (`from app.admin.setup import setup_admin`) and the call (`setup_admin(app)`) — both placed immediately after the existing `register_middleware(app, settings)` anchor. Crucially, **there is no `SessionMiddleware` import at the top of this file**. That would be the first instinct of a developer adding SQLAdmin by hand, and it would break the boot on machines that have not yet run `pip install itsdangerous`. Instead, `SessionMiddleware` is imported lazily inside `setup_admin()` — see §4.4 below.

### 4.3 `app/admin/__init__.py` (NEW)

```python
"""SQLAdmin admin panel package.

Provides a production-grade admin panel mounted on the FastAPI app.
Auto-discovers SQLAlchemy models and generates CRUD views with
authentication gated on superuser status.

Usage::

    from app.admin.setup import setup_admin
    setup_admin(app)
"""
```

Minimal package marker with usage docstring. Intentionally empty of code: the public entry point is `app.admin.setup:setup_admin`, and consumers are told to import it directly.

### 4.4 `app/admin/setup.py` (NEW) — THE LAZY IMPORT PATTERN

```python
"""SQLAdmin admin panel configuration.

Mounts the admin panel on the FastAPI app.  Auto-registers
ModelAdmin classes for every model discovered in app/models/.

Call ``setup_admin(app)`` from the main module after app creation.
The ``sqladmin`` package is imported lazily so the application boots
cleanly even when sqladmin is not installed.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

from app.core.config import settings

logger = logging.getLogger(__name__)


def setup_admin(app: "FastAPI") -> None:
    """Mount the SQLAdmin panel on *app*.

    Imports ``sqladmin`` lazily so the application can boot (and pass
    health checks) without the package installed.  When the import
    fails a warning is logged and the function returns without
    mounting anything.

    Args:
        app: The FastAPI application instance.
    """
    try:
        from sqladmin import Admin
    except ImportError:
        logger.warning(
            "sqladmin not installed — admin panel disabled. "
            "Install with: pip install sqladmin"
        )
        return

    from app.admin.auth import AdminAuthBackend
    from app.admin.views import MODEL_ADMINS
    from app.core.db import engine

    # SessionMiddleware is required by SQLAdmin for cookie-based auth.
    # Added here (not at top of main.py) so the app boots without
    # itsdangerous installed.
    try:
        from starlette.middleware.sessions import SessionMiddleware
        app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
    except ImportError:
        logger.warning("itsdangerous not installed — admin auth disabled")

    path = getattr(settings, "ADMIN_PATH", "/admin")
    title = getattr(settings, "ADMIN_TITLE", "Admin Panel")

    auth_backend = AdminAuthBackend(secret_key=settings.SECRET_KEY)
    admin = Admin(
        app,
        engine,
        base_url=path,
        title=title,
        authentication_backend=auth_backend,
    )
    for view_cls in MODEL_ADMINS:
        admin.add_view(view_cls)
    logger.info("SQLAdmin panel mounted at %s", path)
```

Four things deserve special attention:

1. **`from sqladmin import Admin` is inside the function body.** If `sqladmin` is not installed, `ImportError` is caught, a warning is logged, and the function **returns without mounting anything**. The app keeps booting. `/health` keeps passing. Only `/admin` is missing. This is the contract test `test_lazy_sqladmin_import` enforces.
2. **`from starlette.middleware.sessions import SessionMiddleware` is ALSO inside the function body.** This is the real-bug fix. Starlette's `SessionMiddleware` depends on `itsdangerous` for cookie signing, and `itsdangerous` is not part of the FastAPI or Starlette default installation. Putting the import at the top of `setup.py` (or worse, at the top of `main.py`) turns a missing optional dependency into a **boot failure**. The lazy guard turns it into a warning log + a degraded admin panel. `test_session_middleware_in_setup` enforces that the import lives here and nowhere else.
3. **`path` and `title` use `getattr(settings, "ADMIN_PATH", "/admin")`.** This is defensive: if `_patch_config` did not run (for example, the project had no `app/core/config.py` to patch, so the step was skipped), the admin still mounts with sane defaults. Never raise `AttributeError` on boot.
4. **`auth_backend = AdminAuthBackend(secret_key=settings.SECRET_KEY)`.** The secret key is read from settings and **passed as a constructor argument to the auth backend**, never printed, never logged, never echoed. The backend forwards it to the Starlette `AuthenticationBackend` parent class.

### 4.5 `app/admin/auth.py` (NEW) — REUSE EXISTING AUTH SCAFFOLD

```python
"""SQLAdmin authentication backend — restricts /admin to superusers.

Uses the existing JWT verification from ``app.core.jwt`` and password
verification from ``app.core.security``.  Login page is a simple form
that validates email + password against the User model.

Session tokens are stored via Starlette's ``SessionMiddleware``
(backed by ``itsdangerous``).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

logger = logging.getLogger(__name__)


try:
    from sqladmin.authentication import AuthenticationBackend as _Base
except ImportError:
    # Provide a dummy base so the module can be imported for type
    # checking even when sqladmin is not installed.
    class _Base:  # type: ignore[no-redef]
        def __init__(self, secret_key: str) -> None:
            pass


class AdminAuthBackend(_Base):
    """Cookie-based auth backend for the SQLAdmin panel.

    Authenticates users via email + password using the existing
    scaffold helpers and stores a minimal session token.
    """

    async def login(self, request: "Request") -> bool:
        """Validate login form and create an admin session.

        Args:
            request: The Starlette request with form data containing
                ``username`` (email) and ``password`` fields.

        Returns:
            ``True`` if authentication succeeded, ``False`` otherwise.
        """
        from app.core.db import engine
        from app.core.security import verify_password
        from app.models.user import User
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        form = await request.form()
        email = form.get("username", "")
        password = form.get("password", "")
        if not email or not password:
            return False

        async with AsyncSession(engine) as session:
            stmt = select(User).where(User.email == str(email))
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

        if user is None:
            return False
        if not verify_password(str(password), user.hashed_password):
            return False

        require_superuser = True  # value injected by tool template
        if require_superuser and not getattr(user, "is_superuser", False):
            logger.warning(
                "Admin login denied for non-superuser: %s",
                str(email),
            )
            return False

        request.session["admin_user_id"] = str(user.id)
        request.session["admin_email"] = str(user.email)
        return True

    async def logout(self, request: "Request") -> bool:
        """Clear the admin session."""
        request.session.clear()
        return True

    async def authenticate(self, request: "Request") -> bool:
        """Check whether the current session is authenticated."""
        user_id = request.session.get("admin_user_id")
        if not user_id:
            return False
        return True
```

Four security-critical properties:

1. **`from sqladmin.authentication import AuthenticationBackend as _Base` is wrapped in `try/except ImportError`** with a fallback dummy class. This lets `mypy`, `pyright`, and `pytest --collect-only` import `app.admin.auth` without SQLAdmin installed, so type-checking and test collection run in CI without the extra dependency.
2. **`verify_password(str(password), user.hashed_password)`** reuses the existing scaffold helper — there is no second password hash function, no second bcrypt configuration, no drift between "API login" and "admin login". If you rotate your password hash algorithm tomorrow, both paths move together.
3. **`require_superuser = True` gate.** Even if an attacker knows a valid user email + password, they cannot reach `/admin` without the `is_superuser` flag. `getattr(user, "is_superuser", False)` defaults to `False` if the field does not exist — fail-closed, never fail-open. The denied login is logged with the email (not the password) at WARNING level so downstream SIEM rules can fire on brute-force attempts.
4. **`request.session["admin_user_id"] = str(user.id)`.** Only the user ID and email are stored in the session cookie — **never** the password, the hash, or the JWT. The cookie is signed by Starlette's `SessionMiddleware` using `settings.SECRET_KEY`, which is the same key the rest of the app uses for token signing.

### 4.6 `app/admin/views.py` (NEW) — AUTO-GENERATED FROM MODELS

```python
"""Auto-generated ModelAdmin classes for the SQLAdmin panel.

Each model discovered in ``app/models/__init__.py`` gets a
``ModelAdmin`` subclass with auto-detected columns for list view,
search, and sort.  Sensitive columns are excluded from the list
view and ``can_delete = False`` is set for the User model.

The ``MODEL_ADMINS`` list at the bottom collects all view classes
for registration by ``setup_admin()``.
"""
from __future__ import annotations

try:
    from sqladmin import ModelAdmin
except ImportError:
    # Provide a dummy base so this module can be imported for type
    # checking even when sqladmin is not installed.
    class ModelAdmin:  # type: ignore[no-redef]
        def __init_subclass__(cls, **kwargs: object) -> None:
            super().__init_subclass__()

from app.models.item import Item
from app.models.user import User


class ItemAdmin(ModelAdmin, model=Item):
    """Admin view for the Item model."""

    # Sensitive columns excluded from list view
    column_exclude_list = [
        "hashed_password", "secret_enc", "entry_hash", "prev_hash",
    ]
    column_sortable_list = "__all__"
    can_delete = True
    name = "Item"
    name_plural = "Items"
    icon = "fa-solid fa-database"


class UserAdmin(ModelAdmin, model=User):
    """Admin view for the User model."""

    # Sensitive columns excluded from list view
    column_exclude_list = [
        "hashed_password", "secret_enc", "entry_hash", "prev_hash",
    ]
    column_sortable_list = "__all__"
    can_delete = False
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user"


MODEL_ADMINS: list[type] = [ItemAdmin, UserAdmin]
```

Note the generator behaviour verified by `_discover_models` and `_build_single_view`:

- **`column_exclude_list`** is applied to **every** ModelAdmin (not just `User`) because a sensitive column could appear on any table — audit log entries, recovery secrets, MFA shared secrets. Belt and braces.
- **`can_delete = False` is set only on the `User` admin**, because "support accidentally deleted a customer" is an industry-wide trauma. All other models default to `can_delete = True`.
- **`icon = "fa-solid fa-user"` for `User`, `fa-solid fa-database"` for everything else.** Cosmetic, but nudges the reviewer toward the right mental model.
- **`MODEL_ADMINS: list[type]`** is the registration list `setup_admin()` iterates over. It is generated from `_build_views_content()` using `", ".join(f"{name}Admin" for name in model_names)`.

### 4.7 `app/core/config.py` patch

```python
# BEFORE
class Settings(BaseSettings):
    PROJECT_NAME: str = "MyApp"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # ...

settings = Settings()
```

```python
# AFTER
class Settings(BaseSettings):
    PROJECT_NAME: str = "MyApp"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- Admin panel — added by add_sqladmin tool ---
    ADMIN_PATH: str = "/admin"
    ADMIN_TITLE: str = "Admin Panel"
    ADMIN_REQUIRE_SUPERUSER: bool = True
    # ...

settings = Settings()
```

The patch is **anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`** — the canonical anchor used by every other `extend/` tool. This guarantees the new fields land **inside** the `class Settings` body (4-space indent), so `pydantic-settings` picks them up from env vars. If the anchor is missing, the tool falls back to inserting above `settings = Settings()`. If that is also missing, the tool appends to the file tail. `test_config_fields_patched` verifies the 4-space indentation.

### 4.8 `requirements.txt` patch

```
# BEFORE
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
sqlalchemy>=2.0.0
pydantic>=2.6.0
pydantic-settings>=2.2.0
passlib[bcrypt]>=1.7.4
```

```
# AFTER
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
sqlalchemy>=2.0.0
pydantic>=2.6.0
pydantic-settings>=2.2.0
passlib[bcrypt]>=1.7.4
sqladmin>=0.19.0
itsdangerous>=2.2.0
```

Both deps appended at the tail. Idempotent — if either line is already present, the append is skipped for that line only. `test_requirements_sqladmin` verifies both lines are present after a single run.

### 4.9 `.env.example` patch

```
# BEFORE
SECRET_KEY=change-me
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

```
# AFTER
SECRET_KEY=change-me
ACCESS_TOKEN_EXPIRE_MINUTES=30

# --- SQLAdmin panel (add_sqladmin) ---
# ADMIN_PATH=/admin
# ADMIN_TITLE=Admin Panel
# ADMIN_REQUIRE_SUPERUSER=true
```

The env vars are **commented out by default**. The tool's intent is documentation, not override: production deployments should set `ADMIN_PATH` and `ADMIN_REQUIRE_SUPERUSER` in their secret manager, not in `.env.example`. The leading `#` makes this visible to any developer reading the file.

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **`sqladmin` import is lazy** — always inside `setup_admin()`, never at module top | `_ADMIN_SETUP_TEMPLATE` places `from sqladmin import Admin` inside function body; `test_lazy_sqladmin_import` greps for `try:` + `ImportError` + `from sqladmin` inside `setup.py` |
| QS-2 | **`SessionMiddleware` import is lazy** — always inside `setup_admin()`, never at module top | `_ADMIN_SETUP_TEMPLATE` places `from starlette.middleware.sessions import SessionMiddleware` inside an inner `try/except`; `test_session_middleware_in_setup` verifies `SessionMiddleware` appears in `setup.py` (not in `main.py`) |
| QS-3 | **Admin routes require superuser when `require_superuser=True`** | `AdminAuthBackend.login` checks `getattr(user, "is_superuser", False)` and returns `False` if the flag is absent |
| QS-4 | **Sensitive columns excluded from list views** | `_ADMIN_VIEW_CLASS_TEMPLATE` emits `column_exclude_list = ["hashed_password", "secret_enc", "entry_hash", "prev_hash"]` for every model; `test_sensitive_columns_excluded` verifies |
| QS-5 | **User model is non-deletable from admin** | `_build_single_view` sets `can_delete = False` for `name == "User"`; other models get `can_delete = True` |
| QS-6 | **All generated Python files AST-parse clean** | `_assert_parses` walks every file in `files_created` and raises `SyntaxError` with source location on failure; `test_all_py_parse` runs `ast.parse` across the whole fixture after execution |
| QS-7 | **No generated function exceeds 50 LOC** | `test_no_function_over_50_loc` walks every `FunctionDef` / `AsyncFunctionDef` in `app/` and asserts `end_lineno - lineno + 1 <= 50` |
| QS-8 | **Idempotency — second run is a no-op** | `add_sqladmin` checks `"setup_admin" in setup_file.read_text()` before any work and returns `status="no_op"` with empty `files_created` and `files_modified`; `test_idempotent` verifies |
| QS-9 | **Secrets never logged** | `settings.SECRET_KEY` is read only as a constructor argument to `AdminAuthBackend(secret_key=...)` and `SessionMiddleware(..., secret_key=...)` — never interpolated into a log call |
| QS-10 | **Admin panel auth denied is logged at WARNING** | `AdminAuthBackend.login` calls `logger.warning("Admin login denied for non-superuser: %s", str(email))` — email visible, password never |
| QS-11 | **`dry_run=True` writes nothing** | `add_sqladmin` returns `status="success"` with preview notes but exits before any `.write_text()`; `test_dry_run` hashes every file before and after |
| QS-12 | **Config patch places fields inside `Settings` class body** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` and prepends the block with 4-space indent; `test_config_fields_patched` verifies indent |
| QS-13 | **Tool is non-destructive under partial prerequisites** | Missing `app/core/config.py`, `app/main.py`, `requirements.txt`, or `.env.example` cause the respective patch step to be **skipped silently** — the core `app/admin/` package is still created |
| QS-14 | **Dummy base classes provided for type-checking without sqladmin** | `_ADMIN_VIEWS_HEADER` and `_ADMIN_AUTH_TEMPLATE` both define a `class ModelAdmin` / `class _Base` fallback so `mypy` / `pyright` / `pytest --collect-only` run without `sqladmin` installed |
| QS-15 | **Model discovery is defensive** | `_discover_models` catches `SyntaxError` on `app/models/__init__.py` parse and falls back to `["User"]`; returns `["User"]` when no matches are found |

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh fixture project | `ToolResult.status == "success"` | `test_success_status` |
| CC-02 | Tool is idempotent: second run returns `status="no_op"` with empty `files_created` and `files_modified` | Run tool twice, assert second result `status="no_op"`, `files_created == []`, `files_modified == []` | `test_idempotent` |
| CC-03 | `dry_run=True` returns `status="success"` but writes no files | Snapshot all `.py` files before, run with `dry_run=True`, snapshot after, assert equal | `test_dry_run` |
| CC-04 | Tool creates at least 4 new files | `len(result.files_created) >= 4` and every path exists on disk | `test_files_created_count` |
| CC-05 | Tool modifies at least 2 files | `len(result.files_modified) >= 2` and every path exists on disk | `test_files_modified_count` |
| CC-06 | Every generated `.py` file AST-parses clean | `ast.parse(file.read_text())` on every `.py` under project root | `test_all_py_parse` |
| CC-07 | No function in generated `app/` exceeds 50 LOC | Walk every `FunctionDef` / `AsyncFunctionDef`, assert `end_lineno - lineno + 1 <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `ADMIN_PATH`, `ADMIN_TITLE`, `ADMIN_REQUIRE_SUPERUSER` exist inside the `Settings` class body in `app/core/config.py` with 4-space indentation | Read `config.py`, grep for each field, verify line starts with `"    "` | `test_config_fields_patched` |
| CC-09 | `app/admin/__init__.py` is created | `Path` exists | `test_models_init_patched` |
| CC-10 | `setup_admin` is referenced in `app/main.py` | `"setup_admin" in main.py.read_text()` | `test_routes_registered` |
| CC-11 | `app/admin/setup.py` exists with `setup_admin` function defined | File exists, content contains `setup_admin` | `test_setup_module_created` |
| CC-12 | `app/admin/auth.py` exists with `AdminAuthBackend`, `async def login`, `async def authenticate` | File exists, content contains all three identifiers | `test_auth_backend_created` |
| CC-13 | `app/admin/views.py` exists with `MODEL_ADMINS` list and at least 2 `ModelAdmin` subclasses | File exists; `content.count("Admin(ModelAdmin") >= 2` | `test_views_model_admins` |
| CC-14 | `setup.py` uses `try:` / `ImportError` for `sqladmin` import | Content contains `try:` AND `ImportError` AND `from sqladmin` | `test_lazy_sqladmin_import` |
| CC-15 | `SessionMiddleware` is referenced inside `setup.py` (NOT in `main.py` top-level) | `"SessionMiddleware" in setup.py.read_text()` | `test_session_middleware_in_setup` |
| CC-16 | `views.py` contains `column_exclude_list` with `hashed_password` | Content contains both identifiers | `test_sensitive_columns_excluded` |
| CC-17 | Custom `admin_path="/dashboard"` is propagated into `config.py` | Run tool with `admin_path="/dashboard"`, grep config for `"/dashboard"` | `test_custom_admin_path` |
| CC-18 | `requirements.txt` contains `sqladmin>=` AND `itsdangerous>=` after a successful run | Read `requirements.txt`, assert both substrings present | `test_requirements_sqladmin` |
| CC-19 | `ToolResult.execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-20 | After two runs, all `.py` files in the project still AST-parse clean | Run tool twice, walk every `.py`, call `ast.parse` | `test_idempotent_project_still_parses` |
| CC-21 | `ToolResult.next_steps` is non-empty and mentions `pip install` or `requirements` | `len(next_steps) > 0` and combined text contains keyword | `test_next_steps_present` |

## 7. Definition of Done (DoD)

- [ ] All 21 Completeness Criteria pass their corresponding tests
- [ ] `test_add_sqladmin.py` runs to `21 passed, 0 failed` under `PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_sqladmin.py -v`
- [ ] Tool execution time < 5s on reference fixture
- [ ] Fresh fixture project boots successfully with `uvicorn app.main:app` both **with** and **without** `sqladmin` installed
- [ ] Fresh fixture project boots successfully with `uvicorn app.main:app` both **with** and **without** `itsdangerous` installed
- [ ] `GET /health` returns 200 OK on a project where `sqladmin` is missing (proves lazy import works)
- [ ] `GET /admin/` returns the login page on a project where both deps are installed
- [ ] A non-superuser cannot log in when `require_superuser=True` (log entry at WARNING level confirms denial)
- [ ] A superuser can log in, see the User list, see the Item list, and **cannot** delete a User row (button disabled)
- [ ] `hashed_password` does not appear in any list view column, detail view column, or search filter
- [ ] `sqladmin>=0.19.0` and `itsdangerous>=2.2.0` are both pinned in `requirements.txt`
- [ ] Second tool invocation returns `status="no_op"` with zero file changes
- [ ] All four generated Python files pass `ast.parse` and `ruff check`
- [ ] No function in `app/admin/` exceeds 50 lines
- [ ] Security reviewer has read the entire `app/admin/` package end-to-end (< 300 LOC total)

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SQLADMIN-01 | **`SessionMiddleware` import MUST be lazy** — only imported inside `setup_admin()`, wrapped in `try/except ImportError` | `_ADMIN_SETUP_TEMPLATE` places the import inside the function body; `_patch_main` explicitly does NOT add a top-level `SessionMiddleware` import | `test_session_middleware_in_setup` |
| INV-SQLADMIN-02 | **`sqladmin` import MUST be lazy** — only imported inside `setup_admin()`, wrapped in `try/except ImportError` | `_ADMIN_SETUP_TEMPLATE` starts the function with `try: from sqladmin import Admin except ImportError: ... return` | `test_lazy_sqladmin_import` |
| INV-SQLADMIN-03 | **Admin routes MUST require superuser auth when `require_superuser=True`** | `AdminAuthBackend.login` validates `getattr(user, "is_superuser", False)` and returns `False` on missing flag; the template literal `REQUIRE_SUPERUSER_PLACEHOLDER` is replaced with `"True"` when the tool default is used | CC-12 + manual verification (not unit-tested; property-based test would be flaky without a running Starlette instance) |
| INV-SQLADMIN-04 | **`/admin` MUST NOT be exposed if the superuser flag is absent on the login user** | Same as INV-03; denial is logged at WARNING | CC-12 |
| INV-SQLADMIN-05 | **Sensitive columns MUST be excluded from every ModelAdmin list view** | `_ADMIN_VIEW_CLASS_TEMPLATE` hard-codes `column_exclude_list = ["hashed_password", "secret_enc", "entry_hash", "prev_hash"]` on every generated class | `test_sensitive_columns_excluded` |
| INV-SQLADMIN-06 | **User ModelAdmin MUST have `can_delete = False`** | `_build_single_view` sets `can_delete = "False"` when `name == "User"` | CC-13 (`ModelAdmin` count) + manual |
| INV-SQLADMIN-07 | **Tool MUST be idempotent** — second invocation is a no-op with empty `files_created` and `files_modified` | Pre-flight check `if setup_file.exists() and "setup_admin" in setup_file.read_text(): return ToolResult(status="no_op", ...)` | `test_idempotent` |
| INV-SQLADMIN-08 | **`dry_run=True` MUST write zero bytes to disk** | `add_sqladmin` returns early from the `if inp.dry_run:` branch before any `.write_text()` call | `test_dry_run` |
| INV-SQLADMIN-09 | **All generated Python files MUST AST-parse clean** | `_assert_parses` is called for every entry in `files_created`; a `SyntaxError` aborts the tool with a descriptive error | `test_all_py_parse`, `test_idempotent_project_still_parses` |
| INV-SQLADMIN-10 | **No generated function body MUST exceed 50 LOC** | Design constraint on all templates; `test_no_function_over_50_loc` walks every `FunctionDef` in `app/` and asserts the cap | `test_no_function_over_50_loc` |
| INV-SQLADMIN-11 | **`settings.SECRET_KEY` MUST never appear in a log call** | No `logger.*(..., settings.SECRET_KEY, ...)` in any template; reviewer verifies by grep | Manual + QS-9 |
| INV-SQLADMIN-12 | **Config patch MUST place fields inside the `Settings` class body** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent; fallback anchors preserve indent | `test_config_fields_patched` |
| INV-SQLADMIN-13 | **`requirements.txt` MUST contain `sqladmin>=` and `itsdangerous>=`** after the tool runs | `_patch_requirements` appends each dep only if the substring is not already present | `test_requirements_sqladmin` |
| INV-SQLADMIN-14 | **Custom `admin_path` MUST propagate into `config.py`** | `_patch_config` interpolates the user-provided value into `ADMIN_PATH: str = "{admin_path}"` | `test_custom_admin_path` |
| INV-SQLADMIN-15 | **The tool MUST NOT create new models, migrations, or routes** | Only `app/admin/` files are created; no `app/models/`, no `alembic/versions/`, no `app/api/routes/` writes | `test_models_init_patched`, `test_routes_registered` |

---

## 9. User Stories

### 9.1 Core Admin Flow (US-01 .. US-05)

**US-01: Drop an admin panel into an existing FastAPI project**
- **As a** backend engineer onboarding a new teammate to a production API
- **I want** a working admin panel mounted at `/admin` in under a minute
- **So that** support staff can self-serve common operations without opening tickets
- **Given:** A FastAPI project with `app/models/user.py`, `app/models/item.py`, `app/core/config.py`, and `app/main.py`
- **When:** `add_sqladmin(ToolInput(project_dir="/path/to/project"))` is called
- **Then:**
  - Returns `status="success"` (CC-01)
  - Creates `app/admin/{__init__.py,setup.py,auth.py,views.py}` (CC-04)
  - Modifies `app/main.py`, `app/core/config.py`, `requirements.txt`, `.env.example` (CC-05)
  - `pip install -r requirements.txt && uvicorn app.main:app` serves `/admin/login` on first boot

**US-02: Boot the app before `sqladmin` is installed**
- **As a** CI engineer running `pytest --collect-only` in a sandbox image
- **I want** the app to import cleanly even without `sqladmin` in the venv
- **So that** CI never fails on "ImportError: No module named 'sqladmin'" on the first commit after the tool runs
- **Given:** Tool has run, `sqladmin` is not installed
- **When:** `python -c "from app.main import app"` is executed
- **Then:**
  - Import succeeds without error
  - `logger.warning("sqladmin not installed — admin panel disabled. ...")` is emitted
  - `/health` still returns 200 (INV-SQLADMIN-02)
  - `/admin/` returns 404 (nothing mounted)

**US-03: Boot the app before `itsdangerous` is installed**
- **As a** developer who just cloned the repo and ran `uvicorn app.main:app` before `pip install`
- **I want** the app to boot cleanly without a cryptic `SessionMiddleware` traceback
- **So that** I can iterate on non-admin features without fixing a dep first
- **Given:** Tool has run, `sqladmin` is installed, `itsdangerous` is NOT installed
- **When:** `uvicorn app.main:app` is started
- **Then:**
  - App boots (INV-SQLADMIN-01)
  - `logger.warning("itsdangerous not installed — admin auth disabled")` is emitted
  - `/admin/` returns the login page, but posting the form fails silently (no session cookie)
  - `/health`, `/api/v1/*` all work normally

**US-04: Superuser logs in and sees the User list**
- **As a** founder with `is_superuser=True`
- **I want** to log in at `/admin/login`, see my 10,000 users, and search by email
- **So that** I can triage a support escalation in 30 seconds
- **Given:** A superuser account exists, `sqladmin` + `itsdangerous` are installed
- **When:** Navigate to `/admin/login`, enter email + password, submit
- **Then:**
  - `AdminAuthBackend.login` validates `verify_password` (QS-9)
  - `is_superuser` flag is checked and passes (INV-SQLADMIN-03)
  - Session cookie set with `admin_user_id`, `admin_email`
  - Redirected to `/admin/` user list view
  - `hashed_password` column is NOT visible in the list (INV-SQLADMIN-05)

**US-05: Non-superuser is rejected at login**
- **As a** security engineer verifying hardening
- **I want** a regular user account to be denied at `/admin/login`
- **So that** I can sign off on the privilege boundary
- **Given:** A `is_superuser=False` user account exists
- **When:** Valid credentials are submitted to `/admin/login`
- **Then:**
  - `verify_password` passes
  - `require_superuser` gate rejects the login (INV-SQLADMIN-03)
  - Login returns `False`
  - `logger.warning("Admin login denied for non-superuser: ...")` is logged (QS-10)
  - User stays on login page — no session cookie

### 9.2 Idempotency & Safety (US-06 .. US-10)

**US-06: CI re-runs the tool on every commit**
- **As a** DevOps engineer wiring `fastapi_add_*` tools into a pre-commit hook
- **I want** the tool to be safely re-runnable
- **So that** accidental double-invocation does not corrupt generated files
- **Given:** Tool has already been applied to a project
- **When:** `add_sqladmin(ToolInput(project_dir="..."))` is called again
- **Then:**
  - Returns `status="no_op"` (INV-SQLADMIN-07)
  - `files_created == []`, `files_modified == []` (CC-02)
  - `notes` contains `"SQLAdmin is already installed, skipped."`
  - No file on disk has changed a single byte

**US-07: `dry_run=True` preview without side effects**
- **As a** release engineer evaluating the tool before approving a PR
- **I want** a `dry_run=True` mode that reports what the tool would do
- **So that** I can review the plan in a CI job without mutating the repo
- **Given:** A fresh fixture project
- **When:** `add_sqladmin(ToolInput(project_dir=..., dry_run=True))` is called
- **Then:**
  - Returns `status="success"` (CC-03)
  - `files_created == []`, `files_modified == []`
  - `notes` lists the files that WOULD be created and the discovered model names
  - Zero bytes written (INV-SQLADMIN-08)

**US-08: Partial project — missing `requirements.txt`**
- **As a** developer porting the tool to a project that uses `pyproject.toml` without a `requirements.txt`
- **I want** the tool to still create the admin package
- **So that** a missing optional artefact does not block me
- **Given:** Project has `app/` but no `requirements.txt`
- **When:** Tool runs
- **Then:**
  - `app/admin/` is created normally (QS-13)
  - `requirements.txt` modification step is silently skipped
  - `config.py` and `main.py` are patched
  - `ToolResult.notes` mentions that `requirements.txt` was not found — engineer adds `sqladmin` + `itsdangerous` manually

**US-09: Partial project — missing `app/main.py`**
- **As a** developer on a non-standard project layout
- **I want** the tool to create the admin package anyway
- **So that** I can wire `setup_admin(app)` by hand in my entry point
- **Given:** Project has `app/models/` and `app/core/config.py` but no `app/main.py`
- **When:** Tool runs
- **Then:**
  - `app/admin/` is created normally
  - `main.py` patch step is silently skipped
  - `next_steps` prompts the engineer to call `setup_admin(app)` manually

**US-10: Custom admin path `/ops`**
- **As a** security team that wants to hide `/admin` behind an unpredictable path
- **I want** `admin_path="/ops"` to propagate into `config.py`
- **So that** our WAF can block known admin paths while still letting ops in
- **Given:** Fresh fixture project
- **When:** `add_sqladmin(ToolInput(...), admin_path="/ops")` is called
- **Then:**
  - `config.py` contains `ADMIN_PATH: str = "/ops"` (INV-SQLADMIN-14)
  - `setup_admin()` mounts the panel at `/ops` via `getattr(settings, "ADMIN_PATH", "/admin")`
  - Verified by `test_custom_admin_path`

### 9.3 Security & Privilege (US-11 .. US-15)

**US-11: `hashed_password` never appears in a list view**
- **As a** compliance officer running a SOC2 audit
- **I want** password hashes excluded from every admin screen
- **So that** support staff do not accidentally screenshot or page-capture them
- **Given:** Admin panel mounted, superuser logged in
- **When:** `/admin/user/list` is rendered
- **Then:**
  - `hashed_password` is not in the column headers (INV-SQLADMIN-05)
  - `hashed_password` is not in any row cell
  - Also verified for `secret_enc`, `entry_hash`, `prev_hash` (QS-4)

**US-12: User deletion is disabled in the admin**
- **As a** CEO who lost a customer to "my developer clicked delete by accident"
- **I want** the User admin to be view-only on the delete action
- **So that** accidental or malicious deletion requires a code change
- **Given:** Superuser logged in on the User list
- **When:** Rendering a user detail page
- **Then:**
  - "Delete" button is absent (INV-SQLADMIN-06)
  - `can_delete = False` on `UserAdmin`
  - Other models (Item, etc.) still show the delete button (`can_delete = True`)

**US-13: Session secret reuses `SECRET_KEY`**
- **As a** security engineer reviewing secret rotation procedures
- **I want** the admin session cookie to be signed by the same `SECRET_KEY` as the API JWT
- **So that** rotating one key rotates both
- **Given:** Tool has run
- **When:** Inspecting `setup_admin()`
- **Then:**
  - `SessionMiddleware` receives `secret_key=settings.SECRET_KEY`
  - `AdminAuthBackend` receives `secret_key=settings.SECRET_KEY`
  - Grep `setup.py` / `auth.py` for `SECRET_KEY` returns exactly 2 occurrences, both constructor args

**US-14: Admin denial is logged for SIEM**
- **As a** SOC analyst
- **I want** a log line every time a non-superuser attempts admin login
- **So that** I can fire on brute-force attacks in Splunk
- **Given:** Non-superuser attempts `/admin/login` with valid credentials
- **When:** `AdminAuthBackend.login` denies
- **Then:**
  - `logger.warning("Admin login denied for non-superuser: %s", str(email))` is emitted (QS-10)
  - Email is present, password is absent
  - WARNING level lets SIEM rules filter on severity

**US-15: Secrets never logged in happy path**
- **As a** security auditor running a log-scrape grep
- **I want** `SECRET_KEY` and password material to never appear in any log stream
- **So that** a compromised log store does not leak the signing key
- **Given:** Tool has run, admin panel is mounted
- **When:** Any admin flow executes
- **Then:**
  - `grep -r SECRET_KEY $LOG_DIR` returns zero matches (QS-9)
  - `grep -r hashed_password $LOG_DIR` returns zero matches
  - `grep -r "password=" $LOG_DIR` returns zero matches from admin code paths

### 9.4 Model Discovery & View Generation (US-16 .. US-20)

**US-16: Models auto-discovered from `app/models/__init__.py`**
- **As a** developer who adds a new `Order` model
- **I want** running the tool on a project with `Order` to generate `OrderAdmin` automatically
- **So that** I do not have to hand-edit `views.py`
- **Given:** `app/models/__init__.py` re-exports `from app.models.order import Order`
- **When:** Tool runs
- **Then:**
  - `_discover_models` returns `["Item", "Order", "User"]` (sorted)
  - `views.py` contains `ItemAdmin`, `OrderAdmin`, `UserAdmin`
  - `MODEL_ADMINS = [ItemAdmin, OrderAdmin, UserAdmin]`

**US-17: Fallback when `app/models/__init__.py` has a syntax error**
- **As a** developer running the tool mid-refactor with a broken models file
- **I want** the tool to fall back to `["User"]` instead of crashing
- **So that** the admin package is still installable and I can fix models afterwards
- **Given:** `app/models/__init__.py` has a `SyntaxError`
- **When:** `_discover_models` parses the file
- **Then:**
  - `ast.parse` raises `SyntaxError`
  - `_discover_models` catches and returns `["User"]` (QS-15)
  - `views.py` contains only `UserAdmin`

**US-18: Ignores `Base` and lowercase imports**
- **As a** code reviewer reading the generator logic
- **I want** `Base` (the SQLAlchemy declarative base) to be excluded from discovery
- **So that** `views.py` does not try to register an admin for the metadata class
- **Given:** `app/models/__init__.py` contains `from app.models.base import Base` and `from app.models.utils import lowercase_helper`
- **When:** `_discover_models` runs
- **Then:**
  - `Base` is skipped (`real_name != "Base"` check)
  - `lowercase_helper` is skipped (`real_name[0].isupper()` check)
  - Only PascalCase, non-`Base` names remain

**US-19: Pluralisation for view headers**
- **As a** support agent browsing the admin panel
- **I want** each model section labelled with a reasonable plural
- **So that** "User" / "Users", "Category" / "Categories" look natural
- **Given:** Model names `User`, `Category`, `Process`
- **When:** `_build_single_view` is called for each
- **Then:**
  - `User` → `name_plural = "Users"`
  - `Category` → `name_plural = "Categories"` (y → ies)
  - `Process` → `name_plural = "Processes"` (s → es)
  - Crude but sufficient for scaffolds — engineers can override in `views.py`

**US-20: At least two ModelAdmin classes in the fixture**
- **As a** tool author verifying the generator works end-to-end
- **I want** the fixture project to have at least `User` and `Item` models
- **So that** `views.py` proves the multi-model branch
- **Given:** Fixture has `User` and `Item` models
- **When:** Tool runs
- **Then:**
  - `views.py` contains at least 2 `ModelAdmin` subclasses (CC-13)
  - `MODEL_ADMINS` list has at least 2 entries
  - Verified by `test_views_model_admins`

### 9.5 Tooling & Developer Experience (US-21 .. US-25)

**US-21: `next_steps` guides the developer**
- **As a** developer running the tool for the first time
- **I want** the `ToolResult` to tell me what to do next
- **So that** I do not have to dig through docs
- **Given:** Tool returns `status="success"`
- **When:** Reading `result.next_steps`
- **Then:**
  - At least one step mentions `pip install` or `requirements` (CC-21)
  - One step mentions restarting the FastAPI app
  - One step mentions visiting `admin_path` and logging in as superuser
  - One step points at `app/admin/views.py` for customisation

**US-22: Execution time is recorded**
- **As a** pipeline engineer measuring tool performance
- **I want** `ToolResult.execution_time_ms` to be a positive integer
- **So that** I can alert on drift beyond the 5s SLO
- **Given:** Tool runs to completion
- **When:** Reading `result.execution_time_ms`
- **Then:**
  - Value is a positive integer (CC-19)
  - Typical value < 5000 ms on reference hardware

**US-23: Every generated file parses clean**
- **As a** CI pipeline running `ruff` and `mypy` after the tool
- **I want** every `.py` file in the project to AST-parse
- **So that** downstream linting does not fail on tool output
- **Given:** Tool ran once or twice
- **When:** Walking every `.py` file in `project_dir`
- **Then:**
  - `ast.parse` succeeds on every file (INV-SQLADMIN-09)
  - Verified by `test_all_py_parse` and `test_idempotent_project_still_parses`

**US-24: Functions stay under 50 LOC for review**
- **As a** security reviewer reading the admin package
- **I want** every function to fit on one screen
- **So that** I can review the whole thing end-to-end in one sitting
- **Given:** Tool has run
- **When:** Walking every `FunctionDef` in `app/`
- **Then:**
  - Max function LOC is ≤ 50 (INV-SQLADMIN-10)
  - Verified by `test_no_function_over_50_loc`

**US-25: Tool composes with `add_rbac`, `add_audit_log`, `add_mfa`**
- **As a** platform engineer applying a full hardening recipe
- **I want** `add_sqladmin` to coexist with `add_rbac`, `add_audit_log`, `add_mfa`
- **So that** admin actions are authorised (RBAC), logged (audit_log), and gated on MFA
- **Given:** Tool has run; subsequently `add_audit_log` and `add_mfa` also run
- **When:** A superuser performs an admin action
- **Then:**
  - RBAC permissions apply to the superuser role
  - Audit log entry is written for every admin mutation
  - MFA challenge fires on login (if `add_mfa` is installed)
  - No import loops, no conflicting middleware registrations

---

## 10. Test Plan

### 10.1 Category A — Tool Execution (5 tests)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fresh fixture project | `add_sqladmin(ToolInput(project_dir=...))` | `status == "success"`, `error is None` (CC-01) |
| T-02 | `test_idempotent` | Tool already ran once | Run tool a second time | `status == "no_op"`, `files_created == []`, `files_modified == []` (CC-02, INV-SQLADMIN-07) |
| T-03 | `test_dry_run` | Fresh fixture; snapshot all `.py` files | Run with `dry_run=True`; snapshot again | `status == "success"`, `files_created == []`, `files_modified == []`, before == after (CC-03, INV-SQLADMIN-08) |
| T-04 | `test_files_created_count` | Fresh fixture | Run tool | `len(files_created) >= 4` and every path exists on disk (CC-04) |
| T-05 | `test_files_modified_count` | Fresh fixture | Run tool | `len(files_modified) >= 2` and every path exists on disk (CC-05) |

### 10.2 Category B — Generated Code Quality (5 tests)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fresh fixture | Run tool; walk every `.py` file | `ast.parse` succeeds on every file (CC-06, INV-SQLADMIN-09) |
| T-07 | `test_no_function_over_50_loc` | Fresh fixture | Run tool; walk every `FunctionDef` in `app/` | `end_lineno - lineno + 1 <= 50` for every function (CC-07, INV-SQLADMIN-10) |
| T-08 | `test_config_fields_patched` | Fresh fixture | Run tool; read `app/core/config.py` | `ADMIN_PATH`, `ADMIN_TITLE`, `ADMIN_REQUIRE_SUPERUSER` all present; `ADMIN_PATH` line starts with 4-space indent (CC-08, INV-SQLADMIN-12) |
| T-09 | `test_models_init_patched` | Fresh fixture | Run tool | `app/admin/__init__.py` exists; no new model imports added to `app/models/__init__.py` (CC-09, INV-SQLADMIN-15) |
| T-10 | `test_routes_registered` | Fresh fixture | Run tool; read `app/main.py` | `"setup_admin" in content` (CC-10) |

### 10.3 Category C — Admin Package Structure (5 tests)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_setup_module_created` | Fresh fixture | Run tool; read `app/admin/setup.py` | File exists; content contains `setup_admin` (CC-11) |
| T-12 | `test_auth_backend_created` | Fresh fixture | Run tool; read `app/admin/auth.py` | File exists; content contains `AdminAuthBackend`, `async def login`, `async def authenticate` (CC-12) |
| T-13 | `test_views_model_admins` | Fresh fixture with User + Item | Run tool; read `app/admin/views.py` | Content contains `MODEL_ADMINS`; `content.count("Admin(ModelAdmin") >= 2` (CC-13) |
| T-14 | `test_lazy_sqladmin_import` | Fresh fixture | Run tool; read `app/admin/setup.py` | Content contains `try:`, `ImportError`, `from sqladmin` (CC-14, INV-SQLADMIN-02) |
| T-15 | `test_session_middleware_in_setup` | Fresh fixture | Run tool; read `app/admin/setup.py` | `"SessionMiddleware" in setup.py` (CC-15, INV-SQLADMIN-01) |

### 10.4 Category D — Security & Configuration (3 tests)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-16 | `test_sensitive_columns_excluded` | Fresh fixture | Run tool; read `app/admin/views.py` | Content contains `column_exclude_list` AND `hashed_password` (CC-16, INV-SQLADMIN-05) |
| T-17 | `test_custom_admin_path` | Fresh fixture | `add_sqladmin(inp, admin_path="/dashboard")`; read `config.py` | `"/dashboard" in config.py` content (CC-17, INV-SQLADMIN-14) |
| T-18 | `test_requirements_sqladmin` | Fresh fixture | Run tool; read `requirements.txt` | Contains `sqladmin>=` AND `itsdangerous>=` (CC-18, INV-SQLADMIN-13) |

### 10.5 Category E — Tool Contract & Idempotency (3 tests)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | `test_execution_time_recorded` | Fresh fixture | Run tool; read `result.execution_time_ms` | Value > 0 (CC-19) |
| T-20 | `test_idempotent_project_still_parses` | Fresh fixture | Run tool twice; walk every `.py` file | `ast.parse` succeeds on every file after both runs (CC-20, INV-SQLADMIN-09) |
| T-21 | `test_next_steps_present` | Fresh fixture | Run tool; read `result.next_steps` | `len(next_steps) > 0`; combined lowercase text contains `"pip install"` or `"requirements"` (CC-21) |

**Total: 21 tests, 100% CC coverage.**

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_rbac` | Yes (RBAC before sqladmin) | Composes | RBAC introduces fine-grained permissions that the admin login path can consult. Put RBAC first so `AdminAuthBackend.login` can call `user.has_permission("admin:access")` in addition to the `is_superuser` check. Without RBAC, the `is_superuser` gate is the only authorisation layer. |
| `add_audit_log` | Yes (audit_log after sqladmin) | Composes | Every mutation performed through the admin panel should emit an audit event. SQLAdmin does not fire these natively — wire `add_audit_log`'s SQLAlchemy event listeners after sqladmin so the `before_flush` hooks capture admin-originated changes. Audit entries include `source="admin"` so you can filter them in log search. |
| `add_mfa` | Yes (mfa before sqladmin) | Composes | MFA should gate `/admin/login`. Install MFA first so the admin login form can call `mfa.verify_second_factor(user, totp_code)` before setting the session cookie. Without MFA, single-factor email+password is the only gate on the panel. |
| `add_oauth2_provider` | No | Compatible | OAuth2 for the API is orthogonal — admin auth is cookie-based and uses the password scaffold, not JWT. They coexist without changes. |
| `add_api_key_auth` | No | Compatible | API keys authenticate machine clients against `/api/*`; the admin panel is for humans. No overlap. |
| `add_soft_delete` | No | Compatible | Soft-deleted rows still appear in admin list views. If you want to hide them, override `get_list_query` on the ModelAdmin subclass. |
| `add_cursor_pagination` | No | Compatible | Admin list views use SQLAdmin's built-in offset pagination (`page=1&pageSize=25`), not cursor pagination. No conflict. |
| `add_search` | No | Compatible | Admin search is ModelAdmin's built-in `column_searchable_list`. If `add_search` introduces a separate full-text index, the admin does not use it. |
| `add_multi_tenancy` | Yes (multi_tenancy after sqladmin) | ⚠️ Caveat | Multi-tenant row-level isolation must be applied at the SQLAlchemy session level. If you apply multi-tenancy AFTER sqladmin, the admin session inherits tenant scoping — but a superuser normally needs to see rows across tenants. Override `get_list_query` on each ModelAdmin to bypass tenant filtering when the logged-in user is `is_superuser`. |
| `add_feature_flags` | No | Compatible | Feature flags are model-level. Admin views render whatever the model exposes. |
| `add_long_running_task` | No | Compatible | Task state lives in Redis, not SQL — does not appear in the admin. Add a custom ModelAdmin if you persist tasks to PostgreSQL. |
| `add_cache_layer` | No | ⚠️ Caveat | Admin mutations bypass any API-layer cache. If `add_cache_layer` wraps `GET /api/v1/users/{id}`, a support agent editing a user via `/admin` will leave the cache stale. Pair with a TTL short enough (< 60s) or invalidate via SQLAlchemy event listener. |
| `add_outbox_pattern` | No | Compatible | Outbox events fire via `after_flush` listener — admin mutations trigger them normally. |
| `add_event_driven` | No | Compatible | Same as outbox — domain events fire on admin mutations. |
| `add_sse` | No | Compatible | SSE channels are unrelated to admin. |
| `add_soft_delete` | No | Compatible | See above. |
| `fastapi_generate_project` | Yes (generate first) | Required | `add_sqladmin` assumes `app/`, `app/models/`, `app/core/config.py`, `app/main.py` exist. Run `fastapi_generate_project` first if starting from scratch. |

**Conflicts:** None identified. The tool is additive-only and reuses existing scaffolds.

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
# Revert modified files
git checkout HEAD -- \
  app/core/config.py \
  app/main.py \
  requirements.txt \
  .env.example

# Remove created files
rm -rf app/admin/
```

Alternatively, `git restore .` if the files are uncommitted and the working tree has no other changes.

### 12.2 Database rollback (after deploy)

**N/A** — this tool is code-only. No tables are created, no columns are added, no indexes are changed. `alembic downgrade -1` would be a no-op. Skip this step.

### 12.3 Data preservation rollback

**N/A** — the admin panel operates on existing business data but creates none of its own (no sessions in PostgreSQL, no admin audit table, no admin-specific metadata). Session cookies live on the client side only. Nothing to archive.

### 12.4 Failure mode: tool partially modified files

If the tool crashed mid-write (power loss, killed process, out-of-disk):

```bash
# Reset all tracked modifications
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --

# Remove any admin files that were created
rm -rf app/admin/

# Clean any temp files the tool may have left
find . -name '*.tmp_*' -delete
```

Then re-run the tool. It is idempotent, so a successful re-run will converge to the correct state.

### 12.5 Emergency: disable admin without rolling back

When the admin panel is in production and you need to **shut it off immediately** without a full code rollback:

**Option A — environment variable (fastest, no code change):**

Set `ADMIN_REQUIRE_SUPERUSER=true` and ensure no active superuser accounts exist. Active superusers can be downgraded via a `UPDATE users SET is_superuser = false WHERE ...` — the admin panel then locks everyone out on next login.

**Option B — disable the mount (code change):**

```bash
# Comment out setup_admin in app/main.py
sed -i 's|^setup_admin(app)$|# setup_admin(app)  # DISABLED|' app/main.py

# Restart
systemctl restart fastapi.service
```

This takes `/admin` offline in one deploy without touching the rest of the app.

**Option C — block at the edge (zero deploy):**

Add a WAF rule blocking `/admin/*` at Cloudflare / ALB / NGINX. The FastAPI app keeps running; `/admin` requests are rejected at the edge. Use this when you cannot do a rolling deploy.

### 12.6 Security incident: suspected admin compromise

1. **Invalidate sessions:** rotate `settings.SECRET_KEY`. All existing session cookies (signed with the old key) immediately fail authentication on next request.
2. **Force superuser password resets:** `UPDATE users SET hashed_password = 'invalid' WHERE is_superuser = true;` — forces every superuser through the password reset flow.
3. **Block the admin path at the edge:** WAF rule for `/admin/*` while you triage.
4. **Export audit log entries tagged `source="admin"`** if `add_audit_log` is installed.
5. **Re-deploy:** once triage is done, restore the panel (Option B reverse) or leave it blocked.

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | `sqladmin` not installed at boot | Lazy import inside `setup_admin()` raises `ImportError`; `logger.warning` is emitted; function returns without mounting anything; app continues booting; `/health` returns 200; `/admin/*` returns 404 (INV-SQLADMIN-02) |
| EC-2 | `itsdangerous` not installed at boot | Lazy `SessionMiddleware` import inside `setup_admin()` raises `ImportError`; `logger.warning("itsdangerous not installed — admin auth disabled")` is emitted; admin mounts but login form cannot set a session cookie; login silently fails (INV-SQLADMIN-01) |
| EC-3 | `app/models/__init__.py` has a `SyntaxError` | `_discover_models` catches the exception and falls back to `["User"]`; only `UserAdmin` is generated in `views.py` (QS-15) |
| EC-4 | `app/models/__init__.py` has no PascalCase imports | `_discover_models` returns `["User"]` as the fallback (non-empty default) |
| EC-5 | Model without `__str__` method | SQLAdmin falls back to `repr(instance)` in detail views; list views use `id` as the primary key label; no crash |
| EC-6 | ForeignKey cascade on admin delete | SQLAdmin issues a single `DELETE` statement; the DB enforces `ON DELETE CASCADE` / `ON DELETE RESTRICT`; cascade deletes apply transparently; restricted deletes raise `IntegrityError` which SQLAdmin renders as a red banner without losing the current page |
| EC-7 | `app/core/config.py` missing | `_patch_config` is skipped silently; admin falls back to `getattr(settings, "ADMIN_PATH", "/admin")` in `setup_admin()` (QS-13) |
| EC-8 | `app/main.py` missing | `_patch_main` is skipped silently; engineer must call `setup_admin(app)` manually in their entry point (QS-13) |
| EC-9 | `requirements.txt` missing | `_patch_requirements` is skipped silently; engineer must add `sqladmin>=0.19.0` and `itsdangerous>=2.2.0` to their dependency manifest (pyproject.toml, Pipfile) manually |
| EC-10 | `.env.example` missing | `_patch_env_example` is skipped silently; no error (QS-13) |
| EC-11 | `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` anchor missing in `config.py` | `_patch_config` falls back to inserting before `settings = Settings()`; if that is also missing, appends to file tail |
| EC-12 | Non-superuser attempts login with valid credentials | `verify_password` passes; `is_superuser` gate denies; `logger.warning("Admin login denied for non-superuser: ...")` logged; login returns `False`; login page re-rendered (INV-SQLADMIN-03, INV-SQLADMIN-04) |
| EC-13 | Superuser attempts login with invalid password | `verify_password` returns `False`; login returns `False`; login page re-rendered (no log warning — valid attempts stay quiet) |
| EC-14 | Login form submitted with empty email or password | `if not email or not password: return False` — bounces without a DB query |
| EC-15 | Second tool invocation on already-configured project | Pre-flight check sees `setup_admin` in `setup.py`; returns `status="no_op"` with empty `files_created` and `files_modified`; `notes` contains "SQLAdmin is already installed, skipped." (INV-SQLADMIN-07) |
| EC-16 | `dry_run=True` on a fresh project | Returns `status="success"`; `files_created == []`; `files_modified == []`; `notes` enumerates what would be written and the discovered model names (INV-SQLADMIN-08) |
| EC-17 | Custom `admin_path="/ops"` with special characters | `_patch_config` interpolates the raw string into `ADMIN_PATH: str = "/ops"`; engineer responsibility to pass a valid URL path; no validation at the tool layer |
| EC-18 | Custom `admin_title` with quotes | `_ADMIN_SETUP_TEMPLATE.replace("ADMIN_TITLE_PLACEHOLDER", admin_title)` does simple substring replacement; quoted titles may break the template — recommend ASCII-only titles |
| EC-19 | `settings.SECRET_KEY` is an empty string | `AdminAuthBackend(secret_key="")` is accepted by Starlette; signed cookies are still produced but with a weak key — **not recommended** but does not crash |
| EC-20 | Model name collision between discovery and a Python keyword | `_discover_models` does not filter keywords; if someone names a model `class`, the generated import breaks at `ast.parse` time and `_assert_parses` raises; engineer must rename the model |
| EC-21 | 500+ models discovered | `views.py` contains 500 `ModelAdmin` classes; AST still parses; SQLAdmin handles 500 model views in the left nav (cosmetic: the nav gets long, but functional) |
| EC-22 | `app/models/__init__.py` re-exports `Base` | `_discover_models` filters out `Base` explicitly (`real_name != "Base"`); no `BaseAdmin` is generated |
| EC-23 | Superuser logs in, then flag is set to `False` by another admin | Current session stays valid (session cookie is already signed); next login attempt is denied. Consider pairing with `add_audit_log` for forensics. |
| EC-24 | Admin panel reached before `setup_admin(app)` runs | If the engineer forgot to wire `setup_admin(app)` in `main.py` (e.g. patch step was skipped), `/admin/*` returns 404 |
| EC-25 | Two concurrent tool invocations on the same project | Not supported. First invocation creates `app/admin/`; second invocation (racing) may see the partial state and either create files on top or hit idempotency. File systems provide atomic writes per-file but not per-tool. Serialise invocations with a file lock if running from CI. |

## 14. Acceptance Criteria (Final Sign-off)

1. All 21 Completeness Criteria pass under `PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_sqladmin.py -v` with `21 passed, 0 failed`.
2. Tool execution time < 5s on reference hardware (Apple M1, 16 GB RAM, SSD).
3. Fresh fixture project boots with `uvicorn app.main:app` when **both** `sqladmin` and `itsdangerous` are installed.
4. Fresh fixture project boots with `uvicorn app.main:app` when `sqladmin` is **missing** — `/health` returns 200, `/admin/*` returns 404, `logger.warning` for missing `sqladmin` is emitted exactly once per process.
5. Fresh fixture project boots with `uvicorn app.main:app` when `itsdangerous` is **missing** — `/health` returns 200, admin mounts but sessions cannot be set, `logger.warning` for missing `itsdangerous` is emitted exactly once per process.
6. A superuser can log in at `/admin/login` with valid credentials, reach the User list, search by email, open a detail page, edit a field, and save — all without seeing `hashed_password` at any point.
7. A non-superuser cannot log in at `/admin/login` — `logger.warning("Admin login denied for non-superuser: ...")` is logged at WARNING level.
8. A superuser cannot delete a User row from the admin panel — the delete button is absent on the User detail page.
9. `hashed_password`, `secret_enc`, `entry_hash`, `prev_hash` do not appear in any list view column, detail view, search filter, or export.
10. Second tool invocation returns `status="no_op"` with empty `files_created` and `files_modified`; zero bytes written.
11. `dry_run=True` writes zero bytes; `files_created` and `files_modified` are empty; `notes` describe what would be written.
12. `ruff check app/admin/` returns zero errors.
13. `mypy --strict app/admin/` returns zero errors (type-check runs successfully even without `sqladmin` installed thanks to the dummy base classes).
14. No function in `app/admin/` exceeds 50 lines of code.
15. `requirements.txt` contains exactly one `sqladmin>=0.19.0` line and exactly one `itsdangerous>=2.2.0` line after a successful run.
16. Custom `admin_path="/ops"` propagates into `config.py` as `ADMIN_PATH: str = "/ops"`.
17. `settings.SECRET_KEY` is passed as a constructor argument to `SessionMiddleware` and `AdminAuthBackend` but never appears in any log call.
18. Security reviewer reads the entire `app/admin/` package (`__init__.py` + `setup.py` + `auth.py` + `views.py`, < 300 LOC total) and signs off.
19. On-call engineer successfully resets a test customer's password via the admin panel in < 30 seconds from ingress.

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] Validate `inp.project_dir` exists and is a directory via `validate_project_dir`
- [ ] Ensure `Prereq.BASE_MODEL`, `Prereq.MODELS_INIT`, `Prereq.CONFIG_SETTINGS`, `Prereq.REQUIREMENTS_TXT` are present (or auto-scaffold if not `dry_run`)
- [ ] Compute `app_dir = project / "app"`
- [ ] Check `app/admin/setup.py` for existing `setup_admin` — return `status="no_op"` if present
- [ ] Discover models via `_discover_models(app/models/__init__.py)` with `["User"]` fallback
- [ ] Compute `require_str = "True" if require_superuser else "False"`
- [ ] Handle `dry_run=True` branch: return success with preview notes, write nothing

### 15.2 Admin package skeleton

- [ ] Create `app/admin/` directory with `mkdir(parents=True, exist_ok=True)`
- [ ] Write `app/admin/__init__.py` from `_ADMIN_INIT_TEMPLATE`
- [ ] Append path to `files_created`

### 15.3 Auth backend

- [ ] Substitute `REQUIRE_SUPERUSER_PLACEHOLDER` in `_ADMIN_AUTH_TEMPLATE` with `require_str`
- [ ] Write `app/admin/auth.py`
- [ ] Append path to `files_created`
- [ ] Verify `async def login`, `async def logout`, `async def authenticate` are all present

### 15.4 Model views

- [ ] Call `_build_model_imports(model_names)` to produce import block
- [ ] Call `_build_single_view(name)` for each model, handling `User` special case
- [ ] Concatenate `_ADMIN_VIEWS_HEADER` + imports + view classes + `MODEL_ADMINS` list
- [ ] Write `app/admin/views.py`
- [ ] Append path to `files_created`

### 15.5 Setup module (the lazy-import heart)

- [ ] Substitute `ADMIN_PATH_PLACEHOLDER` and `ADMIN_TITLE_PLACEHOLDER` in `_ADMIN_SETUP_TEMPLATE`
- [ ] Verify the template contains `try: from sqladmin import Admin except ImportError:`
- [ ] Verify the template contains `try: from starlette.middleware.sessions import SessionMiddleware except ImportError:`
- [ ] Verify both imports are **inside** the `setup_admin` function body
- [ ] Write `app/admin/setup.py`
- [ ] Append path to `files_created`

### 15.6 Config patch

- [ ] Read `app/core/config.py`
- [ ] Skip if `"ADMIN_PATH" in src` (idempotent)
- [ ] Build the block with 4-space indent, 3 fields
- [ ] Try anchor: `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] Fallback anchor: `settings = Settings()`
- [ ] Final fallback: append to tail
- [ ] Write back; append to `files_modified`

### 15.7 Main patch

- [ ] Read `app/main.py`
- [ ] Skip if `"setup_admin" in src` (idempotent)
- [ ] Walk lines, find last top-level `from app.*` import, insert `from app.admin.setup import setup_admin` after
- [ ] Find `register_middleware(app` line, append `setup_admin(app)` after
- [ ] Fallback: if no `register_middleware`, insert import at top and append `setup_admin(app)` at tail
- [ ] **DO NOT** add a top-level `SessionMiddleware` import (INV-SQLADMIN-01)
- [ ] Preserve trailing newline; write back; append to `files_modified`

### 15.8 Requirements patch

- [ ] Read `requirements.txt`
- [ ] Append `sqladmin>=0.19.0` if not present
- [ ] Append `itsdangerous>=2.2.0` if not present
- [ ] Write back; append to `files_modified`

### 15.9 `.env.example` patch

- [ ] Read `.env.example` if it exists
- [ ] Skip if `"ADMIN_PATH" in src` (idempotent)
- [ ] Append commented-out `ADMIN_PATH`, `ADMIN_TITLE`, `ADMIN_REQUIRE_SUPERUSER`
- [ ] Write back; append to `files_modified`

### 15.10 AST self-verification

- [ ] For each path in `files_created` with `.py` suffix, call `_assert_parses`
- [ ] Raise `SyntaxError` with the file name on failure
- [ ] Abort the tool (do NOT return `status="success"` on a broken write)

### 15.11 Return contract

- [ ] Build `ToolResult(status="success", files_created=..., files_modified=..., notes=..., next_steps=..., execution_time_ms=...)`
- [ ] Notes: panel description, admin path, models list, SessionMiddleware location, lazy-import note, sensitive columns note
- [ ] Next steps: `pip install -r requirements.txt`, restart app, visit admin_path, customise `views.py`
- [ ] Execution time via `_elapsed_ms(start)`

### 15.12 Documentation

- [ ] Add tool entry to `SKILL.md` tools table under EXTEND > Infrastructure
- [ ] Update `manifest.yaml` with MCP tool metadata (`fastapi_add_sqladmin`)
- [ ] Append to `core/KNOWLEDGE.md` admin section
- [ ] Cross-reference `add_rbac`, `add_audit_log`, `add_mfa` in the interaction matrix

### 15.13 Atomicity & safety

- [ ] Never partially write a template — always call `.write_text()` with the full content
- [ ] Always check `path.exists()` before modifying an optional file (config, main, requirements, env)
- [ ] Never crash on a missing optional file — skip silently and let the engineer wire it

### 15.14 Verification

- [ ] Run `pytest adapt/extend/infrastructure/test_add_sqladmin.py -v` — expect `21 passed`
- [ ] Run `ruff check adapt/extend/infrastructure/add_sqladmin.py` — expect 0 errors
- [ ] Run `mypy --strict adapt/extend/infrastructure/add_sqladmin.py` — expect 0 errors
- [ ] Manual smoke: apply to a fresh fixture, `uvicorn app.main:app`, log in as superuser, open the User list, confirm `hashed_password` absent, confirm delete button absent on User detail

### 15.15 Finalisation

- [ ] Emit `logger.info("SQLAdmin panel mounted at %s", path)` on successful mount (runtime, not tool-time)
- [ ] Commit the four new files + four modified files
- [ ] Update `CHANGELOG.md` with TOOL-056 entry
- [ ] Tag the spec version as `v2-rigorous`

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "/path/to/project/app/admin/__init__.py",
    "/path/to/project/app/admin/auth.py",
    "/path/to/project/app/admin/views.py",
    "/path/to/project/app/admin/setup.py"
  ],
  "files_modified": [
    "/path/to/project/app/core/config.py",
    "/path/to/project/app/main.py",
    "/path/to/project/requirements.txt",
    "/path/to/project/.env.example"
  ],
  "metrics": {
    "execution_time_ms": 1842,
    "files_changed": 8,
    "lines_added": 246,
    "lines_removed": 0,
    "models_discovered": 2,
    "model_admins_generated": 2,
    "max_function_loc": 42,
    "test_cases_generated": 21,
    "sensitive_columns_excluded": 4
  },
  "notes": [
    "SQLAdmin panel added: setup module, auth backend (superuser-gated), auto-generated ModelAdmin views.",
    "Admin mounted at '/admin' with title 'Admin Panel'.",
    "ModelAdmin classes generated for: Item, User.",
    "SessionMiddleware registered inside setup_admin() for cookie-based admin sessions (backed by itsdangerous).",
    "sqladmin is imported lazily inside setup_admin() — the app boots cleanly without sqladmin installed.",
    "Sensitive columns (hashed_password, secret_enc, entry_hash, prev_hash) excluded from list views."
  ],
  "next_steps": [
    "pip install -r requirements.txt  # installs sqladmin + itsdangerous",
    "Restart the FastAPI app so the admin panel is mounted.",
    "Visit /admin and log in with a superuser account.",
    "Customise column_list / column_searchable_list in app/admin/views.py as needed."
  ],
  "warnings": [
    "Admin panel grants read/write access to every SQLAlchemy model — audit your `is_superuser` flag assignments before deploy.",
    "Session cookies are signed by settings.SECRET_KEY — rotate the key to invalidate all admin sessions in an incident.",
    "Without `add_audit_log`, admin mutations are NOT recorded in an audit trail — install it for compliance-critical environments.",
    "Without `add_mfa`, admin login is single-factor (email + password) — install it for production hardening."
  ],
  "idempotent_reinvocation": {
    "status": "no_op",
    "files_created": [],
    "files_modified": [],
    "notes": [
      "setup_admin already present in app/admin/setup.py — SQLAdmin is already installed, skipped."
    ],
    "execution_time_ms": 3
  }
}
```

---

*End of TOOL-056 specification.*
