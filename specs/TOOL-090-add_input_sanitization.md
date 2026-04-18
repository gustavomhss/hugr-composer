# TOOL-090: add_input_sanitization

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_input_sanitization` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Dependencies | FastAPI, Pydantic v2; optional `bleach>=6.0.0` (lazy import, graceful degradation) |
| Signature | `add_input_sanitization(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_input_sanitization", "description": "Add HTML sanitization and XSS prevention middleware to FastAPI.", "tags": ["extend", "infrastructure"], "entry": "add_input_sanitization"}` |
| Files created (typical) | 4 — `app/security/__init__.py`, `app/security/sanitizer.py`, `app/security/sanitize_middleware.py`, `app/security/validators.py` |
| Files modified (typical) | 2 — `app/core/config.py`, `app/security/__init__.py` (if pre-existing) |

---

## 2. Purpose

The `fastapi_add_input_sanitization` tool adds HTML/XSS input sanitization to a FastAPI project at three levels: (1) a reusable `InputSanitizer` class for imperative use, (2) `SanitizeMiddleware` that automatically sanitizes all JSON body string fields on POST/PUT/PATCH requests, and (3) Pydantic annotated types (`SafeString`, `NoSQLInjection`) that sanitize at model validation time.

XSS (cross-site scripting) is the most prevalent web vulnerability class. An API that stores `<script>alert(document.cookie)</script>` in a user's `bio` field and later renders it via a frontend causes stored XSS. `InputSanitizer.sanitize_html` strips disallowed tags via bleach's allowlist (or `html.escape` as a fallback), making the output safe for storage and display. `strip_tags` provides a fast regex fallback. `escape_sql_chars` adds defence-in-depth against SQL injection alongside parameterised queries.

The design priority is zero-breakage: bleach is imported **lazily inside function bodies** so the app boots even without it installed, falling back silently to `html.escape`. This means the tool can be applied to any project and the operator can choose to `pip install bleach` at their convenience. `SanitizeMiddleware` is opt-in via `app.add_middleware` — it is not automatically inserted into `main.py` to avoid surprising side effects on existing APIs. `SafeString` and `NoSQLInjection` are Pydantic annotated types that integrate cleanly with `BaseModel` and `TypeAlias` patterns.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI step budget |
| Files created | ≥ 3 | sanitizer, middleware, validators |
| Files modified | ≥ 1 | `config.py` at minimum |
| Max function LOC in generated code | ≤ 50 | Auditable functions |
| `sanitize_html` with bleach | < 2 ms per call | In-process string operation |
| `sanitize_html` without bleach | < 1 ms per call | `html.escape` is pure C |
| `SanitizeMiddleware` overhead | < 5 ms per request | JSON parse + recursive walk |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # No input sanitization
│   ├── core/
│   │   └── config.py        # No SANITIZE_* fields
│   └── api/
└── requirements.txt         # bleach not required
```

User-supplied strings are stored as-is. `<script>alert(1)</script>` in a `title` field is stored to DB and served back to browsers, causing stored XSS.

### 4.2 InputSanitizer class: AFTER

```python
# app/security/sanitizer.py
class InputSanitizer:
    """HTML/XSS sanitization with optional bleach support."""

    def sanitize_html(self, value: str) -> str:
        """Sanitize via bleach (allowlist), fallback to html.escape."""
        try:
            import bleach  # lazy import — optional dependency
            return bleach.clean(value, tags=self._allowed_tags, strip=True)
        except ImportError:
            return html.escape(value)

    def strip_tags(self, value: str) -> str:
        """Strip ALL HTML tags via regex (no bleach needed)."""
        return re.sub(r"<[^>]*>", "", value)

    def escape_sql_chars(self, value: str) -> str:
        """Remove SQL injection characters (; ' \" \\ --)."""
        return _SQL_CHARS_RE.sub("", value)
```

### 4.3 SanitizeMiddleware: AFTER

```python
# app/security/sanitize_middleware.py
class SanitizeMiddleware(BaseHTTPMiddleware):
    """Recursively sanitizes JSON body string fields."""

    async def dispatch(self, request, call_next):
        if request.method not in {"POST", "PUT", "PATCH"}:
            return await call_next(request)
        if "application/json" not in request.headers.get("content-type", ""):
            return await call_next(request)
        # Parse body, sanitize all string values up to max_depth, reconstruct
        ...
```

### 4.4 Pydantic validators: AFTER

```python
# app/security/validators.py
# Auto-sanitizes HTML and rejects NoSQL injection patterns
SafeString = Annotated[str, BeforeValidator(_sanitize_string)]
NoSQLInjection = Annotated[str, AfterValidator(_validate_no_nosql)]

class ItemCreate(BaseModel):
    title: SafeString      # <script>...</script> stripped at validation
    description: SafeString
```

### 4.5 Config patch: AFTER

```python
# app/core/config.py  (diff, 4-space indented inside class Settings)
    # --- Input Sanitization (added by add_input_sanitization tool) ---
    SANITIZE_ENABLED: bool = True
    SANITIZE_ALLOWED_TAGS: list[str] = []
    SANITIZE_MAX_DEPTH: int = 5
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `"InputSanitizer" in sanitizer_file.read_text()` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any filesystem write |
| QS-3 | **Every generated `.py` file AST-parses** | `ast.parse` loop over `files_created` |
| QS-4 | **No generated function exceeds 50 LOC** | AST walk asserts |
| QS-5 | **bleach is LAZY imported inside function body** | Not at module level; `try: import bleach` inside `sanitize_html` |
| QS-6 | **Fallback to `html.escape` when bleach absent** | `except ImportError: return html.escape(value)` |
| QS-7 | **`SanitizeMiddleware` only touches POST/PUT/PATCH with JSON content-type** | `_SANITIZE_METHODS` check + content-type guard |
| QS-8 | **Recursive sanitization bounded by `max_depth`** | `depth >= max_depth: return value` guard |
| QS-9 | **`NoSQLInjection` validator rejects `$where`, `$gt`, etc.** | `_NOSQL_PATTERNS` regex compiled at module level |
| QS-10 | **`SANITIZE_*` fields 4-space indented inside `class Settings`** | `_patch_config` enforces indent |
| QS-11 | **`execution_time_ms` set on every return path** | `_elapsed_ms(start)` on all branches |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_input_sanitization.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict | `test_dry_run` |
| CC-04 | Tool creates at least 3 new files | `len(result.files_created) >= 3` | `test_files_created_count` |
| CC-05 | Tool modifies at least 1 existing file | `len(result.files_modified) >= 1` | `test_files_modified_count` |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` | `test_all_py_parse` |
| CC-07 | No generated function exceeds 50 LOC | AST walk, `loc <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `SANITIZE_ENABLED`, `SANITIZE_ALLOWED_TAGS`, `SANITIZE_MAX_DEPTH` in `config.py` with 4-space indent | String scan + indent check | `test_config_fields_patched` |
| CC-09 | `app/security/sanitizer.py` with `class InputSanitizer` | File exists + class present | `test_sanitizer_file_created` |
| CC-10 | `sanitize_html()` method present | `"def sanitize_html" in src` | `test_sanitize_html_method` |
| CC-11 | `strip_tags()` method present | `"def strip_tags" in src` | `test_strip_tags_method` |
| CC-12 | `escape_sql_chars()` method present | `"def escape_sql_chars" in src` | `test_escape_sql_chars_method` |
| CC-13 | bleach imported lazily (not at module top-level) | AST walk: no top-level `import bleach` | `test_bleach_lazy_import` |
| CC-14 | Fallback to `html.escape` when bleach absent | `"html.escape" in src` and `"ImportError" in src` | `test_bleach_fallback_to_html_escape` |
| CC-15 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-16 | `next_steps` non-empty and mention bleach or sanitize | `"bleach" in combined or "sanitize" in combined` | `test_next_steps_present` |

---

## 7. Definition of Done (DoD)

- [ ] All 16 Completeness Criteria verified by `test_add_input_sanitization.py`
- [ ] `add_input_sanitization.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] Fingerprint check `"InputSanitizer" in sanitizer.py` returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] bleach imported with `try: import bleach` inside `sanitize_html` body (never at module level)
- [ ] `html.escape` fallback in `except ImportError` block
- [ ] `SanitizeMiddleware` only processes POST/PUT/PATCH with `application/json` content-type
- [ ] `_sanitize_value` recurses into dicts and lists up to `max_depth`
- [ ] `SafeString` and `NoSQLInjection` are Pydantic annotated types
- [ ] `SANITIZE_*` fields inserted with 4-space indent inside `class Settings` body
- [ ] `execution_time_ms` set on every return path
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SAN-01 | Tool is ALWAYS idempotent on second invocation | `"InputSanitizer" in sanitizer_file.read_text()` → `status="no_op"` | `test_idempotent` |
| INV-SAN-02 | `dry_run=True` NEVER writes to disk | Early return before any write | `test_dry_run` |
| INV-SAN-03 | Every generated `.py` MUST parse as valid Python | `ast.parse` loop | `test_all_py_parse` |
| INV-SAN-04 | bleach MUST be a lazy import inside a function body | Not in top-level `import` statements | `test_bleach_lazy_import` |
| INV-SAN-05 | MUST fall back to `html.escape` when bleach absent | `except ImportError` block in `sanitize_html` | `test_bleach_fallback_to_html_escape` |
| INV-SAN-06 | `SanitizeMiddleware` MUST only touch JSON-body requests | `content-type: application/json` guard | `test_sanitize_middleware_sanitizes_json_strings` |
| INV-SAN-07 | `SANITIZE_*` fields MUST be 4-space indented inside `class Settings` | `_patch_config` enforces indent | `test_config_fields_patched` |
| INV-SAN-08 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` on all branches | `test_execution_time_recorded` |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-04)

**US-01: Add XSS protection to a FastAPI project**
- **As a** backend engineer building user-facing content
- **I want** to strip HTML tags from user input before storage
- **So that** stored XSS is prevented even if the frontend renders raw strings
- **Given:** FastAPI project with user text fields
- **When:** `add_input_sanitization(ToolInput(project_dir=...))`
- **Then:** `InputSanitizer`, `SanitizeMiddleware`, `SafeString`, `NoSQLInjection` installed

**US-02: Use SafeString in Pydantic models**
- **As a** developer adding a new model field
- **I want** automatic sanitization at model validation
- **Given:** `from app.security.validators import SafeString`
- **When:** `class PostCreate(BaseModel): title: SafeString`
- **Then:** `<script>` is stripped at validation time, no middleware needed

**US-03: Preview changes without writing files**
- **Given:** Fresh project
- **When:** `add_input_sanitization(ToolInput(project_dir=..., dry_run=True))`
- **Then:** Returns `status="success"` with notes, zero files written

**US-04: App boots without bleach installed**
- **As a** developer who has not yet installed bleach
- **I want** the app to start without errors
- **Given:** bleach not in `pip list`
- **When:** App imports `InputSanitizer` and calls `sanitize_html`
- **Then:** Falls back to `html.escape` silently; debug log emitted

---

## 10. Edge Cases

| Edge Case | Handling |
|-----------|----------|
| bleach not installed | `except ImportError: return html.escape(value)` in `sanitize_html` |
| Nested JSON body beyond `max_depth` | `_sanitize_value` returns value unchanged at depth limit |
| Non-JSON content-type (form data, file upload) | `SanitizeMiddleware` passes through without parsing |
| Invalid JSON body | `except (json.JSONDecodeError, ValueError): return await call_next(request)` |
| `SANITIZE_ALLOWED_TAGS=[]` | bleach strips all tags (safest default) |
| `app/security/__init__.py` already exists with other exports | `_patch_security_init` appends `InputSanitizer` import without overwriting |

---

## 11. Dependencies and Prerequisites

| Dependency | Version | Role | Install? |
|------------|---------|------|---------|
| FastAPI | any | `BaseHTTPMiddleware`, `JSONResponse` | Already present |
| Pydantic | v2 | `BeforeValidator`, `AfterValidator`, `Annotated` | Already present |
| bleach | >=6.0.0 | HTML allowlist sanitization | Optional (`next_steps` advises install) |
| stdlib `html` | 3.10+ | Fallback escape when bleach absent | Always available |

**Prerequisites** (checked by `ensure_prerequisites`):
- `Prereq.CONFIG_SETTINGS` — `app/core/config.py` with `class Settings`
- `Prereq.REQUIREMENTS_TXT` — `requirements.txt` exists

---

## 12. File Map

```
project/
├── app/
│   ├── security/
│   │   ├── __init__.py              [CREATED or MODIFIED] Exports InputSanitizer
│   │   ├── sanitizer.py             [CREATED] InputSanitizer class
│   │   ├── sanitize_middleware.py   [CREATED] SanitizeMiddleware
│   │   └── validators.py            [CREATED] SafeString, NoSQLInjection
│   └── core/
│       └── config.py                [MODIFIED] SANITIZE_* fields added
```

---

## 13. Rollback

To remove input sanitization:

1. Delete `app/security/sanitizer.py`, `app/security/sanitize_middleware.py`, `app/security/validators.py`
2. Remove `InputSanitizer` import from `app/security/__init__.py`
3. Remove `SANITIZE_*` fields from `app/core/config.py`
4. Remove `SanitizeMiddleware` registration from `app/main.py` (if added manually)
5. Revert `SafeString` annotations in models to `str`

---

## 14. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| bleach allowlist bypass | Default `allowed_tags=[]` strips all tags; operators must explicitly allow tags |
| `html.escape` is less powerful than bleach | Encodes all HTML chars; prevents injection but does not support allowlists |
| SQL injection | `escape_sql_chars` is defence-in-depth only; parameterised queries are the primary defence |
| NoSQL injection via `$where`, `$gt`, etc. | `_NOSQL_PATTERNS` regex detects common MongoDB operator injections |
| Sanitization modifying valid data | `sanitize_html` with empty `allowed_tags` may strip intentional markup (rich text fields) — configure `SANITIZE_ALLOWED_TAGS` accordingly |

---

## 15. Observability

| Signal | Where | Content |
|--------|-------|---------|
| `logger.debug` | `sanitize_html` | `"bleach not installed — using html.escape fallback"` |
| `ToolResult.notes` | Success return | Sanitization setup summary |
| `ToolResult.next_steps` | Success return | bleach install, middleware registration, `SafeString` usage |
| `ToolResult.execution_time_ms` | All branches | Wall-clock milliseconds |

---

## 16. Test Coverage Map

| Test | CC | Description |
|------|----|-------------|
| `test_success_status` | CC-01 | Returns `status="success"` on fresh project |
| `test_idempotent` | CC-02 | Second run returns `no_op` |
| `test_dry_run` | CC-03 | `dry_run=True` writes nothing |
| `test_files_created_count` | CC-04 | At least 3 files created |
| `test_files_modified_count` | CC-05 | At least 1 file modified |
| `test_all_py_parse` | CC-06 | All `.py` parse cleanly |
| `test_no_function_over_50_loc` | CC-07 | No function > 50 LOC |
| `test_config_fields_patched` | CC-08 | `SANITIZE_*` fields with 4-space indent |
| `test_sanitizer_file_created` | CC-09 | `sanitizer.py` with `class InputSanitizer` |
| `test_sanitize_html_method` | CC-10 | `sanitize_html()` present |
| `test_strip_tags_method` | CC-11 | `strip_tags()` present |
| `test_escape_sql_chars_method` | CC-12 | `escape_sql_chars()` present |
| `test_bleach_lazy_import` | CC-13 | bleach not at top-level import |
| `test_bleach_fallback_to_html_escape` | CC-14 | `html.escape` fallback with `ImportError` |
| `test_sanitize_middleware_file_created` | INV-SAN-06 | `sanitize_middleware.py` with `SanitizeMiddleware` |
| `test_sanitize_middleware_sanitizes_json_strings` | INV-SAN-06 | Handles JSON body |
| `test_sanitize_middleware_configurable_depth` | INV-SAN-06 | `max_depth` parameter present |
| `test_validators_file_created` | INV-SAN-07 | `validators.py` with `SafeString` |
| `test_nosql_injection_validator` | INV-SAN-07 | `NoSQLInjection` with `$where` detection |
| `test_next_steps_present` | CC-16 | Non-empty `next_steps` |
| `test_execution_time_recorded` | CC-15 | `execution_time_ms > 0` |
| `test_idempotent_project_still_parses` | INV-SAN-01/03 | After two runs all `.py` parseable |
