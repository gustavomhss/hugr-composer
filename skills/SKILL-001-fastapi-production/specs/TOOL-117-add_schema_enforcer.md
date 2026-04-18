# TOOL-117 — add_schema_enforcer

## 1. Overview

| Field | Value |
|---|---|
| **Tool ID** | TOOL-117 |
| **MCP name** | `fastapi_add_schema_enforcer` |
| **Entry point** | `adapt/extend/testing_tools/add_schema_enforcer.py::add_schema_enforcer` |
| **Tags** | `testing`, `schema`, `openapi`, `fuzz`, `shadow-routes`, `mass-assignment` |
| **Input** | `ToolInput(project_dir, dry_run=False)` |
| **Output** | `ToolResult(status, files_created, files_modified, notes, next_steps, execution_time_ms)` |
| **Idempotency fingerprint** | `"SchemaEnforcerMiddleware" in app/middleware/schema_enforcer.py` |
| **Prerequisite check** | `app/` directory exists |
| **Files created (min)** | 3 (`schema_enforcer.py` core, `schema_enforcer.py` middleware, `test_schema_fuzz.py`) |
| **Files modified (min)** | 2 (`app/core/config.py`, `app/main.py`) |
| **Test file** | `adapt/extend/testing_tools/test_add_schema_enforcer.py` |

---

## 2. Purpose

APIs drift from their OpenAPI specifications over time. Undocumented ("shadow") routes, extra fields in request bodies, and missing validations create attack surface. `add_schema_enforcer` installs a three-mode schema enforcement system:

1. **`app/core/schema_enforcer.py`** — Engine with four pure functions:
   - `load_spec(spec_path)` — loads OpenAPI JSON from `SCHEMA_ENFORCER_SPEC_PATH` or returns `{}` if unavailable.
   - `extract_route_paths(spec)` — returns the `set` of documented path strings from a parsed OpenAPI spec dict.
   - `detect_shadow_routes(app_routes, spec_routes)` — returns routes present in the app but absent from the spec. Paths starting with `/openapi` are excluded from the shadow list.
   - `has_extra_fields(body, schema)` — returns field names present in the request body but not in the schema's `properties` block, enabling mass-assignment prevention.

2. **`app/middleware/schema_enforcer.py`** — ASGI middleware with three modes:
   - `enforce` — validates every request/response; returns `403` for shadow routes (when `SCHEMA_ENFORCER_BLOCK_SHADOW=true`).
   - `detect` — logs violations but lets requests through; emits `schema_enforcer.shadow_route` log events.
   - `fuzz` — generates random valid/invalid payloads for testing.
   - `register_schema_enforcer(app)` — factory function injected into `app/main.py`.

3. **`tests/test_schema_fuzz.py`** — At least 5 `test_fuzz_*` functions that generate adversarial payloads against the app's schema.

Config fields (`SCHEMA_ENFORCER_MODE`, `SCHEMA_ENFORCER_SPEC_PATH`, `SCHEMA_ENFORCER_BLOCK_SHADOW`) are injected with 4-space indent inside `Settings`. `register_schema_enforcer(app)` is appended AFTER `app = FastAPI(...)` in `main.py`. `jsonschema>=4.23.0` is added to `requirements.txt`.

---

## 3. Performance SLOs

| Metric | Target |
|---|---|
| Tool execution time | < 2 s on a cold fixture project |
| `execution_time_ms` field | > 0 (always recorded) |
| Spec load on startup | < 50 ms (disk read + JSON parse) |
| Shadow route check per request | < 1 ms (set lookup) |
| Files created | ≥ 3 |
| Files modified | ≥ 2 |
| Max function LOC in generated `app/` | ≤ 50 |

---

## 4. Before / After

### 4.1 Project state — before

```
app/
  core/
    config.py    # No SCHEMA_ENFORCER_* fields
  main.py        # app = FastAPI(...); no schema middleware
requirements.txt # no jsonschema
```

### 4.2 Project state — after

```
app/
  core/
    config.py                      # 3 SCHEMA_ENFORCER_* fields injected
    schema_enforcer.py             # load_spec, extract_route_paths,
                                   # detect_shadow_routes, has_extra_fields
  middleware/
    schema_enforcer.py             # SchemaEnforcerMiddleware,
                                   # register_schema_enforcer
  main.py                          # register_schema_enforcer(app) appended
tests/
  test_schema_fuzz.py              # >= 5 test_fuzz_* functions
requirements.txt                   # jsonschema>=4.23.0 appended
```

### 4.3 load_spec — spec loader (generated)

```python
# app/core/schema_enforcer.py (generated)
def load_spec(spec_path: str | None = None) -> dict[str, Any]:
    """Load the OpenAPI spec from disk or return an empty spec.

    Args:
        spec_path: Optional filesystem path to an openapi.json file.
            Falls back to settings.SCHEMA_ENFORCER_SPEC_PATH.

    Returns:
        Parsed OpenAPI spec dict, or empty dict when unavailable.
    """
    path_str = spec_path or getattr(settings, "SCHEMA_ENFORCER_SPEC_PATH", "")
    if not path_str:
        return {}
    p = Path(path_str)
    if not p.is_file():
        logger.warning("schema_enforcer.spec_not_found", extra={"path": path_str})
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        logger.error("schema_enforcer.spec_parse_error", extra={"exc": str(exc)})
        return {}
```

### 4.4 detect_shadow_routes

```python
def detect_shadow_routes(
    app_routes: list[str],
    spec_routes: set[str],
) -> list[str]:
    shadow: list[str] = []
    for route in app_routes:
        if route not in spec_routes and not route.startswith("/openapi"):
            shadow.append(route)
    return shadow
```

### 4.5 SchemaEnforcerMiddleware — enforce mode

```python
class SchemaEnforcerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        mode = getattr(settings, "SCHEMA_ENFORCER_MODE", "detect")
        shadow = detect_shadow_routes([path], _spec_routes)
        if shadow:
            logger.warning("schema_enforcer.shadow_route", extra={"path": path})
            if mode == "enforce" and getattr(settings, "SCHEMA_ENFORCER_BLOCK_SHADOW", False):
                return Response(status_code=403, content=b'{"detail": "Undocumented route"}')
        return await call_next(request)
```

### 4.6 Config patch (3 fields)

```python
    # --- Schema enforcer — added by add_schema_enforcer tool ---
    SCHEMA_ENFORCER_MODE: str = "detect"  # enforce | detect | fuzz
    SCHEMA_ENFORCER_SPEC_PATH: str = ""
    SCHEMA_ENFORCER_BLOCK_SHADOW: bool = False
```

---

## 5. Quality Standards

| ID | Standard |
|---|---|
| QS-1 | `status == "success"` on first run against a fresh fixture project |
| QS-2 | Second run returns `status == "no_op"` with empty `files_created` and `files_modified` |
| QS-3 | `dry_run=True` returns success without writing any bytes to disk |
| QS-4 | `files_created` contains ≥ 3 entries; all paths exist on disk |
| QS-5 | `files_modified` contains ≥ 2 entries; all paths exist on disk |
| QS-6 | Every generated `.py` file passes `ast.parse()` without `SyntaxError` |
| QS-7 | No function in generated `app/` exceeds 50 LOC |
| QS-8 | All 3 `SCHEMA_ENFORCER_*` fields present in `config.py` with 4-space indent |
| QS-9 | `app/core/schema_enforcer.py` contains `load_spec`, `extract_route_paths`, `detect_shadow_routes`, `has_extra_fields` |
| QS-10 | `app/middleware/schema_enforcer.py` contains `SchemaEnforcerMiddleware` and `register_schema_enforcer` |
| QS-11 | `tests/test_schema_fuzz.py` exists with at least one `def test_fuzz_` function |
| QS-12 | Middleware calls `detect_shadow_routes` and logs `schema_enforcer.shadow_route` |
| QS-13 | Middleware returns `status_code=403` for shadow routes in `enforce` mode |
| QS-14 | `main.py` imports and calls `register_schema_enforcer(app)` |
| QS-15 | `has_extra_fields` references `properties` in its implementation |
| QS-16 | Middleware references both `"enforce"` and `"detect"` mode strings |
| QS-17 | `requirements.txt` contains `jsonschema` |
| QS-18 | Exactly 3 `SCHEMA_ENFORCER_*` field lines in `config.py` (deduplicated) |
| QS-19 | `load_spec` uses `json.loads` or `json.load` |
| QS-20 | `register_schema_enforcer(app)` appears AFTER `app = FastAPI(...)` in `main.py` |

---

## 6. Completeness Criteria

| ID | Test function | What it verifies |
|---|---|---|
| CC-01 | `test_success_status` | Tool returns `status='success'` on a fresh project |
| CC-02 | `test_idempotent` | Second run returns `status='no_op'`; no files created or modified |
| CC-03 | `test_dry_run` | `dry_run=True` returns success without writing any bytes to disk |
| CC-04 | `test_files_created_count` | At least 3 files created; all exist on disk |
| CC-05 | `test_files_modified_count` | At least 2 files modified; all exist on disk |
| CC-06 | `test_all_py_parse` | Every generated `.py` file AST-parses clean |
| CC-07 | `test_no_function_over_50_loc` | No function in `app/` exceeds 50 LOC |
| CC-08 | `test_config_fields_patched` | 3 `SCHEMA_ENFORCER_*` fields present with 4-space indent |
| CC-09 | `test_core_engine_created` | `load_spec`, `extract_route_paths`, `detect_shadow_routes`, `has_extra_fields` present |
| CC-10 | `test_middleware_created` | `SchemaEnforcerMiddleware` and `register_schema_enforcer` present |
| CC-11 | `test_fuzz_test_file_created` | `tests/test_schema_fuzz.py` exists with `def test_fuzz_` |
| CC-12 | `test_shadow_route_detection_in_middleware` | Middleware calls `detect_shadow_routes` and logs `schema_enforcer.shadow_route` |
| CC-13 | `test_enforce_mode_blocks_undocumented_endpoints` | Middleware has `status_code=403` and `"enforce"` string |
| CC-14 | `test_main_registers_enforcer` | `main.py` imports and calls `register_schema_enforcer` |
| CC-15 | `test_has_extra_fields_prevents_mass_assignment` | `has_extra_fields` exists and references `properties` |
| CC-16 | `test_three_modes_referenced` | Middleware references `"enforce"` and `"detect"` |
| CC-17 | `test_jsonschema_added_to_requirements` | `requirements.txt` contains `jsonschema` |
| CC-18 | `test_execution_time_recorded` | `execution_time_ms > 0` |
| CC-19 | `test_next_steps_present` | `next_steps` mentions `schema_enforcer_mode` and `fuzz` |
| CC-20 | `test_idempotent_project_still_parses` | All `.py` files parse after two consecutive runs |
| CC-21 | `test_three_config_fields_exactly` | Exactly 3 `SCHEMA_ENFORCER_*` field lines in `config.py` |
| CC-22 | `test_load_spec_returns_dict` | `load_spec` return type includes `dict`; uses `json` |
| CC-23 | `test_register_enforcer_positioned_after_fastapi` | `register_schema_enforcer(app)` index > `app = FastAPI(` index |
| CC-24 | `test_fuzz_test_file_has_multiple_tests` | `tests/test_schema_fuzz.py` has ≥ 5 `test_` functions |
| CC-25 | `test_no_files_mutated_outside_scope` | No file outside `files_created`/`files_modified` was changed |

---

## 7. Definition of Done

- [ ] All 25 tests in `test_add_schema_enforcer.py` pass
- [ ] `load_spec`, `extract_route_paths`, `detect_shadow_routes`, `has_extra_fields` generated in core engine
- [ ] `SchemaEnforcerMiddleware` with `enforce` / `detect` / `fuzz` modes
- [ ] `tests/test_schema_fuzz.py` with ≥ 5 `test_fuzz_*` functions
- [ ] `register_schema_enforcer(app)` injected into `main.py` AFTER `app = FastAPI(...)`
- [ ] Exactly 3 `SCHEMA_ENFORCER_*` config fields with 4-space indent
- [ ] `jsonschema>=4.23.0` added to `requirements.txt`
- [ ] `next_steps` mentions `SCHEMA_ENFORCER_MODE` and fuzz tests

---

## 8. Invariants

| ID | Invariant |
|---|---|
| INV-SE-001 | Exactly 3 `SCHEMA_ENFORCER_*` config field lines in `config.py` |
| INV-SE-002 | `register_schema_enforcer(app)` MUST appear after `app = FastAPI(...)` in `main.py` |
| INV-SE-003 | `load_spec()` MUST return a `dict` (never `None`) |
| INV-SE-004 | Routes starting with `/openapi` MUST be excluded from shadow route detection |
| INV-SE-005 | `has_extra_fields()` MUST check against `properties` key from schema dict |
| INV-SE-006 | Idempotency fingerprint is `"SchemaEnforcerMiddleware" in app/middleware/schema_enforcer.py` |
| INV-SE-007 | `tests/test_schema_fuzz.py` MUST contain ≥ 5 `test_` functions |
| INV-SE-008 | All generated `.py` files pass `ast.parse()` before `ToolResult` is returned |

---

## 9. User Stories

| ID | Story |
|---|---|
| US-01 | As a security engineer, I want shadow route detection so that I can find undocumented endpoints before attackers do. |
| US-02 | As a developer, I want `detect` mode so that I can observe violations in staging before enforcing them in production. |
| US-03 | As a compliance engineer, I want `has_extra_fields` to prevent mass-assignment vulnerabilities. |
| US-04 | As a QA engineer, I want `tests/test_schema_fuzz.py` so that I have a starting point for schema-driven fuzz testing. |
| US-05 | As an operator, I want `SCHEMA_ENFORCER_SPEC_PATH` so that I can point the enforcer at an external spec file. |
| US-06 | As a developer, I want `SCHEMA_ENFORCER_BLOCK_SHADOW=false` default so that I can observe violations before blocking them. |

---

## 10. Design Decisions

| Decision | Rationale |
|---|---|
| Three modes (enforce/detect/fuzz) | Gradual rollout: observe first, enforce when confident |
| `load_spec` returns `{}` on missing file | Middleware must not block requests when spec is unavailable |
| Exclude `/openapi*` from shadow routes | FastAPI always adds these; they are not shadow routes |
| `has_extra_fields` checks `properties` key | Standard OpenAPI schema structure |
| `jsonschema>=4.23.0` in requirements | Required for `validate()` calls in fuzz tests |
| `register_schema_enforcer(app)` factory | Clean middleware registration pattern |
| `SCHEMA_ENFORCER_BLOCK_SHADOW` separate from mode | Allows `enforce` mode logging without blocking |

---

## 11. Dependencies

| Package | Version | Purpose | Import style |
|---|---|---|---|
| `jsonschema` | `>=4.23.0` | JSON Schema validation in fuzz tests | Top-level |
| `starlette` | (FastAPI dep) | `BaseHTTPMiddleware`, `Request` | Top-level |
| `json` | stdlib | Spec parsing | Top-level |

---

## 12. Error Handling

| Scenario | Behavior |
|---|---|
| `schema_enforcer.py` already contains `SchemaEnforcerMiddleware` | Return `status="no_op"` |
| `app/` directory missing | Return `status="error"` with descriptive message |
| Generated `.py` has `SyntaxError` | Return `status="error"`; file NOT committed |
| `SCHEMA_ENFORCER_SPEC_PATH` missing file | `load_spec()` returns `{}`; no exception |
| Malformed OpenAPI JSON | `load_spec()` logs error and returns `{}` |
| Unknown `SCHEMA_ENFORCER_MODE` value | Middleware falls back to `detect` mode |

---

## 13. Security Considerations

- `has_extra_fields()` must be applied before any ORM write — extra fields not caught here can overwrite protected attributes.
- Shadow route blocking (`SCHEMA_ENFORCER_BLOCK_SHADOW=true`) returns 403, not 404, to avoid fingerprinting route existence.
- The spec file path (`SCHEMA_ENFORCER_SPEC_PATH`) should not be user-controllable — it is read at startup, not per-request.
- In `fuzz` mode, the generated payloads include malformed inputs; this mode should only be active in CI, never production.

---

## 14. Testing Guide

```bash
# Run full test suite
PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_schema_enforcer.py -v

# Run standalone
PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_schema_enforcer.py

# Verify fuzz test count
python3 -c "
import ast
from pathlib import Path
from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_schema_enforcer import add_schema_enforcer
from tests.common.fixture_factory import create_fixture_project
p = create_fixture_project(name='se_manual')
add_schema_enforcer(ToolInput(project_dir=str(p)))
content = (p / 'tests' / 'test_schema_fuzz.py').read_text()
tree = ast.parse(content)
fns = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')]
print(f'Fuzz test functions: {len(fns)} — {fns}')
"
```

---

## 15. Files Reference

| File | Role |
|---|---|
| `adapt/extend/testing_tools/add_schema_enforcer.py` | Tool entry point |
| `adapt/extend/testing_tools/test_add_schema_enforcer.py` | 25-test structural test suite |
| `app/core/schema_enforcer.py` | load_spec, extract_route_paths, detect_shadow_routes, has_extra_fields |
| `app/middleware/schema_enforcer.py` | SchemaEnforcerMiddleware, register_schema_enforcer |
| `tests/test_schema_fuzz.py` | >= 5 schema fuzz test functions |
| `app/core/config.py` | Patched with SCHEMA_ENFORCER_MODE, SCHEMA_ENFORCER_SPEC_PATH, SCHEMA_ENFORCER_BLOCK_SHADOW |
| `app/main.py` | Patched with register_schema_enforcer(app) |
| `requirements.txt` | Patched with jsonschema>=4.23.0 |

---

## 16. Changelog

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-04-15 | Initial spec — 25 CCs, three modes, shadow route detection, mass-assignment prevention |
