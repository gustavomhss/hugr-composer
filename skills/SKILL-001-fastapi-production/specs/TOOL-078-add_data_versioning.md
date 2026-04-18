# TOOL-078: add_data_versioning

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_data_versioning` |
| Category | EXTEND > CRUD/Data |
| Complexity | High |
| Dependencies | FastAPI, SQLAlchemy 2.0, Alembic, pydantic-settings, difflib (stdlib) |
| Signature | `add_data_versioning(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_data_versioning", "description": "Add draft/published/archived lifecycle with diff to any content type.", "tags": ["extend", "crud_data"], "entry": "add_data_versioning"}` |
| Files created (typical) | 8 — `app/versioning/__init__.py`, `app/versioning/service.py`, `app/models/content_version.py`, `app/schemas/content_version.py`, `app/crud/content_version.py`, `app/api/routes/versioning.py`, `alembic/versions/0078_add_data_versioning.py` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py` |

---

## 2. Purpose

The `fastapi_add_data_versioning` tool installs a content versioning system with `draft → published → archived` lifecycle management into a FastAPI project. CMS and document-management applications need this pattern but it is consistently under-engineered: versions are stored as mutable records (losing history), there is no diff mechanism to show what changed between versions, and there is no cap on concurrent drafts per content item, leading to confusion about which draft to publish.

This tool generates: (a) `app/models/content_version.py` — a `ContentVersion` SQLAlchemy model with `content_id` UUID (FK to the parent content table), `version_number` Integer auto-incremented per `content_id`, `status` (`draft`/`published`/`archived`), `content` JSONB (the actual content snapshot), `author_id` UUID FK, `created_at`, `published_at`, `archived_at`; (b) `app/versioning/service.py` — `VersioningService` with `create_draft`, `publish` (atomically archives all other published versions), `archive`, `get_history`, and `diff` (uses `difflib.unified_diff` on JSON serializations); (c) Pydantic schemas, CRUD helpers, REST endpoints (`POST /versioning/{content_id}/drafts`, `POST /versioning/{content_id}/versions/{version_id}/publish`, `GET /versioning/{content_id}/history`, `GET /versioning/{content_id}/diff`); (d) `VERSIONING_MAX_DRAFTS` config field (default 5) limiting concurrent drafts per content item — `create_draft` raises HTTP 409 when exceeded; (e) Alembic migration.

Key design decisions: `publish()` is an atomic operation — it sets the target version's `status="published"` and all other `published` versions for that `content_id` to `archived` in a single transaction; `diff()` uses stdlib `difflib.unified_diff` on JSON-serialized content objects — no extra dep; `VERSIONING_MAX_DRAFTS` prevents runaway draft accumulation (default 10; configurable per operator); version numbers are auto-incremented per `content_id` via a `SELECT MAX(version_number) + 1` pattern inside the service; the `UniqueConstraint("content_id", "version_number")` at the DB level catches race conditions on version number generation.

The lifecycle state machine for a `ContentVersion` row is: `draft → published` (via `publish()`), `draft → archived` (via `archive()`), `published → archived` (atomically when a newer version is published). There is no transition from `archived` back to `draft` or `published` — archives are immutable history. The `author_id` FK uses `ON DELETE SET NULL` so that deleting a `User` does not cascade-delete their version history; the `ContentVersion` row is preserved with `author_id=null`.

The `diff()` method accepts two `ContentVersion` objects by value and returns a unified diff string. The caller is responsible for fetching the two versions from the DB (typically by `version_number`). The diff format uses `fromfile=f"v{v1.version_number}"` and `tofile=f"v{v2.version_number}"` labels for clarity in PR-style review UIs.

---

### Design Decisions Table

| Decision | Chosen Approach | Rejected Alternative | Reason |
|----------|----------------|---------------------|--------|
| Status values | `draft`, `published`, `archived` (string) | Enum column | String is simpler; easy to add new states without migration |
| `publish()` atomicity | Two UPDATEs in a single transaction | Two separate commits | Single `commit()` prevents window where no published version exists |
| `diff()` dependency | `difflib.unified_diff` (stdlib) | `diff-match-patch` or `jsondiff` | Zero external dep; unified diff is universally understood |
| Version number computation | `MAX(version_number) + 1` per `content_id` | Global auto-increment | Per-content versioning; version 1 always means "first version of this item" |
| Max drafts enforcement | `COUNT(*) WHERE status='draft' AND content_id=?` | Application-level flag | DB read is authoritative; handles concurrent draft creation correctly |
| Archive-on-publish | All `published` versions for `content_id` archived | Only one explicit previous version | Ensures invariant: at most one `published` version per `content_id` at any time |

---

### Generated file tree

```
project/ (after tool run)
├── app/
│   ├── versioning/
│   │   ├── __init__.py                  # package marker
│   │   └── service.py                   # VersioningService (create_draft, publish, archive, get_history, diff)
│   ├── models/
│   │   ├── __init__.py                  # MODIFIED: + ContentVersion import
│   │   └── content_version.py           # ContentVersion SQLAlchemy model + uq_version_content_number
│   ├── schemas/
│   │   └── content_version.py           # ContentVersionCreate, ContentVersionRead, DiffRequest, DiffResponse
│   ├── crud/
│   │   └── content_version.py           # CRUD helpers (thin wrappers around VersioningService)
│   └── api/routes/
│       └── versioning.py                # 5 endpoints: drafts, publish, archive, history, diff
├── app/core/
│   └── config.py                        # MODIFIED: + VERSIONING_MAX_DRAFTS
├── app/routes/
│   └── __init__.py                      # MODIFIED: + versioning_router
└── alembic/versions/
    └── 0078_add_data_versioning.py      # content_versions table + uq_version_content_number
```

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget |
| Files created | ≥ 7 | Full versioning kit |
| Files modified | ≥ 2 | Config + models init |
| Max function LOC | ≤ 50 | Auditability |
| `create_draft()` latency | < 10 ms | Single INSERT with version number computation |
| `publish()` latency | < 20 ms | Two-query atomic transaction (archive others + publish target) |
| `get_history()` latency | < 15 ms | Index scan on `(content_id, version_number)` |
| `diff()` latency | < 50 ms | Two-row PK load + stdlib `difflib.unified_diff` |
| `archive()` latency | < 10 ms | Single UPDATE by PK |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── core/config.py       # No VERSIONING_MAX_DRAFTS
│   ├── models/__init__.py   # No ContentVersion
│   └── routes/__init__.py   # No versioning router
└── alembic/versions/
```

Content stored as mutable rows with no history, no draft/publish lifecycle.

### 4.2 ContentVersion model: AFTER

```python
# app/models/content_version.py
class ContentVersion(Base):
    __tablename__ = "content_versions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default="draft", nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("content_id", "version_number", name="uq_version_content_number"),
    )
```

### 4.3 VersioningService: AFTER

```python
# app/versioning/service.py (excerpt)
class VersioningService:
    async def publish(
        self, session: AsyncSession, content_id: uuid.UUID, version_id: uuid.UUID
    ) -> ContentVersion:
        """Atomically publish one version and archive all others."""
        # Archive all currently published versions for this content_id
        archive_stmt = (
            update(ContentVersion)
            .where(
                ContentVersion.content_id == content_id,
                ContentVersion.status == "published",
                ContentVersion.id != version_id,
            )
            .values(status="archived", archived_at=datetime.utcnow())
        )
        await session.execute(archive_stmt)
        # Promote target version
        publish_stmt = (
            update(ContentVersion)
            .where(ContentVersion.id == version_id)
            .values(status="published", published_at=datetime.utcnow())
            .returning(ContentVersion)
        )
        result = await session.execute(publish_stmt)
        return result.scalar_one()

    def diff(self, v1: ContentVersion, v2: ContentVersion) -> str:
        """Return unified diff of JSON-serialized content."""
        import difflib
        a = json.dumps(v1.content, indent=2, sort_keys=True).splitlines(keepends=True)
        b = json.dumps(v2.content, indent=2, sort_keys=True).splitlines(keepends=True)
        return "".join(difflib.unified_diff(a, b, fromfile=f"v{v1.version_number}", tofile=f"v{v2.version_number}"))
```

### 4.4 Routes: AFTER

```
POST /versioning/{content_id}/drafts                              → create draft (enforce VERSIONING_MAX_DRAFTS)
POST /versioning/{content_id}/versions/{version_id}/publish       → atomic publish (archive others)
POST /versioning/{content_id}/versions/{version_id}/archive       → archive single version
GET  /versioning/{content_id}/history                             → list all versions ordered by version_number
GET  /versioning/{content_id}/diff?from_version=1&to_version=2   → stdlib unified diff
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Idempotent | `"ContentVersion" in app/models/content_version.py` → `no_op` |
| QS-2 | `dry_run=True` zero writes | Early return before any `dest.write_text(...)` |
| QS-3 | All `.py` parse | `ast.parse` loop after all writes |
| QS-4 | No function > 50 LOC | Construction discipline + AST walk |
| QS-5 | `publish()` is atomic | Both archive and publish updates in single `await session.commit()` |
| QS-6 | `VERSIONING_MAX_DRAFTS` enforced | `create_draft` counts current drafts; raises `HTTP 409` when `count >= VERSIONING_MAX_DRAFTS` |
| QS-7 | `diff()` uses stdlib only | `difflib.unified_diff` — no third-party dep required (INV-VER-07) |
| QS-8 | Version numbers auto-increment per content item | `SELECT MAX(version_number) + 1 WHERE content_id=?` inside `create_draft` |
| QS-9 | `execution_time_ms` positive | `_elapsed_ms(start)` all branches |
| QS-10 | Migration chained to head | `find_migration_head` used |
| QS-11 | History ordered by version | `ORDER BY version_number ASC` in `get_history` |
| QS-12 | `author_id` FK allows NULL | `ON DELETE SET NULL` preserves version history when users deleted |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | `status="success"` on fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run `no_op` | `r2.status == "no_op"`, empty lists | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` zero writes | Filesystem byte-identical | T-03 (`test_dry_run`) |
| CC-04 | ≥ 7 files created | `len(files_created) >= 7`, each exists | T-04 (`test_files_created_count`) |
| CC-05 | ≥ 2 files modified | `len(files_modified) >= 2`, each exists | T-05 (`test_files_modified_count`) |
| CC-06 | All `.py` AST-parse | `ast.parse` over all `.py` | T-06 (`test_all_py_parse`) |
| CC-07 | No function > 50 LOC | AST walk, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `VERSIONING_MAX_DRAFTS` in Settings with indent | Substring + 4-space indent | T-08 (`test_config_fields_patched`) |
| CC-09 | `ContentVersion` in `app/models/__init__.py` | `"ContentVersion" in content` | T-09 (`test_models_init_patched`) |
| CC-10 | Versioning router registered | `"version" in routes.__init__` | T-10 (`test_routes_registered`) |
| CC-11 | `app/models/content_version.py` with `uq_version_content_number` | File + `"class ContentVersion"` + constraint name | T-11 (`test_model_created`) |
| CC-12 | `app/versioning/service.py` with `VersioningService`, `publish`, `diff` | File + substrings | T-12 (`test_service_created`) |
| CC-13 | Routes have `/drafts`, `/publish`, `/history`, `/diff` | File + path strings | T-13 (`test_routes_created`) |
| CC-14 | Migration creates `content_versions` table | Migration file + `"content_versions"` | T-14 (`test_migration_created`) |
| CC-15 | `execution_time_ms` positive | `result.execution_time_ms > 0` | T-15 (`test_execution_time_recorded`) |
| CC-16 | `next_steps` mentions `alembic` | Lowercase-join contains `"alembic"` | T-16 (`test_next_steps_mention_alembic`) |

---

## 7. Definition of Done (DoD)

- [ ] All 16 CC verified by `test_add_data_versioning.py`
- [ ] `publish()` atomically archives all other published versions for same `content_id`
- [ ] `VERSIONING_MAX_DRAFTS` config field added; `create_draft` enforces it
- [ ] `diff()` uses `difflib.unified_diff` — no external dep
- [ ] Version numbers auto-increment per `content_id`

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-VER-01 | Tool ALWAYS idempotent on second invocation | `"ContentVersion" in model_file` → `no_op` | T-02 |
| INV-VER-02 | `dry_run=True` NEVER writes to disk | Early return before any write | T-03 |
| INV-VER-03 | Every generated `.py` MUST parse as valid Python | `ast.parse` loop | T-06 |
| INV-VER-04 | `publish()` MUST be atomic | Both archive and publish updates in single transaction commit | T-12 |
| INV-VER-05 | Max drafts MUST be enforced | `create_draft` raises `HTTP 409` when count `>= VERSIONING_MAX_DRAFTS` | T-12 |
| INV-VER-06 | `execution_time_ms` MUST be positive | `_elapsed_ms(start)` on all branches | T-15 |
| INV-VER-07 | `diff()` MUST use stdlib only | `difflib.unified_diff` — no third-party dep | T-12 |

---

## 9. User Stories

**US-01: Install versioning into a clean project**
- **Given:** FastAPI project with base prereqs
- **When:** `add_data_versioning(ToolInput(project_dir=...))`
- **Then:** `status="success"`, `files_created >= 7`, `files_modified >= 2` (CC-01, CC-04, CC-05)

**US-02: Create a first draft**
- **Given:** Content item `content_id` with no existing versions
- **When:** `POST /versioning/{content_id}/drafts` with `{content: {...}}`
- **Then:** `ContentVersion` row created with `status="draft"`, `version_number=1`

**US-03: Create a second draft**
- **Given:** One draft already exists (`version_number=1`)
- **When:** `POST /versioning/{content_id}/drafts` again
- **Then:** New row with `version_number=2`; first draft unchanged

**US-04: Publish a draft**
- **Given:** Draft `v2` exists; `v1` is currently `"published"`
- **When:** `POST /versioning/{content_id}/versions/{v2.id}/publish`
- **Then:** `v2.status = "published"`, `v1.status = "archived"` — atomic single transaction (INV-VER-04)

**US-05: Reject excess drafts**
- **Given:** `VERSIONING_MAX_DRAFTS=5` and 5 drafts already exist
- **When:** `POST /versioning/{content_id}/drafts` again
- **Then:** `HTTP 409 Conflict` returned; no row inserted (INV-VER-05)

**US-06: Archive a version explicitly**
- **Given:** Published version `v1`
- **When:** `POST /versioning/{content_id}/versions/{v1.id}/archive`
- **Then:** `v1.status = "archived"`, `archived_at` set; content item has no published version

**US-07: View version history**
- **Given:** 4 versions exist (2 archived, 1 published, 1 draft)
- **When:** `GET /versioning/{content_id}/history`
- **Then:** Returns all 4 ordered by `version_number` ascending

**US-08: Compute diff between two versions**
- **Given:** Version 1 has `{title: "Foo"}`, version 3 has `{title: "Bar"}`
- **When:** `GET /versioning/{content_id}/diff?from_version=1&to_version=3`
- **Then:** Unified diff using `difflib.unified_diff` on JSON serializations; no external dep (QS-7)

**US-09: Diff of identical versions**
- **Given:** Two versions with identical content
- **When:** `GET diff?from_version=X&to_version=X`
- **Then:** Empty diff string returned (EC-03)

**US-10: Re-run tool on already-configured project**
- **Given:** `app/models/content_version.py` already contains `"ContentVersion"`
- **When:** Tool invoked again
- **Then:** `status="no_op"`, empty lists (CC-02, INV-VER-01)

**US-11: dry_run preview**
- **Given:** Fresh fixture project
- **When:** `add_data_versioning(ToolInput(dry_run=True))`
- **Then:** `status="success"`, filesystem unchanged (CC-03, INV-VER-02)

**US-12: VERSIONING_MAX_DRAFTS=0 blocks all drafts**
- **Given:** `VERSIONING_MAX_DRAFTS=0` in env
- **When:** Any `POST /versioning/{content_id}/drafts` call
- **Then:** Immediate `HTTP 409` regardless of existing draft count (EC-04)

---

## 10. Test Plan

All 16 tests live in `adapt/extend/crud_data/test_add_data_versioning.py`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `ver_t01` | `add_data_versioning(ToolInput(project_dir))` | `result.status == "success"` |
| T-02 | `test_idempotent` | Fixture `ver_t02`; run once | Run again | `r2.status == "no_op"`, empty `files_created` + `files_modified` |
| T-03 | `test_dry_run` | Fixture `ver_t03` | `add_data_versioning(ToolInput(dry_run=True))` | `status == "success"`; no files written |
| T-04 | `test_files_created_count` | Fixture `ver_t04` | Run tool | `len(files_created) >= 7`, each path exists on disk |
| T-05 | `test_files_modified_count` | Fixture `ver_t05` | Run tool | `len(files_modified) >= 2`, each path exists on disk |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `ver_t06`; run tool | `ast.parse` every `.py` under `app/` | No `SyntaxError` |
| T-07 | `test_no_function_over_50_loc` | Fixture `ver_t07`; run tool | AST walk `app/`; count lines per `FunctionDef` | `max_loc <= 50` |
| T-08 | `test_config_fields_patched` | Fixture `ver_t08`; run tool | Read `app/core/config.py` | `"VERSIONING_MAX_DRAFTS"` present with 4-space indent inside `class Settings` |
| T-09 | `test_models_init_patched` | Fixture `ver_t09`; run tool | Read `app/models/__init__.py` | `"ContentVersion"` in content |
| T-10 | `test_routes_registered` | Fixture `ver_t10`; run tool | Read `app/routes/__init__.py` | `"version"` in content |

### 10.3 Category C — Domain-specific modules (T-11 .. T-14)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_model_created` | Fixture `ver_t11`; run tool | Read `app/models/content_version.py` | `"class ContentVersion"` + `"uq_version_content_number"` + `"published_at"` present |
| T-12 | `test_service_created` | Fixture `ver_t12`; run tool | Read `app/versioning/service.py` | `"VersioningService"` + `"publish"` + `"diff"` present |
| T-13 | `test_routes_created` | Fixture `ver_t13`; run tool | Read `app/api/routes/versioning.py` | `"/drafts"` + `"/publish"` + `"/diff"` present |
| T-14 | `test_migration_created` | Fixture `ver_t14`; run tool | Scan `alembic/versions/` | File matching `*versioning*` with `"content_versions"` in content |

### 10.4 Category D — Meta (T-15 .. T-16)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-15 | `test_execution_time_recorded` | Fixture `ver_t15`; run tool | `result.execution_time_ms` | `> 0` |
| T-16 | `test_next_steps_mention_alembic` | Fixture `ver_t16`; run tool | Lowercase-join `result.next_steps` | Contains `"alembic"` |

---

## 11. Interaction Matrix

| Other tool | Interaction | Notes |
|------------|-------------|-------|
| `add_data_import` (TOOL-077) | ✅ Compatible | Import can create versioned content items |
| `add_event_sourcing` (TOOL-079) | ✅ Compatible | Versioning publishes `version.published` events |
| `add_audit_log` (TOOL-005) | ✅ Compatible | `publish()` and `archive()` emit audit entries |
| `add_soft_delete` (TOOL-001) | ⚠️ Caveat | Soft-deleting a `ContentVersion` should not be allowed; history must be immutable |

---

## 11.1 Anti-patterns This Tool Prevents

| Anti-pattern | How this tool avoids it |
|-------------|------------------------|
| Mutable content rows (no history) | `content_versions` table stores immutable snapshots; rows never UPDATEd |
| Multiple published versions simultaneously | `publish()` atomically archives all other `published` versions in same transaction — INV-VER-04 |
| Unlimited draft accumulation per content item | `VERSIONING_MAX_DRAFTS` + `COUNT(*)` guard in `create_draft` — INV-VER-05 |
| Third-party diff library dependency | `difflib.unified_diff` from stdlib — INV-VER-07 |
| Version numbers that reset across content items | `MAX(version_number) + 1 WHERE content_id=?` — per-item monotonic sequence |
| Deleting user cascading to lost version history | `author_id` FK with `ON DELETE SET NULL` — version rows preserved with `author_id=null` |
| Race condition on version number | `UniqueConstraint("content_id", "version_number")` — DB enforces sequence uniqueness |

---

## 12. Rollback Procedure

### 12.1 Code rollback

```bash
git checkout HEAD -- app/core/config.py app/models/__init__.py app/routes/__init__.py
rm -rf app/versioning/ app/models/content_version.py app/schemas/content_version.py \
       app/crud/content_version.py app/api/routes/versioning.py
find alembic/versions/ -name '*versioning*' -delete
```

### 12.2 Database rollback

```bash
alembic downgrade -1   # drops content_versions table
```

---

## 13. Edge Cases

| # | Scenario | Expected |
|---|----------|----------|
| EC-01 | Publish already-published version | `status="published"` stays; no SQL update; no-op response |
| EC-02 | Archive already-archived version | `HTTP 409 Conflict` |
| EC-03 | Diff on same version number | Empty diff string returned (no lines differ) |
| EC-04 | `VERSIONING_MAX_DRAFTS=0` | Every draft creation rejected with `HTTP 409` immediately |
| EC-05 | `alembic/versions/` missing | Migration step skipped; tool still returns `"success"` with note |
| EC-06 | Second run (idempotent) | `status="no_op"`, empty lists |
| EC-07 | `from_version` or `to_version` not found | `HTTP 404` for missing version |
| EC-08 | Content JSONB is `null` | `diff` treats as empty dict; no crash |
| EC-09 | `author_id` FK points to deleted user | `ON DELETE SET NULL` preserves history; `author_id` becomes `null` |
| EC-10 | Invalid `project_dir` | `status="error"` with diagnostic message |
| EC-11 | Missing prerequisites | `status="error"` listing missing files |
| EC-12 | `version_number` auto-increment race | `UniqueConstraint("content_id", "version_number")` raises `IntegrityError`; service retries |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 16 CC verified by `test_add_data_versioning.py`
2. ✅ `publish()` atomically archives all other published versions in a single transaction (INV-VER-04)
3. ✅ `VERSIONING_MAX_DRAFTS` enforced; `create_draft` raises `HTTP 409` when exceeded (INV-VER-05)
4. ✅ `diff()` uses `difflib.unified_diff` only — no external dep (QS-7)
5. ✅ Version numbers auto-increment per `content_id` via `MAX(version_number) + 1` (QS-8)
6. ✅ Second invocation returns `status="no_op"` (INV-VER-01)
7. ✅ `dry_run=True` produces zero writes (INV-VER-02)
8. ✅ All generated `.py` files AST-parse (INV-VER-03)
9. ✅ `execution_time_ms` positive on all return paths (INV-VER-06)

---

## 15. Implementation Checklist (Ultra-granular)

- [ ] `validate_project_dir` confirms path exists and is a directory
- [ ] `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS)` passes
- [ ] Fingerprint check: `"ContentVersion" in (project_dir / "app/models/content_version.py").read_text()` → `no_op`
- [ ] `dry_run` guard: early return with `status="success"` before any file write
- [ ] Write `app/models/content_version.py` with `ContentVersion` model (all columns: `content_id`, `version_number`, `status`, `content`, `author_id`, `created_at`, `published_at`, `archived_at`) + `UniqueConstraint("content_id", "version_number", name="uq_version_content_number")`
- [ ] `_patch_models_init` appends `from app.models.content_version import ContentVersion` idempotently
- [ ] Write `app/versioning/__init__.py` (package marker)
- [ ] Write `app/versioning/service.py` with `VersioningService` (`create_draft`, `publish`, `archive`, `get_history`, `diff`)
- [ ] Ensure `publish()` is atomic: single call archives others + promotes target in same `await session.commit()`
- [ ] Ensure `diff()` uses `difflib.unified_diff` — no `import difflib` at module level; inside method body only
- [ ] Ensure `create_draft` computes `version_number = (MAX(version_number) for content_id) + 1`
- [ ] Ensure `create_draft` enforces `VERSIONING_MAX_DRAFTS` via `COUNT(*) WHERE status='draft' AND content_id=?`
- [ ] Write `app/schemas/content_version.py` (`ContentVersionCreate`, `ContentVersionRead`, `DiffRequest`, `DiffResponse`)
- [ ] Write `app/crud/content_version.py` (CRUD helpers calling `VersioningService`)
- [ ] Write `app/api/routes/versioning.py` with 5 endpoints (drafts, publish, archive, history, diff)
- [ ] `_patch_routes_init` registers `versioning_router` idempotently
- [ ] `_patch_config` injects `VERSIONING_MAX_DRAFTS: int = 10` inside `class Settings`
- [ ] `find_migration_head` resolves current Alembic head; write `alembic/versions/0078_add_data_versioning.py`
- [ ] `ast.parse` loop over all created `.py` files; return `status="error"` if any fail
- [ ] Return `ToolResult` with `next_steps` including `alembic upgrade head`

---

## 16. References

| Document | Purpose |
|----------|---------|
| `adapt/extend/crud_data/add_data_versioning.py` | Source implementation |
| `adapt/contracts/__init__.py` | `ToolInput`, `ToolResult` |
| `adapt/contracts/migration_helper.py` | `find_migration_head` |
| `specs/TOOL-077-add_data_import.md` | Sibling data tool (import can create versioned items) |
| `specs/TOOL-079-add_event_sourcing.md` | Sibling data tool (versioning publishes events) |
| `specs/TOOL-005-add_audit_log.md` | Compatible: `publish()` and `archive()` emit audit entries |

---

## 16.1 Troubleshooting Guide

### Symptom → Root Cause → Fix

| Symptom | Likely Cause | Diagnostic Command | Fix |
|---------|-------------|-------------------|-----|
| `publish()` returns but old `published` row still has status `published` | `UPDATE ... WHERE status='published'` not committed before second UPDATE | Inspect transaction isolation in test | Confirm single `await session.commit()` at end of `publish()`; both UPDATEs must be in the same transaction |
| `diff()` output is empty for two different versions | Splitting on `\n` produces identical lists due to trailing newline | `repr(content_a.splitlines())` | Use `.splitlines(keepends=True)` or `.split("\n")` consistently for both sides |
| `create_draft` raises `IntegrityError` on `version_number` | Two concurrent requests both read `MAX(version_number)` as N and both try to insert N+1 | `SHOW transaction_isolation;` | Add `SELECT ... FOR UPDATE` lock on the content row before computing max, or use a DB sequence |
| Draft cap not enforced | `VERSIONING_MAX_DRAFTS` env var is set but `_enforce_draft_cap` reads hardcoded `10` | `grep VERSIONING_MAX_DRAFTS app/services/versioning.py` | Replace literal with `int(os.environ.get("VERSIONING_MAX_DRAFTS", "10"))` at call time |
| `status` column accepts arbitrary strings | No DB-level constraint in migration | `\d content_versions` in psql | Add `CheckConstraint("status IN ('draft','published','archived')", name="ck_cv_status")` to migration |
| `archived_at` is NULL after archive | `archive()` sets `status="archived"` but forgets to set `archived_at` | `SELECT archived_at FROM content_versions WHERE status='archived' LIMIT 5;` | Add `.values(status="archived", archived_at=datetime.utcnow())` |
| Tool idempotency broken — re-run adds duplicate router registration | `_patch_routes_init` uses simple string append instead of idempotency check | `grep versioning_router app/api/routes/__init__.py` | Check `if "versioning_router" not in content` before appending |

### Version Lifecycle State Diagram

```
         create_draft()
              │
              ▼
           [draft] ──── create_draft() ──▶ [draft] (new version, same content_id)
              │
              │ publish()
              ▼
         [published] ◀─────────────────────────────────────────────────┐
              │                                                         │
              │ publish(other_version)                                  │
              ▼                                                         │
          [archived]           (previous published auto-archived)       │
              │                                                         │
              │ re-publish?  (requires new draft creation first)  ──────┘
```

- Only **one** `published` version per `content_id` is enforced by the `publish()` atomic UPDATE.
- `archived` versions are immutable; they cannot transition back to `draft` or `published` without creating a new draft (by copying content).
- `VERSIONING_MAX_DRAFTS` is checked at `create_draft` time only; existing drafts are never auto-deleted.
