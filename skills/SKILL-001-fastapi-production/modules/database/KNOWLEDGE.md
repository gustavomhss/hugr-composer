# Module: Database — Production PostgreSQL + Async SQLAlchemy for FastAPI

> The LLM generates: `create_engine()` + synchronous sessions + no pool config + `Session(autocommit=True)`.
> The staff engineer knows: async engine with pool sizing, expire_on_commit=False, raiseload for N+1 prevention, advisory locks, zero-downtime migrations, EXPLAIN ANALYZE interpretation.

---

## 1. Async Session Factory with Auto Commit/Rollback

### WHY
SQLAlchemy 2.0+ with asyncpg is the standard for FastAPI. The critical difference from sync: you MUST set `expire_on_commit=False`. In async mode, accessing an expired attribute after commit triggers a lazy load, which requires I/O -- but there is no running event loop context to do that load. Your code will raise `MissingGreenlet` or silently return stale data. The official SQLAlchemy docs explicitly state: "expire_on_commit should normally be set to False when using asyncio."

### HOW
```python
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# One engine per process -- NEVER per-request
engine = create_async_engine(
    settings.database_url,  # "postgresql+asyncpg://..."
    pool_size=5,
    max_overflow=10,
    pool_recycle=1800,
    pool_pre_ping=True,
    echo=settings.debug,  # SQL logging only in dev
)

# Factory -- NOT a session. Create sessions per-request.
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # CRITICAL for async
)


# FastAPI dependency with auto commit/rollback
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Type alias for route signatures
from typing import Annotated
from fastapi import Depends

SessionDep = Annotated[AsyncSession, Depends(get_session)]


# Usage in a route
@app.post("/users", status_code=201)
async def create_user(body: CreateUser, session: SessionDep):
    user = User(**body.model_dump())
    session.add(user)
    # commit happens automatically when request completes
    await session.flush()  # get user.id without committing
    return {"id": user.id}
```

### GOTCHA
- `expire_on_commit=False` means attributes retain their in-memory values after commit. If another process modifies the same row, your session will NOT see the change until you explicitly `await session.refresh(obj)`.
- Never call `session.commit()` inside the route body -- let the dependency handle it. If the route raises, the dependency rolls back.
- The engine MUST be disposed in the lifespan shutdown to close all pooled connections cleanly.

---

## 2. Connection Pool Sizing -- Real Production Numbers

### WHY
PostgreSQL defaults to `max_connections = 100`. SQLAlchemy's pool default is `pool_size=5, max_overflow=10`, meaning each process can open up to 15 connections. With 4 Uvicorn workers, that is 60 connections. With 4 Kubernetes pods, that is 240 -- already exceeding `max_connections`. This causes `FATAL: too many connections` at 2 AM when traffic spikes and autoscaling kicks in.

### HOW
```python
# Formula: total_connections = workers * pods * (pool_size + max_overflow)
# Target: total_connections <= max_connections - reserved_connections

# Example: 4 workers, 3 pods, max_connections=200, reserved=20 (for admin/migrations)
# Budget per process: (200 - 20) / (4 * 3) = 15 connections
# So: pool_size=5, max_overflow=10 (5 + 10 = 15) -- exactly right

engine = create_async_engine(
    database_url,
    pool_size=5,          # Persistent idle connections per worker
    max_overflow=10,       # Burst connections (closed after use)
    pool_recycle=1800,     # Recycle connections every 30min (prevent stale TCP)
    pool_pre_ping=True,    # Test connection before checkout (catches dead connections)
    pool_timeout=30,       # Wait max 30s for a connection from pool
    pool_reset_on_return="rollback",  # Clean state on return to pool
)
```

### Pool Parameter Reference

| Parameter | Default | Recommended | Why |
|-----------|---------|-------------|-----|
| `pool_size` | 5 | 3-10 | Idle connections held open. Higher = faster checkout, more memory |
| `max_overflow` | 10 | 5-20 | Extra connections for bursts. Closed when returned if pool is full |
| `pool_recycle` | -1 (never) | 1800 | Seconds before connection is recycled. Prevents stale TCP connections behind load balancers and PgBouncer |
| `pool_pre_ping` | False | True | Issues `SELECT 1` before checkout. Adds ~1ms latency but catches dead connections (essential with cloud DBs) |
| `pool_timeout` | 30 | 30 | Seconds to wait for connection from pool before raising `TimeoutError` |

### GOTCHA
- `pool_recycle` matters behind load balancers that silently kill idle TCP connections (AWS ALB: 350s, PgBouncer: configurable). Set to less than the LB idle timeout.
- `pool_pre_ping=True` adds negligible overhead (~1ms per checkout) but prevents `connection was closed` errors that crash your request handler.
- If using PgBouncer in transaction mode, set `pool_size=1, max_overflow=0` on SQLAlchemy -- let PgBouncer handle pooling.
- The formula `(vCPU * 2) + spare` is a good starting point for `pool_size` per process, but measure under real load using `pg_stat_activity`.

---

## 3. Alembic Async Migrations (env.py with run_async)

### WHY
Alembic's core migration engine is synchronous, but your FastAPI app uses `asyncpg`. You need an async `env.py` so migrations can run against the same connection string (`postgresql+asyncpg://...`) without maintaining a separate sync driver. Alembic provides an official `async` template since Alembic 1.13+.

### HOW
```bash
# Initialize with async template
alembic init -t async alembic
```

```python
# alembic/env.py -- async version
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.models.base import Base  # Your declarative base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from settings (NEVER hardcode in alembic.ini)
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def do_run_migrations(connection):
    """Synchronous migration runner -- called inside async context."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,       # Detect column type changes
        compare_server_default=True,  # Detect default value changes
        render_as_batch=False,   # True for SQLite
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    """Create async engine and run migrations within async transaction."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # No pool for migrations
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online():
    """Entry point -- handles both sync and async execution."""
    asyncio.run(run_async_migrations())


run_migrations_online()
```

### GOTCHA
- Use `poolclass=pool.NullPool` for migrations -- you do NOT want connection pooling during schema changes.
- NEVER hardcode the database URL in `alembic.ini`. Override it in `env.py` from your app settings.
- `compare_type=True` enables autogenerate to detect column type changes (e.g., `String(50)` to `String(100)`). Without it, type changes are silently ignored.
- Always review autogenerated migrations. Alembic cannot detect renamed columns (it sees a drop + add), index reordering, or CHECK constraint changes.
- If running in an environment where an event loop already exists (e.g., Jupyter), use `asyncio.get_event_loop().run_until_complete()` instead of `asyncio.run()`.

---

## 4. N+1 Query Prevention (selectinload, joinedload, raiseload)

### WHY
N+1 is the #1 ORM performance killer. A query for 100 orders that accesses `order.items` triggers 100 additional queries. In a real 2025 case study, migrating to `selectinload` on user-facing queries reduced query count by 56x and p99 latency from 4.2s to 45ms. SQLAlchemy 2.0 makes this explicit: relationships are lazy by default, and you MUST opt in to eager loading.

### HOW
```python
from sqlalchemy.orm import selectinload, joinedload, raiseload, relationship

# --- Model definition ---
class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # Default: lazy="select" (triggers N+1 if accessed in a loop)
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")
    user: Mapped["User"] = relationship()


# --- CORRECT: Eager loading at query time ---

# selectinload -- BEST for collections (one-to-many, many-to-many)
# Issues: SELECT * FROM order_items WHERE order_id IN (1, 2, 3, ...)
stmt = select(Order).options(selectinload(Order.items))

# joinedload -- BEST for single relations (many-to-one, one-to-one)
# Issues: SELECT ... FROM orders JOIN users ON ...
stmt = select(Order).options(joinedload(Order.user))

# Combined -- load order + user + items in exactly 2 queries
stmt = (
    select(Order)
    .options(joinedload(Order.user))
    .options(selectinload(Order.items))
)

# --- SAFETY NET: raiseload to CATCH N+1 in development ---

# raiseload -- raises InvalidRequestError if lazy load is triggered
# Use this to find ALL N+1 bugs during development
stmt = select(Order).options(
    raiseload(Order.items),
    raiseload(Order.user),
)
# Accessing order.items will RAISE instead of silently issuing a query

# Global raiseload on all relationships (development only)
stmt = select(Order).options(raiseload("*"))
```

### When to Use Which

| Strategy | When | SQL Pattern | Rows Returned |
|----------|------|-------------|---------------|
| `selectinload` | One-to-many, many-to-many | `SELECT ... WHERE id IN (...)` | No row multiplication |
| `joinedload` | Many-to-one, one-to-one | `JOIN` | Possible row multiplication |
| `subqueryload` | Large collections | Correlated subquery | No row multiplication |
| `raiseload` | Development/safety net | N/A -- raises exception | N/A |

### GOTCHA
- `joinedload` on collections causes row multiplication. If an order has 10 items, the JOIN returns 10 rows per order. For 100 orders with 10 items each, you get 1,000 rows instead of 100 + 100.
- `selectinload` issues a separate `SELECT ... WHERE fk IN (...)` query. This avoids row multiplication but adds one extra round-trip. For most cases this is the correct choice for collections.
- `raiseload("*")` prevents ALL lazy loads on all relationships. Use it in development to find N+1 bugs, but remove it in production (or make it configurable).
- In async mode, lazy loading is not supported at all unless you use the `AsyncAttrs` mixin. Without it, accessing an unloaded relationship raises `MissingGreenlet`. This is actually a FEATURE -- it forces you to be explicit about loading.

---

## 5. Multi-Tenancy Patterns

### WHY
Multi-tenancy is a spectrum, not a binary choice. The right pattern depends on your compliance requirements, tenant count, and data volume. Picking wrong means a painful migration later. PostgreSQL supports all three patterns natively.

### HOW

#### Pattern A: Tenant Column + WHERE (simplest, 1-10K tenants)
```python
# Model
class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(200))

# Every query must include tenant_id
stmt = select(Document).where(Document.tenant_id == current_tenant_id)

# Danger: forgetting the WHERE clause leaks data across tenants
# Solution: use a dependency that injects the tenant filter
async def get_tenant_session(
    session: SessionDep,
    tenant_id: str = Depends(get_current_tenant),
) -> tuple[AsyncSession, str]:
    return session, tenant_id
```

#### Pattern B: Row-Level Security (database-enforced, 1-100K tenants)
```sql
-- Enable RLS on the table
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

-- Policy: users can only see their tenant's rows
CREATE POLICY tenant_isolation ON documents
    USING (tenant_id = current_setting('app.current_tenant')::text);

-- Force RLS even for table owners
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
```

```python
# Set the tenant context before each request
@app.middleware("http")
async def set_tenant_context(request: Request, call_next):
    tenant_id = get_tenant_from_token(request)
    async with async_session_factory() as session:
        await session.execute(
            text("SET LOCAL app.current_tenant = :tid"),
            {"tid": tenant_id},
        )
        # All subsequent queries in this transaction are automatically filtered
        response = await call_next(request)
    return response
```

#### Pattern C: Schema Per Tenant (strongest isolation, 1-1K tenants)
```python
# Create schema for each tenant
await session.execute(text(f"CREATE SCHEMA IF NOT EXISTS tenant_{tenant_id}"))

# Set search_path per request
await session.execute(
    text(f"SET search_path TO tenant_{tenant_id}, public")
)

# Alembic: run migrations against each schema
for schema in tenant_schemas:
    with engine.connect() as conn:
        conn.execute(text(f"SET search_path TO {schema}"))
        context.configure(connection=conn, target_metadata=metadata)
        context.run_migrations()
```

### Decision Matrix

| Factor | Tenant Column | RLS | Schema |
|--------|---------------|-----|--------|
| Setup complexity | Low | Medium | High |
| Query safety | App-enforced (leak risk) | DB-enforced (secure) | Physical isolation |
| Tenant count | Unlimited | Unlimited | ~1K (connection overhead) |
| Migration complexity | One migration | One migration | N migrations (per schema) |
| Cross-tenant queries | Easy | Needs `SET ROLE` | Needs `UNION ALL` |
| Compliance (SOC2, HIPAA) | Weak | Medium | Strong |
| Resource isolation | None | None (shared CPU/IO) | Partial (shared instance) |

### GOTCHA
- RLS with `current_setting()` requires `SET LOCAL` (transaction-scoped), NOT `SET` (session-scoped). With connection pooling, `SET` leaks the tenant context to the next request that reuses the connection.
- RLS adds ~2-5% query overhead due to the automatic WHERE clause injection. Measure on your workload.
- Schema per tenant breaks down above ~1,000 schemas. PostgreSQL's catalog gets slow, and `pg_dump` becomes unusable.
- The tenant_id column approach is the most common in practice. Combine it with RLS for defense-in-depth: the app filters by tenant_id, AND the DB enforces it via RLS policy.

---

## 6. Index Strategy (Partial, Covering/INCLUDE, Composite Order)

### WHY
Wrong indexes waste disk space and slow down writes with zero benefit. Right indexes turn a 4-second query into 2ms. PostgreSQL supports partial indexes (index only active records), covering indexes with INCLUDE (avoid heap lookups), composite indexes (column order matters), and hash indexes (equality-only, faster than B-tree for exact matches).

### HOW
```sql
-- PARTIAL INDEX: only index rows you actually query
-- 95% of orders are completed. You only query active ones.
CREATE INDEX idx_orders_active ON orders (created_at)
    WHERE status = 'active';
-- This index is 20x smaller than indexing all orders.
-- Queries must include WHERE status = 'active' to use it.

-- COVERING INDEX (INCLUDE): avoid heap lookup entirely
-- When all selected columns are in the index, PostgreSQL does an
-- Index Only Scan -- never touches the table heap.
CREATE INDEX idx_users_email_covering ON users (email)
    INCLUDE (id, name);
-- SELECT id, name FROM users WHERE email = 'x' -> Index Only Scan

-- COMPOSITE INDEX: column order is LEFT-TO-RIGHT
-- This index supports: WHERE tenant_id = X
--                       WHERE tenant_id = X AND status = Y
--                       WHERE tenant_id = X AND status = Y AND created_at > Z
-- But NOT: WHERE status = Y (skips the leading column)
CREATE INDEX idx_orders_tenant_status ON orders (tenant_id, status, created_at);

-- HASH INDEX: fastest for equality-only (no range, no sort)
CREATE INDEX idx_sessions_token ON sessions USING hash (session_token);
-- Only supports: WHERE session_token = 'abc123'
-- Cannot do: WHERE session_token > 'abc' or ORDER BY session_token
-- 30% faster than B-tree for equality, crash-safe since PostgreSQL 10

-- FOREIGN KEY indexes (PostgreSQL does NOT auto-create these)
-- Without this, DELETE on parent table does a sequential scan on child
CREATE INDEX idx_order_items_order_id ON order_items (order_id);
```

### GOTCHA
- PostgreSQL does NOT automatically create indexes on foreign keys. Every FK column should have an explicit index, or DELETE/UPDATE on the parent table will do a sequential scan on the child table.
- Composite index column order matters. The leading column must appear in the WHERE clause. `(a, b, c)` supports `WHERE a = ?`, `WHERE a = ? AND b = ?`, `WHERE a = ? AND b = ? AND c = ?`. It does NOT support `WHERE b = ?` alone.
- Partial indexes ONLY work when the query predicate matches the index WHERE clause exactly. `WHERE status = 'active'` uses the index; `WHERE status IN ('active', 'pending')` does NOT.
- INCLUDE columns are stored in the index leaf pages but NOT in the B-tree structure. They cannot be used for filtering or sorting -- only for returning data in an Index Only Scan.
- Hash indexes do not support `UNIQUE` constraints. If you need unique enforcement, use B-tree.

---

## 7. EXPLAIN ANALYZE Reading Guide

### WHY
Blind index creation is cargo cult. EXPLAIN ANALYZE shows you the actual execution plan, actual row counts, and actual time. Without it, you are guessing. A Seq Scan on a 10M-row table is a problem. A Seq Scan on a 100-row lookup table is optimal (the entire table fits in one disk page).

### HOW
```sql
-- Always use ANALYZE (runs the query) + BUFFERS (shows I/O)
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT * FROM orders WHERE user_id = 42 AND status = 'active';

-- Example output (PROBLEM):
-- Seq Scan on orders  (cost=0.00..28547.00 rows=15 width=120)
--                      (actual time=1203.412..1847.221 rows=12 loops=1)
--   Filter: ((user_id = 42) AND (status = 'active'))
--   Rows Removed by Filter: 1000000
--   Buffers: shared read=14284
-- Planning Time: 0.121 ms
-- Execution Time: 1847.445 ms

-- Translation: Scanned 1,000,012 rows to find 12. Took 1.8 seconds.
-- Fix: CREATE INDEX idx_orders_user_status ON orders (user_id, status);

-- Example output (GOOD):
-- Index Scan using idx_orders_user_status on orders
--                      (cost=0.42..24.45 rows=12 width=120)
--                      (actual time=0.031..0.052 rows=12 loops=1)
--   Index Cond: ((user_id = 42) AND (status = 'active'))
--   Buffers: shared hit=4
-- Planning Time: 0.098 ms
-- Execution Time: 0.073 ms

-- Translation: Read exactly 12 rows via index. 4 buffer hits (all from cache).
-- 0.073ms vs 1847ms = 25,000x improvement.
```

### What to Look For

| Signal | Meaning | Action |
|--------|---------|--------|
| `Seq Scan` on >10K rows | Full table scan | Add index on filter columns |
| `Seq Scan` on <1K rows | Normal (too small for index) | Leave it |
| `Rows Removed by Filter: 999988` | Index exists but is not selective | Composite or partial index |
| `Buffers: shared read=14284` | Cold cache (disk I/O) | Normal on first run |
| `Buffers: shared hit=4` | Warm cache (memory) | Good |
| `Bitmap Heap Scan` | Between index and seq scan | Fine for 1-15% selectivity |
| `Index Only Scan` | Best case (no heap access) | VACUUM regularly to keep visibility map current |
| `Sort` + `external merge Disk` | Sort spilled to disk | Increase `work_mem` or add index for ORDER BY |
| `Nested Loop` with high `loops=` | N+1 at SQL level | Consider `Hash Join` via different query structure |
| `actual rows=1000` vs `rows=1` (estimated) | Bad statistics | Run `ANALYZE tablename` |

### GOTCHA
- `cost=0.00..28547.00` is in arbitrary "cost units", not milliseconds. Only `actual time` is real wall-clock time.
- `rows=15` (estimated) vs `actual rows=12` shows a small estimation error. If estimated is 1 and actual is 100K, run `ANALYZE` to update statistics.
- `EXPLAIN ANALYZE` actually EXECUTES the query. For destructive queries (UPDATE, DELETE), wrap in a transaction and rollback: `BEGIN; EXPLAIN ANALYZE DELETE FROM ...; ROLLBACK;`
- `Buffers: shared read` = disk reads. `shared hit` = cache hits. High `read` on a warm system means your dataset exceeds `shared_buffers`.

---

## 8. Batch Operations (COPY, Core INSERT, executemany)

### WHY
Inserting 100K rows one-by-one takes 45 seconds. Using `session.add()` in a loop: 30 seconds. Using Core `insert().values()`: 2 seconds. Using PostgreSQL `COPY`: 0.3 seconds. The ORM adds overhead per row (identity map, event hooks, state tracking). For bulk operations, bypass it.

### HOW
```python
# --- Level 1: ORM add_all (slowest, but tracks objects) ---
# Use when: you need the ORM objects after insert (e.g., for relationships)
users = [User(name=f"user_{i}") for i in range(1000)]
session.add_all(users)
await session.flush()  # all 1000 get IDs via RETURNING


# --- Level 2: Core INSERT with executemany (fast, no ORM overhead) ---
# Use when: bulk import, no need for ORM objects after insert
from sqlalchemy import insert

stmt = insert(User).values([
    {"name": f"user_{i}", "email": f"user_{i}@example.com"}
    for i in range(10_000)
])
await session.execute(stmt)
# With psycopg/asyncpg, SQLAlchemy batches this into efficient multi-row INSERT


# --- Level 3: Core INSERT with RETURNING (fast + get IDs back) ---
stmt = (
    insert(User)
    .values([{"name": f"user_{i}"} for i in range(10_000)])
    .returning(User.id, User.name)
)
result = await session.execute(stmt)
inserted = result.all()  # [(1, "user_0"), (2, "user_1"), ...]


# --- Level 4: PostgreSQL COPY (fastest, raw protocol) ---
# Use when: importing millions of rows (ETL, data migration)
import asyncpg

# Direct asyncpg COPY (bypasses SQLAlchemy entirely)
raw_conn = await engine.raw_connection()
asyncpg_conn = raw_conn.connection._connection  # underlying asyncpg connection
await asyncpg_conn.copy_records_to_table(
    "users",
    records=[(f"user_{i}", f"user_{i}@example.com") for i in range(1_000_000)],
    columns=["name", "email"],
)
await raw_conn.close()


# --- Batch UPDATE (efficient mass update) ---
from sqlalchemy import update

stmt = (
    update(Order)
    .where(Order.status == "pending")
    .where(Order.created_at < cutoff_date)
    .values(status="expired")
)
result = await session.execute(stmt)
print(f"Expired {result.rowcount} orders")
```

### GOTCHA
- `session.add_all()` still issues one INSERT per row with most drivers (except psycopg2/psycopg3 with `executemany_mode='values_plus_batch'`). For true bulk, use Core `insert().values()`.
- PostgreSQL COPY is 10-50x faster than INSERT but bypasses triggers, constraints (checked after COPY), and the ORM entirely. Use for ETL only.
- For bulk upsert (INSERT ... ON CONFLICT), use `from sqlalchemy.dialects.postgresql import insert as pg_insert` and call `.on_conflict_do_update()`.
- In async mode, `bulk_save_objects()` is NOT available on `AsyncSession`. Use Core `insert().values()` instead.

---

## 9. Advisory Locks for Job Queues

### WHY
`SELECT ... FOR UPDATE` blocks all other workers trying to lock the same rows. With 10 workers competing for jobs, 9 are waiting. Advisory locks are held in memory (no disk write), do not block other lock attempts (with `pg_try_advisory_lock`), and are automatically released at session end. Job queues like `que` (Ruby) and `procrastinate` (Python) use advisory locks for exactly this reason.

### HOW
```python
# --- Pattern 1: Try-lock for job dequeue (non-blocking) ---
async def dequeue_job(session: AsyncSession) -> Job | None:
    """Dequeue next available job using advisory lock. Non-blocking."""
    # Find oldest pending job that no other worker has locked
    result = await session.execute(text("""
        SELECT id, payload
        FROM jobs
        WHERE status = 'pending'
          AND pg_try_advisory_lock(hashtext('job_' || id::text))
        ORDER BY created_at
        LIMIT 1
    """))
    row = result.first()
    if row is None:
        return None

    # Mark as processing (we hold the advisory lock)
    await session.execute(text("""
        UPDATE jobs SET status = 'processing', started_at = now()
        WHERE id = :id
    """), {"id": row.id})

    return Job(id=row.id, payload=row.payload)


# --- Pattern 2: Application-level distributed lock ---
async def with_advisory_lock(
    session: AsyncSession,
    lock_key: int,
) -> bool:
    """Acquire a session-level advisory lock. Returns True if acquired."""
    result = await session.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": lock_key},
    )
    return result.scalar()


# --- Pattern 3: SKIP LOCKED (alternative, simpler) ---
# PostgreSQL 9.5+ -- skip rows locked by other transactions
async def dequeue_with_skip_locked(session: AsyncSession) -> Job | None:
    result = await session.execute(text("""
        SELECT id, payload
        FROM jobs
        WHERE status = 'pending'
        ORDER BY created_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    """))
    row = result.first()
    if row is None:
        return None

    await session.execute(text("""
        UPDATE jobs SET status = 'processing' WHERE id = :id
    """), {"id": row.id})

    return Job(id=row.id, payload=row.payload)
```

### Advisory Lock vs SELECT FOR UPDATE

| Feature | Advisory Lock | FOR UPDATE SKIP LOCKED |
|---------|--------------|------------------------|
| Blocking | Non-blocking (`pg_try_`) | Non-blocking (SKIP LOCKED) |
| Disk I/O | None (in-memory) | Row-level lock (disk write on UPDATE) |
| Table bloat | None | Creates dead tuples on UPDATE |
| Auto-release | Session end or explicit | Transaction end |
| Throughput | Higher (no disk write for lock) | Lower (disk write per lock) |
| Complexity | Higher (must manage lock IDs) | Lower (standard SQL) |

### GOTCHA
- `pg_try_advisory_lock` returns `false` if the lock is already held -- it does NOT block. `pg_advisory_lock` (without `try`) BLOCKS until acquired.
- Advisory locks are per-session (connection), not per-transaction by default. Use `pg_try_advisory_xact_lock` for transaction-scoped locks that auto-release on commit/rollback.
- Lock keys are 64-bit integers. Use `hashtext('meaningful_name')` to convert strings to lock keys deterministically.
- With connection pooling (PgBouncer), advisory locks can leak between requests if the pool reuses the connection. Use transaction-scoped advisory locks (`pg_try_advisory_xact_lock`) with PgBouncer.

---

## 10. Soft Delete vs Hard Delete

### WHY
Hard delete is permanent -- data is gone. Soft delete marks rows with `deleted_at` timestamp, keeping them for audit trails, undo functionality, and compliance (GDPR requires you to know what was deleted). The trade-off: every query must filter `WHERE deleted_at IS NULL`, and your database grows forever unless you purge old soft-deleted rows.

### HOW
```python
from datetime import datetime, timezone
from sqlalchemy import DateTime, event
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase


class Base(DeclarativeBase):
    """Base model with timestamps and optional soft delete."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SoftDeleteMixin:
    """Mixin that adds soft delete capability to any model."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        index=True,  # Partial index recommended (see below)
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)

    def restore(self) -> None:
        self.deleted_at = None


class User(Base, SoftDeleteMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)


# --- Querying with soft delete ---

# Active records only (default)
stmt = select(User).where(User.deleted_at.is_(None))

# Include soft-deleted records (admin view)
stmt = select(User)  # no filter

# Only soft-deleted records (for restore UI)
stmt = select(User).where(User.deleted_at.isnot(None))


# --- Partial index for performance ---
# Only index non-deleted rows (the ones you actually query)
# CREATE INDEX idx_users_email_active ON users (email) WHERE deleted_at IS NULL;
```

```sql
-- Partial index: only index active (non-deleted) rows
CREATE INDEX idx_users_email_active ON users (email) WHERE deleted_at IS NULL;

-- Unique constraint on active records only
CREATE UNIQUE INDEX idx_users_email_unique_active ON users (email)
    WHERE deleted_at IS NULL;
-- This allows: deleted user "alice@example.com" + active "alice@example.com"

-- Purge old soft-deleted rows (run monthly via cron)
DELETE FROM users WHERE deleted_at < now() - interval '90 days';
```

### GOTCHA
- The biggest risk: forgetting `.where(deleted_at.is_(None))` in a query. One missed filter leaks deleted data. Consider using a custom query class or SQLAlchemy event hook that auto-injects the filter (libraries like `sqlalchemy-easy-softdelete` do this).
- Soft delete breaks unique constraints. If you soft-delete user "alice@example.com" and a new user registers with the same email, you need a partial unique index `WHERE deleted_at IS NULL`.
- Soft-deleted rows still consume disk space and slow down queries. Schedule a purge job to hard-delete rows past your retention period (e.g., 90 days).
- For GDPR "right to erasure", soft delete is NOT sufficient. You must eventually hard delete or anonymize the personal data fields.

---

## 11. Database Testing with Test Transactions

### WHY
Running tests against a real database catches bugs that mocks miss: constraint violations, migration issues, query performance. But each test must see a clean state. The pattern: wrap each test in a SAVEPOINT, roll it back after the test. Tests run against real PostgreSQL but leave no data behind.

### HOW
```python
# conftest.py
import asyncio
import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.models.base import Base


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for all tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def engine():
    """Create test engine once for the entire test session."""
    engine = create_async_engine(
        "postgresql+asyncpg://test:test@localhost:5432/test_db",
        echo=False,
    )
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def session(engine):
    """
    Per-test session wrapped in a SAVEPOINT.

    Each test sees a clean database. All changes are rolled back after
    the test completes, even if the test commits.
    """
    async with engine.connect() as conn:
        # Start an outer transaction
        trans = await conn.begin()

        # Bind a session to this connection with SAVEPOINT behavior
        async_session = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

        async with async_session() as session:
            yield session

        # Rollback the outer transaction -- all test data vanishes
        await trans.rollback()


# --- Usage in tests ---

@pytest.mark.asyncio
async def test_create_user(session: AsyncSession):
    user = User(email="test@example.com", name="Test")
    session.add(user)
    await session.commit()  # Commits to SAVEPOINT, not real DB

    result = await session.execute(
        select(User).where(User.email == "test@example.com")
    )
    assert result.scalar_one().name == "Test"
    # After test: transaction is rolled back -- user does not persist


@pytest.mark.asyncio
async def test_unique_constraint(session: AsyncSession):
    user1 = User(email="dup@example.com", name="First")
    session.add(user1)
    await session.commit()

    user2 = User(email="dup@example.com", name="Second")
    session.add(user2)
    with pytest.raises(IntegrityError):
        await session.commit()
```

### GOTCHA
- `join_transaction_mode="create_savepoint"` is the key. It makes the session use SAVEPOINTs instead of real transactions, so the outer transaction can roll everything back.
- This pattern tests real constraints, real SQL, and real driver behavior. Mocking `session.execute()` does not catch any of that.
- For parallel test execution (pytest-xdist), each worker needs its own database. Use `test_db_worker_0`, `test_db_worker_1`, etc.
- If your code calls `session.close()` explicitly, the outer transaction is lost. The session fixture should be the only thing managing the session lifecycle in tests.

---

## 12. Zero-Downtime Migrations

### WHY
`ALTER TABLE users ADD COLUMN phone VARCHAR(20) NOT NULL DEFAULT ''` on a 50M-row table takes an `ACCESS EXCLUSIVE` lock for the entire rewrite duration (minutes). All reads and writes to that table are blocked. In PostgreSQL 11+, adding a column with a DEFAULT is metadata-only (instant), but adding `NOT NULL` still requires a table scan. The safe pattern: add nullable, backfill, then add the constraint.

### HOW
```python
# --- Migration 1: Add nullable column (instant, no lock) ---
# Alembic migration: 001_add_phone_column.py

def upgrade():
    op.add_column("users", sa.Column("phone", sa.String(20), nullable=True))
    # PostgreSQL 11+: this is metadata-only, no table rewrite, no lock


# --- Migration 2: Backfill in batches (no lock, runs online) ---
# Alembic migration: 002_backfill_phone.py
# Run this AFTER deploying code that writes to the new column

def upgrade():
    # Batch update to avoid holding a long lock
    conn = op.get_bind()
    while True:
        result = conn.execute(sa.text("""
            UPDATE users
            SET phone = ''
            WHERE phone IS NULL
            AND id IN (
                SELECT id FROM users WHERE phone IS NULL LIMIT 1000
            )
        """))
        if result.rowcount == 0:
            break


# --- Migration 3: Add NOT NULL constraint (safe, minimal lock) ---
# Alembic migration: 003_add_phone_not_null.py
# Run this AFTER backfill is complete and code always writes phone

def upgrade():
    # NOT VALID = instant, does not scan existing rows
    op.execute("""
        ALTER TABLE users
        ADD CONSTRAINT users_phone_not_null
        CHECK (phone IS NOT NULL) NOT VALID
    """)
    # VALIDATE = scans existing rows but holds a weaker lock
    # (ShareUpdateExclusiveLock -- does NOT block reads or writes)
    op.execute("""
        ALTER TABLE users
        VALIDATE CONSTRAINT users_phone_not_null
    """)
```

### The 4-Phase Pattern

| Phase | Migration | Lock Level | Duration | Blocks Writes? |
|-------|-----------|------------|----------|----------------|
| 1. Add column | `ADD COLUMN ... NULL` | AccessExclusive (PG 11+: instant) | Milliseconds | No |
| 2. Deploy code | Write to new column | N/A | Deploy time | No |
| 3. Backfill | UPDATE in batches of 1000 | RowExclusive per batch | Minutes | No |
| 4. Add constraint | `NOT VALID` then `VALIDATE` | ShareUpdateExclusive | Seconds + scan | No |

### Other Dangerous Operations

| Operation | Risk | Safe Alternative |
|-----------|------|------------------|
| `ADD COLUMN NOT NULL DEFAULT` | Table rewrite (pre-PG11) | Add nullable + backfill + constraint |
| `ALTER COLUMN TYPE` | Full table rewrite | Create new column, copy, swap |
| `CREATE INDEX` | Blocks writes | `CREATE INDEX CONCURRENTLY` |
| `DROP COLUMN` | Instant but irreversible | Rename + drop later |
| `ADD FOREIGN KEY` | Scans + locks parent | `NOT VALID` + `VALIDATE` |
| `RENAME TABLE` | Breaks running queries | Use views during transition |

### GOTCHA
- `CREATE INDEX CONCURRENTLY` cannot run inside a transaction. In Alembic: `op.execute("CREATE INDEX CONCURRENTLY ...")` and set `autocommit=True` in the migration or use `op.create_index(..., postgresql_concurrently=True)` with `with op.get_context().autocommit_block():`.
- The `NOT VALID` + `VALIDATE` split is critical. `ADD CONSTRAINT ... NOT VALID` is instant (just registers the constraint metadata). `VALIDATE CONSTRAINT` scans existing rows but uses `ShareUpdateExclusiveLock`, which does NOT block reads or writes.
- In PostgreSQL 11+, `ADD COLUMN ... DEFAULT value` is metadata-only (no rewrite). But `ADD COLUMN ... DEFAULT value NOT NULL` still needs the NOT NULL enforcement, which requires either a constraint or the rewrite. Use the phased approach for safety.
- Always test migrations against a copy of production data. A migration that runs in 1ms on a dev database with 10 rows can take 45 minutes on production with 50M rows.
