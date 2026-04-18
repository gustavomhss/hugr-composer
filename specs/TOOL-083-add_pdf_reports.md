# TOOL-083: add_pdf_reports

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_pdf_reports` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Dependencies | FastAPI, Jinja2 (required), WeasyPrint (optional, lazy-imported), pydantic-settings |
| Signature | `add_pdf_reports(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_pdf_reports", "description": "Add a production-grade PDF report generation layer with WeasyPrint lazy import, Jinja2 templates, async generation via run_in_executor, and download routes.", "tags": ["extend", "infrastructure"], "entry": "add_pdf_reports"}` |
| Files created (typical) | 7 — `app/reports/__init__.py`, `app/reports/engine.py`, `app/reports/templates/invoice.html`, `app/reports/templates/summary.html`, `app/reports/templates/receipt.html`, `app/schemas/report.py`, `app/api/routes/reports.py` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/routes/__init__.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_pdf_reports` tool installs a production-grade PDF generation pipeline into a FastAPI project using a **WeasyPrint + Jinja2** approach. Teams needing PDFs typically reach for one of three bad paths: (1) blocking the event loop by calling `weasyprint.HTML(string=html).write_pdf()` directly in a route handler — which serialises all PDF requests through a single Uvicorn worker; (2) importing `weasyprint` at module level — which crashes the application on any server that lacks `libcairo` / `libpango` system dependencies; or (3) paying for a SaaS PDF API that adds per-page pricing and a dependency on external uptime. This tool takes a fourth path: lazy import, async executor offload, and template-first design.

It generates: (a) an `app/reports/` package with a `ReportEngine` class that wraps `render_template()` (Jinja2, autoescape enabled, renders the HTML) and `render_html_to_pdf()` (WeasyPrint, lazy-imported inside the method) and `generate_pdf_async()` (runs rendering in a `ThreadPoolExecutor` via `loop.run_in_executor` so the async event loop is never blocked); (b) three built-in HTML templates — `invoice.html`, `summary.html`, `receipt.html` — all using Jinja2 variable syntax with `default` filters so missing context keys never throw `UndefinedError`; (c) `ReportRequest` / `ReportResponse` Pydantic schemas; (d) two HTTP routes — `POST /reports/generate` (render + save to disk, returns `{report_id, download_url, size_bytes}`) and `GET /reports/{report_id}/download` (file download via `FileResponse`); (e) three settings fields — `REPORT_TEMPLATE_DIR`, `REPORT_OUTPUT_DIR`, `REPORT_MAX_PAGES` — injected inside `class Settings`; and (f) `jinja2>=3.1.0` appended to `requirements.txt` (WeasyPrint is intentionally NOT added — operators install it separately so container builds without PDF support stay slim).

Key design decisions: WeasyPrint is **lazy-imported** inside `render_html_to_pdf()` — the app boots without it; `generate_pdf_async()` uses a module-level `ThreadPoolExecutor(max_workers=4)` — not the default executor — so PDF rendering threads have a named pool (`thread_name_prefix="pdf-worker"`) and do not compete with other CPU-bound work; Jinja2 templates use `autoescape=select_autoescape(["html", "xml"])` so user-supplied context values cannot inject HTML/JavaScript; output paths are derived from `REPORT_OUTPUT_DIR` — the route handler never concatenates user-supplied filenames into the path (each report gets a `uuid4()` prefix); the tool is **idempotent** — second run detects `ReportEngine` in `app/reports/__init__.py` and returns `status="no_op"`.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget (T-18) |
| Files created | ≥ 6 | Package (2), templates (3), schemas, routes (T-04) |
| Files modified | ≥ 2 | Config, routes `__init__`, requirements (T-05) |
| Max function LOC in generated code | ≤ 50 | Auditable by construction (T-07) |
| Event loop block time | 0 ms | `generate_pdf_async()` delegates to `ThreadPoolExecutor` |
| `POST /reports/generate` latency | < PDF render time + 10 ms | Dominated by WeasyPrint; async so other requests proceed |
| `GET /reports/{id}/download` latency | < 20 ms | `glob` + `FileResponse` path resolution |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── core/config.py       # No REPORT_* settings
│   └── routes/__init__.py   # No reports router
└── requirements.txt         # no jinja2, no weasyprint
```

PDF generation either absent, or blocking the event loop, or crashing at boot due to top-level `import weasyprint`.

### 4.2 ReportEngine: AFTER

```python
# app/reports/engine.py
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pdf-worker")

class ReportEngine:
    def render_template(self, template_name: str, context: dict) -> str:
        """Render Jinja2 HTML template — autoescape enabled."""
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        env = Environment(loader=FileSystemLoader(str(self.template_dir)),
                          autoescape=select_autoescape(["html", "xml"]))
        return env.get_template(template_name).render(**context)

    def render_html_to_pdf(self, html: str) -> bytes:
        """Convert HTML to PDF bytes — WeasyPrint imported lazily."""
        from weasyprint import HTML  # lazy — optional dep
        return HTML(string=html).write_pdf()

    async def generate_pdf_async(self, template_name: str, context: dict) -> bytes:
        """Off-loop: render template then convert to PDF in executor."""
        loop = asyncio.get_running_loop()
        html = self.render_template(template_name, context)
        return await loop.run_in_executor(_executor, self.render_html_to_pdf, html)
```

### 4.3 HTTP routes: AFTER

```python
# app/api/routes/reports.py
router = APIRouter(prefix="/reports", tags=["reports"])

POST  /reports/generate          → ReportResponse (201)
GET   /reports/{report_id}/download → FileResponse (PDF)
```

### 4.4 Config patch: AFTER

```python
# app/core/config.py  (added by _patch_config)
    # --- PDF reports — added by add_pdf_reports tool ---
    REPORT_TEMPLATE_DIR: str = "app/reports/templates"
    REPORT_OUTPUT_DIR: str = "/tmp/reports"
    REPORT_MAX_PAGES: int = 100
```

### 4.5 Requirements patch: AFTER

```
# requirements.txt (appended by _patch_requirements)
jinja2>=3.1.0
```

WeasyPrint is NOT added — install separately (`pip install weasyprint`) when PDF rendering is needed.

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Fingerprint `"ReportEngine" in app/reports/__init__.py` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any write |
| QS-3 | **Every generated `.py` AST-parses** | `ast.parse` loop on all created `.py` |
| QS-4 | **No generated function exceeds 50 LOC** | `ReportEngine` methods kept short |
| QS-5 | **WeasyPrint lazy-imported inside `render_html_to_pdf`** | `from weasyprint import HTML` inside method body only |
| QS-6 | **Jinja2 autoescape enabled for HTML/XML** | `autoescape=select_autoescape(["html", "xml"])` in `render_template()` |
| QS-7 | **PDF rendering off the event loop** | `loop.run_in_executor(_executor, self.render_html_to_pdf, html)` |
| QS-8 | **Output paths derived from settings, not user input** | `output_dir = Path(settings.REPORT_OUTPUT_DIR)` in route; report filename uses `uuid4()` |
| QS-9 | **`REPORT_*` fields inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` |
| QS-10 | **`jinja2>=3.1.0` added to requirements** | `_patch_requirements` appends if absent; WeasyPrint omitted intentionally |
| QS-11 | **Router registered in `app/routes/__init__.py`** | `_register_router` injects import + `api_router.include_router(reports_router)` |
| QS-12 | **`execution_time_ms` set on every return path** | `_elapsed_ms(start)` on all branches |
| QS-13 | **Templates use `default` filter for all variables** | `{{ invoice_number | default('INV-0001') }}` — `UndefinedError` never thrown |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | Both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes | Filesystem snapshot identical | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 6 new files | `len(files_created) >= 6`; all paths exist | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(files_modified) >= 2`; all paths exist | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses | `ast.parse` over all `.py` | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC | AST walk; `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `REPORT_TEMPLATE_DIR` exists inside `class Settings` | String scan + 4-space indent | T-08 (`test_config_fields_patched`) |
| CC-09 | Reports router registered in `app/routes/__init__.py` | `"report" in content.lower()` | T-09 (`test_routes_registered`) |
| CC-10 | `jinja2>=3.1.0` in `requirements.txt` | `"jinja2" in content.lower()` | T-10 (`test_requirements_patched`) |
| CC-11 | `app/reports/__init__.py` contains `ReportEngine` | File exists + `"ReportEngine" in content` | T-11 (`test_reports_init_created`) |
| CC-12 | `app/reports/engine.py` has all three methods | `render_template`, `render_html_to_pdf`, `generate_pdf_async` present | T-12 (`test_engine_created`) |
| CC-13 | WeasyPrint is lazy-imported inside `render_html_to_pdf` | `"from weasyprint"` found inside method body, not at module level | T-13 (`test_weasyprint_lazy_imported`) |
| CC-14 | Three HTML templates exist | `invoice.html`, `summary.html`, `receipt.html` all exist | T-14 (`test_templates_created`) |
| CC-15 | Templates use `default` filter for all variables | None of the three templates has an unguarded `{{ var }}` without `default` | T-15 (`test_templates_use_defaults`) |
| CC-16 | `app/api/routes/reports.py` has `generate_report` and `download_report` | File exists + substring checks | T-16 (`test_routes_created`) |
| CC-17 | `generate_pdf_async` uses `run_in_executor` | `"run_in_executor" in engine.py` | T-17 (`test_async_executor_used`) |
| CC-18 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | T-18 (`test_execution_time_recorded`) |
| CC-19 | `next_steps` include `weasyprint` install guidance | `"weasyprint" in " ".join(result.next_steps).lower()` | T-19 (`test_next_steps_mention_weasyprint`) |
| CC-20 | Running the tool twice leaves project AST-parseable | `ast.parse` over all `.py` after two runs | T-20 (`test_idempotent_project_still_parses`) |

---

## 7. Definition of Done (DoD)

- [ ] All 20 Completeness Criteria verified by `test_add_pdf_reports.py`
- [ ] `ast.parse` run on every created `.py` before returning success
- [ ] Fingerprint `"ReportEngine" in app/reports/__init__.py` → `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty lists
- [ ] `from weasyprint import HTML` is inside `render_html_to_pdf()` method body only
- [ ] `generate_pdf_async()` uses `loop.run_in_executor(_executor, ...)` — event loop never blocked
- [ ] Jinja2 `autoescape=select_autoescape(["html", "xml"])` in `render_template()`
- [ ] All three HTML templates use `default` filter on every variable
- [ ] Output paths use `Path(settings.REPORT_OUTPUT_DIR)` — never user-supplied filename directly
- [ ] `REPORT_*` fields anchored inside `class Settings`
- [ ] `jinja2>=3.1.0` added to `requirements.txt`; WeasyPrint NOT added
- [ ] `execution_time_ms` set on every return path
- [ ] Tool exits within 5 s on fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}`

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-PDF-01 | Tool is ALWAYS idempotent on second invocation | `"ReportEngine" in reports_init` short-circuits to `no_op` | T-02, T-20 |
| INV-PDF-02 | `dry_run=True` NEVER writes to disk | Early return before any write | T-03 |
| INV-PDF-03 | Every generated `.py` MUST parse as valid Python | Final `ast.parse` loop | T-06, T-20 |
| INV-PDF-04 | WeasyPrint MUST be lazy-imported inside `render_html_to_pdf` | `from weasyprint import HTML` inside method body | T-13 |
| INV-PDF-05 | PDF rendering MUST be off the async event loop | `loop.run_in_executor(_executor, ...)` in `generate_pdf_async` | T-17 |
| INV-PDF-06 | Jinja2 autoescape MUST be enabled | `select_autoescape(["html", "xml"])` in `render_template` | T-12 |
| INV-PDF-07 | Templates MUST use `default` filter on all variables | No bare `{{ var }}` in any template | T-15 |
| INV-PDF-08 | Output paths MUST be derived from `REPORT_OUTPUT_DIR` | `Path(settings.REPORT_OUTPUT_DIR)` in route handler | T-16 |
| INV-PDF-09 | Config fields MUST live inside `class Settings` | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` | T-08 |
| INV-PDF-10 | `jinja2>=3.1.0` MUST be in `requirements.txt` | `_patch_requirements` appends if absent | T-10 |
| INV-PDF-11 | `ToolResult.execution_time_ms` MUST be positive | `_elapsed_ms(start)` on every return path | T-18 |
| INV-PDF-12 | `next_steps` MUST reference WeasyPrint install | `"weasyprint"` in lowercased `next_steps` join | T-19 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install PDF generation into a clean project**
- **As a** backend engineer needing invoices
- **When:** `add_pdf_reports(ToolInput(project_dir=...))`
- **Then:** `status="success"`, ≥ 6 files created, ≥ 2 modified (T-01, T-04, T-05)

**US-02: Re-run on already-installed project**
- **Given:** `app/reports/__init__.py` contains `ReportEngine`
- **When:** Tool invoked again
- **Then:** `status="no_op"`, empty lists, project parses (T-02, T-20)

**US-03: Dry-run preview**
- **When:** `add_pdf_reports(ToolInput(dry_run=True))`
- **Then:** Success + notes; filesystem unchanged (T-03)

**US-04: App boots without WeasyPrint installed**
- **Given:** `weasyprint` not installed
- **When:** App starts
- **Then:** No `ImportError`; error only raised when `render_html_to_pdf()` called (INV-PDF-04)

**US-05: Autoescape prevents XSS via template context**
- **Given:** Context `{"customer_name": "<script>alert(1)</script>"}`
- **When:** Template rendered
- **Then:** `&lt;script&gt;` in output; script does not execute (INV-PDF-06)

### 9.2 ReportEngine (US-06 .. US-10)

**US-06: Render invoice template**
- **Given:** `invoice.html` template exists with items/total context
- **When:** `engine.render_template("invoice.html", {"invoice_number": "INV-001", "items": [...]})`
- **Then:** Returns HTML string containing `"INV-001"` (T-12)

**US-07: Missing context key uses default**
- **Given:** `invoice.html` with `{{ total | default('0.00') }}`
- **When:** `engine.render_template("invoice.html", {})` — no `total` key
- **Then:** Renders `0.00`; no `UndefinedError` (INV-PDF-07, T-15)

**US-08: PDF generation is async and off-loop**
- **Given:** Running FastAPI event loop
- **When:** `await engine.generate_pdf_async("invoice.html", {})`
- **Then:** Rendering runs in `ThreadPoolExecutor`; event loop handles other requests (INV-PDF-05, T-17)

**US-09: WeasyPrint import fails gracefully**
- **Given:** `weasyprint` not installed
- **When:** `engine.render_html_to_pdf(html)`
- **Then:** `ImportError("weasyprint is required: pip install weasyprint")` raised with clear message |

**US-10: Three built-in templates cover common cases**
- **Given:** Tool installed
- **When:** Developer queries `app/reports/templates/`
- **Then:** `invoice.html`, `summary.html`, `receipt.html` all present and Jinja2-valid (T-14)

### 9.3 HTTP routes (US-11 .. US-15)

**US-11: Generate a report via HTTP**
- **When:** `POST /reports/generate` `{"template_name": "invoice", "context": {...}}`
- **Then:** Returns `{"report_id": "...", "download_url": "/api/v1/reports/{id}/download", "size_bytes": N}` (T-16)

**US-12: Unknown template returns 404**
- **When:** `POST /reports/generate` `{"template_name": "nonexistent", ...}`
- **Then:** HTTP 404 `"Template 'nonexistent' not found."` (T-16)

**US-13: Download a generated report**
- **Given:** Report generated with ID `abc`
- **When:** `GET /reports/abc/download`
- **Then:** `FileResponse` with `Content-Type: application/pdf` (T-16)

**US-14: Download unknown report_id returns 404**
- **When:** `GET /reports/unknown_id/download`
- **Then:** HTTP 404 `"Report not found."` (T-16)

**US-15: Output directory created on demand**
- **Given:** `REPORT_OUTPUT_DIR=/tmp/custom_reports` does not exist
- **When:** First `POST /reports/generate`
- **Then:** `output_dir.mkdir(parents=True, exist_ok=True)` creates it; no crash (T-16)

### 9.4 Templates (US-16 .. US-20)

**US-16: Invoice template renders line items**
- **Given:** Context `{"items": [{"description": "Widget", "quantity": 2, "unit_price": "10.00", "total": "20.00"}]}`
- **When:** `render_template("invoice.html", context)`
- **Then:** HTML contains `"Widget"` and `"20.00"` (T-14)

**US-17: Summary template renders metric key-value pairs**
- **Given:** Context `{"title": "Q1 Report", "metrics": {"Revenue": "$100K"}}`
- **When:** `render_template("summary.html", context)`
- **Then:** HTML contains `"Q1 Report"` and `"Revenue"` (T-14)

**US-18: Receipt template renders correct total**
- **Given:** Context `{"total": "29.99"}`
- **When:** `render_template("receipt.html", context)`
- **Then:** HTML contains `"29.99"` (T-14)

**US-19: All templates are valid Jinja2**
- **Given:** All three template files
- **When:** `jinja2.Environment(...).get_template(name)` called for each
- **Then:** No `TemplateSyntaxError` (T-14, T-15)

**US-20: `output_filename` kwarg used in file naming**
- **Given:** `POST /reports/generate` `{"template_name": "invoice", "output_filename": "customer_invoice"}`
- **When:** Report generated
- **Then:** File written as `customer_invoice_{report_id}.pdf` in `REPORT_OUTPUT_DIR` (T-16)

### 9.5 Config and operator experience (US-21 .. US-25)

**US-21: Config binds from environment variables**
- **Given:** `REPORT_OUTPUT_DIR=/mnt/reports` in `.env`
- **When:** `Settings()` instantiated
- **Then:** `settings.REPORT_OUTPUT_DIR == "/mnt/reports"` (INV-PDF-09, T-08)

**US-22: `jinja2` added to requirements**
- **Given:** `requirements.txt` without jinja2
- **When:** Tool runs
- **Then:** `requirements.txt` contains `jinja2>=3.1.0` (INV-PDF-10, T-10)

**US-23: WeasyPrint NOT added to requirements**
- **Given:** Operator wants a slim container without PDF support
- **When:** `requirements.txt` inspected after tool run
- **Then:** `"weasyprint"` not present in `requirements.txt` (INV-PDF-10)

**US-24: `next_steps` guide operator**
- **When:** `result.next_steps` inspected
- **Then:** Contains `"pip install weasyprint"` (INV-PDF-12, T-19)

**US-25: Execution time recorded**
- **Then:** `result.execution_time_ms > 0` (INV-PDF-11, T-18)

---

## 10. Test Plan

All 20 tests live in `adapt/extend/infrastructure/test_add_pdf_reports.py`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `pdf_t01` | `add_pdf_reports(ToolInput(project_dir))` | `result.status == "success"` (CC-01) |
| T-02 | `test_idempotent` | Fixture `pdf_t02`; run once | Run again | `r2.status == "no_op"`; lists empty (CC-02) |
| T-03 | `test_dry_run` | Fixture `pdf_t03` | `dry_run=True` | Success + notes; FS unchanged (CC-03) |
| T-04 | `test_files_created_count` | Fixture `pdf_t04` | Run tool | `len(files_created) >= 6`; all exist (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `pdf_t05` | Run tool | `len(files_modified) >= 2`; all exist (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `pdf_t06`; run | AST-parse every `.py` | No `SyntaxError` (CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `pdf_t07`; run | AST walk `app/` | `max_loc <= 50` (CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `pdf_t08`; run | Read `config.py` | `REPORT_TEMPLATE_DIR` with 4-space indent (CC-08) |
| T-09 | `test_routes_registered` | Fixture `pdf_t09`; run | Read `routes/__init__.py` | Contains `"report"` (CC-09) |
| T-10 | `test_requirements_patched` | Fixture `pdf_t10`; run | Read `requirements.txt` | `"jinja2"` present (CC-10) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_reports_init_created` | Fixture `pdf_t11`; run | Read `app/reports/__init__.py` | Contains `"ReportEngine"` (CC-11) |
| T-12 | `test_engine_created` | Fixture `pdf_t12`; run | Read `app/reports/engine.py` | Contains `render_template`, `render_html_to_pdf`, `generate_pdf_async` (CC-12) |
| T-13 | `test_weasyprint_lazy_imported` | Fixture `pdf_t13`; run | Read `app/reports/engine.py` | `"from weasyprint"` inside function body (not at module level) (INV-PDF-04, CC-13) |
| T-14 | `test_templates_created` | Fixture `pdf_t14`; run | Check `app/reports/templates/` | All three HTML files exist (CC-14) |
| T-15 | `test_templates_use_defaults` | Fixture `pdf_t15`; run | Read all three templates | No unguarded `{{ var }}` without `default` filter (INV-PDF-07, CC-15) |
| T-16 | `test_routes_created` | Fixture `pdf_t16`; run | Read `app/api/routes/reports.py` | Contains `generate_report` and `download_report` (CC-16) |
| T-17 | `test_async_executor_used` | Fixture `pdf_t17`; run | Read `app/reports/engine.py` | Contains `"run_in_executor"` (INV-PDF-05, CC-17) |

### 10.4 Category D — Meta (T-18 .. T-20)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-18 | `test_execution_time_recorded` | Fixture `pdf_t18` | Read `result.execution_time_ms` | `> 0` (CC-18) |
| T-19 | `test_next_steps_mention_weasyprint` | Fixture `pdf_t19` | Lowercase-join `result.next_steps` | Contains `"weasyprint"` (INV-PDF-12, CC-19) |
| T-20 | `test_idempotent_project_still_parses` | Fixture `pdf_t20`; run twice | AST-parse every `.py` | No `SyntaxError` (CC-20) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_pdf_reports.py -v
```

Target: 20/20 passed, 0 failed.

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | `POST /reports/generate` can enqueue as an arq task for async processing |
| `add_file_upload` (TOOL-003) | No | ✅ Compatible | Report output can be uploaded to S3 via `add_s3_storage` |
| `add_s3_storage` (TOOL-060) | No | ✅ Compatible | Store generated PDFs in S3 instead of local disk |
| `add_rbac` (TOOL-012) | Yes — RBAC runs AFTER | ⚠️ Caveat | Add role gate to `POST /reports/generate` and download endpoint |
| `add_audit_log` (TOOL-005) | No | ✅ Compatible | Emit audit entry on report generation for compliance |
| `add_stripe_checkout` (TOOL-054) | No | ✅ Compatible | Generate invoice PDF after successful Stripe charge |
| `add_multi_tenancy` (TOOL-008) | No | ⚠️ Caveat | Template context may include tenant-specific branding; inject via middleware |

---

## 12. Rollback Procedure

### 12.1 Code rollback

```bash
git checkout HEAD -- app/core/config.py app/routes/__init__.py requirements.txt
rm -rf app/reports/ app/schemas/report.py app/api/routes/reports.py
```

No database rollback required (PDF layer has no ORM model or migration).

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Missing `app/` directory | `validate_project_dir` fails → `status="error"` |
| EC-02 | `app/reports/__init__.py` already contains `ReportEngine` | Early return `status="no_op"` |
| EC-03 | `dry_run=True` | Success + notes; no filesystem changes |
| EC-04 | WeasyPrint not installed | `render_html_to_pdf` raises `ImportError` with clear message |
| EC-05 | Unknown template name in POST body | `FileNotFoundError` caught → HTTP 404 |
| EC-06 | `REPORT_OUTPUT_DIR` does not exist | `output_dir.mkdir(parents=True, exist_ok=True)` creates it |
| EC-07 | Template context missing all variables | Jinja2 `default` filters prevent `UndefinedError` |
| EC-08 | `REPORT_TEMPLATE_DIR` already in config | `_patch_config` early-returns |
| EC-09 | `jinja2` already in requirements | `_patch_requirements` early-returns |
| EC-10 | `app/routes/__init__.py` already registers reports router | `_register_router` early-returns |
| EC-11 | `app/schemas/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` |
| EC-12 | `app/api/routes/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` |
| EC-13 | Tool runs twice | Second run returns `no_op`; project parses (T-20) |

---

## 14. Security Considerations

| # | Concern | Mitigation |
|---|---------|------------|
| SEC-01 | XSS via template context | Jinja2 autoescape enabled for HTML/XML (INV-PDF-06) |
| SEC-02 | Path traversal in report download | `output_dir.glob(f"*_{report_id}.pdf")` — report_id is `uuid4()`, not user-controlled |
| SEC-03 | Unauthenticated report download | `GET /reports/{id}/download` has no auth gate by default; add `CurrentUser` gate after install |
| SEC-04 | Disk exhaustion | `REPORT_MAX_PAGES` limits per-report size; add periodic cleanup job for `REPORT_OUTPUT_DIR` |
| SEC-05 | CPU exhaustion via concurrent PDF renders | `ThreadPoolExecutor(max_workers=4)` caps concurrent renders; queuing via arq recommended for production |

---

## 15. Observability

| Signal | Location | Notes |
|--------|----------|-------|
| `Report generated: {id} ({N} bytes)` | `generate_report` route | INFO level |
| `PDF generation failed` | `generate_report` catch block | ERROR level with exception |
| `Rendering HTML to PDF ({N} chars)` | `render_html_to_pdf` | DEBUG level |
| `weasyprint is required` | `render_html_to_pdf` | `ImportError` message |

---

## 16. Changelog

| Version | Date | Change |
|---------|------|--------|
| v1 | 2026-04-15 | Initial spec — WeasyPrint lazy, Jinja2 autoescape, ThreadPoolExecutor, 3 templates, 20 CCs |
