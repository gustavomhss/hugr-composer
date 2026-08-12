---
spec_id: "TOOL-080"
tool_name: "add_cqrs"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-CQRS-01"
  - "INV-CQRS-02"
  - "INV-CQRS-03"
  - "INV-CQRS-04"
  - "INV-CQRS-05"
  - "INV-CQRS-06"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
tags:
  - "performance"
  - "data"
  - "realtime"
  - "compliance"
  - "api"
---
# TOOL-080: add_cqrs

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_cqrs` |
| Category | EXTEND > API Design |
| Complexity | Medium |
| Dependencies | FastAPI, SQLAlchemy 2.0, pydantic-settings |
| Signature | `add_cqrs(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_cqrs", "description": "Add a production-grade CQRS layer with CommandBus, QueryBus, read-replica session routing, and HTTP routes for both buses.", "tags": ["extend", "api_design"], "entry": "add_cqrs"}` |
| Files created (typical) | 7 — `app/cqrs/__init__.py`, `app/cqrs/bus.py`, `app/cqrs/commands.py`, `app/cqrs/queries.py`, `app/cqrs/read_replica.py`, `app/api/routes/cqrs.py` |
| Files modified (typical) | 2 — `app/core/config.py`, `app/routes/__init__.py` |

---

## 2. Purpose

The `fastapi_add_cqrs` tool installs a production-grade Command/Query Responsibility Segregation layer into a FastAPI project. CQRS enforces the discipline that mutating operations (Commands) and reading operations (Queries) travel through separate pathways, preventing the accidental mix of write and read concerns that makes FastAPI services fragile as they scale. Without this separation, developers add side effects to query handlers, break caching invariants by reading stale data after a write, and build no natural extension point for read replicas.

This tool generates: (a) `app/cqrs/bus.py` — `CommandBus` (`register(name, handler)`, `dispatch(command)`) and `QueryBus` (`register(name, handler)`, `query(q)`) using a registry dict keyed on message class name; (b) `app/cqrs/commands.py` — `Command` Pydantic base + three example commands (`CreateItemCommand`, `UpdateItemCommand`, `DeleteItemCommand`); (c) `app/cqrs/queries.py` — `Query` Pydantic base + three example queries (`GetItemQuery`, `ListItemsQuery`, `SearchItemsQuery`); (d) `app/cqrs/read_replica.py` — `ReadReplicaSession` FastAPI dependency that lazily creates an `async_sessionmaker` for `settings.DATABASE_READ_URL` and falls back to the primary session when `DATABASE_READ_URL` is empty — graceful degradation without crashing; (e) `app/cqrs/__init__.py` re-exporting `CommandBus`, `QueryBus`, `ReadReplicaSession`; (f) `app/api/routes/cqrs.py` — `POST /cqrs/commands` and `POST /cqrs/queries` dispatch endpoints using a `BusRequest` envelope (`{name, payload}`) and module-level bus singletons.

Key design decisions: handlers are registered by class name string — no hidden magic decorators; `ReadReplicaSession` uses a cached `_replica_session_factory` (created once on first read-replica request) to avoid per-request engine creation; `DATABASE_READ_URL` defaults to empty string, meaning all queries fall back to primary — the feature degrades gracefully without operator action; `CQRS_ENABLED=false` setting disables the HTTP surface while keeping buses usable in application code; the idempotency fingerprint is `"CommandBus" in app/cqrs/__init__.py`.

---

### Design Decisions Table

| Decision | Chosen Approach | Rejected Alternative | Reason |
|----------|----------------|---------------------|--------|
| Handler registration key | `type(command).__name__` (class name string) | Decorator-based registration | No hidden magic; handler registration is explicit `bus.register("CreateItemCommand", handler)` |
| Read replica session | `ReadReplicaSession` FastAPI dependency (async generator) | Separate `AsyncSession` in handler args | Same `Depends()` pattern as primary session; easy to swap |
| Replica engine lifecycle | Module-level `_replica_session_factory` cache | Per-request engine creation | Engine creation is expensive; one per process is correct |
| No migration | CQRS is routing layer only | Adding a `bus_handlers` tracking table | Avoids unnecessary schema overhead for a pure in-process pattern |
| `BusRequest` envelope | `{name: str, payload: dict}` JSON body | URL path `POST /cqrs/commands/{name}` | Envelope pattern allows versioning without URL changes |
| Command/Query base classes | Pydantic `BaseModel` subclasses | dataclasses or TypedDict | Pydantic gives validation + JSON serialization automatically |

---

### Generated file tree

```
project/ (after tool run)
├── app/
│   ├── cqrs/
│   │   ├── __init__.py                  # re-exports CommandBus, QueryBus, ReadReplicaSession
│   │   ├── bus.py                       # CommandBus + QueryBus (registry dict + dispatch/query)
│   │   ├── commands.py                  # Command base + CreateItemCommand, UpdateItemCommand, DeleteItemCommand
│   │   ├── queries.py                   # Query base + GetItemQuery, ListItemsQuery, SearchItemsQuery
│   │   └── read_replica.py              # ReadReplicaSession dependency (cached factory + primary fallback)
│   └── api/routes/
│       └── cqrs.py                      # POST /cqrs/commands, POST /cqrs/queries
├── app/core/
│   └── config.py                        # MODIFIED: + DATABASE_READ_URL, CQRS_ENABLED
└── app/routes/
    └── __init__.py                      # MODIFIED: + cqrs_router
```

Note: No Alembic migration — CQRS is a routing/architectural layer with no new tables.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget |
| Files created | ≥ 6 | Full CQRS kit |
| Files modified | ≥ 2 | Config + routes init |
| Max function LOC | ≤ 50 | Auditability |
| `CommandBus.dispatch()` overhead | < 1 ms | Dict lookup + async call |
| `QueryBus.query()` overhead | < 1 ms | Dict lookup + async call |
| `ReadReplicaSession` first-call factory creation | < 50 ms | Engine creation (once) |
| `ReadReplicaSession` subsequent calls | < 1 ms | Cached factory |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── core/config.py       # No DATABASE_READ_URL or CQRS_ENABLED
│   └── routes/__init__.py   # No cqrs router
```

No command/query separation. Every route handler directly calls both read and write ORM operations with no structural boundary. Read and write scaling are coupled.

### 4.2 CommandBus: AFTER

```python
# app/cqrs/bus.py (excerpt)
from typing import Any, Callable, Awaitable

Handler = Callable[..., Awaitable[Any]]

class CommandBus:
    def __init__(self) -> None:
        self._registry: dict[str, Handler] = {}

    def register(self, command_name: str, handler: Handler) -> None:
        self._registry[command_name] = handler

    async def dispatch(self, command: object, **kwargs: Any) -> Any:
        name = type(command).__name__
        handler = self._registry.get(name)
        if handler is None:
            raise KeyError(f"No handler registered for command: {name!r}")
        return await handler(command, **kwargs)


class QueryBus:
    def __init__(self) -> None:
        self._registry: dict[str, Handler] = {}

    def register(self, query_name: str, handler: Handler) -> None:
        self._registry[query_name] = handler

    async def query(self, q: object, **kwargs: Any) -> Any:
        name = type(q).__name__
        handler = self._registry.get(name)
        if handler is None:
            raise KeyError(f"No handler registered for query: {name!r}")
        return await handler(q, **kwargs)
```

### 4.3 Example Commands and Queries: AFTER

```python
# app/cqrs/commands.py
class Command(BaseModel):
    pass

class CreateItemCommand(Command):
    title: str
    owner_id: uuid.UUID

class UpdateItemCommand(Command):
    item_id: uuid.UUID
    title: str | None = None

class DeleteItemCommand(Command):
    item_id: uuid.UUID
```

```python
# app/cqrs/queries.py
class Query(BaseModel):
    pass

class GetItemQuery(Query):
    item_id: uuid.UUID

class ListItemsQuery(Query):
    owner_id: uuid.UUID | None = None
    page: int = 1
    page_size: int = 20

class SearchItemsQuery(Query):
    q: str
    page: int = 1
```

### 4.4 ReadReplicaSession: AFTER

```python
# app/cqrs/read_replica.py — graceful fallback to primary
_replica_session_factory: async_sessionmaker | None = None

def _get_replica_factory() -> async_sessionmaker | None:
    global _replica_session_factory
    if _replica_session_factory is None:
        url = os.environ.get("DATABASE_READ_URL", "").strip()
        if url:
            engine = create_async_engine(url, pool_pre_ping=True)
            _replica_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _replica_session_factory

async def ReadReplicaSession() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency. Uses read replica if DATABASE_READ_URL set; falls back to primary."""
    factory = _get_replica_factory()
    if factory is not None:
        async with factory() as session:
            yield session
        return
    async for session in get_session():  # primary fallback (INV-CQRS-04)
        yield session
```

### 4.5 HTTP Routes: AFTER

```
POST /cqrs/commands  → BusRequest{name, payload} → CommandBus.dispatch(command_instance)
POST /cqrs/queries   → BusRequest{name, payload} → QueryBus.query(query_instance)
```

Both endpoints use a `BusRequest` envelope model: `{name: str, payload: dict}`. The route handler resolves the correct `Command` / `Query` Pydantic class by name lookup, instantiates it from `payload`, and dispatches it.

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Idempotent | `"CommandBus" in app/cqrs/__init__.py` → `no_op` |
| QS-2 | `dry_run=True` zero writes | Early return before any `dest.write_text(...)` |
| QS-3 | All `.py` AST-parse | `ast.parse` loop after all writes |
| QS-4 | No function > 50 LOC | Construction discipline + AST walk |
| QS-5 | `ReadReplicaSession` falls back to primary | Empty `DATABASE_READ_URL` → `get_session()` used (INV-CQRS-04) |
| QS-6 | Replica engine created exactly once | `_replica_session_factory` module-level cache; created on first call (INV-CQRS-06) |
| QS-7 | `CQRS_ENABLED=false` disables HTTP surface | Config field checked in route handlers; buses remain usable in application code |
| QS-8 | Handlers registered by class name | `type(command).__name__` as registry key — no hidden decorator magic |
| QS-9 | `execution_time_ms` positive | `_elapsed_ms(start)` on all paths (INV-CQRS-05) |
| QS-10 | `BusRequest` envelope validates payload | Pydantic `BusRequest(name: str, payload: dict)` schema at HTTP boundary |
| QS-11 | No migration required | CQRS layer adds no DB tables; only config + route changes |
| QS-12 | `DATABASE_READ_URL` defaults to empty | Graceful zero-config degradation; no crash when read replica not set |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | `status="success"` on fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run `no_op` | `r2.status == "no_op"`, empty lists | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` zero writes | Filesystem byte-identical | T-03 (`test_dry_run`) |
| CC-04 | ≥ 6 files created | `len(files_created) >= 6`, each path exists | T-04 (`test_files_created_count`) |
| CC-05 | ≥ 2 files modified | `len(files_modified) >= 2`, each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | All `.py` AST-parse | `ast.parse` over all `.py` under `app/` | T-06 (`test_all_py_parse`) |
| CC-07 | No function > 50 LOC | AST walk, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `DATABASE_READ_URL` and `CQRS_ENABLED` in Settings with indent | Substring + 4-space indent for both fields | T-08 (`test_config_fields_patched`) |
| CC-09 | CQRS router registered in `app/routes/__init__.py` | `"cqrs"` in content | T-09 (`test_routes_registered`) |
| CC-10 | `app/cqrs/__init__.py` re-exports `CommandBus` | `"CommandBus"` in file content | T-10 (`test_cqrs_init`) |
| CC-11 | `app/cqrs/bus.py` contains `CommandBus` and `QueryBus` with `dispatch` and `query` | File + all 4 substrings | T-11 (`test_bus_created`) |
| CC-12 | `app/cqrs/read_replica.py` contains `ReadReplicaSession` with primary fallback pattern | File + `"ReadReplicaSession"` + `"get_session"` reference | T-12 (`test_read_replica_created`) |
| CC-13 | `app/api/routes/cqrs.py` has `/commands` and `/queries` endpoints | File + `"/commands"` + `"/queries"` | T-13 (`test_routes_created`) |
| CC-14 | `app/cqrs/commands.py` + `queries.py` have `class Command` and `class Query` | Both files exist; correct base class names | T-14 (`test_message_classes`) |
| CC-15 | `execution_time_ms` positive | `result.execution_time_ms > 0` | T-15 (`test_execution_time_recorded`) |
| CC-16 | `next_steps` mentions `DATABASE_READ_URL` | Lowercase-join contains `"database_read_url"` | T-16 (`test_next_steps_mention_read_url`) |

---

## 7. Definition of Done (DoD)

- [ ] All 16 CC verified by `test_add_cqrs.py`
- [ ] `CommandBus` and `QueryBus` use registry dict keyed by class name
- [ ] `ReadReplicaSession` falls back to primary when `DATABASE_READ_URL` empty
- [ ] Replica engine created once and cached
- [ ] `CQRS_ENABLED` config field added
- [ ] `ast.parse` on all generated files before success return

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-CQRS-01 | Tool ALWAYS idempotent on second invocation | `"CommandBus" in __init__.py` → `no_op` | T-02 |
| INV-CQRS-02 | `dry_run=True` NEVER writes to disk | Early return before any write | T-03 |
| INV-CQRS-03 | Every generated `.py` MUST parse as valid Python | `ast.parse` loop | T-06 |
| INV-CQRS-04 | `ReadReplicaSession` MUST fall back to primary | Empty `DATABASE_READ_URL` → `get_session()` used | T-12 |
| INV-CQRS-05 | `execution_time_ms` MUST be positive | `_elapsed_ms(start)` on all branches | T-15 |
| INV-CQRS-06 | Replica engine MUST be created only once | `_replica_session_factory` module-level cache; created on first call | T-12 |

---

## 9. User Stories

**US-01: Install CQRS into a clean project**
- **Given:** FastAPI project with base prereqs
- **When:** `add_cqrs(ToolInput(project_dir=...))`
- **Then:** `status="success"`, `files_created >= 6`, `files_modified >= 2` (CC-01, CC-04, CC-05)

**US-02: Register and dispatch a command**
- **Given:** `CreateItemCommand` handler registered on `command_bus`
- **When:** `await command_bus.dispatch(CreateItemCommand(title="X", owner_id=uid))`
- **Then:** Handler invoked by class name lookup; result returned to caller

**US-03: Dispatch query to read replica**
- **Given:** `DATABASE_READ_URL` set to replica URL; `GetItemQuery` handler registered
- **When:** Query handler injects `ReadReplicaSession`
- **Then:** Separate replica session used; primary DB unaffected (INV-CQRS-04)

**US-04: Graceful fallback when no read replica configured**
- **Given:** `DATABASE_READ_URL=""` in env (default)
- **When:** `ReadReplicaSession()` dependency resolves
- **Then:** Falls back to primary session; no error raised (INV-CQRS-04)

**US-05: Replica engine created once**
- **Given:** 100 concurrent query requests
- **When:** `ReadReplicaSession()` called 100 times
- **Then:** `_replica_session_factory` created on first call; cached; no duplicate engine creation (QS-6)

**US-06: Unregistered command returns 404**
- **Given:** `POST /cqrs/commands` with `name="UnknownCommand"`
- **When:** `CommandBus.dispatch()` raises `KeyError`
- **Then:** Route handler catches → `HTTP 404 Not Found` (EC-02)

**US-07: Dispatch via HTTP command endpoint**
- **Given:** `CreateItemCommand` registered; `POST /cqrs/commands` with `{name: "CreateItemCommand", payload: {title: "X", owner_id: "..."}}`
- **When:** Route handler resolves class, instantiates from payload, dispatches
- **Then:** Command handled; response returned

**US-08: Disable HTTP surface with CQRS_ENABLED=false**
- **Given:** `CQRS_ENABLED=false` in env
- **When:** `POST /cqrs/commands` called
- **Then:** Route returns `HTTP 503 Service Unavailable` or `404`; buses still usable in application code (QS-7)

**US-09: Re-run tool on already-configured project**
- **Given:** `app/cqrs/__init__.py` contains `"CommandBus"`
- **When:** Tool invoked again
- **Then:** `status="no_op"`, empty lists (CC-02, INV-CQRS-01)

**US-10: dry_run preview**
- **Given:** Fresh fixture project
- **When:** `add_cqrs(ToolInput(dry_run=True))`
- **Then:** `status="success"`, filesystem unchanged (CC-03, INV-CQRS-02)

**US-11: Search via query bus with pagination**
- **Given:** `SearchItemsQuery` handler registered with `ReadReplicaSession`
- **When:** `await query_bus.query(SearchItemsQuery(q="foo", page=2))`
- **Then:** Handler executes paginated full-text query on replica; returns `ListItemsQuery` results

**US-12: All generated files parse cleanly**
- **Given:** Tool runs on fresh fixture
- **When:** `ast.parse` called on every created `.py`
- **Then:** No `SyntaxError` raised on any file (INV-CQRS-03)

---

## 10. Test Plan

All 16 tests live in `adapt/extend/api_design/test_add_cqrs.py`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `cq_t01` | `add_cqrs(ToolInput(project_dir))` | `result.status == "success"` |
| T-02 | `test_idempotent` | Fixture `cq_t02`; run once | Run again | `r2.status == "no_op"`, empty `files_created` + `files_modified` |
| T-03 | `test_dry_run` | Fixture `cq_t03` | `add_cqrs(ToolInput(dry_run=True))` | `status == "success"`; no files written |
| T-04 | `test_files_created_count` | Fixture `cq_t04` | Run tool | `len(files_created) >= 6`, each path exists |
| T-05 | `test_files_modified_count` | Fixture `cq_t05` | Run tool | `len(files_modified) >= 2`, each path exists |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `cq_t06`; run tool | `ast.parse` every `.py` under `app/` | No `SyntaxError` |
| T-07 | `test_no_function_over_50_loc` | Fixture `cq_t07`; run tool | AST walk `app/`; count lines per `FunctionDef` | `max_loc <= 50` |
| T-08 | `test_config_fields_patched` | Fixture `cq_t08`; run tool | Read `app/core/config.py` | `"DATABASE_READ_URL"` and `"CQRS_ENABLED"` with 4-space indent inside `class Settings` |
| T-09 | `test_routes_registered` | Fixture `cq_t09`; run tool | Read `app/routes/__init__.py` | `"cqrs"` in content |
| T-10 | `test_cqrs_init` | Fixture `cq_t10`; run tool | Read `app/cqrs/__init__.py` | `"CommandBus"` in content |

### 10.3 Category C — Domain-specific modules (T-11 .. T-14)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_bus_created` | Fixture `cq_t11`; run tool | Read `app/cqrs/bus.py` | `"CommandBus"` + `"QueryBus"` + `"dispatch"` + `"query"` present |
| T-12 | `test_read_replica_created` | Fixture `cq_t12`; run tool | Read `app/cqrs/read_replica.py` | `"ReadReplicaSession"` + fallback pattern (`get_session` reference) present |
| T-13 | `test_routes_created` | Fixture `cq_t13`; run tool | Read `app/api/routes/cqrs.py` | `"/commands"` + `"/queries"` present |
| T-14 | `test_message_classes` | Fixture `cq_t14`; run tool | Read `app/cqrs/commands.py` + `app/cqrs/queries.py` | `"class Command"` in commands file; `"class Query"` in queries file |

### 10.4 Category D — Meta (T-15 .. T-16)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-15 | `test_execution_time_recorded` | Fixture `cq_t15`; run tool | `result.execution_time_ms` | `> 0` |
| T-16 | `test_next_steps_mention_read_url` | Fixture `cq_t16`; run tool | Lowercase-join `result.next_steps` | Contains `"database_read_url"` |

---

## 11. Interaction Matrix

| Other tool | Interaction | Notes |
|------------|-------------|-------|
| `add_event_sourcing` (TOOL-079) | ✅ Compatible | Commands append events; queries read projections |
| `add_multi_tenancy` (TOOL-008) | ✅ Compatible | Commands/queries carry tenant context |
| `add_rbac` (TOOL-012) | ✅ Compatible | Route guards wrap bus dispatch endpoints |

---

## 11.1 Anti-patterns This Tool Prevents

| Anti-pattern | How this tool avoids it |
|-------------|------------------------|
| Read and write operations in the same handler (no separation) | `CommandBus` for writes; `QueryBus` for reads — structural separation enforced |
| Creating a new DB engine per request for read replicas | `_replica_session_factory` module-level cache — engine created once — INV-CQRS-06 |
| Crashing app when `DATABASE_READ_URL` is not set | `ReadReplicaSession` falls back to primary silently — INV-CQRS-04 |
| Hidden decorator-based handler registration | `bus.register("CommandName", handler)` — explicit, auditable |
| Caching query results that are stale after writes | Commands go through `CommandBus` → primary; queries use `QueryBus` → replica — clear boundary |
| Unregistered command/query silently no-ops | `KeyError` raised → HTTP 404 — fail loudly |

---

## 12. Rollback Procedure

```bash
git checkout HEAD -- app/core/config.py app/routes/__init__.py
rm -rf app/cqrs/ app/api/routes/cqrs.py
```

---

## 13. Edge Cases

| # | Scenario | Expected |
|---|----------|----------|
| EC-01 | `DATABASE_READ_URL` empty (default) | `_get_replica_factory()` returns `None`; `ReadReplicaSession` falls back to `get_session()` (INV-CQRS-04) |
| EC-02 | Unregistered command name in `POST /cqrs/commands` | `CommandBus.dispatch()` raises `KeyError`; route handler returns `HTTP 404` |
| EC-03 | Unregistered query name in `POST /cqrs/queries` | `QueryBus.query()` raises `KeyError`; route handler returns `HTTP 404` |
| EC-04 | `CQRS_ENABLED=false` | HTTP routes disabled (or return `HTTP 503`); bus instances in `app/cqrs/__init__.py` remain usable |
| EC-05 | `app/routes/__init__.py` missing | Router registration skipped; note emitted in `result.notes`; tool still returns `"success"` |
| EC-06 | Invalid `project_dir` | `status="error"` with diagnostic message |
| EC-07 | Missing prerequisites | `status="error"` listing missing files |
| EC-08 | Second run (idempotent) | `status="no_op"`, empty lists |
| EC-09 | `DATABASE_READ_URL` points to unreachable host | Engine created; `pool_pre_ping=True` surfaces error on first query; no crash at startup |
| EC-10 | Both buses already registered (partial install) | Fingerprint check catches via `"CommandBus" in __init__.py`; returns `no_op` |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 16 CC verified by `test_add_cqrs.py`
2. ✅ `ReadReplicaSession` falls back to primary when `DATABASE_READ_URL` empty (INV-CQRS-04)
3. ✅ Replica engine created once and cached in `_replica_session_factory` (INV-CQRS-06)
4. ✅ Both buses use registry dict keyed by `type(command).__name__` (QS-8)
5. ✅ Second invocation returns `status="no_op"` (INV-CQRS-01)
6. ✅ `dry_run=True` produces zero writes (INV-CQRS-02)
7. ✅ All generated `.py` files AST-parse (INV-CQRS-03)
8. ✅ `execution_time_ms` positive on all return paths (INV-CQRS-05)

---

## 15. Implementation Checklist (Ultra-granular)

- [ ] `validate_project_dir` confirms path exists and is a directory
- [ ] `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT)` passes (no ALEMBIC_VERSIONS needed — no migration)
- [ ] Fingerprint check: `"CommandBus" in (project_dir / "app/cqrs/__init__.py").read_text()` (if file exists) → `no_op`
- [ ] `dry_run` guard: early return with `status="success"` before any file write
- [ ] Write `app/cqrs/__init__.py` (re-exports `CommandBus`, `QueryBus`, `ReadReplicaSession`)
- [ ] Write `app/cqrs/bus.py` with `CommandBus` (registry dict + `register` + `dispatch`) and `QueryBus` (registry dict + `register` + `query`)
- [ ] Write `app/cqrs/commands.py` with `Command` base class + 3 example commands (`CreateItemCommand`, `UpdateItemCommand`, `DeleteItemCommand`)
- [ ] Write `app/cqrs/queries.py` with `Query` base class + 3 example queries (`GetItemQuery`, `ListItemsQuery`, `SearchItemsQuery`)
- [ ] Write `app/cqrs/read_replica.py` with `ReadReplicaSession` (module-level `_replica_session_factory` cache + fallback to `get_session()`)
- [ ] Write `app/api/routes/cqrs.py` with `POST /cqrs/commands` and `POST /cqrs/queries` using `BusRequest` envelope
- [ ] `_patch_config` injects `DATABASE_READ_URL: str = ""` and `CQRS_ENABLED: bool = True` anchored inside `class Settings`
- [ ] `_patch_routes_init` registers `cqrs_router` idempotently
- [ ] `ast.parse` loop over all created `.py` files; return `status="error"` if any fail
- [ ] Return `ToolResult` with `next_steps` mentioning `DATABASE_READ_URL` configuration for read replicas

---

## 16. References

| Document | Purpose |
|----------|---------|
| `adapt/extend/api_design/add_cqrs.py` | Source implementation (~689 lines) |
| `adapt/contracts/__init__.py` | `ToolInput`, `ToolResult` |
| `specs/TOOL-079-add_event_sourcing.md` | Companion: commands append events; queries read projections |
| `specs/TOOL-008-add_multi_tenancy.md` | Compatible: commands/queries carry tenant context |
| `specs/TOOL-012-add_rbac.md` | Compatible: route guards wrap bus dispatch endpoints |

---

## 16.1 Troubleshooting Guide

### Symptom → Root Cause → Fix

| Symptom | Likely Cause | Diagnostic Command | Fix |
|---------|-------------|-------------------|-----|
| `KeyError: 'CreateItemCommand'` on dispatch | Handler not registered before first request | Print `command_bus._registry` at startup | Call `command_bus.register(CreateItemCommand, handle_create_item)` in app lifespan or `startup` event |
| `ReadReplicaSession` always yields primary session | `DATABASE_READ_URL` not set or empty string | `echo $DATABASE_READ_URL` | Set env var; `_get_replica_factory()` returns `None` when URL is empty, triggering primary fallback (this is correct behaviour — no error needed) |
| Replica factory created once but URL later updated | `_replica_session_factory` module-level cache never reset | Restart needed | This is by design (process-lifetime cache); document that `DATABASE_READ_URL` changes require process restart |
| `POST /cqrs/commands` returns 422 for valid payload | `BusRequest` expects `handler` field but caller sends `command_type` | Test with `{"handler": "CreateItemCommand", "payload": {}}` | Verify `BusRequest` field name matches what caller sends; update OpenAPI schema accordingly |
| Read-after-write inconsistency via replica | Query dispatched to replica immediately after command committed to primary | Use `EXPLAIN` to confirm replica lag | Add `prefer_primary: bool = False` to `QueryBus.query()` to allow opt-in to primary for critical reads |
| `CommandBus` and `QueryBus` created as module-level singletons but reset between tests | `importlib.reload` in test clears registry | Check test teardown | Use `command_bus.clear()` method (add if missing) in test fixtures, or create fresh bus instances per test |
| Tool returns `no_op` even though `app/cqrs/` doesn't exist | Fingerprint checks `"CommandBus" in routes/__init__.py` which has a stale reference | `grep CommandBus app/api/routes/__init__.py` | Tighten fingerprint to `"from app.cqrs.bus import CommandBus" in app/cqrs/bus.py` |

### CQRS Request Flow Diagram

```
Client
  │
  ├─ POST /cqrs/commands  {"handler": "CreateItemCommand", "payload": {...}}
  │         │
  │         ▼
  │   CommandBus.dispatch(CreateItemCommand(**payload))
  │         │
  │         ▼
  │   _registry["CreateItemCommand"](command, session)
  │         │  (write session — primary DB)
  │         ▼
  │   mutates DB state, optionally appends event
  │         │
  │         ▼
  │   returns result dict → HTTP 200
  │
  └─ POST /cqrs/queries   {"handler": "GetItemQuery", "payload": {"id": 1}}
            │
            ▼
      QueryBus.query(GetItemQuery(**payload))
            │
            ▼
      _registry["GetItemQuery"](query, replica_session)
            │  (ReadReplicaSession — replica DB if configured, else primary)
            ▼
      returns read model → HTTP 200
```

**Key property**: commands and queries never share a handler. A handler registered on `CommandBus` cannot be dispatched via `QueryBus` and vice versa — enforced by separate `_registry` dicts on separate bus instances.
