# TOOL-077: add_data_import

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_data_import` |
| Category | EXTEND > CRUD/Data |
| Complexity | High |
| Dependencies | FastAPI, SQLAlchemy 2.0, Alembic, pydantic-settings, csv (stdlib), openpyxl (lazy) |
| Signature | `add_data_import(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_data_import", "description": "Add CSV/Excel upload with async processing, validation and error reporting.", "tags": ["extend", "crud_data"], "entry": "add_data_import"}` |
| Files created (typical) | 8 — `app/imports/__init__.py`, `app/imports/processor.py`, `app/imports/validator.py`, `app/models/import_job.py`, `app/schemas/import_job.py`, `app/crud/import_job.py`, `app/api/routes/imports.py`, `alembic/versions/0077_add_data_import.py` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py` |

---

## 2. Purpose

The `fastapi_add_data_import` tool installs a production-grade data import pipeline for CSV and Excel files into a FastAPI project. The canonical failure mode for hand-rolled import handlers is processing files synchronously inside the request handler: a 50,000-row CSV blocks a Uvicorn worker for minutes, errors on row 40,000 discard all previous work, and there is no way for the user to check progress or download the error report.

This tool generates: (a) `app/models/import_job.py` — an `ImportJob` SQLAlchemy model tracking `filename`, `status` (pending/processing/completed/failed), `total_rows`, `processed_rows`, `error_count`, `result` (JSONB), `error_report` (JSONB), `created_by` UUID FK, `created_at`, `completed_at`; (b) `app/imports/processor.py` — `ImportProcessor` with `process_file` (dispatches to `_process_csv` or `_process_excel`) and `_process_batch` that validates rows in configurable batches (controlled by `IMPORT_BATCH_SIZE`), updates `ImportJob.processed_rows` after each batch, and collects per-row errors into `error_report`; (c) `app/imports/validator.py` — `RowValidator` base class + `DefaultRowValidator` that checks for required columns and non-empty values; (d) Pydantic schemas, async CRUD helpers (`create_import_job`, `update_import_progress`, `complete_import_job`, `fail_import_job`, `get_import_job`); (e) route handlers: `POST /imports/upload` (save file, create `ImportJob`, kick off `BackgroundTask`), `GET /imports/{job_id}/status` (poll progress), `GET /imports/{job_id}/errors` (download error report); (f) Alembic migration.

Key design decisions: `openpyxl` is imported lazily inside `_process_excel` only; CSV is parsed with stdlib `csv` module (no extra dep); large files are processed in `IMPORT_BATCH_SIZE` row batches so memory usage is bounded; per-row errors accumulate in `error_report` JSONB — not raised as exceptions — so a bad row on line 3 does not abort the import of 50,000 good rows; `BackgroundTasks` is used for the processing loop (replaceable with arq when `add_arq_worker` is also installed).

---

### Design Decisions Table

| Decision | Chosen Approach | Rejected Alternative | Reason |
|----------|----------------|---------------------|--------|
| Processing async | `BackgroundTasks` per request | Synchronous in handler | Prevents Uvicorn worker blocking; upload returns immediately |
| Excel import | Lazy `import openpyxl` inside `_process_excel` | Top-level import | App boots without openpyxl; `ImportError` only on first Excel upload |
| CSV parsing | stdlib `csv` module | `pandas.read_csv` | Zero extra dep; bounded memory; row-by-row iteration |
| Per-row errors | `error_report` JSONB accumulator | Raise exception on first bad row | Partial success is better than complete abort for large imports |
| Batch size | `IMPORT_BATCH_SIZE` config (default 100) | Process all rows in one query | Bounded memory; allows progress reporting per batch |
| Job status tracking | `ImportJob` DB row | In-memory state | Survives process restart; pollable from any replica |
| Error report retrieval | `GET /imports/{id}/errors` endpoint | Inline in status response | Decouples lightweight status poll from potentially large error report |

---

### Generated file tree

```
project/ (after tool run)
├── app/
│   ├── imports/
│   │   ├── __init__.py                  # package marker + ImportProcessor re-export
│   │   ├── processor.py                 # ImportProcessor (process_file, _process_csv, _process_excel, _process_batch)
│   │   └── validator.py                 # RowValidator base + DefaultRowValidator
│   ├── models/
│   │   ├── __init__.py                  # MODIFIED: + ImportJob import
│   │   └── import_job.py                # ImportJob SQLAlchemy model (10 columns)
│   ├── schemas/
│   │   └── import_job.py                # ImportJobCreate, ImportJobStatus, ImportJobError
│   ├── crud/
│   │   └── import_job.py                # create_import_job, update_import_progress, complete_import_job, fail_import_job, get_import_job
│   └── api/routes/
│       └── imports.py                   # POST /imports/upload, GET /{id}/status, GET /{id}/errors
├── app/core/
│   └── config.py                        # MODIFIED: + IMPORT_BATCH_SIZE, IMPORT_MAX_FILE_SIZE_MB
├── app/routes/
│   └── __init__.py                      # MODIFIED: + imports_router
└── alembic/versions/
    └── 0077_add_data_import.py          # import_jobs table
```

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget |
| Files created | ≥ 7 | Full import pipeline |
| Files modified | ≥ 2 | Config + models init |
| Max function LOC | ≤ 50 | Auditability |
| Upload endpoint response time | < 100 ms | File save + DB insert; processing async |
| Status poll latency | < 10 ms | Single-row PK lookup |
| Batch size default | 100 rows | Bounded memory; configurable |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── core/config.py       # No IMPORT_BATCH_SIZE or IMPORT_MAX_FILE_SIZE_MB
│   ├── models/__init__.py   # No ImportJob
│   └── routes/__init__.py   # No imports router
└── alembic/versions/
```

No import capability. CSV files must be processed synchronously in request handlers, blocking a Uvicorn worker for the duration.

### 4.2 ImportJob model: AFTER

```python
# app/models/import_job.py
class ImportJob(Base):
    __tablename__ = "import_jobs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default="pending", nullable=False)
    total_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_rows: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_report: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

### 4.3 ImportProcessor: AFTER

```python
# app/imports/processor.py (excerpt)
class ImportProcessor:
    async def process_file(
        self, job_id: uuid.UUID, file_path: str, session: AsyncSession
    ) -> None:
        ext = Path(file_path).suffix.lower()
        if ext == ".csv":
            await self._process_csv(job_id, file_path, session)
        elif ext in (".xlsx", ".xls"):
            await self._process_excel(job_id, file_path, session)
        else:
            await fail_import_job(session, job_id, error=f"Unsupported: {ext}")

    async def _process_excel(
        self, job_id: uuid.UUID, file_path: str, session: AsyncSession
    ) -> None:
        import openpyxl  # lazy: avoids import at module load time
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        sheet = wb.active
        rows = list(sheet.iter_rows(values_only=True))
        headers = [str(c) for c in rows[0]] if rows else []
        await self._process_batch(job_id, headers, rows[1:], session)
```

### 4.4 RowValidator: AFTER

```python
# app/imports/validator.py
class RowValidator:
    """Base class for row-level import validation."""
    def validate(self, row: dict) -> list[str]:
        raise NotImplementedError

class DefaultRowValidator(RowValidator):
    def __init__(self, required_fields: list[str] | None = None) -> None:
        self.required_fields = required_fields or []

    def validate(self, row: dict) -> list[str]:
        errors: list[str] = []
        for field in self.required_fields:
            if not row.get(field):
                errors.append(f"Missing required field: {field!r}")
        return errors
```

### 4.5 CRUD helpers: AFTER

```python
# app/crud/import_job.py (excerpt)
async def create_import_job(
    session: AsyncSession, filename: str, created_by: uuid.UUID | None = None
) -> ImportJob:
    job = ImportJob(filename=filename, status="pending", created_by=created_by)
    session.add(job)
    await session.flush()
    return job

async def update_import_progress(
    session: AsyncSession, job_id: uuid.UUID, processed_rows: int, error_count: int
) -> None:
    stmt = (
        update(ImportJob)
        .where(ImportJob.id == job_id)
        .values(processed_rows=processed_rows, error_count=error_count, status="processing")
    )
    await session.execute(stmt)
```

### 4.6 Routes: AFTER

```
POST /imports/upload           → save file + create ImportJob + BackgroundTask(process_file)
GET  /imports/{job_id}/status  → return ImportJob row as ImportJobStatus schema
GET  /imports/{job_id}/errors  → return error_report JSONB as JSON array
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Idempotent | `"ImportJob" in app/models/import_job.py` → `no_op` |
| QS-2 | `dry_run=True` zero writes | Early return before any `dest.write_text(...)` |
| QS-3 | All `.py` AST-parse | `ast.parse` loop after all writes |
| QS-4 | No function > 50 LOC | Construction discipline + AST walk |
| QS-5 | `openpyxl` lazy-imported | `import openpyxl` inside `_process_excel` body only; AST confirms absence at module level (INV-IMP-04) |
| QS-6 | Processing in batches | `IMPORT_BATCH_SIZE` config field (default 100) |
| QS-7 | Per-row errors collected, not raised | `error_report` JSONB list accumulator; no exception re-raised on row validation failure (INV-IMP-06) |
| QS-8 | Upload endpoint returns immediately | `BackgroundTasks` for file processing; upload handler returns < 100 ms |
| QS-9 | `execution_time_ms` positive | `_elapsed_ms(start)` all paths (INV-IMP-05) |
| QS-10 | Migration chained to head | `find_migration_head` |
| QS-11 | `ImportJob.status` machine | Values: `pending → processing → completed` or `pending → failed` |
| QS-12 | File size validated at upload | `IMPORT_MAX_FILE_SIZE_MB` guard in upload handler |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | `status="success"` on fresh project | `result.status == "success"` | T-01 |
| CC-02 | Second run `status="no_op"` | Empty lists | T-02 |
| CC-03 | `dry_run=True` zero writes | Filesystem unchanged | T-03 |
| CC-04 | ≥ 7 files created | `len(files_created) >= 7` | T-04 |
| CC-05 | ≥ 2 files modified | `len(files_modified) >= 2` | T-05 |
| CC-06 | All `.py` parse | `ast.parse` over tree | T-06 |
| CC-07 | No function > 50 LOC | AST walk | T-07 |
| CC-08 | `IMPORT_BATCH_SIZE` in Settings | Substring + indent | T-08 |
| CC-09 | `ImportJob` in `models/__init__` | Substring check | T-09 |
| CC-10 | Imports router registered | `"import" in routes.__init__` | T-10 |
| CC-11 | `app/models/import_job.py` contains `class ImportJob` | File + `"error_report"` | T-11 |
| CC-12 | `app/imports/processor.py` contains `ImportProcessor` with lazy openpyxl | File + `"import openpyxl"` inside function | T-12 |
| CC-13 | Routes have upload, status, errors endpoints | File + `/upload` + `/errors` | T-13 |
| CC-14 | Migration creates `import_jobs` table | File + `"import_jobs"` | T-14 |
| CC-15 | `execution_time_ms` positive | `> 0` | T-15 |
| CC-16 | `next_steps` mentions `alembic` | Contains `"alembic"` | T-16 |

---

## 7. Definition of Done (DoD)

- [ ] All 16 CC verified by `test_add_data_import.py`
- [ ] `openpyxl` lazy-imported in `_process_excel` only
- [ ] Per-row errors collected into `error_report`, not raised
- [ ] `BackgroundTasks` used for async processing
- [ ] `IMPORT_BATCH_SIZE` config field added to Settings

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-IMP-01 | Tool ALWAYS idempotent on second invocation | `"ImportJob" in model_file` → `no_op` | T-02 |
| INV-IMP-02 | `dry_run=True` NEVER writes to disk | Early return before any write | T-03 |
| INV-IMP-03 | Every generated `.py` MUST parse as valid Python | `ast.parse` loop after writes | T-06 |
| INV-IMP-04 | `openpyxl` MUST be lazy-imported | `import openpyxl` only inside `_process_excel` body; AST confirms no module-level import | T-12 |
| INV-IMP-05 | `execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` on all branches | T-15 |
| INV-IMP-06 | Per-row validation errors MUST NOT abort processing | `error_report` list accumulator; exception caught per row | T-11, T-12 |

---

## 9. User Stories

**US-01: Upload CSV and get job ID immediately**
- **Given:** `POST /imports/upload` with a 50,000-row CSV file
- **When:** File received by the upload endpoint
- **Then:** `ImportJob` row created with `status="pending"`; `job_id` returned immediately in < 100 ms; processing kicked off via `BackgroundTasks` (QS-8)

**US-02: Upload Excel file**
- **Given:** `POST /imports/upload` with a `.xlsx` file
- **When:** `ImportProcessor.process_file` called by background task
- **Then:** `import openpyxl` executed lazily inside `_process_excel`; rows extracted via `sheet.iter_rows` (INV-IMP-04)

**US-03: Poll progress mid-import**
- **Given:** `ImportJob` with `status="processing"`, `processed_rows=500`, `total_rows=10000`
- **When:** `GET /imports/{job_id}/status`
- **Then:** Returns `ImportJobStatus` with current `processed_rows` and `error_count`; response < 10 ms

**US-04: Complete import with no errors**
- **Given:** 1,000-row CSV, all rows valid
- **When:** Background task finishes
- **Then:** `status="completed"`, `processed_rows=1000`, `error_count=0`, `completed_at` set

**US-05: Bad rows don't abort import**
- **Given:** CSV with 3 invalid rows out of 100
- **When:** `_process_batch` encounters validation failure on row 3
- **Then:** Error appended to `error_report` list; processing continues for rows 4..100 (INV-IMP-06); final `error_count=3`

**US-06: Download error report**
- **Given:** Import completed with `error_count > 0`
- **When:** `GET /imports/{job_id}/errors`
- **Then:** Returns `error_report` JSONB array with per-row `{row_number, errors}` objects

**US-07: Re-run tool on already-configured project**
- **Given:** `app/models/import_job.py` already contains `"ImportJob"`
- **When:** Tool invoked again
- **Then:** `status="no_op"`, empty lists (CC-02, INV-IMP-01)

**US-08: dry_run preview**
- **Given:** Fresh fixture project
- **When:** `add_data_import(ToolInput(dry_run=True))`
- **Then:** `status="success"`, filesystem unchanged (CC-03, INV-IMP-02)

**US-09: Configure batch size**
- **Given:** `IMPORT_BATCH_SIZE=500` in env
- **When:** `_process_batch` processes the CSV
- **Then:** Rows processed in batches of 500; `update_import_progress` called after each batch

**US-10: File exceeds size limit**
- **Given:** `IMPORT_MAX_FILE_SIZE_MB=10`; uploaded file is 15 MB
- **When:** `POST /imports/upload` called
- **Then:** `HTTP 413 Request Entity Too Large` returned before job is created

**US-11: All rows invalid**
- **Given:** CSV where every row fails `DefaultRowValidator`
- **When:** Import completes
- **Then:** `status="completed"`, `error_count == total_rows`; `result` still set (EC-04)

**US-12: App boots without openpyxl installed**
- **Given:** `openpyxl` not in virtualenv
- **When:** FastAPI app starts; no Excel upload occurs
- **Then:** No `ImportError` at startup; error occurs only when Excel file is processed (INV-IMP-04)

---

## 10. Test Plan

All 16 tests live in `adapt/extend/crud_data/test_add_data_import.py`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `imp_t01` | `add_data_import(ToolInput(project_dir))` | `result.status == "success"` |
| T-02 | `test_idempotent` | Fixture `imp_t02`; run once | Run again | `r2.status == "no_op"`, empty `files_created` + `files_modified` |
| T-03 | `test_dry_run` | Fixture `imp_t03` | `add_data_import(ToolInput(dry_run=True))` | `status == "success"`; no new files on disk |
| T-04 | `test_files_created_count` | Fixture `imp_t04` | Run tool | `len(files_created) >= 7`, each path exists on disk |
| T-05 | `test_files_modified_count` | Fixture `imp_t05` | Run tool | `len(files_modified) >= 2`, each path exists on disk |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `imp_t06`; run tool | `ast.parse` every `.py` under `app/` | No `SyntaxError` raised |
| T-07 | `test_no_function_over_50_loc` | Fixture `imp_t07`; run tool | AST walk `app/`; count lines per `FunctionDef` | `max_loc <= 50` |
| T-08 | `test_config_fields_patched` | Fixture `imp_t08`; run tool | Read `app/core/config.py` | `"IMPORT_BATCH_SIZE"` present with 4-space indent |
| T-09 | `test_models_init_patched` | Fixture `imp_t09`; run tool | Read `app/models/__init__.py` | `"ImportJob"` in content |
| T-10 | `test_routes_registered` | Fixture `imp_t10`; run tool | Read `app/routes/__init__.py` | `"import"` in content (case-sensitive or case-insensitive) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-14)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_import_job_model` | Fixture `imp_t11`; run tool | Read `app/models/import_job.py` | `"class ImportJob"` + `"error_report"` + `"status"` present |
| T-12 | `test_processor_created` | Fixture `imp_t12`; run tool | Read `app/imports/processor.py` | `"ImportProcessor"` present; `"import openpyxl"` appears inside a function body (AST check: module-level import absent) |
| T-13 | `test_routes_created` | Fixture `imp_t13`; run tool | Read `app/api/routes/imports.py` | `"/upload"` + `"/errors"` + `"/status"` present |
| T-14 | `test_migration_created` | Fixture `imp_t14`; run tool | Scan `alembic/versions/` | File matching `*data_import*` exists; content contains `"import_jobs"` |

### 10.4 Category D — Meta (T-15 .. T-16)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-15 | `test_execution_time_recorded` | Fixture `imp_t15`; run tool | `result.execution_time_ms` | `> 0` |
| T-16 | `test_next_steps_mention_alembic` | Fixture `imp_t16`; run tool | Lowercase-join `result.next_steps` | Contains `"alembic"` |

---

## 11. Interaction Matrix

| Other tool | Interaction | Notes |
|------------|-------------|-------|
| `add_arq_worker` (TOOL-053) | ✅ Compatible | Replace `BackgroundTasks` with `enqueue("process_import_task", ...)` for durable retry |
| `add_data_versioning` (TOOL-078) | ✅ Compatible | Import can create versioned content items |
| `add_excel_export` (TOOL-084) | ✅ Compatible | Import/export symmetry; same openpyxl dependency |

---

## 11.1 Anti-patterns This Tool Prevents

| Anti-pattern | How this tool avoids it |
|-------------|------------------------|
| Synchronous CSV processing in request handler (blocks Uvicorn worker) | `BackgroundTasks` — processing happens after response is sent — QS-8 |
| Raising exception on first bad row, aborting 50,000-row import | Per-row errors collected in `error_report` accumulator — INV-IMP-06 |
| `import openpyxl` at module level (crash if not installed) | Lazy `import openpyxl` inside `_process_excel` — INV-IMP-04 |
| Loading entire file into memory (OOM for large files) | Batch processing via `_process_batch(batch_size=IMPORT_BATCH_SIZE)` |
| No progress reporting | `processed_rows` updated after each batch; polled via `GET /imports/{id}/status` |
| No error detail for failed rows | `error_report` JSONB array with `{row_number, errors}` per failed row |
| Import results lost on process restart | `ImportJob` row in DB — survives restart; queryable from any replica |

---

## 12. Rollback Procedure

```bash
git checkout HEAD -- app/core/config.py app/models/__init__.py app/routes/__init__.py
rm -rf app/imports/ app/models/import_job.py app/schemas/import_job.py \
       app/crud/import_job.py app/api/routes/imports.py
find alembic/versions/ -name '*data_import*' -delete
alembic downgrade -1
```

---

## 13. Edge Cases

| # | Scenario | Expected |
|---|----------|----------|
| EC-01 | Empty CSV (0 rows, headers only) | `total_rows=0`; job status transitions to `"completed"` immediately |
| EC-02 | Empty CSV (no headers) | `total_rows=0`; `error_report` records `"Empty file"` |
| EC-03 | Excel `.xlsx` file | `import openpyxl` executed lazily inside `_process_excel`; first sheet processed |
| EC-04 | File with only a header row | `total_rows=0`; `status="completed"` |
| EC-05 | All rows invalid | `status="completed"` with `error_count == total_rows`; `result` still populated |
| EC-06 | Invalid project_dir | `status="error"` with diagnostic message |
| EC-07 | Missing prerequisites | `status="error"` listing missing files |
| EC-08 | Second run (idempotent) | `status="no_op"`, empty `files_created` and `files_modified` |
| EC-09 | `alembic/versions/` missing | Migration step skipped; tool still returns `"success"` |
| EC-10 | File size exceeds `IMPORT_MAX_FILE_SIZE_MB` | Upload endpoint returns `HTTP 413` |
| EC-11 | `openpyxl` not installed at upload time | No error at upload; `ImportError` raised only when Excel file is processed |
| EC-12 | Row with extra columns | Extra columns ignored by `DefaultRowValidator`; no error |
| EC-13 | Row with missing required column | `DefaultRowValidator` appends error; row counted in `error_report` |
| EC-14 | Background task crashes mid-processing | `status` set to `"failed"` via `fail_import_job` CRUD helper |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 16 CC verified by `test_add_data_import.py`
2. ✅ Upload endpoint returns < 100 ms (async processing via `BackgroundTasks`)
3. ✅ `openpyxl` lazy-imported inside `_process_excel` only (INV-IMP-04)
4. ✅ Per-row errors collected into `error_report` JSONB; do not abort processing (QS-7)
5. ✅ `IMPORT_BATCH_SIZE` config field added to Settings; default 100
6. ✅ Second invocation returns `status="no_op"` (INV-IMP-01)
7. ✅ `dry_run=True` produces zero writes (INV-IMP-02)
8. ✅ All generated `.py` files AST-parse (INV-IMP-03)
9. ✅ `execution_time_ms` positive on all return paths (INV-IMP-05)

---

## 15. Implementation Checklist (Ultra-granular)

- [ ] `validate_project_dir` confirms path exists and is a directory
- [ ] `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS)` passes
- [ ] Fingerprint check on `app/models/import_job.py` (`"ImportJob" in content` → `no_op`)
- [ ] `dry_run` guard: early return with `status="success"` before any file write
- [ ] Write `app/models/import_job.py` with `ImportJob` model (all 10 columns including `error_report`, `status`, `processed_rows`, `completed_at`)
- [ ] `_patch_models_init` appends `from app.models.import_job import ImportJob` idempotently
- [ ] Write `app/imports/__init__.py` (package marker, re-export `ImportProcessor`)
- [ ] Write `app/imports/processor.py` with `ImportProcessor` (`process_file`, `_process_csv`, `_process_excel` with lazy `import openpyxl`, `_process_batch`)
- [ ] Write `app/imports/validator.py` with `RowValidator` base class + `DefaultRowValidator`
- [ ] Write `app/schemas/import_job.py` (`ImportJobCreate`, `ImportJobStatus`, `ImportJobError`)
- [ ] Write `app/crud/import_job.py` (`create_import_job`, `update_import_progress`, `complete_import_job`, `fail_import_job`, `get_import_job`)
- [ ] Write `app/api/routes/imports.py` (upload endpoint with `BackgroundTasks`, status endpoint, errors endpoint)
- [ ] `_patch_routes_init` registers `imports_router` idempotently
- [ ] `_patch_config` injects `IMPORT_BATCH_SIZE: int = 100` and `IMPORT_MAX_FILE_SIZE_MB: int = 50` anchored inside `class Settings`
- [ ] `find_migration_head` resolves current Alembic head; write `alembic/versions/0077_add_data_import.py`
- [ ] `ast.parse` loop over all created `.py` files; return `status="error"` if any fail
- [ ] Return `ToolResult` with `next_steps` including `alembic upgrade head` and optional `pip install openpyxl` note

---

## 16. References

| Document | Purpose |
|----------|---------|
| `adapt/extend/crud_data/add_data_import.py` | Source implementation |
| `adapt/extend/crud_data/test_add_data_import.py` | Reference test file (31 tests) |
| `adapt/contracts/__init__.py` | `ToolInput`, `ToolResult` |
| `adapt/contracts/migration_helper.py` | `find_migration_head` |
| `specs/TOOL-053-add_arq_worker.md` | Reference template (replace BackgroundTasks with arq) |
| `specs/TOOL-078-add_data_versioning.md` | Sibling data tool |
| `specs/TOOL-084-add_excel_export.md` | Companion export tool (shared openpyxl dependency) |

---

## 16.1 Troubleshooting Guide

### Symptom → Root Cause → Fix

| Symptom | Likely Cause | Diagnostic Command | Fix |
|---------|-------------|-------------------|-----|
| `ImportError: No module named 'openpyxl'` at test time | `openpyxl` imported at module level | `grep -n "^import openpyxl" app/services/import_processor.py` | Move import inside `_process_excel` body only |
| `ImportJob` stuck in `processing` status | `BackgroundTasks` background function raised uncaught exception | Check `stderr` / logs for traceback | Wrap `_run_import` body in `try/except`, call `fail_import_job` in except block |
| CSV rows silently dropped | BOM character `\ufeff` in header row | `repr(headers[0])` in debug log | Open file with `open(path, encoding="utf-8-sig")` to strip BOM |
| Large file causes OOM | `list(sheet.iter_rows(...))` loads entire file into memory | Monitor RSS during import | Stream rows in chunks: `iter_rows` in batches of `IMPORT_BATCH_SIZE` without materialising the whole list |
| `error_report` JSONB column won't accept dict | SQLAlchemy `JSON` type not imported in migration | Check `alembic/versions/0077_add_data_import.py` | Add `sa.JSON` for `error_report` column; ensure `postgresql_using="jsonb"` |
| Tool returns `no_op` on first run | Fingerprint check too broad: any `ImportJob` reference in project | `grep -r "ImportJob" app/` | Narrow fingerprint to `"class ImportJob(" in models/import_job.py` |
| Duplicate rows on retry | `create_import_job` uses auto-increment PK but caller re-submits same file | Check `import_jobs.filename` column | Add `UNIQUE(filename, status)` partial index on `processing` rows or use idempotency key |

### Import Performance Reference

| File Type | Rows | IMPORT_BATCH_SIZE | Typical Wall Time | Peak Memory |
|-----------|------|-------------------|-------------------|-------------|
| CSV (UTF-8) | 10 000 | 100 | < 3 s | < 50 MB |
| CSV (UTF-8) | 100 000 | 500 | < 30 s | < 120 MB |
| XLSX | 10 000 | 100 | < 8 s | < 80 MB |
| XLSX | 50 000 | 200 | < 60 s | < 200 MB |

Numbers are indicative for a mid-range server with a local Postgres instance. Tune `IMPORT_BATCH_SIZE` upwards for network-latency-dominated workloads and downwards for memory-constrained environments.
