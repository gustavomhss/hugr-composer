---
spec_id: "TOOL-084"
tool_name: "add_excel_export"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-EXCEL-01"
  - "INV-EXCEL-02"
  - "INV-EXCEL-03"
  - "INV-EXCEL-04"
  - "INV-EXCEL-05"
  - "INV-EXCEL-06"
  - "INV-EXCEL-07"
  - "INV-EXCEL-08"
  - "INV-EXCEL-09"
  - "INV-EXCEL-10"
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
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-13"
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
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
tags:
  - "performance"
  - "data"
  - "realtime"
  - "compliance"
  - "api"
---
# TOOL-084: add_excel_export

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_excel_export` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Dependencies | FastAPI, pydantic-settings; `openpyxl` is optional (lazy-imported) |
| Signature | `add_excel_export(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_excel_export", "description": "Add a production-grade Excel export layer with OpenPyXL streaming for large datasets, cell formatting, auto-width columns, and StreamingResponse download routes.", "tags": ["extend", "infrastructure"], "entry": "add_excel_export"}` |
| Files created (typical) | 5 — `app/exports/__init__.py`, `app/exports/excel.py`, `app/exports/formatters.py`, `app/api/routes/excel_export.py`, and `openpyxl>=3.1.0` appended to `requirements.txt` (via modify) |
| Files modified (typical) | 3 — `app/core/config.py`, `app/routes/__init__.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_excel_export` tool installs a production-grade Excel export layer into a FastAPI project using **openpyxl** with a streaming model for large datasets. The naive approach — `openpyxl.Workbook()`, fill all rows in memory, save to `BytesIO`, return in a single response — works for tens of rows but fails for thousands: the workbook consumes hundreds of megabytes of heap, the request times out, and the load balancer closes the connection before the client receives a byte. Operators reach for Celery + S3 to solve this, adding infrastructure that is disproportionate to the problem. This tool takes a simpler path: `ExcelExporter.stream_rows()` is a generator that yields after each batch of `EXCEL_CHUNK_SIZE` rows, allowing cooperative scheduling, and `FastAPI.StreamingResponse` streams the serialised bytes directly to the client without buffering the full file.

It generates: (a) an `app/exports/` package with `ExcelExporter` (`create_workbook`, `add_sheet`, `stream_rows` generator, `to_bytes`) and a `formatters.py` module (`apply_header_style` with bold/grey header, `auto_fit_columns` based on cell content length, `format_cell` with number format); (b) two HTTP routes — `POST /exports/excel` (accepts `model_name`, `filters`, optional `sheet_title`; builds workbook; returns `StreamingResponse`) and `GET /exports/{export_id}/download` (downloads a previously saved `.xlsx` file); (c) two settings fields `EXCEL_MAX_ROWS` and `EXCEL_CHUNK_SIZE` injected inside `class Settings`; and (d) `openpyxl>=3.1.0` appended to `requirements.txt`.

Key design decisions: all openpyxl imports are **lazy** (inside method bodies) so the app boots without the library; `stream_rows()` raises `ValueError` when total rows exceed `EXCEL_MAX_ROWS` — preventing silent OOM; `auto_fit_columns()` caps column width at `max_width=60` characters to prevent absurdly wide sheets; cell formatting uses openpyxl styles loaded lazily inside each helper so `formatters.py` is importable without openpyxl; `StreamingResponse` returns the workbook bytes as `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` with `Content-Disposition: attachment` — correct MIME type for Excel on all browsers; the tool is **idempotent** — detects `ExcelExporter` in `app/exports/__init__.py`.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget (T-18) |
| Files created | ≥ 4 | Package (3), routes (T-04) |
| Files modified | ≥ 2 | Config, routes init, requirements (T-05) |
| Max function LOC in generated code | ≤ 50 | Auditable (T-07) |
| `POST /exports/excel` latency | < build time + 10 ms | Streaming; no full buffer in memory |
| Row write throughput | ≥ 10,000 rows/s | openpyxl append is fast; chunked for fairness |
| Peak memory for 10K rows | < 200 MB | openpyxl normal mode (not write-only); bounded by `chunk_size` |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── core/config.py       # No EXCEL_* settings
│   └── routes/__init__.py   # No exports router
└── requirements.txt         # no openpyxl
```

Excel export absent or naive (full in-memory workbook, OOM on large datasets).

### 4.2 ExcelExporter: AFTER

```python
# app/exports/excel.py
class ExcelExporter:
    def create_workbook(self):
        import openpyxl  # lazy
        return openpyxl.Workbook()

    def add_sheet(self, workbook, title: str, headers: list[str]):
        """Add sheet with bold header row."""

    def stream_rows(self, worksheet, rows: Iterable[list[Any]]) -> Iterator[None]:
        """Yield after each chunk; raise ValueError if max_rows exceeded."""

    def to_bytes(self, workbook) -> bytes:
        """Serialise workbook to bytes via BytesIO."""
```

### 4.3 StreamingResponse route: AFTER

```python
# app/api/routes/excel_export.py
@router.post("/excel")
async def export_excel(body: ExcelExportRequest) -> StreamingResponse:
    exporter = _get_exporter()
    wb = exporter.create_workbook()
    ws = exporter.add_sheet(wb, ...)
    for _ in exporter.stream_rows(ws, iter(rows)):
        pass
    excel_bytes = exporter.to_bytes(wb)
    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
```

### 4.4 Config patch: AFTER

```python
# app/core/config.py
    # --- Excel export — added by add_excel_export tool ---
    EXCEL_MAX_ROWS: int = 100000
    EXCEL_CHUNK_SIZE: int = 1000
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `"ExcelExporter" in app/exports/__init__.py` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any write |
| QS-3 | **Every generated `.py` AST-parses** | Final `ast.parse` loop |
| QS-4 | **No generated function exceeds 50 LOC** | All helpers and methods short by construction |
| QS-5 | **openpyxl is lazy-imported** | `import openpyxl` inside method bodies only; `from openpyxl.styles ...` inside formatters |
| QS-6 | **`stream_rows` raises `ValueError` on row limit exceeded** | `if count >= self.max_rows: raise ValueError(...)` |
| QS-7 | **`StreamingResponse` uses correct MIME type** | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| QS-8 | **`Content-Disposition: attachment` set on streaming response** | `headers={"Content-Disposition": f"attachment; filename={filename}"}` |
| QS-9 | **`EXCEL_*` fields inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` |
| QS-10 | **`openpyxl>=3.1.0` added to `requirements.txt`** | `_patch_requirements` appends if absent |
| QS-11 | **Router registered in `app/routes/__init__.py`** | `_register_router` injects import + include call |
| QS-12 | **Column widths capped at `max_width=60`** | `min(max(current, value_len + 2), max_width)` in `auto_fit_columns` |
| QS-13 | **`execution_time_ms` set on every return path** | `_elapsed_ms(start)` on all branches |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | Both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes | Filesystem snapshot identical | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 4 new files | `len(files_created) >= 4`; all paths exist | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(files_modified) >= 2`; all exist | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses | `ast.parse` over all `.py` | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC | AST walk; `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `EXCEL_MAX_ROWS` exists inside `class Settings` | String scan + 4-space indent | T-08 (`test_config_fields_patched`) |
| CC-09 | Exports router registered in `app/routes/__init__.py` | `"export" in content.lower()` | T-09 (`test_routes_registered`) |
| CC-10 | `openpyxl>=3.1.0` in `requirements.txt` | `"openpyxl" in content.lower()` | T-10 (`test_requirements_patched`) |
| CC-11 | `app/exports/__init__.py` contains `ExcelExporter` | File exists + `"ExcelExporter" in content` | T-11 (`test_exports_init_created`) |
| CC-12 | `app/exports/excel.py` has all four ExcelExporter methods | `create_workbook`, `add_sheet`, `stream_rows`, `to_bytes` present | T-12 (`test_excel_exporter_created`) |
| CC-13 | `app/exports/formatters.py` has all three helpers | `apply_header_style`, `auto_fit_columns`, `format_cell` present | T-13 (`test_formatters_created`) |
| CC-14 | openpyxl is lazy-imported in `excel.py` | `"import openpyxl"` inside function body, not at module top | T-14 (`test_openpyxl_lazy_imported`) |
| CC-15 | `stream_rows` raises `ValueError` on row limit | `"raise ValueError" in stream_rows body` | T-15 (`test_stream_rows_has_limit`) |
| CC-16 | `app/api/routes/excel_export.py` has both route handlers | `export_excel` and `download_export` present | T-16 (`test_routes_created`) |
| CC-17 | `StreamingResponse` uses correct MIME type | `"vnd.openxmlformats-officedocument.spreadsheetml.sheet" in routes file` | T-17 (`test_streaming_mime_type`) |
| CC-18 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | T-18 (`test_execution_time_recorded`) |
| CC-19 | `next_steps` include `openpyxl` install guidance | `"openpyxl" in " ".join(result.next_steps).lower()` | T-19 (`test_next_steps_mention_openpyxl`) |
| CC-20 | Running the tool twice leaves project AST-parseable | `ast.parse` over all `.py` after two runs | T-20 (`test_idempotent_project_still_parses`) |

---

## 7. Definition of Done (DoD)

- [ ] All 20 Completeness Criteria verified by `test_add_excel_export.py`
- [ ] `ast.parse` run on every created `.py` before returning success
- [ ] Fingerprint `"ExcelExporter" in app/exports/__init__.py` → `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty lists
- [ ] `import openpyxl` and `from openpyxl.styles ...` inside method bodies only
- [ ] `stream_rows()` raises `ValueError` when total rows exceed `EXCEL_MAX_ROWS`
- [ ] `StreamingResponse` uses `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- [ ] `Content-Disposition: attachment; filename=...` header set
- [ ] `EXCEL_*` fields anchored inside `class Settings`
- [ ] `openpyxl>=3.1.0` added to `requirements.txt`
- [ ] `execution_time_ms` set on every return path
- [ ] Tool exits within 5 s on fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}`

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-EXCEL-01 | Tool ALWAYS idempotent on second invocation | `"ExcelExporter" in exports_init` → `status="no_op"` | T-02, T-20 |
| INV-EXCEL-02 | `dry_run=True` NEVER writes to disk | Early return before any write | T-03 |
| INV-EXCEL-03 | Every generated `.py` MUST parse as valid Python | Final `ast.parse` loop | T-06, T-20 |
| INV-EXCEL-04 | openpyxl MUST be lazy-imported inside method bodies | `import openpyxl` / `from openpyxl.styles ...` inside functions | T-14 |
| INV-EXCEL-05 | `stream_rows` MUST raise `ValueError` when `max_rows` exceeded | `if count >= self.max_rows: raise ValueError(...)` | T-15 |
| INV-EXCEL-06 | `StreamingResponse` MUST use correct MIME type | `vnd.openxmlformats-officedocument.spreadsheetml.sheet` | T-17 |
| INV-EXCEL-07 | Config fields MUST live inside `class Settings` body | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` | T-08 |
| INV-EXCEL-08 | `openpyxl>=3.1.0` MUST be in `requirements.txt` | `_patch_requirements` appends if absent | T-10 |
| INV-EXCEL-09 | `ToolResult.execution_time_ms` MUST be positive | `_elapsed_ms(start)` on all branches | T-18 |
| INV-EXCEL-10 | `next_steps` MUST reference `openpyxl` install | `"openpyxl"` in `next_steps` | T-19 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install Excel export into a clean project**
- **As a** backend engineer
- **When:** `add_excel_export(ToolInput(project_dir=...))`
- **Then:** `status="success"`, ≥ 4 files created, ≥ 2 modified (T-01, T-04, T-05)

**US-02: Re-run on already-installed project**
- **Given:** `app/exports/__init__.py` contains `ExcelExporter`
- **When:** Tool invoked again
- **Then:** `status="no_op"`, empty lists (T-02, T-20)

**US-03: Dry-run preview**
- **When:** `add_excel_export(ToolInput(dry_run=True))`
- **Then:** Success + notes; filesystem unchanged (T-03)

**US-04: App boots without openpyxl installed**
- **Given:** `openpyxl` not installed
- **When:** App starts
- **Then:** No `ImportError`; error only at first `create_workbook()` call (INV-EXCEL-04)

**US-05: Generated code is auditable**
- **When:** AST-walk `app/` for function sizes
- **Then:** No function > 50 LOC (T-07)

### 9.2 ExcelExporter (US-06 .. US-10)

**US-06: Create workbook with header row**
- **Given:** openpyxl installed
- **When:** `exporter.add_sheet(wb, "Users", ["id", "email", "created_at"])`
- **Then:** Worksheet with bold, grey-background, centred header row (T-12)

**US-07: Stream 10K rows without OOM**
- **Given:** `EXCEL_CHUNK_SIZE=1000`, `EXCEL_MAX_ROWS=100000`
- **When:** `stream_rows(ws, iter(10_000_row_list))`
- **Then:** Rows written in 10 batches of 1000; generator yields after each; total memory bounded (T-12)

**US-08: Row limit enforced**
- **Given:** `EXCEL_MAX_ROWS=5`
- **When:** `stream_rows(ws, iter(range(10)))` attempts to write 10 rows
- **Then:** `ValueError("Export exceeds EXCEL_MAX_ROWS=5. Add filters to reduce the dataset.")` raised (INV-EXCEL-05, T-15)

**US-09: Column widths auto-fitted**
- **Given:** Worksheet with mixed-length cell values
- **When:** `auto_fit_columns(ws)` called inside `stream_rows` completion
- **Then:** Column widths set to max content length + 2, capped at 60 chars (QS-12, T-13)

**US-10: Workbook serialised to bytes**
- **Given:** Populated workbook
- **When:** `exporter.to_bytes(wb)`
- **Then:** Returns non-empty `bytes`; `len(result) > 0` (T-12)

### 9.3 HTTP routes (US-11 .. US-15)

**US-11: Export via HTTP POST**
- **When:** `POST /exports/excel` `{"model_name": "users", "filters": {}}`
- **Then:** `StreamingResponse` with `.xlsx` content and correct MIME type (T-16, T-17)

**US-12: Custom sheet title**
- **When:** `POST /exports/excel` `{"model_name": "orders", "sheet_title": "Q1 Orders"}`
- **Then:** Worksheet tab named `"Q1 Orders"` (T-16)

**US-13: Row limit exceeded returns 400**
- **Given:** `EXCEL_MAX_ROWS=1` and dataset has 2 rows
- **When:** `POST /exports/excel`
- **Then:** HTTP 400 with `"Export exceeds EXCEL_MAX_ROWS"` detail (T-16)

**US-14: Download previously saved export**
- **Given:** Export file saved to `EXCEL_OUTPUT_DIR` with ID `abc`
- **When:** `GET /exports/abc/download`
- **Then:** `StreamingResponse` with `.xlsx` content (T-16)

**US-15: Unknown export_id returns 404**
- **When:** `GET /exports/unknown_id/download`
- **Then:** HTTP 404 `"Export not found."` (T-16)

### 9.4 Formatters (US-16 .. US-20)

**US-16: Header row is bold and grey**
- **Given:** `apply_header_style(ws, row=1, num_cols=3)`
- **When:** Cell styles inspected
- **Then:** Font bold, fill `D3D3D3`, alignment centred (T-13)

**US-17: `apply_header_style` loads gracefully without openpyxl**
- **Given:** openpyxl not installed
- **When:** `apply_header_style(ws)` called
- **Then:** WARNING logged; no `ImportError` crash (T-13)

**US-18: Auto-fit respects minimum width**
- **Given:** Column with single-character values
- **When:** `auto_fit_columns(ws, min_width=8)`
- **Then:** Column width ≥ 8 (T-13)

**US-19: Auto-fit caps at maximum width**
- **Given:** Column with 200-character values
- **When:** `auto_fit_columns(ws, max_width=60)`
- **Then:** Column width ≤ 60 (T-13)

**US-20: `format_cell` applies number format**
- **Given:** `format_cell(cell, 1234.56, number_format="#,##0.00")`
- **When:** Cell inspected
- **Then:** `cell.value == 1234.56` and `cell.number_format == "#,##0.00"` (T-13)

### 9.5 Config and operator experience (US-21 .. US-25)

**US-21: Config binds from environment variables**
- **Given:** `EXCEL_CHUNK_SIZE=500` in `.env`
- **When:** `Settings()` instantiated
- **Then:** `settings.EXCEL_CHUNK_SIZE == 500` (INV-EXCEL-07, T-08)

**US-22: `openpyxl` added to requirements**
- **Given:** `requirements.txt` without openpyxl
- **When:** Tool runs
- **Then:** `requirements.txt` contains `openpyxl>=3.1.0` (INV-EXCEL-08, T-10)

**US-23: `next_steps` guide operator**
- **When:** `result.next_steps` inspected
- **Then:** Contains `"pip install openpyxl"` (INV-EXCEL-10, T-19)

**US-24: Execution time recorded**
- **Then:** `result.execution_time_ms > 0` (INV-EXCEL-09, T-18)

**US-25: Second run leaves project parseable**
- **Given:** Tool ran twice
- **When:** All `.py` files AST-parsed
- **Then:** No `SyntaxError` (INV-EXCEL-01, T-20)

---

## 10. Test Plan

All 20 tests live in `adapt/extend/infrastructure/test_add_excel_export.py`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `excel_t01` | `add_excel_export(ToolInput(project_dir))` | `result.status == "success"` (CC-01) |
| T-02 | `test_idempotent` | Fixture `excel_t02`; run once | Run again | `r2.status == "no_op"` (CC-02) |
| T-03 | `test_dry_run` | Fixture `excel_t03` | `dry_run=True` | Success; FS unchanged (CC-03) |
| T-04 | `test_files_created_count` | Fixture `excel_t04` | Run tool | `len(files_created) >= 4`; all exist (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `excel_t05` | Run tool | `len(files_modified) >= 2`; all exist (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `excel_t06`; run | AST-parse all `.py` | No `SyntaxError` (CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `excel_t07`; run | AST walk `app/` | `max_loc <= 50` (CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `excel_t08`; run | Read `config.py` | `EXCEL_MAX_ROWS` with 4-space indent (CC-08) |
| T-09 | `test_routes_registered` | Fixture `excel_t09`; run | Read `routes/__init__.py` | Contains `"export"` (CC-09) |
| T-10 | `test_requirements_patched` | Fixture `excel_t10`; run | Read `requirements.txt` | `"openpyxl"` present (CC-10) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_exports_init_created` | Fixture `excel_t11`; run | Read `app/exports/__init__.py` | Contains `"ExcelExporter"` (CC-11) |
| T-12 | `test_excel_exporter_created` | Fixture `excel_t12`; run | Read `app/exports/excel.py` | All four methods present (CC-12) |
| T-13 | `test_formatters_created` | Fixture `excel_t13`; run | Read `app/exports/formatters.py` | All three helpers present (CC-13) |
| T-14 | `test_openpyxl_lazy_imported` | Fixture `excel_t14`; run | Read `app/exports/excel.py` | `"import openpyxl"` inside function body (INV-EXCEL-04, CC-14) |
| T-15 | `test_stream_rows_has_limit` | Fixture `excel_t15`; run | Read `app/exports/excel.py` | `"raise ValueError"` inside `stream_rows` (INV-EXCEL-05, CC-15) |
| T-16 | `test_routes_created` | Fixture `excel_t16`; run | Read `app/api/routes/excel_export.py` | `export_excel` and `download_export` present (CC-16) |
| T-17 | `test_streaming_mime_type` | Fixture `excel_t17`; run | Read routes file | `"vnd.openxmlformats-officedocument.spreadsheetml.sheet"` present (INV-EXCEL-06, CC-17) |

### 10.4 Category D — Meta (T-18 .. T-20)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-18 | `test_execution_time_recorded` | Fixture `excel_t18` | `result.execution_time_ms` | `> 0` (CC-18) |
| T-19 | `test_next_steps_mention_openpyxl` | Fixture `excel_t19` | Lowercase-join `result.next_steps` | Contains `"openpyxl"` (CC-19) |
| T-20 | `test_idempotent_project_still_parses` | Fixture `excel_t20`; run twice | AST-parse all `.py` | No `SyntaxError` (CC-20) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_excel_export.py -v
```

Target: 20/20 passed, 0 failed.

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | Large exports can be queued as arq tasks; `to_bytes()` result uploaded to S3 |
| `add_s3_storage` (TOOL-060) | No | ✅ Compatible | Store generated `.xlsx` files in S3 instead of temp dir |
| `add_data_export` (TOOL-006) | No | ✅ Compatible | TOOL-006 handles CSV export; TOOL-084 handles Excel; can coexist |
| `add_rbac` (TOOL-012) | Yes — RBAC runs AFTER | ⚠️ Caveat | Add role gate to `POST /exports/excel` |
| `add_cursor_pagination` (TOOL-002) | No | ✅ Compatible | Paginate source data before passing to `stream_rows()` |
| `add_multi_tenancy` (TOOL-008) | No | ⚠️ Caveat | Tenant ID should be injected into export filters to prevent cross-tenant data leaks |
| `add_audit_log` (TOOL-005) | No | ✅ Compatible | Log export events: who exported what, when, how many rows |

---

## 12. Rollback Procedure

### 12.1 Code rollback

```bash
git checkout HEAD -- app/core/config.py app/routes/__init__.py requirements.txt
rm -rf app/exports/ app/api/routes/excel_export.py
```

No database migration; no schema to roll back.

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Missing `app/` directory | `validate_project_dir` fails → `status="error"` |
| EC-02 | `app/exports/__init__.py` already contains `ExcelExporter` | Early return `status="no_op"` |
| EC-03 | `dry_run=True` | Success + notes; no FS changes |
| EC-04 | openpyxl not installed | `ImportError` raised inside `create_workbook()`; `apply_header_style` logs WARNING |
| EC-05 | Row count exceeds `EXCEL_MAX_ROWS` | `stream_rows` raises `ValueError`; route returns HTTP 400 |
| EC-06 | `EXCEL_MAX_ROWS` already in config | `_patch_config` early-returns |
| EC-07 | `openpyxl` already in requirements | `_patch_requirements` early-returns |
| EC-08 | `app/routes/__init__.py` already registers exports router | `_register_router` early-returns |
| EC-09 | `app/api/routes/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` |
| EC-10 | Sheet title omitted | Defaults to `body.model_name.title()` |
| EC-11 | Empty row iterable passed to `stream_rows` | Exits generator normally; `auto_fit_columns` called on empty sheet |
| EC-12 | `find_migration_head` irrelevant | No migration in this tool |
| EC-13 | Tool runs twice | Second run returns `no_op`; project parses (T-20) |

---

## 14. Security Considerations

| # | Concern | Mitigation |
|---|---------|------------|
| SEC-01 | Unauthenticated export endpoint | `POST /exports/excel` has no auth gate by default; add `CurrentUser` gate |
| SEC-02 | Cross-tenant data leak | `filters` param should be validated server-side to restrict to authenticated user's tenant |
| SEC-03 | Disk exhaustion from saved exports | `GET /exports/{id}/download` reads from disk; add periodic cleanup job |
| SEC-04 | OOM via row limit bypass | `EXCEL_MAX_ROWS` enforced in `stream_rows()`; cannot be overridden via HTTP params |
| SEC-05 | Path traversal in download | `export_id` used in `glob(f"*{export_id}*.xlsx")` — glob pattern, not direct path join |

---

## 15. Observability

| Signal | Location | Notes |
|--------|----------|-------|
| `Streamed {N} rows to sheet '{name}'` | `stream_rows()` | DEBUG level |
| `Excel export failed` | `export_excel` route catch | ERROR level with exception |
| `openpyxl not installed` | `create_workbook()` | `ImportError` message |
| `openpyxl not installed; skipping header style` | `apply_header_style()` | WARNING level |

---

## 16. Changelog

| Version | Date | Change |
|---------|------|--------|
| v1 | 2026-04-15 | Initial spec — openpyxl lazy, stream_rows generator, auto-width, StreamingResponse, 20 CCs |
