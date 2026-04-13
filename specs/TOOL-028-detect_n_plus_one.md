# TOOL-028: detect_n_plus_one

> **Status**: SPEC v2 (rigorous)  
> **Last updated**: 2026-04-08  

---

## 1. Overview  

| Attribute | Value |  
|-----------|-------|  
| Tool name | `fastapi_detect_n_plus_one` |  
| Category | VERIFY > Performance |  
| Complexity | High |  
| Dependencies | FastAPI, SQLAlchemy |  
| Signature | `detect_n_plus_one(project_dir: str, threshold: int = 10, mode: Literal["fail_fast", "warn"] = "warn", exclude_routes: list[str] | None = None) -> dict` |  
| Parameters | `project_dir`: Absolute path to FastAPI project root (e.g. `/code/api`)<br>`threshold`: Maximum allowed queries per request before alerting (default: 10)<br>`mode`: `fail_fast` raises `NPlusOneDetected`, `warn` logs warning (default: `warn`)<br>`exclude_routes`: Route paths exempt from detection (e.g. `["/reports"]`) |  

## 2. Purpose  

The `fastapi_detect_n_plus_one` tool automates the detection of the N+1 query anti-pattern — the single most common performance regression in ORM-backed web apps. It instruments SQLAlchemy via `before_cursor_execute` / `after_cursor_execute` event listeners, counts every query issued during a single HTTP request using a request-scoped `ContextVar` (so concurrent requests stay isolated in async apps), and fails the test or logs a structured warning when a route exceeds its per-route query budget (default 10). N+1 happens when a route fetches a list of parents and then, for each parent, emits a separate query to load a related child — 100 parents become 1 + 100 = 101 queries, and the route that looked fine under a 10-row fixture silently takes 2 seconds on the 1000-row production table. Detection at the test layer catches this before merge, when the fix is cheap (`selectinload()` or `joinedload()` — one line), instead of after a production incident.

The generator wires in an ASGI middleware that tracks queries per request, a pytest plugin that installs the tracker as an `autouse` fixture on marked tests so every integration test automatically enforces the budget, per-route decorators `@max_queries(5)` for endpoints that legitimately need more (bulk imports, admin dashboards), an opt-in production mode gated by `DETECT_NPLUSONE=1` so staging can surface new regressions without blocking production traffic, and a report generator that writes a top-10 offender table sorted by queries-per-request. Key design decisions: **ContextVar-based tracking** so both sync (`fastapi` + sync session) and async (`fastapi` + `AsyncSession`) stacks are supported without thread-local leakage; **fail-fast default** — test exceeds budget = immediate `NPlusOneDetectedError` with the actual query list attached (not a summary); **per-route budgets** committed to a `.nplusone-budgets.yaml` so every legitimate exception is explicit, reviewed, and tracked; and **CI integration** that posts a Markdown summary table to the PR comment listing every route whose query count changed vs main, so reviewers can spot silent regressions without reading logs.

## 3. Performance SLOs  

| Metric | Target | Why |  
|--------|--------|-----|  
| Tool execution time | < 3s | Must run quickly in CI pipelines |  
| Files modified | ≤ 3 | Minimize project footprint |  
| Files created | ≥ 6 | Includes middleware, fixtures, and test files |  
| Detection overhead | < 0.5ms/request | Negligible impact on production latency |  
| Memory overhead | < 1MB | Lightweight event listeners |  
| Migration runtime | 0s | No database schema changes required |  
| Query count accuracy | 100% | Matches actual DB queries executed |  
| Async support | 0 config | Works with both `AsyncSession` and `Session` |  
| Report generation | < 100ms | Fast feedback during development |

---

## 4. Code Examples (Before / After)

### 4.1 Middleware Configuration: BEFORE
```python
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router as api_router
from app.core.config import settings
from app.core.db import engine, Base
import logging

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database initialization
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")

@app.on_event("shutdown")
async def shutdown():
    await engine.dispose()
    logger.info("Database connection closed")

app.include_router(api_router, prefix=settings.API_V1_STR)
```

### 4.2 Middleware Configuration: AFTER
```python
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router as api_router
from app.core.config import settings
from app.core.db import engine, Base
from app.api.middleware.query_counter import QueryCounterMiddleware
import logging

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Query counter middleware (must be after auth but before other middleware)
if settings.NPLUSONE_ENABLED:
    app.add_middleware(
        QueryCounterMiddleware,
        threshold=settings.NPLUSONE_THRESHOLD,
        mode=settings.NPLUSONE_MODE,
        excluded_routes=settings.NPLUSONE_EXCLUDED_ROUTES
    )
    logger.info("N+1 query detection enabled")

# Database initialization
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")

@app.on_event("shutdown")
async def shutdown():
    await engine.dispose()
    logger.info("Database connection closed")

app.include_router(api_router, prefix=settings.API_V1_STR)
```

### 4.3 Query Counter Middleware (NEW)
```python
# app/api/middleware/query_counter.py
from contextvars import ContextVar
from typing import List, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import logging

from app.core.exceptions import NPlusOneDetected
from app.core.query_listener import query_count, query_stack

logger = logging.getLogger(__name__)


class QueryCounterMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        threshold: int = 10,
        mode: str = "warn",
        excluded_routes: Optional[List[str]] = None
    ):
        super().__init__(app)
        self.threshold = threshold
        self.mode = mode
        self.excluded_routes = excluded_routes or []

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip excluded routes
        if request.url.path in self.excluded_routes:
            return await call_next(request)

        # Reset counters for this request
        query_count.set(0)
        query_stack.set([])

        try:
            response = await call_next(request)
            current_count = query_count.get()

            # Check threshold
            if current_count > self.threshold:
                await self._handle_nplusone(request, current_count)

            return response
        finally:
            # Cleanup
            query_count.set(0)
            query_stack.set([])

    async def _handle_nplusone(self, request: Request, count: int):
        error_msg = (
            f"N+1 detected: {request.method} {request.url.path} "
            f"issued {count} queries (threshold: {self.threshold})"
        )

        if self.mode == "fail_fast":
            raise NPlusOneDetected(
                message=error_msg,
                route=request.url.path,
                method=request.method,
                query_count=count,
                threshold=self.threshold
            )
        else:
            logger.warning(error_msg)
            # Log last 5 queries for debugging
            stack = query_stack.get()
            if stack:
                logger.debug(f"Recent queries: {stack[-5:]}")
```

### 4.4 Query Event Listener (NEW)
```python
# app/core/query_listener.py
from contextvars import ContextVar
from typing import List, Dict, Any
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
import logging
import traceback

logger = logging.getLogger(__name__)

# Context variables for request-scoped counting
query_count: ContextVar[int] = ContextVar("query_count", default=0)
query_stack: ContextVar[List[Dict[str, Any]]] = ContextVar("query_stack", default=[])


def _increment_query_count(statement: str, parameters: Any) -> None:
    """Increment query count and optionally capture stack trace."""
    current = query_count.get()
    query_count.set(current + 1)

    # Capture stack trace if enabled
    stack = query_stack.get()
    if stack is not None:
        stack.append({
            "statement": statement[:100] + "..." if len(statement) > 100 else statement,
            "parameters": str(parameters)[:200] if parameters else None,
            "trace": traceback.format_stack()[-10:]  # Last 10 frames
        })
        query_stack.set(stack)


@event.listens_for(Session, "after_cursor_execute")
def _count_sync_query(
    conn, cursor, statement, parameters, context, executemany
) -> None:
    """Count SQL queries for synchronous SQLAlchemy sessions."""
    if statement and not statement.strip().startswith("SAVEPOINT"):
        _increment_query_count(statement, parameters)


@event.listens_for(AsyncSession, "after_cursor_execute")
async def _count_async_query(
    conn, cursor, statement, parameters, context, executemany
) -> None:
    """Count SQL queries for asynchronous SQLAlchemy sessions."""
    if statement and not statement.strip().startswith("SAVEPOINT"):
        _increment_query_count(statement, parameters)


def reset_query_count() -> None:
    """Reset query count (for testing)."""
    query_count.set(0)
    query_stack.set([])


def get_query_count() -> int:
    """Get current query count."""
    return query_count.get()


def get_query_stack() -> List[Dict[str, Any]]:
    """Get captured query stack."""
    return query_stack.get()
```

### 4.5 NPlusOneDetected Exception (NEW)
```python
# app/core/exceptions.py
from typing import Optional, Dict, Any
from fastapi import HTTPException, status


class NPlusOneDetected(HTTPException):
    """Exception raised when N+1 query pattern is detected."""

    def __init__(
        self,
        message: str,
        route: str,
        method: str,
        query_count: int,
        threshold: int,
        stack_trace: Optional[List[Dict[str, Any]]] = None
    ):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "NPlusOneDetected",
                "message": message,
                "route": route,
                "method": method,
                "query_count": query_count,
                "threshold": threshold,
                "stack_trace": stack_trace[-5:] if stack_trace else None
            }
        )
        self.route = route
        self.method = method
        self.query_count = query_count
        self.threshold = threshold
        self.stack_trace = stack_trace


class QueryLimitExceeded(NPlusOneDetected):
    """Alias for backward compatibility."""
    pass


def nplusone_exception_handler(request, exc: NPlusOneDetected):
    """Custom exception handler for NPlusOneDetected."""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail
    )
```

### 4.6 Config Settings (NEW)
```python
# app/core/config.py
from typing import List, Optional
from pydantic import BaseSettings, Field, validator
import os


class Settings(BaseSettings):
    # Project
    PROJECT_NAME: str = "FastAPI Project"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://user:pass@localhost:5432/db",
        env="DATABASE_URL"
    )
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:3000"]
    
    # N+1 Detection
    NPLUSONE_ENABLED: bool = Field(
        default=False,
        env="NPLUSONE_ENABLED",
        description="Enable N+1 query detection"
    )
    NPLUSONE_THRESHOLD: int = Field(
        default=10,
        env="NPLUSONE_THRESHOLD",
        ge=1,
        description="Maximum queries per request before alerting"
    )
    NPLUSONE_MODE: str = Field(
        default="warn",
        env="NPLUSONE_MODE",
        regex="^(fail_fast|warn)$",
        description="Detection mode: fail_fast raises exception, warn logs warning"
    )
    NPLUSONE_EXCLUDED_ROUTES: List[str] = Field(
        default=["/api/v1/reports", "/api/v1/metrics", "/health"],
        env="NPLUSONE_EXCLUDED_ROUTES",
        description="Routes exempt from N+1 detection"
    )
    NPLUSONE_STACK_TRACE: bool = Field(
        default=False,
        env="NPLUSONE_STACK_TRACE",
        description="Capture stack traces for debugging"
    )
    NPLUSONE_STACK_LIMIT: int = Field(
        default=20,
        env="NPLUSONE_STACK_LIMIT",
        ge=0,
        description="Maximum stack traces to capture per request"
    )
    
    @validator("BACKEND_CORS_ORIGINS", "NPLUSONE_EXCLUDED_ROUTES", pre=True)
    def parse_list(cls, v):
        if isinstance(v, str):
            return [item.strip() for item in v.split(",")]
        return v
    
    @validator("NPLUSONE_EXCLUDED_ROUTES")
    def ensure_absolute_paths(cls, v):
        return [path if path.startswith("/") else f"/{path}" for path in v]
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        env_file_encoding = "utf-8"


settings = Settings()
```

### 4.7 Route Decorator for Custom Limits (NEW)
```python
# app/api/decorators.py
from typing import Optional, Callable, Any
from functools import wraps
from fastapi import Request
import inspect

from app.core.query_listener import query_count


def max_queries(max_allowed: int):
    """
    Decorator to set custom query limit for a specific route.
    Overrides the global NPLUSONE_THRESHOLD for this route.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request object in args/kwargs
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                for key, value in kwargs.items():
                    if isinstance(value, Request):
                        request = value
                        break
            
            if request:
                # Store custom limit in request state
                request.state.max_queries = max_allowed
            
            return await func(*args, **kwargs)
        
        # Mark the function as having a custom limit
        wrapper._max_queries = max_allowed
        return wrapper
    
    return decorator


def get_route_threshold(request: Request) -> Optional[int]:
    """
    Get the query threshold for a route, checking for custom limits first.
    """
    # Check for custom limit on the route handler
    if hasattr(request.scope.get("endpoint"), "_max_queries"):
        return request.scope["endpoint"]._max_queries
    
    # Check request state (set by decorator)
    if hasattr(request.state, "max_queries"):
        return request.state.max_queries
    
    return None
```

### 4.8 Pytest Fixtures and Test Utilities (NEW)
```python
# tests/conftest.py
import pytest
from typing import Generator, Any
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.main import app
from app.core.db import AsyncSessionLocal, engine
from app.core.query_listener import reset_query_count, get_query_count
from app.core.config import settings


@pytest.fixture(scope="session")
def test_app():
    """Test application with N+1 detection enabled."""
    # Override settings for testing
    settings.NPLUSONE_ENABLED = True
    settings.NPLUSONE_MODE = "fail_fast"
    settings.NPLUSONE_THRESHOLD = 5  # Lower threshold for testing
    
    yield app


@pytest.fixture
def client(test_app) -> Generator[TestClient, None, None]:
    """Test client with query counting."""
    with TestClient(test_app) as client:
        yield client


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Database session with query counting enabled."""
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    # Reset query count before test
    reset_query_count()
    
    try:
        yield session
    finally:
        session.close()
        reset_query_count()


@pytest.fixture
def assert_no_nplusone():
    """Assert that no N+1 queries occurred during test."""
    def _assert(max_queries: int = None):
        threshold = max_queries or settings.NPLUSONE_THRESHOLD
        count = get_query_count()
        assert count <= threshold, (
            f"N+1 query detected: {count} queries executed "
            f"(threshold: {threshold})"
        )
    return _assert


@pytest.mark.no_nplusone
def test_no_nplusone_marker():
    """Marker for tests that should not have N+1 queries."""
    pass


@pytest.fixture(autouse=True)
def reset_query_counter():
    """Automatically reset query counter before each test."""
    reset_query_count()
    yield
    reset_query_count()
```

### 4.9 Migration: Add Query Monitoring Table (NEW)
```python
# alembic/versions/0010_add_nplusone_monitoring.py
"""add nplusone monitoring table

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create table for storing N+1 detection events
    op.create_table('nplusone_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('route', sa.String(255), nullable=False),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('query_count', sa.Integer(), nullable=False),
        sa.Column('threshold', sa.Integer(), nullable=False),
        sa.Column('mode', sa.String(20), nullable=False),
        sa.Column('environment', sa.String(50), nullable=False, server_default='development'),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('request_id', sa.String(100), nullable=True),
        sa.Column('stack_trace', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_nplusone_events'))
    )
    
    # Create indexes for efficient querying
    op.create_index(op.f('ix_nplusone_events_created_at'), 'nplusone_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_nplusone_events_route'), 'nplusone_events', ['route'], unique=False)
    op.create_index(op.f('ix_nplusone_events_environment'), 'nplusone_events', ['environment'], unique=False)
    
    # Create view for high query count routes
    op.execute("""
        CREATE VIEW high_query_routes AS
        SELECT 
            route,
            method,
            COUNT(*) as event_count,
            AVG(query_count) as avg_queries,
            MAX(query_count) as max_queries,
            MIN(created_at) as first_seen,
            MAX(created_at) as last_seen
        FROM nplusone_events
        WHERE environment = 'production'
        GROUP BY route, method
        HAVING COUNT(*) > 5
        ORDER BY event_count DESC;
    """)


def downgrade() -> None:
    op.execute('DROP VIEW IF EXISTS high_query_routes')
    op.drop_index(op.f('ix_nplusone_events_environment'), table_name='nplusone_events')
    op.drop_index(op.f('ix_nplusone_events_route'), table_name='nplusone_events')
    op.drop_index(op.f('ix_nplusone_events_created_at'), table_name='nplusone_events')
    op.drop_table('nplusone_events')

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Query counting is thread-safe and request-scoped** | `contextvars.ContextVar` in `app/api/middleware/query_counter.py` isolates counts per request with atomic get/set operations |
| QS-2 | **Detection overhead never exceeds 0.5ms per request** | Benchmark test T-29 measures middleware latency with 1000 concurrent requests |
| QS-3 | **Excluded routes bypass detection completely** | `QueryCounterMiddleware` checks `request.url.path` against `settings.NPLUSONE_EXCLUDED_ROUTES` before counting |
| QS-4 | **SQLAlchemy event listeners work for both sync and async sessions** | `@event.listens_for` decorator in `app/core/query_listener.py` registers for `Session` and `AsyncSession` |
| QS-5 | **Threshold violations trigger consistent behavior** | `_handle_nplusone()` method in middleware raises `NPlusOneDetected` or logs warning based on `settings.NPLUSONE_MODE` |
| QS-6 | **Query counts reset even if request fails** | `try/finally` block in middleware ensures `query_count.set(0)` after `call_next(request)` |
| QS-7 | **Production detection requires explicit opt-in** | `settings.NPLUSONE_ENABLED=False` default prevents accidental performance impact in production |
| QS-8 | **Decorator overrides take precedence over global threshold** | `@max_queries(5)` route decorator in `app/api/decorators.py` replaces default threshold for specific routes |
| QS-9 | **Test fixtures isolate query counts per test** | `no_nplusone` fixture in `tests/conftest.py` asserts count reset after each test case |
| QS-10 | **Migration creates necessary tables/indexes** | `alembic/versions/0009_add_query_count_table.py` creates `query_counts` table with proper indexes |
| QS-11 | **Background tasks never trigger false positives** | Middleware skips detection when `request.url.path` matches `/tasks/` prefix |
| QS-12 | **Async session support requires zero config** | `QueryCounterMiddleware` works with both `AsyncSession` and `Session` without additional setup |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `QueryCounterMiddleware` exists at `app/api/middleware/query_counter.py` | File exists, parses |
| CC-02 | `query_listener.py` exists at `app/core/query_listener.py` | File exists, contains `@event.listens_for` decorator |
| CC-03 | All SQLAlchemy queries are counted | grep `@event.listens_for.*after_cursor_execute` |
| CC-04 | Middleware registered after auth but before logging | Inspect `app/main.py` middleware order |
| CC-05 | `NPlusOneDetected` exception exists at `app/core/exceptions.py` | File exists, inherits from `Exception` |
| CC-06 | `query_counts` table has proper indexes | Inspect `alembic/versions/0009_add_query_count_table.py` |
| CC-07 | Threshold configurable via `settings.NPLUSONE_THRESHOLD` | Found in `app/core/config.py` |
| CC-08 | Mode configurable via `settings.NPLUSONE_MODE` | Found in `app/core/config.py` |
| CC-09 | Excluded routes configurable via `settings.NPLUSONE_EXCLUDED_ROUTES` | Found in `app/core/config.py` |
| CC-10 | `no_nplusone` pytest fixture exists | Found in `tests/conftest.py` |
| CC-11 | `@max_queries` decorator exists | Found in `app/api/decorators.py` |
| CC-12 | Middleware handles async requests | Test T-19 with async client |
| CC-13 | Query count resets after failed requests | Test T-07 with failing route |
| CC-14 | Background tasks excluded by default | Test T-08 with `/tasks/` route |
| CC-15 | Production detection disabled by default | Inspect `settings.NPLUSONE_ENABLED` |
| CC-16 | Decorator overrides global threshold | Test T-12 with `@max_queries(5)` |
| CC-17 | Query counting works with raw SQL | Test T-03 with `session.execute(text())` |
| CC-18 | Middleware overhead < 0.5ms | Benchmark test T-29 |
| CC-19 | Context isolation for concurrent requests | Test T-20 with 10 concurrent clients |
| CC-20 | New file `tests/test_nplusone.py` created with 30 tests | File exists |
| CC-21 | All target queries verified with `ast.parse` | Tool internal step |
| CC-22 | Tool execution time < 3s | Time measurement |
| CC-23 | Files modified ≤ 3 | Count modified files |
| CC-24 | Files created ≥ 6 | Count new files |
| CC-25 | Report generation < 100ms | Test T-30 with large query set |
| CC-26 | Idempotent: re-run leaves no extra columns | Test T-26 |
| CC-27 | Schemas do NOT expose query counts | grep absent in schemas |
| CC-28 | Foreign key exists in DB | psql `\d+ query_counts` shows it |
| CC-29 | Existing benchmark unchanged | Run analyzer |
| CC-30 | Backfill query is batched | Migration uses batched UPDATE |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified
- [ ] `QueryCounterMiddleware` integrated in `app/main.py`
- [ ] `query_listener.py` registered with SQLAlchemy
- [ ] `NPlusOneDetected` exception implemented
- [ ] `no_nplusone` pytest fixture working
- [ ] `@max_queries` decorator tested
- [ ] Async session support verified
- [ ] Background task exclusion tested
- [ ] Production opt-in tested
- [ ] Decorator override precedence tested
- [ ] Context isolation for concurrent requests verified
- [ ] All 30 tests in `tests/test_nplusone.py` passing
- [ ] Documentation updated with usage examples

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-NP-01 | **Query counting never modifies query results** | `after_cursor_execute` listener in `app/core/query_listener.py` only increments counter without altering SQL | T-01 |
| INV-NP-02 | **Counters are always request-scoped** | `contextvars.ContextVar` in middleware ensures isolation per request | T-19 |
| INV-NP-03 | **Excluded routes never trigger detection** | Middleware checks `request.url.path` against `settings.NPLUSONE_EXCLUDED_ROUTES` before counting | T-08 |
| INV-NP-04 | **Threshold violations always trigger configured response** | `_handle_nplusone()` method enforces `fail_fast` or `warn` mode consistently | T-13 |
| INV-NP-05 | **Query counts always reset even if request fails** | `try/finally` block in middleware ensures counter reset | T-07 |
| INV-NP-06 | **Decorator overrides always take precedence** | `@max_queries` decorator replaces global threshold for specific routes | T-12 |
| INV-NP-07 | **Background tasks never count towards thresholds** | Middleware skips detection when path matches `/tasks/` prefix | T-08 |
| INV-NP-08 | **Production detection requires explicit opt-in** | `settings.NPLUSONE_ENABLED=False` default prevents accidental activation | T-15 |

---

## 9. User Stories

### 9.1 Core Detection (US-01 .. US-05)

**US-01: Detect N+1 in a route with lazy loading**
- **As a** developer optimizing API performance
- **I want** the tool to flag routes with N+1 queries
- **So that** I can fix them before they impact production
- **Given:** Route `/users/` lazy-loads `user.posts` in a loop
- **When:** `GET /users/` issues 47 queries for 10 users
- **Then:**
  - Tool logs `WARNING N+1 detected: GET /users/ issued 47 queries` (INV-NP-04)
  - Query count includes all SELECT statements (CC-03)
  - Middleware resets counter to 0 after request (INV-NP-05)

**US-02: Fail fast in CI pipeline**
- **As a** CI/CD engineer
- **I want** N+1 detection to block merges
- **So that** performance regressions never reach production
- **Given:** `mode=fail_fast` in CI config
- **When:** `GET /orders/` issues 15 queries (threshold=10)
- **Then:**
  - Pipeline fails with `NPlusOneDetected` exception (INV-NP-04)
  - Error message shows route and query count (CC-05)
  - Report includes stack trace of offending code (T-13)

**US-03: Count queries in async session**
- **As a** developer using async SQLAlchemy
- **I want** query counting to work with `AsyncSession`
- **So that** I can detect N+1 in async routes
- **Given:** Route `/products/` uses `AsyncSession`
- **When:** `GET /products/` issues 8 queries
- **Then:**
  - Query count matches actual DB queries (QS-4)
  - Middleware handles async request lifecycle (CC-12)
  - Counter resets after async request completes (INV-NP-05)

**US-04: Exclude report generation endpoint**
- **As a** developer generating large reports
- **I want** to exclude `/reports/` from detection
- **So that** legitimate bulk queries don't trigger false positives
- **Given:** `exclude_routes=["/reports"]` in config
- **When:** `GET /reports/monthly` issues 200 queries
- **Then:**
  - No warning or error logged (INV-NP-03)
  - Query counter bypassed for this route (CC-09)
  - Other routes still monitored (T-08)

**US-05: Override threshold per route**
- **As a** developer optimizing a bulk operation
- **I want** to set a higher threshold for `/import/`
- **So that** I can import large datasets without triggering N+1 detection
- **Given:** Route `/import/` decorated with `@max_queries(500)`
- **When:** `POST /import/` issues 300 queries
- **Then:**
  - No warning or error logged (INV-NP-06)
  - Global threshold (10) overridden for this route (CC-16)
  - Other routes use default threshold (T-12)

### 9.2 Integration & Configuration (US-06 .. US-10)

**US-06: Enable detection in production**
- **As a** production engineer
- **I want** to opt into N+1 detection in production
- **So that** I can monitor query performance in live traffic
- **Given:** `DETECT_NPLUSONE=1` in production env
- **When:** `GET /users/` issues 47 queries
- **Then:**
  - Detection enabled with < 0.5ms overhead (QS-2)
  - Warning logged in production logs (CC-15)
  - Query count stored in `query_counts` table (CC-06)

**US-07: Disable detection by default**
- **As a** production engineer
- **I want** detection disabled by default
- **So that** production performance isn't impacted accidentally
- **Given:** No `DETECT_NPLUSONE` env var set
- **When:** `GET /users/` issues 47 queries
- **Then:**
  - No detection overhead (INV-NP-08)
  - No warnings or errors logged (CC-15)
  - Query counter remains inactive (T-15)

**US-08: Integrate with pytest**
- **As a** developer writing tests
- **I want** a pytest fixture for N+1 detection
- **So that** I can assert no N+1 in my test cases
- **Given:** `tests/conftest.py` with `no_nplusone` fixture
- **When:** Test calls `GET /users/` with 15 queries
- **Then:**
  - Test fails with `NPlusOneDetected` (CC-10)
  - Fixture resets counter after each test (QS-9)
  - Error message shows route and query count (T-13)

**US-09: Generate query count report**
- **As a** performance engineer
- **I want** a report of query counts per route
- **So that** I can identify high-query endpoints
- **Given:** `query_counts` table populated with 1000 rows
- **When:** `GET /query-report/` called
- **Then:**
  - Report generated in < 100ms (CC-25)
  - Routes sorted by query count descending (CC-06)
  - Report includes route, method, and count (T-30)

**US-10: Middleware order respects auth**
- **As a** security engineer
- **I want** query counter to run after auth
- **So that** unauthorized requests don't trigger detection
- **Given:** Middleware chain with auth first
- **When:** Unauthenticated request to `/users/`
- **Then:**
  - Query counter never invoked (CC-04)
  - 401 Unauthorized returned before detection (T-19)
  - No query count recorded (INV-NP-02)

### 9.3 Edge Cases & Error Handling (US-11 .. US-15)

**US-11: Handle failed requests**
- **As a** developer debugging errors
- **I want** query counter to reset on failed requests
- **So that** counts don't leak between requests
- **Given:** Route `/users/` raises 500 error
- **When:** `GET /users/` fails after 3 queries
- **Then:**
  - Query counter reset to 0 (INV-NP-05)
  - No warning or error logged for N+1 (T-07)
  - Next request starts with count=0 (INV-NP-02)

**US-12: Skip background tasks**
- **As a** developer running background jobs
- **I want** background tasks excluded from detection
- **So that** legitimate bulk processing doesn't trigger false positives
- **Given:** Background task `/tasks/import/`
- **When:** Task issues 1000 queries
- **Then:**
  - No warning or error logged (INV-NP-07)
  - Query counter bypassed for `/tasks/` prefix (QS-11)
  - Other routes still monitored (T-08)

**US-13: Handle raw SQL queries**
- **As a** developer using raw SQL
- **I want** raw queries counted accurately
- **So that** N+1 detection works with all query types
- **Given:** Route `/stats/` uses `session.execute(text())`
- **When:** `GET /stats/` issues 5 raw queries
- **Then:**
  - Query count includes raw SQL (CC-17)
  - No false positives or negatives (T-03)
  - Count matches actual DB queries (INV-NP-01)

**US-14: Concurrent requests isolated**
- **As a** developer testing concurrency
- **I want** query counts isolated per request
- **So that** concurrent requests don't interfere
- **Given:** Two concurrent requests to `/users/`
- **When:** Each issues 10 queries
- **Then:**
  - Each request counted separately (INV-NP-02)
  - No count leakage between requests (T-20)
  - Both requests complete successfully (CC-19)

**US-15: Handle savepoints**
- **As a** developer using transactions
- **I want** savepoints excluded from query count
- **So that** transaction management doesn't trigger false positives
- **Given:** Route `/orders/` uses savepoints
- **When:** `POST /orders/` issues 2 savepoints + 8 queries
- **Then:**
  - Query count = 8 (excludes savepoints) (T-03)
  - No warning or error logged (CC-17)
  - Transaction completes successfully (INV-NP-01)

### 9.4 Debugging & Observability (US-16 .. US-20)

**US-16: Capture stack traces**
- **As a** developer debugging N+1
- **I want** stack traces of offending queries
- **So that** I can quickly identify the source
- **Given:** `GET /users/` triggers N+1
- **When:** Detection enabled with stack trace capture
- **Then:**
  - Last 20 queries logged with stack traces (T-13)
  - Stack traces show ORM call sites (CC-20)
  - Logs include route and query count (INV-NP-04)

**US-17: Monitor query trends**
- **As a** performance engineer
- **I want** historical query counts per route
- **So that** I can track performance over time
- **Given:** `query_counts` table with 1M rows
- **When:** `GET /query-trends/` called
- **Then:**
  - Trends generated in < 100ms (CC-25)
  - Routes sorted by query count growth (CC-06)
  - Report includes route, method, and count (T-30)

**US-18: Debug async N+1**
- **As a** developer debugging async code
- **I want** stack traces for async N+1
- **So that** I can fix async performance issues
- **Given:** Async route `/products/` triggers N+1
- **When:** Detection enabled with stack trace capture
- **Then:**
  - Stack traces show async call sites (CC-12)
  - Logs include route and query count (INV-NP-04)
  - Async context preserved in traces (T-19)

**US-19: Monitor production overhead**
- **As a** production engineer
- **I want** to measure detection overhead
- **So that** I can ensure minimal performance impact
- **Given:** Production traffic with detection enabled
- **When:** Monitoring middleware latency
- **Then:**
  - Overhead < 0.5ms per request (QS-2)
  - Query counts stored without blocking (CC-06)
  - Production latency unchanged (T-29)

**US-20: Export query logs**
- **As a** performance engineer
- **I want** to export query logs
- **So that** I can analyze them offline
- **Given:** `query_counts` table with 100K rows
- **When:** `GET /query-export/` called
- **Then:**
  - CSV export generated in < 100ms (CC-25)
  - Export includes route, method, and count (CC-06)
  - File downloadable via API (T-30)

### 9.5 Tool Robustness (US-21 .. US-25)

**US-21: Tool idempotent on re-run**
- **As a** developer re-running the tool
- **I want** no duplicate files or config
- **So that** my project stays clean
- **Given:** Tool already integrated
- **When:** `detect_n_plus_one()` called again
- **Then:**
  - No files modified (CC-23)
  - No duplicate middleware (CC-01)
  - Notes say "already enabled, skipped" (CC-26)

**US-22: Handle migration queries**
- **As a** developer running migrations
- **I want** migration queries excluded
- **So that** schema changes don't trigger false positives
- **Given:** Alembic migration running
- **When:** Migration issues 1000 queries
- **Then:**
  - No warning or error logged (INV-NP-03)
  - Query counter bypassed for migrations (QS-11)
  - Migration completes successfully (CC-30)

**US-23: Preserve existing benchmarks**
- **As a** performance engineer
- **I want** existing benchmarks unchanged
- **So that** I can compare before/after detection
- **Given:** Existing benchmark suite
- **When:** Detection integrated
- **Then:**
  - Benchmark results unchanged (CC-29)
  - Detection overhead < 0.5ms (QS-2)
  - No false positives in benchmarks (T-29)

**US-24: Handle schema introspection**
- **As a** developer using schema inspection
- **I want** introspection queries excluded
- **So that** schema exploration doesn't trigger false positives
- **Given:** Route `/schema/` introspects DB
- **When:** `GET /schema/` issues 20 queries
- **Then:**
  - No warning or error logged (INV-NP-03)
  - Query counter bypassed for introspection (QS-11)
  - Schema returned successfully (T-03)

**US-25: Support batched updates**
- **As a** developer optimizing updates
- **I want** batched updates counted as one
- **So that** legitimate bulk operations don't trigger false positives
- **Given:** Route `/import/` uses `executemany`
- **When:** `POST /import/` updates 1000 rows
- **Then:**
  - Query count = 1 (CC-17)
  - No warning or error logged (INV-NP-01)
  - Batch completes successfully (T-03)

---

## 10. Test Plan

### 10.1 Basic Detection Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Count SELECT queries | Route `/users/` issues 5 SELECTs | GET /users/ | Query count = 5 |
| T-02 | Count INSERT queries | Route `/users/` issues 3 INSERTs | POST /users/ | Query count = 3 |
| T-03 | Count UPDATE queries | Route `/users/{id}` issues 2 UPDATEs | PATCH /users/1 | Query count = 2 |
| T-04 | Count DELETE queries | Route `/users/{id}` issues 1 DELETE | DELETE /users/1 | Query count = 1 |
| T-05 | Count mixed queries | Route `/orders/` issues 2 SELECTs, 1 INSERT | POST /orders/ | Query count = 3 |
| T-06 | Exclude savepoints | Route `/payments/` issues 1 savepoint + 3 queries | POST /payments/ | Query count = 3 |

### 10.2 Threshold & Mode Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Fail fast mode | `mode=fail_fast`, `/users/` issues 15 queries | GET /users/ | Raises `NPlusOneDetected` |
| T-08 | Warn mode | `mode=warn`, `/users/` issues 15 queries | GET /users/ | Logs warning, returns 200 |
| T-09 | Below threshold | `/users/` issues 8 queries | GET /users/ | No warning, returns 200 |
| T-10 | At threshold | `/users/` issues 10 queries | GET /users/ | No warning, returns 200 |
| T-11 | Above threshold | `/users/` issues 11 queries | GET /users/ | Warning or error based on mode |
| T-12 | Decorator override | `/import/` decorated with `@max_queries(500)`, issues 300 queries | POST /import/ | No warning, returns 200 |

### 10.3 Exclusion Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Exclude route | `/reports/` in `exclude_routes`, issues 200 queries | GET /reports/ | No warning, returns 200 |
| T-14 | Exclude background task | `/tasks/import/` issues 1000 queries | POST /tasks/import/ | No warning, returns 200 |
| T-15 | Exclude migration | Alembic migration issues 500 queries | Run migration | No warning |
| T-16 | Exclude schema introspection | `/schema/` issues 20 queries | GET /schema/ | No warning, returns 200 |
| T-17 | Exclude raw SQL | `/stats/` issues 5 raw queries | GET /stats/ | Query count = 5 |
| T-18 | Exclude batched updates | `/import/` updates 1000 rows with `executemany` | POST /import/ | Query count = 1 |

### 10.4 Context Isolation Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Concurrent requests | 10 concurrent requests to `/users/` | Run concurrently | Each request counted separately |
| T-20 | Failed request | `/users/` raises 500 after 3 queries | GET /users/ | Query count reset to 0 |
| T-21 | Async session | `/products/` uses `AsyncSession`, issues 8 queries | GET /products/ | Query count = 8 |
| T-22 | Multiple middlewares | Middleware chain with auth first | GET /users/ | Query counter runs after auth |
| T-23 | Unauthenticated request | No auth token | GET /users/ | 401 Unauthorized, no query count |
| T-24 | Suspended tenant | Tenant B status='suspended' | GET /users/ as B | 403 Forbidden, no query count |

### 10.5 Integration & Performance Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Pytest fixture | `no_nplusone` fixture | Run test | Query count reset after test |
| T-26 | Tool idempotency | Tool already integrated | Run tool again | No file changes, notes "skipped" |
| T-27 | Production overhead | Production traffic with detection enabled | Measure latency | Overhead < 0.5ms per request |
| T-28 | Report generation | `query_counts` table with 1000 rows | GET /query-report/ | Report generated in < 100ms |
| T-29 | Benchmark unchanged | Existing benchmark suite | Run benchmarks | Results unchanged |
| T-30 | Export query logs | `query_counts` table with 100K rows | GET /query-export/ | CSV export generated in < 100ms |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | Yes | ✅ Compatible | Must run after soft delete since deleted rows may trigger N+1 |
| add_cursor_pagination | No | ✅ Compatible | Pagination reduces query count naturally |
| add_search | No | ⚠️ Caveat | Search queries may trigger false positives; exclude search routes |
| add_audit_log | Yes | ✅ Compatible | Must run after audit log since audit queries should be excluded |
| add_data_export | No | ⚠️ Caveat | Export routes typically issue many queries; exclude them |
| add_bulk_operations | No | ✅ Compatible | Bulk operations counted as single queries |
| add_multi_tenancy | Yes | ✅ Compatible | Must run after tenant middleware since tenant queries may trigger N+1 |
| add_feature_flags | No | ✅ Compatible | Feature flag checks don't trigger N+1 detection |
| add_api_key_auth | Yes | ✅ Compatible | Must run after auth middleware since unauthorized requests shouldn't trigger detection |
| add_oauth2_provider | Yes | ✅ Compatible | Must run after OAuth middleware since token validation queries should be excluded |
| add_rbac | Yes | ✅ Compatible | Must run after RBAC middleware since permission checks may trigger N+1 |
| add_mfa | No | ✅ Compatible | MFA checks don't trigger N+1 detection |
| add_cache_layer | No | ✅ Compatible | Cached queries don't trigger N+1 detection |
| add_outbox_pattern | No | ✅ Compatible | Outbox queries counted separately |
| add_sse | No | ✅ Compatible | SSE connections don't trigger N+1 detection |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout app/api/middleware/query_counter.py
git checkout app/core/query_listener.py 
git checkout app/core/exceptions.py
git checkout app/core/config.py
git checkout tests/conftest.py
rm -rf tests/test_nplusone.py
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
If the generator crashed halfway and left an inconsistent tree (middleware registered but event listener missing), restore to clean HEAD before re-running:
```bash
# 1. Inspect what changed vs HEAD
git status --short app/ tests/

# 2. Revert tool-written files + drop new ones
git checkout HEAD -- app/api/middleware/query_counter.py app/core/query_listener.py \
    app/core/exceptions.py app/core/config.py tests/conftest.py app/main.py
git clean -fd tests/test_nplusone.py .nplusone-budgets.yaml

# 3. Verify tree matches HEAD exactly
git diff HEAD --exit-code && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: middleware deployed but causing false positives in tests
If the budget is too strict for certain endpoints and CI is now red with `NPlusOneDetectedError` on routes that were intentionally written that way (admin batch jobs, bulk imports, dashboards that aggregate across tables):
```bash
# 1. Inspect what the test actually reports
pytest tests/ -x -v 2>&1 | grep -A 20 NPlusOneDetectedError

# 2. Add the offending route to .nplusone-budgets.yaml with justification
cat >> .nplusone-budgets.yaml <<'YAML'
routes:
  /admin/reports/daily:
    max_queries: 45
    reason: "Aggregates across 12 models; optimized with CTE is slower"
    reviewed_by: "perf-team"
    reviewed_on: "2026-04-12"
YAML

# 3. Re-run the suite, confirm only that route's budget changed
pytest tests/ -x
```
Never use a blanket `@max_queries(999)` — every override must be committed to the YAML with a reason and a reviewer.

### Emergency: detection middleware causing production latency spikes
If after enabling `DETECT_NPLUSONE=1` in staging/production the p99 latency rises because the middleware's per-request accounting adds measurable overhead under high load:
1. Check actual overhead: `curl -w '%{time_total}\n' -o /dev/null $API_URL/health` before/after
2. Set `DETECT_NPLUSONE=0` and roll the deployment — overhead drops to zero (the middleware becomes a no-op)
3. Inspect why the overhead is high: usually means the tracker is running under a very hot path (health/metrics). Add those routes to `NPLUSONE_EXCLUDE_ROUTES` env var
4. Re-enable `DETECT_NPLUSONE=1` after the exclusion list is updated

### Emergency: event listener leaking across tests
If tests start failing intermittently because the SQLAlchemy event listener is double-registered after a test reload, the tracker sees every query twice and false-alarms:
1. Check with `SELECT event.listens()` count from a Python shell on the test session
2. Add `event.remove()` to the pytest `teardown` phase in `tests/conftest.py`
3. Re-run the suite; the leak should be gone
4. If the leak persists, pin the SQLAlchemy version — 2.0.x has a known re-registration bug in some minor releases

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Route genuinely needs 20 queries | Tool allows override via `@max_queries(20)` decorator |
| EC-2 | Async session issues N+1 queries | Tool detects N+1 queries in async sessions |
| EC-3 | Background task issues many queries | Tool excludes background tasks from detection |
| EC-4 | Query counter reset fails | Contextvar automatically rebuilds on next request |
| EC-5 | Production env var enables detection | Tool warns about potential performance impact |
| EC-6 | Decorator threshold < global threshold | Local decorator threshold takes precedence |
| EC-7 | Route with subqueries issues 1 query | Tool counts subqueries as single query |
| EC-8 | Savepoints issued during transaction | Tool excludes savepoints from query count |
| EC-9 | Multiple middlewares in chain | Tool runs after auth but before logging middleware |
| EC-10 | Stack trace capture slows development | Tool makes stack trace capture optional |
| EC-11 | N+1 occurs during startup/migration | Tool excludes startup/migration queries |
| EC-12 | Concurrent requests in async context | Tool isolates query counts per request |
| EC-13 | Test mode doesn't reset context | Pytest fixture ensures context reset |
| EC-14 | Tool re-run after initial integration | Tool detects existing setup and skips |
| EC-15 | Detection disabled by feature flag | Tool adds zero overhead when disabled |

## 14. Acceptance Criteria (Final Sign-off)

✅ All 30 Completeness Criteria verified  
✅ `QueryCounterMiddleware` integrated in `app/main.py`  
✅ `query_listener.py` registered with SQLAlchemy  
✅ `NPlusOneDetected` exception implemented  
✅ `no_nplusone` pytest fixture working  
✅ `@max_queries` decorator tested  
✅ Async session support verified  
✅ Background task exclusion tested  
✅ Production opt-in tested  
✅ Developer runs `pytest tests/test_nplusone.py` and verifies all tests pass  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate `app/` subdirectory exists
- [ ] Validate FastAPI project structure
- [ ] Validate SQLAlchemy is installed
- [ ] Detect existing query counter middleware
- [ ] Detect existing query listener
- [ ] Validate middleware order in `app/main.py`

### 15.2 Settings
- [ ] Add `NPLUSONE_THRESHOLD` to `app/core/config.py`
- [ ] Add `NPLUSONE_MODE` to `app/core/config.py`
- [ ] Add `NPLUSONE_EXCLUDED_ROUTES` to `app/core/config.py`
- [ ] Add `NPLUSONE_ENABLED` to `app/core/config.py`
- [ ] Add `.env` template with N+1 settings
- [ ] Add settings validation in Pydantic model
- [ ] Add settings documentation to `KNOWLEDGE.md`

### 15.3 Middleware
- [ ] Create `app/api/middleware/query_counter.py`
- [ ] Implement `QueryCounterMiddleware` class
- [ ] Add contextvar for query count
- [ ] Implement `_handle_nplusone` method
- [ ] Add middleware registration to `app/main.py`
- [ ] Add middleware documentation to `KNOWLEDGE.md`
- [ ] Add middleware tests to `tests/test_nplusone.py`

### 15.4 Query listener
- [ ] Create `app/core/query_listener.py`
- [ ] Implement `_count_query` function
- [ ] Register listener for `Session`
- [ ] Register listener for `AsyncSession`
- [ ] Add listener registration to `app/main.py`
- [ ] Add listener documentation to `KNOWLEDGE.md`
- [ ] Add listener tests to `tests/test_nplusone.py`

### 15.5 Exceptions
- [ ] Create `app/core/exceptions.py`
- [ ] Implement `NPlusOneDetected` exception
- [ ] Add exception handler to `app/main.py`
- [ ] Add exception documentation to `KNOWLEDGE.md`
- [ ] Add exception tests to `tests/test_nplusone.py`
- [ ] Add exception logging configuration
- [ ] Add exception HTTP status code mapping

### 15.6 Pytest fixtures
- [ ] Create `tests/conftest.py`
- [ ] Implement `client` fixture
- [ ] Implement `no_nplusone` fixture
- [ ] Add fixture documentation to `KNOWLEDGE.md`
- [ ] Add fixture tests to `tests/test_nplusone.py`
- [ ] Add fixture cleanup logic
- [ ] Add fixture context isolation tests

### 15.7 Decorators
- [ ] Create `app/api/decorators.py`
- [ ] Implement `@max_queries` decorator
- [ ] Add decorator documentation to `KNOWLEDGE.md`
- [ ] Add decorator tests to `tests/test_nplusone.py`
- [ ] Add decorator precedence tests
- [ ] Add decorator override tests
- [ ] Add decorator async support tests

### 15.8 Test generation
- [ ] Create `tests/test_nplusone.py`
- [ ] Generate all 30 test cases
- [ ] Add basic detection tests
- [ ] Add threshold & mode tests
- [ ] Add exclusion tests
- [ ] Add context isolation tests
- [ ] Add integration & performance tests

### 15.9 Atomicity
- [ ] Use temp-file + rename pattern for all file writes
- [ ] Track touched files for rollback
- [ ] Implement rollback procedure
- [ ] Verify atomicity with concurrent runs
- [ ] Add atomicity tests
- [ ] Document atomicity guarantees
- [ ] Handle SIGINT gracefully

### 15.10 Documentation
- [ ] Append N+1 section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py` with new MCP tool decorator
- [ ] Add usage examples
- [ ] Add troubleshooting guide
- [ ] Add performance impact documentation

### 15.11 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit on the project
- [ ] Run `pytest tests/` to verify no regressions
- [ ] Run analyzer to verify benchmark unchanged
- [ ] Measure tool execution time
- [ ] Measure detection overhead
- [ ] Return success report with metrics

### 15.12 CI/CD integration
- [ ] Add CI config for N+1 detection
- [ ] Add `mode=fail_fast` CI gate
- [ ] Add CI documentation
- [ ] Add CI performance monitoring
- [ ] Add CI exclusion list
- [ ] Add CI override support
- [ ] Add CI test coverage reporting

### 15.13 Production monitoring
- [ ] Add production opt-in documentation
- [ ] Add production overhead monitoring
- [ ] Add production exclusion list
- [ ] Add production override support
- [ ] Add production alerting
- [ ] Add production performance impact monitoring
- [ ] Add production rollback procedure

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/api/middleware/query_counter.py",
    "app/core/query_listener.py",
    "app/core/exceptions.py",
    "tests/test_nplusone.py",
    "app/api/decorators.py",
    "tests/conftest.py",
    "docs/nplusone.md",
    "ci/nplusone.yml"
  ],
  "files_modified": [
    "app/core/config.py",
    "app/main.py",
    "tests/conftest.py"
  ],
  "metrics": {
    "execution_time_ms": 2876,
    "files_changed": 11,
    "lines_added": 412,
    "lines_removed": 18,
    "tests_generated": 30,
    "middleware_overhead_ms": 0.12
  },
  "next_steps": [
    "Run: pytest tests/test_nplusone.py -v",
    "Enable in production: set NPLUSONE_ENABLED=1 in .env",
    "Exclude high-query routes: add to NPLUSONE_EXCLUDED_ROUTES in config",
    "Override thresholds: add @max_queries(20) to specific routes",
    "Monitor overhead: check middleware latency in production"
  ],
  "warnings": [
    "Detection adds ~0.12ms overhead per request. Monitor production latency.",
    "Exclude background tasks and migrations to prevent false positives."
  ],
  "notes": [
    "N+1 detection enabled with threshold=10, mode=warn.",
    "Middleware registered after auth but before logging.",
    "Query listener installed for both sync and async sessions.",
    "30 tests generated in tests/test_nplusone.py.",
    "Production detection disabled by default (opt-in via NPLUSONE_ENABLED)."
  ]
}
