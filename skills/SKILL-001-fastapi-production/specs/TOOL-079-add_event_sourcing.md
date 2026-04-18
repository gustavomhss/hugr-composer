# TOOL-079: add_event_sourcing

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_event_sourcing` |
| Category | EXTEND > CRUD/Data |
| Complexity | High |
| Dependencies | FastAPI, SQLAlchemy 2.0, Alembic, pydantic-settings |
| Signature | `add_event_sourcing(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_event_sourcing", "description": "Add append-only event store with projections and replay.", "tags": ["extend", "crud_data"], "entry": "add_event_sourcing"}` |
| Files created (typical) | 8 — `app/events/__init__.py`, `app/events/store.py`, `app/events/projector.py`, `app/models/event.py`, `app/schemas/event.py`, `app/crud/event.py`, `app/api/routes/events.py`, `alembic/versions/0079_add_event_sourcing.py` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py` |

---

## 2. Purpose

The `fastapi_add_event_sourcing` tool installs a production-grade append-only event store with projections and replay capability into a FastAPI project. Event sourcing is the pattern where the current state of an entity is derived by replaying a sequence of immutable events rather than reading a mutable row. The key failure mode in hand-rolled implementations is mutability: developers store events but also update a separate "state" table directly, defeating the purpose and creating divergence between the event log and the derived state.

This tool generates: (a) `app/models/event.py` — an `Event` SQLAlchemy model with `stream_id` UUID (the entity being modeled), `stream_type` String (e.g., `"Order"`), `event_type` String (e.g., `"OrderPlaced"`), `version` Integer (per-stream sequence number), `payload` JSONB (the event data), `metadata` JSONB, `created_at`, and `aggregate_id` UUID FK (optional FK to the primary entity record); (b) `app/events/store.py` — `EventStore` with `append(event)` (enforces optimistic concurrency via `version = expected_version + 1`), `get_stream(stream_id)`, `get_all_since(position)` for catch-up subscriptions, and snapshot support via `EVENT_STORE_SNAPSHOT_INTERVAL`; (c) `app/events/projector.py` — `Projector` with `project(event)` (dispatches to registered handlers by `event_type`) and `rebuild(stream_id)` (replays all events to reconstruct state); (d) Pydantic schemas, CRUD helpers, REST endpoints (`POST /events/streams/{stream_id}` to append, `GET /events/streams/{stream_id}` to retrieve, `POST /events/streams/{stream_id}/replay` to rebuild projection); (e) Alembic migration.

Key design decisions: `version` is a per-stream monotonic sequence enforced at the DB level via a unique constraint on `(stream_id, version)` — concurrent appends raise `UniqueViolation` which the service translates to HTTP 409 Conflict (optimistic concurrency); `EVENT_STORE_SNAPSHOT_INTERVAL` (default 50) controls how often the projector saves a snapshot to avoid full replays; the event store is append-only — no `UPDATE` or `DELETE` on events table; `get_all_since(position)` enables catch-up subscriptions for read models.

---

### Design Decisions Table

| Decision | Chosen Approach | Rejected Alternative | Reason |
|----------|----------------|---------------------|--------|
| Concurrency control | DB `UniqueConstraint("stream_id", "version")` → HTTP 409 | Application-level lock | DB constraint is atomic and survives process restarts |
| Event storage format | JSONB `payload` column | Separate typed event tables | Schema-free events allow evolving event payloads without migrations |
| Snapshot storage | Inline snapshot in `Projector` (in-process) | Separate snapshot table | Simpler starting point; production teams add a snapshot table when needed |
| Catch-up subscriptions | `get_all_since(position)` by `created_at` timestamp | Global auto-increment sequence column | Avoids adding a sequence; `created_at` is sufficient for most use cases |
| Stream identity | UUID `stream_id` | String stream name | UUIDs are type-safe and collision-free |
| Append-only enforcement | Design: no `UPDATE`/`DELETE` in `store.py` | DB-level row security | Simpler for the generated starter code; DB RLS can be added by the operator |

---

### Generated file tree

```
project/ (after tool run)
├── app/
│   ├── events/
│   │   ├── __init__.py                  # package marker + EventStore, Projector re-exports
│   │   ├── store.py                     # EventStore (append, get_stream, get_all_since)
│   │   └── projector.py                 # Projector (register, project, rebuild) + snapshot support
│   ├── models/
│   │   ├── __init__.py                  # MODIFIED: + Event import
│   │   └── event.py                     # Event model (stream_id, stream_type, event_type, version, payload, metadata)
│   ├── schemas/
│   │   └── event.py                     # EventAppend, EventRead, ProjectionResult
│   ├── crud/
│   │   └── event.py                     # thin CRUD helpers wrapping EventStore
│   └── api/routes/
│       └── events.py                    # 4 endpoints: append, get_stream, replay, since
├── app/core/
│   └── config.py                        # MODIFIED: + EVENT_STORE_SNAPSHOT_INTERVAL
├── app/routes/
│   └── __init__.py                      # MODIFIED: + events_router
└── alembic/versions/
    └── 0079_add_event_sourcing.py       # events table + uq_event_stream_version + ix_events_stream_id
```

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget |
| Files created | ≥ 7 | Full event sourcing kit |
| Files modified | ≥ 2 | Config + models init |
| Max function LOC | ≤ 50 | Auditability |
| `append()` latency | < 10 ms | Single INSERT with version check |
| `get_stream()` latency | < 15 ms | Index scan on `(stream_id, version)` |
| `rebuild()` latency | < 100 ms | Full stream replay + projection; depends on stream length |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── core/config.py       # No EVENT_STORE_SNAPSHOT_INTERVAL
│   ├── models/__init__.py   # No Event
│   └── routes/__init__.py   # No events router
└── alembic/versions/
```

No event store. State is derived by reading mutable rows, losing all history of how state was reached.

### 4.2 Event model: AFTER

```python
# app/models/event.py
class Event(Base):
    __tablename__ = "events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    stream_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    stream_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("stream_id", "version", name="uq_event_stream_version"),
    )
```

### 4.3 EventStore: AFTER

```python
# app/events/store.py (excerpt)
class EventStore:
    async def append(
        self, session: AsyncSession, stream_id: uuid.UUID, stream_type: str,
        event_type: str, payload: dict, expected_version: int | None = None,
        metadata: dict | None = None,
    ) -> Event:
        """Append event with optimistic concurrency. Raises 409 on version conflict."""
        if expected_version is not None:
            # version must equal expected_version + 1
            new_version = expected_version + 1
        else:
            # compute next version from current max
            result = await session.execute(
                select(func.max(Event.version)).where(Event.stream_id == stream_id)
            )
            max_v = result.scalar() or 0
            new_version = max_v + 1
        event = Event(
            stream_id=stream_id, stream_type=stream_type, event_type=event_type,
            version=new_version, payload=payload, metadata=metadata,
        )
        session.add(event)
        await session.flush()  # raises IntegrityError on UniqueViolation → translate to HTTP 409
        return event

    async def get_stream(
        self, session: AsyncSession, stream_id: uuid.UUID
    ) -> list[Event]:
        result = await session.execute(
            select(Event).where(Event.stream_id == stream_id).order_by(Event.version)
        )
        return list(result.scalars())
```

### 4.4 Projector: AFTER

```python
# app/events/projector.py (excerpt)
class Projector:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict, dict], dict]] = {}

    def register(self, event_type: str, handler: Callable[[dict, dict], dict]) -> None:
        self._handlers[event_type] = handler

    def project(self, state: dict, event: Event) -> dict:
        handler = self._handlers.get(event.event_type)
        if handler:
            return handler(state, event.payload)
        return state  # unknown events are no-ops

    async def rebuild(
        self, session: AsyncSession, store: EventStore, stream_id: uuid.UUID
    ) -> dict:
        events = await store.get_stream(session, stream_id)
        state: dict = {}
        for event in events:
            state = self.project(state, event)
        return state
```

### 4.5 Routes: AFTER

```
POST /events/streams/{stream_id}         → append event (optimistic concurrency)
GET  /events/streams/{stream_id}         → get all events for stream ordered by version
POST /events/streams/{stream_id}/replay  → rebuild projection by replaying stream
GET  /events/since/{position}            → catch-up subscription (events after global position)
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Idempotent | `"EventStore" in app/events/store.py` → `no_op` |
| QS-2 | `dry_run=True` zero writes | Early return before any `dest.write_text(...)` |
| QS-3 | All `.py` AST-parse | `ast.parse` loop after all writes |
| QS-4 | No function > 50 LOC | Construction discipline + AST walk |
| QS-5 | Append-only event store | No `UPDATE` or `DELETE` SQL helpers in `store.py`; only `INSERT` (INV-ES-04) |
| QS-6 | Optimistic concurrency at DB level | `UniqueConstraint("stream_id", "version", name="uq_event_stream_version")` |
| QS-7 | Snapshot interval configurable | `EVENT_STORE_SNAPSHOT_INTERVAL: int = 50` config field |
| QS-8 | `execution_time_ms` positive | `_elapsed_ms(start)` on all paths (INV-ES-06) |
| QS-9 | Migration chained to head | `find_migration_head` |
| QS-10 | Projector handles unknown event types as no-ops | `handler = self._handlers.get(event_type)` — missing returns `state` unchanged |
| QS-11 | `get_all_since` enables catch-up subscriptions | Query filters `created_at > position` ordered by `created_at` |
| QS-12 | `version` monotonically increases per stream | `SELECT MAX(version) + 1 WHERE stream_id=?`; DB constraint enforces uniqueness |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | `status="success"` on fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run `no_op` | `r2.status == "no_op"`, empty lists | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` zero writes | Filesystem byte-identical | T-03 (`test_dry_run`) |
| CC-04 | ≥ 7 files created | `len(files_created) >= 7`, each exists | T-04 (`test_files_created_count`) |
| CC-05 | ≥ 2 files modified | `len(files_modified) >= 2`, each exists | T-05 (`test_files_modified_count`) |
| CC-06 | All `.py` AST-parse | `ast.parse` over all `.py` under `app/` | T-06 (`test_all_py_parse`) |
| CC-07 | No function > 50 LOC | AST walk, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `EVENT_STORE_SNAPSHOT_INTERVAL` in Settings with indent | Substring + 4-space indent | T-08 (`test_config_fields_patched`) |
| CC-09 | `Event` in `app/models/__init__.py` | `"Event"` in content | T-09 (`test_models_init_patched`) |
| CC-10 | Events router registered in `app/routes/__init__.py` | `"event"` in content | T-10 (`test_routes_registered`) |
| CC-11 | `app/models/event.py` with `uq_event_stream_version` constraint | File + `"class Event"` + constraint name | T-11 (`test_event_model_created`) |
| CC-12 | `app/events/store.py` with `EventStore`, `append`, `get_stream`; no UPDATE/DELETE | Substrings; absence check for UPDATE/DELETE helpers | T-12 (`test_event_store_created`) |
| CC-13 | `app/events/projector.py` with `Projector`, `rebuild` | File + substrings | T-13 (`test_projector_created`) |
| CC-14 | Migration creates `events` table | File + `"events"` | T-14 (`test_migration_created`) |
| CC-15 | `execution_time_ms` positive | `result.execution_time_ms > 0` | T-15 (`test_execution_time_recorded`) |
| CC-16 | `next_steps` mentions `alembic` | Lowercase-join contains `"alembic"` | T-16 (`test_next_steps_mention_alembic`) |

---

## 7. Definition of Done (DoD)

- [ ] All 16 CC verified by `test_add_event_sourcing.py`
- [ ] `events` table append-only (no UPDATE/DELETE helpers generated)
- [ ] `(stream_id, version)` unique constraint for optimistic concurrency
- [ ] `EVENT_STORE_SNAPSHOT_INTERVAL` config field
- [ ] `Projector.rebuild()` replays all events for a stream

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-ES-01 | Tool ALWAYS idempotent on second invocation | `"EventStore" in store_file` → `no_op` | T-02 |
| INV-ES-02 | `dry_run=True` NEVER writes to disk | Early return before any write | T-03 |
| INV-ES-03 | Every generated `.py` MUST parse as valid Python | `ast.parse` loop | T-06 |
| INV-ES-04 | Event store MUST be append-only | No `UPDATE` or `DELETE` SQL helpers generated in `store.py` | T-12 |
| INV-ES-05 | Optimistic concurrency MUST be enforced at DB level | `UniqueConstraint("stream_id", "version", name="uq_event_stream_version")` | T-11 |
| INV-ES-06 | `execution_time_ms` MUST be positive | `_elapsed_ms(start)` on all branches | T-15 |
| INV-ES-07 | `rebuild()` MUST complete in < 100 ms for reasonable stream | Snapshot interval + indexed scan | T-13 (latency assertion optional) |

---

## 9. User Stories

**US-01: Install event sourcing into a clean project**
- **Given:** FastAPI project with base prereqs
- **When:** `add_event_sourcing(ToolInput(project_dir=...))`
- **Then:** `status="success"`, `files_created >= 7`, `files_modified >= 2` (CC-01, CC-04, CC-05)

**US-02: Append first event to a new stream**
- **Given:** No events exist for `order_id` stream
- **When:** `POST /events/streams/{order_id}` with `{event_type: "OrderPlaced", payload: {item_ids: [...]}}`
- **Then:** `Event` row inserted with `version=1`; response includes event `id` and `version`

**US-03: Append subsequent event with expected_version**
- **Given:** Stream `order_id` at `version=3`
- **When:** `POST /events/streams/{order_id}` with `{expected_version: 3, ...}`
- **Then:** `Event` inserted with `version=4`; optimistic concurrency satisfied

**US-04: Detect concurrent append conflict**
- **Given:** Two concurrent clients both expect `version=5`
- **When:** Second `append()` attempts to insert `version=6`
- **Then:** DB raises `UniqueViolation` on `(stream_id, version)` → service translates to `HTTP 409 Conflict`

**US-05: Read all events in a stream**
- **Given:** 30 events for stream `order_id`
- **When:** `GET /events/streams/{order_id}`
- **Then:** Returns all 30 events ordered by `version` ascending

**US-06: Rebuild projection from events**
- **Given:** 30 events for `order_id`; `Projector` has handlers for all event types
- **When:** `POST /events/streams/{order_id}/replay`
- **Then:** `Projector.rebuild()` replays events 1..30; returns final projected `dict` state

**US-07: Replay empty stream**
- **Given:** No events exist for stream
- **When:** `POST /events/streams/{stream_id}/replay`
- **Then:** Returns empty dict `{}`; no error (EC-03)

**US-08: Catch-up subscription**
- **Given:** Read model last processed global position 100
- **When:** `GET /events/since/100`
- **Then:** Returns events created after position 100, ordered by `created_at` ascending

**US-09: Snapshot reduces replay cost**
- **Given:** `EVENT_STORE_SNAPSHOT_INTERVAL=50`; stream at 100 events
- **When:** `Projector.rebuild()` called
- **Then:** Starts from snapshot at event 50; replays only events 51..100; < 100 ms (INV-ES-07)

**US-10: Re-run tool on already-configured project**
- **Given:** `app/events/store.py` already contains `"EventStore"`
- **When:** Tool invoked again
- **Then:** `status="no_op"`, empty lists (CC-02, INV-ES-01)

**US-11: dry_run preview**
- **Given:** Fresh fixture project
- **When:** `add_event_sourcing(ToolInput(dry_run=True))`
- **Then:** `status="success"`, filesystem unchanged (CC-03, INV-ES-02)

**US-12: Unknown event type during rebuild**
- **Given:** Event with `event_type="LegacyEvent"` not registered on `Projector`
- **When:** `Projector.project(state, event)` called
- **Then:** `state` returned unchanged; no exception raised (unknown events are no-ops)

---

## 10. Test Plan

All 16 tests live in `adapt/extend/crud_data/test_add_event_sourcing.py`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `es_t01` | `add_event_sourcing(ToolInput(project_dir))` | `result.status == "success"` |
| T-02 | `test_idempotent` | Fixture `es_t02`; run once | Run again | `r2.status == "no_op"`, empty `files_created` + `files_modified` |
| T-03 | `test_dry_run` | Fixture `es_t03` | `add_event_sourcing(ToolInput(dry_run=True))` | `status == "success"`; no files written |
| T-04 | `test_files_created_count` | Fixture `es_t04` | Run tool | `len(files_created) >= 7`, each path exists |
| T-05 | `test_files_modified_count` | Fixture `es_t05` | Run tool | `len(files_modified) >= 2`, each path exists |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `es_t06`; run tool | `ast.parse` every `.py` under `app/` | No `SyntaxError` |
| T-07 | `test_no_function_over_50_loc` | Fixture `es_t07`; run tool | AST walk `app/`; count lines per `FunctionDef` | `max_loc <= 50` |
| T-08 | `test_config_fields_patched` | Fixture `es_t08`; run tool | Read `app/core/config.py` | `"EVENT_STORE_SNAPSHOT_INTERVAL"` present with 4-space indent inside `class Settings` |
| T-09 | `test_models_init_patched` | Fixture `es_t09`; run tool | Read `app/models/__init__.py` | `"Event"` in content |
| T-10 | `test_routes_registered` | Fixture `es_t10`; run tool | Read `app/routes/__init__.py` | `"event"` in content |

### 10.3 Category C — Domain-specific modules (T-11 .. T-14)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_event_model_created` | Fixture `es_t11`; run tool | Read `app/models/event.py` | `"class Event"` + `"uq_event_stream_version"` + `"stream_id"` present |
| T-12 | `test_event_store_created` | Fixture `es_t12`; run tool | Read `app/events/store.py` | `"EventStore"` + `"append"` + `"get_stream"` present; no `UPDATE` or `DELETE` SQL in file |
| T-13 | `test_projector_created` | Fixture `es_t13`; run tool | Read `app/events/projector.py` | `"Projector"` + `"rebuild"` present |
| T-14 | `test_migration_created` | Fixture `es_t14`; run tool | Scan `alembic/versions/` | File matching `*event_sourcing*` with `"events"` in content |

### 10.4 Category D — Meta (T-15 .. T-16)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-15 | `test_execution_time_recorded` | Fixture `es_t15`; run tool | `result.execution_time_ms` | `> 0` |
| T-16 | `test_next_steps_mention_alembic` | Fixture `es_t16`; run tool | Lowercase-join `result.next_steps` | Contains `"alembic"` |

---

## 11. Interaction Matrix

| Other tool | Interaction | Notes |
|------------|-------------|-------|
| `add_data_versioning` (TOOL-078) | ✅ Compatible | Versioning publishes events |
| `add_cqrs` (TOOL-080) | ✅ Compatible | Commands append events; queries read projections |
| `add_arq_worker` (TOOL-053) | ✅ Compatible | Event processing via background jobs |

---

## 11.1 Anti-patterns This Tool Prevents

| Anti-pattern | How this tool avoids it |
|-------------|------------------------|
| Storing events but also updating mutable state row (defeating event sourcing) | No `UPDATE`/`DELETE` helpers in `EventStore`; state derived exclusively by `Projector.rebuild()` — INV-ES-04 |
| No optimistic concurrency → duplicate events at same version | `UniqueConstraint("stream_id", "version")` → DB-level 409 on conflict — INV-ES-05 |
| Full stream replay every time (O(n) cost for large streams) | `EVENT_STORE_SNAPSHOT_INTERVAL` config; `Projector` saves snapshots periodically |
| Projector crashing on unknown event types | Unknown `event_type` returns `state` unchanged — no exception raised |
| Events with mutable payloads (retroactive history rewriting) | `JSONB` stored on insert; no update endpoint in routes |
| No catch-up mechanism for read models | `get_all_since(position)` enables incremental catch-up subscriptions |

---

## 12. Rollback Procedure

```bash
git checkout HEAD -- app/core/config.py app/models/__init__.py app/routes/__init__.py
rm -rf app/events/ app/models/event.py app/schemas/event.py \
       app/crud/event.py app/api/routes/events.py
find alembic/versions/ -name '*event_sourcing*' -delete
alembic downgrade -1
```

---

## 13. Edge Cases

| # | Scenario | Expected |
|---|----------|----------|
| EC-01 | Empty stream (no events) | `get_stream()` returns `[]`; `rebuild()` returns `{}` |
| EC-02 | Concurrent append at same version | DB `UniqueViolation` on `(stream_id, version)` → service returns `HTTP 409 Conflict` |
| EC-03 | `rebuild()` on empty stream | `Projector.rebuild()` returns `{}` (initial empty state) with no error |
| EC-04 | `EVENT_STORE_SNAPSHOT_INTERVAL=0` | Snapshots disabled; full replay from event 1 always |
| EC-05 | `alembic/versions/` missing | Migration step skipped; tool returns `"success"` with note |
| EC-06 | Second run (idempotent) | `status="no_op"`, empty lists |
| EC-07 | `append()` with `expected_version` on wrong version | DB inserts wrong `version`; `UniqueViolation` raised → `HTTP 409` |
| EC-08 | Unknown `event_type` during replay | `Projector.project()` returns state unchanged (no-op for unknown types) |
| EC-09 | `get_all_since(position)` with very large position | Returns empty list; no crash |
| EC-10 | Invalid `project_dir` | `status="error"` with diagnostic message |
| EC-11 | `stream_type` and `event_type` exceed 100 chars | DB raises truncation/constraint error at insert |
| EC-12 | Payload is empty dict `{}` | Valid; `JSONB` stores `{}`; no validation error |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 16 CC verified by `test_add_event_sourcing.py`
2. ✅ Append-only events table — no `UPDATE`/`DELETE` helpers in `store.py` (INV-ES-04)
3. ✅ Optimistic concurrency via `UniqueConstraint("stream_id", "version")` (INV-ES-05)
4. ✅ `EVENT_STORE_SNAPSHOT_INTERVAL` config field added; default 50 or 100
5. ✅ `Projector.rebuild()` replays all events for a stream
6. ✅ Second invocation returns `status="no_op"` (INV-ES-01)
7. ✅ `dry_run=True` produces zero writes (INV-ES-02)
8. ✅ All generated `.py` files AST-parse (INV-ES-03)
9. ✅ `execution_time_ms` positive on all return paths (INV-ES-06)

---

## 15. Implementation Checklist (Ultra-granular)

- [ ] `validate_project_dir` confirms path exists and is a directory
- [ ] `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS)` passes
- [ ] Fingerprint check: `"EventStore" in (project_dir / "app/events/store.py").read_text()` (if file exists) → `no_op`
- [ ] `dry_run` guard: early return with `status="success"` before any file write
- [ ] Write `app/models/event.py` with `Event` model (`stream_id`, `stream_type`, `event_type`, `version`, `payload`, `metadata`, `created_at`) + `UniqueConstraint("stream_id", "version", name="uq_event_stream_version")`
- [ ] `_patch_models_init` appends `from app.models.event import Event` idempotently
- [ ] Write `app/events/__init__.py` (package marker)
- [ ] Write `app/events/store.py` with `EventStore` (`append`, `get_stream`, `get_all_since`)
- [ ] Verify `store.py` contains NO `UPDATE` or `DELETE` SQL helpers (append-only invariant)
- [ ] Write `app/events/projector.py` with `Projector` (`register`, `project`, `rebuild`) + snapshot support
- [ ] Write `app/schemas/event.py` (`EventAppend`, `EventRead`, `ProjectionResult`)
- [ ] Write `app/crud/event.py` (thin CRUD helpers wrapping `EventStore`)
- [ ] Write `app/api/routes/events.py` with 4 endpoint handlers (append, get_stream, replay, since)
- [ ] `_patch_routes_init` registers `events_router` idempotently
- [ ] `_patch_config` injects `EVENT_STORE_SNAPSHOT_INTERVAL: int = 50` inside `class Settings`
- [ ] `find_migration_head` resolves current Alembic head; write `alembic/versions/0079_add_event_sourcing.py` creating `events` table
- [ ] `ast.parse` loop over all created `.py` files; return `status="error"` if any fail
- [ ] Return `ToolResult` with `next_steps` including `alembic upgrade head`

---

## 16. References

| Document | Purpose |
|----------|---------|
| `adapt/extend/crud_data/add_event_sourcing.py` | Source implementation |
| `adapt/contracts/__init__.py` | `ToolInput`, `ToolResult` |
| `adapt/contracts/migration_helper.py` | `find_migration_head` |
| `specs/TOOL-078-add_data_versioning.md` | Sibling data tool (versioning publishes events) |
| `specs/TOOL-080-add_cqrs.md` | Companion: commands append events; queries read projections |
| `specs/TOOL-053-add_arq_worker.md` | Compatible: event processing via background jobs |

---

## 16.1 Troubleshooting Guide

### Symptom → Root Cause → Fix

| Symptom | Likely Cause | Diagnostic Command | Fix |
|---------|-------------|-------------------|-----|
| `UniqueViolationError` on `(stream_id, version)` | Concurrent appends both read `MAX(version)=N` and both insert `N+1` | `SHOW transaction_isolation;` | Use `SELECT MAX(version) FROM events WHERE stream_id=? FOR UPDATE` to serialise concurrent writers on the same stream |
| `append()` ignores `expected_version` | `expected_version=None` branch taken even when caller passes a value | `print(type(expected_version))` | Check caller isn't passing `expected_version=0` which is falsy — use `if expected_version is not None` (already correct in reference impl; verify no regression) |
| `Projector.rebuild()` returns empty state | `_handlers` registry is empty — `register()` never called | `print(projector._handlers)` | Call `projector.register("EventType", handler_fn)` before `rebuild()` |
| Snapshot not taken after N events | `EVENT_STORE_SNAPSHOT_INTERVAL` not read from env; hardcoded `50` | `grep -n "50" app/events/event_store.py` | Replace literal with `int(os.environ.get("EVENT_STORE_SNAPSHOT_INTERVAL", "50"))` |
| `get_stream()` returns events in wrong order | Missing `ORDER BY version ASC` in query | `EXPLAIN SELECT * FROM events WHERE stream_id=? LIMIT 1000;` | Add `.order_by(Event.version.asc())` to the select statement |
| `replay` endpoint replays all streams | Route accepts `stream_id` as optional but `EventStore.get_stream` requires it | Hit `/events/replay` without query param | Make `stream_id` required in route, or add validation before calling `get_stream` |
| `payload` JSONB silently truncates nested objects | `payload` column defined as `Text` instead of `JSON` | `\d events` in psql | Change column type to `sa.JSON` (or `postgresql.JSONB`) in migration |

### Event Sourcing Consistency Model

```
Writer path (strong consistency):
  POST /events/append
    │
    ├── [optional] check expected_version → SELECT MAX FOR UPDATE
    ├── INSERT event (stream_id, version, event_type, payload)
    └── COMMIT  ← serialisation point

Reader path (eventual consistency):
  GET /events/{stream_id}
    │
    └── SELECT * FROM events WHERE stream_id=? ORDER BY version ASC
          │
          └── [if snapshot exists] start from snapshot version, replay delta

Projector rebuild():
    events = get_stream(stream_id)
    state = initial_state
    for event in events:
        handler = _handlers[event.event_type]
        state = handler(state, event.payload)
    return state
```

**Key invariant**: the `(stream_id, version)` unique constraint is the sole concurrency control mechanism. No external lock manager, no queue. This is sufficient for single-writer streams; for multi-writer streams, use `expected_version` for optimistic concurrency.
