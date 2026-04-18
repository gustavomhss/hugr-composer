# TOOL-124: add_api_fuzzer

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_api_fuzzer` |
| Category | EXTEND > Testing Tools |
| Complexity | Medium |
| Dependencies | FastAPI, asyncio, os, argparse, json (stdlib); httpx (deferred, already in requirements) |
| Signature | `add_api_fuzzer(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_api_fuzzer", "description": "Add schema-aware API fuzzing: APIFuzzer reads OpenAPI schema, generates adversarial inputs per field type (boundary ints, unicode, SQL payloads, XSS vectors, empty/null/huge strings). FuzzRunner hits each endpoint N times, reports non-JSON 5xx/timeout/crash. scripts/run_fuzz.py CLI. Config: FUZZ_ITERATIONS, FUZZ_TIMEOUT_S, FUZZ_EXCLUDE_PATHS. No external deps.", "tags": ["extend", "testing_tools"], "entry": "add_api_fuzzer"}` |
| Files created (typical) | 4 — `app/fuzzer/__init__.py`, `app/fuzzer/generators.py`, `app/fuzzer/runner.py`, `scripts/run_fuzz.py` |
| Files modified (typical) | 1 — `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_api_fuzzer` tool installs a schema-aware adversarial API fuzzer into a FastAPI project. The fastest path to discovering injection vulnerabilities, unhandled edge cases, and crash-inducing inputs is to send adversarial data to every endpoint automatically rather than waiting for a human tester to hit them manually during a penetration test that happens once per quarter. The gap between "every endpoint is tested with valid inputs in CI" and "every endpoint is hardened against adversarial inputs" is exactly what this tool closes: it generates an `APIFuzzer` that reads the application's own `/openapi.json` schema to enumerate every POST, PUT, and PATCH endpoint, produces a comprehensive set of adversarial payloads per field type, and runs them through a `FuzzRunner` that collects any non-JSON 5xx responses, timeout errors, or request-level crashes as *findings* — the signal that a specific combination of endpoint + adversarial value needs human attention.

The adversarial payload generators in `app/fuzzer/generators.py` cover the categories that account for the majority of real-world API vulnerabilities found in bug bounty reports: SQL injection strings (`' OR '1'='1`, `'; DROP TABLE users; --`), cross-site scripting vectors (`<script>alert(1)</script>`, `"><img src=x onerror=alert(1)>`), integer boundary values (`2**31 - 1`, `-(2**31)`, `2**63 - 1`), unicode edge cases (`\x00`, `\uffff`, `\u202e`), a 1 MB string (`"A" * 1_048_576`) for size-limit and timeout testing, empty strings, null values, and type-confusion payloads (`0`, `False`, `[]`, `{}` in place of expected strings). The generator system is table-driven via `_FIELD_TYPE_GENERATORS`, which maps OpenAPI `type` values (`integer`, `number`, `string`, `boolean`, `array`) to generator functions so that each field receives contextually appropriate adversarial values rather than the same generic string blasted at every field regardless of type.

`FuzzResult` is the per-request result container. Its `is_finding()` method implements the detection logic: any `self.error` (request-level exception), any `self.status_code >= 500` where `self.is_json is False`, or both constitutes a finding. The `status_code >= 500 and not is_json` rule is intentional — a well-behaved FastAPI application returns structured JSON error responses even for 500s (thanks to the default exception handlers); a non-JSON 5xx means the application hit an unhandled code path and is leaking raw stack traces or crashing the worker. The `--output` CLI flag pipes the full `[r.to_dict() for r in results]` list to a JSON file suitable for CI artifact storage and ticket filing.

The `scripts/run_fuzz.py` CLI script uses `argparse` with `--base-url` (required), `--iterations`, `--timeout`, and `--output` flags. The `if __name__ == "__main__": sys.exit(asyncio.run(_main()))` guard at the bottom means it is invocable directly as a Python script without any test runner. The exit code is `0` when there are no findings, `1` when findings are detected (CI fail), and `2` on import error. `httpx` is imported lazily inside `FuzzRunner.run()` — never at module top level — so the fuzzer module loads cleanly even before `httpx` is installed, and tools that import `app.fuzzer` for introspection do not trigger an `ImportError`.

Config fields `FUZZ_ITERATIONS` (default `10`), `FUZZ_TIMEOUT_S` (default `5`), and `FUZZ_EXCLUDE_PATHS` (default `"/docs,/openapi.json,/redoc"`) are injected into `class Settings` with 4-space indent in `app/core/config.py`. The tool is idempotent: a second run detects `"APIFuzzer" in app/fuzzer/__init__.py` and returns `status="no_op"` without modifying any file.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (CC-17) |
| Files created | ≥ 4 | fuzzer package (3 files) + CLI script (CC-04) |
| Files modified | ≥ 1 | config.py always patched with FUZZ_ITERATIONS field (CC-05) |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk over `app/fuzzer/` subtree (CC-07) |
| Payloads per schema-field scan | ≤ 3 per field, cap at 20 total | `build_payloads_for_schema` uses `gen()[:3]` and caps at `_MAX_PAYLOADS_PER_SCHEMA = 20` |
| `FuzzRunner.run()` per-request timeout | = `FUZZ_TIMEOUT_S` s | httpx `AsyncClient(timeout=self.timeout_s)` |
| `FuzzResult.is_finding()` false-negative rate | 0% for non-JSON 5xx | Checks `status_code >= 500 and not is_json`; no exception swallowed silently |
| Optional SDK import cost | 0 ms | httpx imported lazily inside `run()`; fuzzer package loads without httpx installed |
| Config patch idempotency | 0 modifications on second run | `_patch_config` short-circuits when `FUZZ_ITERATIONS` already present |
| Syntax correctness of all generated files | 100% | `ast.parse()` validation loop on all created `.py` files before returning success (CC-06) |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   ├── core/
│   │   └── config.py        # No FUZZ_* fields
│   └── api/
│       └── routes/
└── requirements.txt         # httpx already present
# No fuzzer package, no scripts/run_fuzz.py
```

The only adversarial testing that happens is whatever the developer manually types into the Swagger UI. SQL injection and unicode edge cases are not tested. A `\x00` in a username field that causes a PostgreSQL `\x00` literal error and returns a 500 with a raw traceback goes undiscovered until a bug bounty submission.

### 4.2 APIFuzzer with endpoint discovery: AFTER

```python
# app/fuzzer/__init__.py

class APIFuzzer:
    def __init__(self, base_url: str, schema: dict[str, Any] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._schema: dict[str, Any] = schema or {}

    def endpoint_list(self) -> list[dict[str, Any]]:
        endpoints = []
        paths = self._schema.get("paths", {})
        exclude_raw = os.getenv("FUZZ_EXCLUDE_PATHS", "/docs,/openapi.json,/redoc")
        excluded = [p.strip() for p in exclude_raw.split(",") if p.strip()]
        for path, methods in paths.items():
            if any(path.startswith(ex) for ex in excluded):
                continue
            for method in ("post", "put", "patch"):
                if method not in methods:
                    continue
                op = methods[method]
                body_schema = _extract_body_schema(op, self._schema)
                endpoints.append({
                    "method": method.upper(),
                    "path": path,
                    "body_schema": body_schema,
                })
        return endpoints

    def generate_payloads(self, body_schema: dict[str, Any] | None) -> list[dict[str, Any]]:
        from app.fuzzer.generators import build_payloads_for_schema
        return build_payloads_for_schema(body_schema or {})
```

### 4.3 Adversarial generators: AFTER

```python
# app/fuzzer/generators.py

def int_values() -> list[Any]:
    return [0, 1, -1, 2**31 - 1, -(2**31), 2**63 - 1, -(2**63),
            99999999999, -99999999999, None, "not_an_int", 1.5]

def string_values() -> list[Any]:
    sql_payloads = ["' OR '1'='1", "'; DROP TABLE users; --",
                    "1; SELECT * FROM information_schema.tables"]
    xss_vectors = ['<script>alert(1)</script>', '"><img src=x onerror=alert(1)>',
                   "javascript:alert(1)"]
    unicode_edge = ["\x00", "\uffff", "\u202e", "A" * 1_048_576, ""]
    control_chars = ["\r\n", "\n" * 3, "\t" * 3]
    null_and_type_confuse: list[Any] = [None, 0, False, [], {}]
    return sql_payloads + xss_vectors + unicode_edge + control_chars + null_and_type_confuse

_FIELD_TYPE_GENERATORS = {
    "integer": int_values,
    "number":  number_values,
    "string":  string_values,
    "boolean": bool_values,
    "array":   array_values,
}

_MAX_PAYLOADS_PER_SCHEMA = 20

def build_payloads_for_schema(schema: dict[str, Any]) -> list[dict[str, Any]]:
    props = schema.get("properties", {})
    if not props:
        return [_empty_payload(), _huge_payload(), _nested_null()]
    payloads: list[dict[str, Any]] = []
    defaults = _default_values(props)
    for field_name, field_schema in list(props.items())[:8]:
        field_type = field_schema.get("type", "string")
        gen = _FIELD_TYPE_GENERATORS.get(field_type, string_values)
        for value in gen()[:3]:
            payload = dict(defaults)
            payload[field_name] = value
            payloads.append(payload)
            if len(payloads) >= _MAX_PAYLOADS_PER_SCHEMA:
                return payloads
    return payloads or [_empty_payload()]
```

### 4.4 FuzzRunner with lazy httpx and FuzzResult: AFTER

```python
# app/fuzzer/runner.py

class FuzzResult:
    def is_finding(self) -> bool:
        if self.error:
            return True
        if self.status_code >= 500 and not self.is_json:
            return True
        return False

class FuzzRunner:
    def __init__(self, base_url: str, iterations: int | None = None,
                 timeout_s: int | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.iterations = iterations or int(os.getenv("FUZZ_ITERATIONS", "10"))
        self.timeout_s = timeout_s or int(os.getenv("FUZZ_TIMEOUT_S", "5"))

    async def run(self) -> list[FuzzResult]:
        import httpx  # noqa: PLC0415 — lazy import; never at module top level
        from app.fuzzer import APIFuzzer
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout_s,
        ) as client:
            schema = await self._fetch_schema(client)
            fuzzer = APIFuzzer(self.base_url, schema=schema)
            endpoints = fuzzer.endpoint_list()
            results: list[FuzzResult] = []
            for ep in endpoints:
                payloads = fuzzer.generate_payloads(ep["body_schema"])
                for payload in payloads[: self.iterations]:
                    result = await self._fuzz_one(
                        client, ep["method"], ep["path"], payload
                    )
                    results.append(result)
            return results
```

### 4.5 CLI script: AFTER

```python
# scripts/run_fuzz.py

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Schema-aware API fuzzer for FastAPI")
    parser.add_argument("--base-url", required=True, help="Target server base URL")
    parser.add_argument("--iterations", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--output", default=None)
    return parser.parse_args()

if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
```

### 4.6 Config injection: AFTER

```python
# app/core/config.py (patch excerpt)

class Settings(BaseSettings):
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # ... existing fields ...

    # API fuzzer settings — added by add_api_fuzzer tool
    FUZZ_ITERATIONS: int = 10
    FUZZ_TIMEOUT_S: int = 5
    FUZZ_EXCLUDE_PATHS: str = "/docs,/openapi.json,/redoc"
```

---

## 5. Quality Standards

| Standard | Requirement |
|----------|-------------|
| Syntax | All generated `.py` files pass `ast.parse()` before `ToolResult` is returned |
| Function size | No generated function exceeds 50 LOC (AST walk over `app/fuzzer/`) |
| Lazy imports | `httpx` never imported at module top level in any fuzzer file |
| No forbidden external deps | Generated fuzzer files do not import `hypothesis`, `atheris`, `boofuzz`, or `schemathesis` |
| Config indent | `FUZZ_ITERATIONS`, `FUZZ_TIMEOUT_S`, `FUZZ_EXCLUDE_PATHS` start with 4 spaces (inside `class Settings`) |
| Idempotency | Second run returns `status="no_op"` with empty `files_created` and `files_modified` |
| Dry-run safety | `dry_run=True` writes zero bytes; project directory is unchanged |
| SQL and XSS coverage | `generators.py` includes `' OR '1'='1'` or `DROP TABLE` and `<script>` or `onerror` |
| Boundary integers | `generators.py` includes `2**31` or `2147483647` |
| Unicode edge cases | `generators.py` includes `\x00` or `\uffff` |
| 1 MB string | `generators.py` includes `1_048_576` or `1048576` |
| `is_finding()` semantics | Detects non-JSON 5xx (`status_code >= 500 and not is_json`) AND request-level errors (`self.error`) |
| CLI `__main__` guard | `scripts/run_fuzz.py` has `if __name__ == "__main__":` |
| Exit code convention | CLI exits `0` (no findings), `1` (findings detected), `2` (import error) |

---

## 6. Completeness Criteria

Each criterion maps to a test function in `adapt/extend/testing_tools/test_add_api_fuzzer.py`.

| ID | Criterion | Test function |
|----|-----------|---------------|
| CC-01 | Tool returns `status="success"` on a fresh fixture project | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with no `files_created` or `files_modified` | `test_idempotent` |
| CC-03 | `dry_run=True` returns success but writes no files; project directory is byte-for-byte identical before/after | `test_dry_run` |
| CC-04 | At least 4 files are created and all paths exist on disk | `test_files_created_count` |
| CC-05 | At least 1 file is modified and all paths exist on disk | `test_files_modified_count` |
| CC-06 | Every `.py` file in the project parses without `SyntaxError` (recursive `ast.parse`) | `test_all_py_parse` |
| CC-07 | No generated function in `app/fuzzer/` exceeds 50 LOC (AST walk via `ast.FunctionDef` / `ast.AsyncFunctionDef`) | `test_no_function_over_50_loc` |
| CC-08 | `FUZZ_ITERATIONS`, `FUZZ_TIMEOUT_S`, and `FUZZ_EXCLUDE_PATHS` are present in `app/core/config.py`, and the line containing `FUZZ_ITERATIONS` starts with 4 spaces | `test_config_fields_patched` |
| CC-09 | `app/fuzzer/__init__.py` exists, contains `APIFuzzer`, `endpoint_list`, and `generate_payloads` | `test_api_fuzzer_init` |
| CC-10 | `app/fuzzer/generators.py` exists, contains `int_values`, `string_values`, `bool_values`, `number_values`, and `build_payloads_for_schema` | `test_generators_file` |
| CC-11 | `generators.py` contains `DROP TABLE` or `OR '1'='1'` AND contains `script` (case-insensitive) or `onerror` | `test_adversarial_payloads_in_generators` |
| CC-12 | `app/fuzzer/runner.py` exists, contains `FuzzRunner`, `FuzzResult`, `async def run`, and `is_finding` | `test_runner_file` |
| CC-13 | `scripts/run_fuzz.py` exists, uses `argparse` or `ArgumentParser`, accepts `--base-url`, and has `__main__` guard | `test_cli_script_created` |
| CC-14 | `generators.py` contains `2**31` or `2147483647` | `test_boundary_integers_in_generators` |
| CC-15 | `generators.py` contains `\x00` or `\uffff` or `unicode` (case-insensitive) | `test_unicode_edge_cases_in_generators` |
| CC-16 | `generators.py` contains `1_048_576` or `1048576` | `test_huge_string_in_generators` |
| CC-17 | Generated fuzzer files do not contain `hypothesis`, `atheris`, `boofuzz`, or `schemathesis` | `test_no_external_deps_beyond_httpx` |
| CC-18 | `runner.py` contains `500` or `>= 500` AND contains `is_json` | `test_fuzz_result_finding_detection` |
| CC-N-1 | `result.execution_time_ms` is a positive integer | `test_execution_time_recorded` |
| CC-N | `result.next_steps` is non-empty; mentions `run_fuzz`, `FUZZ_ITERATIONS`, or `fuzz` (case-insensitive) | `test_next_steps_present` |
| CC-19 | `httpx` does not appear in any `ast.Import` / `ast.ImportFrom` node at the top level of `runner.py`'s module body | `test_httpx_import_is_lazy` |
| CC-20 | `runner.py` contains `FUZZ_ITERATIONS` and `FUZZ_TIMEOUT_S` | `test_fuzz_runner_reads_env_vars` |
| CC-21 | `result.notes` mentions `openapi` or `schema` AND mentions `fuzz` or `adversar` (case-insensitive) | `test_notes_mention_openapi_and_schema` |
| CC-LAST | After two sequential runs all `.py` files in the project remain parseable | `test_idempotent_project_still_parses` |

---

## 7. Definition of Done

The tool is complete when:

1. `adapt/extend/testing_tools/test_add_api_fuzzer.py` — all 24 test functions (`CC-01` through `CC-LAST`) pass when run with `PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_api_fuzzer.py -v`.
2. `app/fuzzer/__init__.py` — contains `APIFuzzer` class with `endpoint_list()` returning per-method descriptors from `self._schema["paths"]` (respecting `FUZZ_EXCLUDE_PATHS`), `generate_payloads(body_schema)` delegating to `build_payloads_for_schema`, and `_extract_body_schema()` module-level helper for `$ref` resolution.
3. `app/fuzzer/generators.py` — contains `int_values()`, `string_values()`, `bool_values()`, `number_values()`, `array_values()`, `_FIELD_TYPE_GENERATORS` dispatch table, `_MAX_PAYLOADS_PER_SCHEMA = 20`, `build_payloads_for_schema()`, `_empty_payload()`, `_huge_payload()` (`"A" * 1_048_576`), `_nested_null()`; `string_values()` includes SQL injection (`' OR '1'='1'`) and XSS vectors (`<script>alert(1)</script>`); `int_values()` includes `2**31 - 1`; unicode edge cases include `\x00` and `\uffff`.
4. `app/fuzzer/runner.py` — contains `FuzzResult` with `is_finding()` checking `self.error` and `status_code >= 500 and not is_json`; `FuzzRunner` with `iterations` and `timeout_s` reading from `FUZZ_ITERATIONS` and `FUZZ_TIMEOUT_S` env vars; `async def run()` with `import httpx` deferred inside the function body (not at module top level).
5. `scripts/run_fuzz.py` — `argparse.ArgumentParser` with `--base-url` (required), `--iterations`, `--timeout`, `--output`; `if __name__ == "__main__": sys.exit(asyncio.run(_main()))` guard; exit codes 0/1/2.
6. `app/core/config.py` — `FUZZ_ITERATIONS: int = 10`, `FUZZ_TIMEOUT_S: int = 5`, `FUZZ_EXCLUDE_PATHS: str = "/docs,/openapi.json,/redoc"` injected with 4-space indent inside `class Settings`.
7. All generated `.py` files pass `ast.parse()` with zero `SyntaxError`.
8. No generated function in `app/fuzzer/` exceeds 50 LOC.
9. `httpx` is not present in any `ast.Import`/`ast.ImportFrom` node at the top level of `runner.py`'s module body.
10. Second run returns `status="no_op"` without modifying any file.
11. `dry_run=True` writes no bytes and returns `status="success"`.

---

## 8. Invariants

| ID | Invariant | Enforced by |
|----|-----------|-------------|
| INV-FUZZ-001 | Idempotency fingerprint is `"APIFuzzer" in app/fuzzer/__init__.py` | Tool source; CC-02 |
| INV-FUZZ-002 | `httpx` is imported lazily inside `FuzzRunner.run()`, never at module top level in any generated file | CC-19 |
| INV-FUZZ-003 | No external fuzzing framework (`hypothesis`, `atheris`, `boofuzz`, `schemathesis`) is imported in any generated file | CC-17 |
| INV-FUZZ-004 | `FuzzResult.is_finding()` detects non-JSON 5xx responses (`status_code >= 500 and not is_json`) AND request-level errors (`self.error`) | CC-18 |
| INV-FUZZ-005 | `generators.py` includes SQL injection strings containing `OR '1'='1'` or `DROP TABLE` | CC-11 |
| INV-FUZZ-006 | `generators.py` includes XSS vectors containing `<script>` or `onerror` | CC-11 |
| INV-FUZZ-007 | `generators.py` includes boundary integer `2**31` or literal `2147483647` | CC-14 |
| INV-FUZZ-008 | `generators.py` includes unicode edge cases `\x00` or `\uffff` | CC-15 |
| INV-FUZZ-009 | `generators.py` includes a 1 MB string via `1_048_576` or `1048576` | CC-16 |
| INV-FUZZ-010 | Config fields are injected with 4-space indent inside `class Settings` | CC-08 |
| INV-FUZZ-011 | `_MAX_PAYLOADS_PER_SCHEMA = 20` caps total payloads per endpoint to prevent unbounded fuzzing runs | Tool source |
| INV-FUZZ-012 | `scripts/run_fuzz.py` has `if __name__ == "__main__"` guard so it is invocable as a standalone script | CC-13 |
| INV-FUZZ-013 | All generated `.py` files pass `ast.parse()` before the tool returns `status="success"` | CC-06 |
| INV-FUZZ-014 | `dry_run=True` writes zero bytes and returns `status="success"` | CC-03 |

---

## 9. User Stories

**Story 1 — Catching SQL injection before the pen tester does**
As a backend developer preparing for a quarterly penetration test, I run `python scripts/run_fuzz.py --base-url http://localhost:8000` against my local server after adding a new `/users/search` endpoint. The fuzzer sends `' OR '1'='1'` as the `query` parameter. The endpoint returns HTTP 500 with a raw PostgreSQL error traceback (non-JSON). `FuzzResult.is_finding()` returns `True`. I fix the parameterised query before the pen tester ever sees the endpoint.

**Story 2 — CI gate against regressions**
As a platform engineer, I add `python scripts/run_fuzz.py --base-url http://staging-api --output fuzz_report.json` as a post-deploy CI step. The script exits `1` on findings (non-zero CI fail) and exits `0` when clean. A regression that makes `/orders` return a 500 on empty string input is caught in CI before the deploy reaches production.

**Story 3 — Zero-setup developer experience**
As a developer who just ran `fastapi_add_api_fuzzer` on my project, I do not install any fuzzing framework. I run `python scripts/run_fuzz.py --base-url http://localhost:8000`. The script imports `httpx` lazily at runtime; since `httpx` is already in my `requirements.txt` (added by the base project generator), no extra install step is needed. The fuzzer reads `/openapi.json` from the live server, discovers my 3 POST endpoints, and runs 10 payloads each in under 2 seconds.

**Story 4 — Custom iteration depth for thoroughness**
As a security engineer running a dedicated fuzzing sprint, I set `FUZZ_ITERATIONS=50` in `.env` and run `python scripts/run_fuzz.py --base-url http://localhost:8000`. The fuzzer tries 50 payloads per endpoint (up to `_MAX_PAYLOADS_PER_SCHEMA = 20` per schema, cycling through iterations), maximising coverage within the configured budget.

**Story 5 — Excluding documentation routes**
As a developer, I set `FUZZ_EXCLUDE_PATHS=/docs,/openapi.json,/redoc,/health` in `.env`. The fuzzer's `endpoint_list()` reads `FUZZ_EXCLUDE_PATHS` and skips those paths, so Swagger UI and the health map are not fuzz-targeted (they are read-only and their 404/422 responses are expected).

---

## 10. Design Decisions

### DD-01: Schema-aware fuzzing instead of blind fuzzing
Blind fuzzing (sending random bytes to every route) generates enormous noise and very few actionable findings per API call. Schema-aware fuzzing reads the OpenAPI schema to enumerate real endpoints and construct payloads that are structurally valid except for one adversarial field at a time — the `build_payloads_for_schema` approach. A 422 (validation error) is expected and ignored; a 500 (non-JSON) is the actual signal. This precision makes schema-aware fuzzing compatible with CI (bounded duration, actionable findings) in a way that blind fuzzing is not.

### DD-02: `is_finding()` targets non-JSON 5xx, not all 5xx
A well-configured FastAPI application with proper exception handlers returns structured JSON on 500 (`{"detail": "Internal Server Error"}`). Flagging every 5xx as a finding would generate false positives for expected error handling. The rule `status_code >= 500 and not is_json` isolates unhandled code paths that bypass the exception handler — exactly the cases that expose stack traces, crash the worker, or indicate a code path the developer forgot to test.

### DD-03: `httpx` imported lazily inside `run()`
`httpx` is already a standard dependency for FastAPI projects (used in tests and async HTTP calls). Importing it at module top level would cause `ImportError` in environments where it is temporarily absent (e.g., a lightweight CI image that installs only production deps). Deferring the import to inside `run()` means the fuzzer module is always importable for introspection, and the `ImportError` only surfaces when the developer actually attempts to run a fuzzing session.

### DD-04: No external fuzzing frameworks
`hypothesis`, `atheris`, `boofuzz`, and `schemathesis` are all powerful tools, but each adds tens of megabytes to the dependency tree and requires configuration specific to the framework. The tool's design goal is zero-friction adoption: the developer runs one tool and gets a working fuzzer with no additional configuration, no Jupyter notebooks, no grammar files. The stdlib-only generator approach achieves this at the cost of less sophisticated payload generation, which is an acceptable trade-off for a first-line fuzzing defence.

### DD-05: Table-driven generators via `_FIELD_TYPE_GENERATORS`
Dispatching on OpenAPI field `type` to a type-specific generator ensures that integer fields receive boundary integers, boolean fields receive type-confusion values, and string fields receive the full adversarial string battery. Applying `string_values()` to every field regardless of type would flood integer fields with strings that FastAPI's Pydantic validators reject at 422 before reaching business logic — generating noise rather than findings.

### DD-06: `_MAX_PAYLOADS_PER_SCHEMA = 20` hard cap
Without a cap, a schema with many fields could generate hundreds of payloads per endpoint, making a 10-endpoint API produce thousands of requests per fuzzing run. `_MAX_PAYLOADS_PER_SCHEMA = 20` bounds the per-endpoint request count so the total fuzzing session duration remains predictable and CI-compatible. The `--iterations` CLI flag provides a separate per-endpoint cap that the developer can adjust.

### DD-07: `FUZZ_EXCLUDE_PATHS` as comma-separated env var
Exclusion via env var rather than a config file allows different exclusion lists per environment without file changes. The default value `/docs,/openapi.json,/redoc` excludes the three FastAPI read-only routes that are not business logic and would only produce 404/405 noise.

---

## 11. Dependencies

| Dependency | Version | Why |
|------------|---------|-----|
| fastapi | ≥ 0.100.0 | Project context; OpenAPI schema served at `/openapi.json` |
| httpx | ≥ 0.25.0 | Async HTTP client for `FuzzRunner`; deferred import inside `run()` |
| asyncio | stdlib | `asyncio.run` in CLI, `async def run()` in FuzzRunner |
| argparse | stdlib | CLI argument parsing in `scripts/run_fuzz.py` |
| json | stdlib | Schema parsing, report serialisation |
| os | stdlib | `os.getenv("FUZZ_ITERATIONS", ...)` and `FUZZ_EXCLUDE_PATHS` |
| ast | stdlib | Tool-level syntax validation of generated files |

No new entries are added to `requirements.txt` — `httpx` is expected to be present from the base project generator. All other dependencies are Python stdlib.

---

## 12. Error Handling

| Scenario | Behaviour |
|----------|-----------|
| `validate_project_dir` fails | Return `ToolResult(status="error", error=<message>)` immediately |
| Prerequisites not met | Return `ToolResult(status="error", error="Prerequisites not met: ...")` with `notes` pointing to `fastapi_generate_project` |
| `app/core/config.py` does not exist | Skip config patch; `files_modified` remains empty for that file |
| Idempotency guard triggers | Return `ToolResult(status="no_op", notes=["APIFuzzer already present..."])` |
| Generated `.py` file has `SyntaxError` | Return `ToolResult(status="error", error=f"Generated file has syntax error: {p}: {exc}")` |
| `_patch_config`: `FUZZ_ITERATIONS` already present | `_patch_config` short-circuits with no write |
| `_fetch_schema` fails (server unreachable) | `except Exception` returns `{}` with `logger.warning`; fuzzer continues with empty schema (no endpoints fuzzed, zero findings) |
| `FuzzRunner._fuzz_one` — request exception (timeout, connection error) | `except Exception` returns `FuzzResult(..., error=str(exc))`; `is_finding()` returns `True` for error |
| `FuzzRunner._fuzz_one` — response body not JSON | `is_json = False` set by inner `except Exception` on `resp.json()`; triggers `is_finding()` if `status_code >= 500` |
| `_main()` — `ImportError` on `FuzzRunner` | Prints error to stderr, returns exit code `2` |
| `_emit_report` — findings list non-empty | Returns exit code `1`; prints `{n} finding(s) detected!` to stderr |
| `_emit_report` — no findings | Returns exit code `0`; prints `No findings.` to stderr |

---

## 13. Security Considerations

| Concern | Mitigation |
|---------|------------|
| Fuzzer targets production | `scripts/run_fuzz.py` requires `--base-url` to be explicitly provided; there is no default that accidentally targets a production endpoint |
| SQL injection payloads in fuzzer code | Payloads are stored as string literals in `generators.py` for testing purposes; they do not execute against any database — they are sent as HTTP request bodies to the target server |
| XSS vectors stored in source | Same as above — these are test inputs, not live DOM injections |
| Huge string (1 MB) DoS potential | A 1 MB string sent to a production endpoint can cause resource exhaustion. Operators MUST only run the fuzzer against development or staging environments |
| `FuzzResult.to_dict()` includes `payload` | The payload dict may contain SQL injection strings or XSS vectors. The JSON report written by `--output` MUST be treated as potentially sensitive and not logged to public channels |
| httpx `AsyncClient` follows redirects | By default httpx follows redirects. If the target server redirects fuzzing requests to a third-party endpoint, adversarial payloads could be sent there. Operators SHOULD pass `follow_redirects=False` or verify the `base-url` is an internal endpoint |
| `_extract_body_schema` resolves `$ref` | The `$ref` resolver walks the full OpenAPI schema dict. A schema with circular `$ref`s could cause infinite recursion. The resolver only walks one level per `$ref` path component, which terminates cleanly for standard OpenAPI 3.x schemas |

---

## 14. Testing Guide

### Running the test file

```bash
# With pytest (recommended)
PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_api_fuzzer.py -v

# Without pytest (standalone runner)
PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_api_fuzzer.py
```

### Test file location

`adapt/extend/testing_tools/test_add_api_fuzzer.py`

### Test inventory

| Test function | CC | What it verifies |
|---------------|----|------------------|
| `test_success_status` | CC-01 | `result.status == "success"` on fresh project |
| `test_idempotent` | CC-02 | Second run → `status="no_op"`, zero files created/modified |
| `test_dry_run` | CC-03 | `dry_run=True` → no bytes written; project identical before/after |
| `test_files_created_count` | CC-04 | `len(files_created) >= 4`; all paths exist on disk |
| `test_files_modified_count` | CC-05 | `len(files_modified) >= 1`; all paths exist on disk |
| `test_all_py_parse` | CC-06 | All `.py` files under project root parse without `SyntaxError` |
| `test_no_function_over_50_loc` | CC-07 | AST walk over `app/fuzzer/`; no function > 50 LOC |
| `test_config_fields_patched` | CC-08 | `FUZZ_ITERATIONS` + `FUZZ_TIMEOUT_S` + `FUZZ_EXCLUDE_PATHS` in config; 4-space indent |
| `test_api_fuzzer_init` | CC-09 | `app/fuzzer/__init__.py` has `APIFuzzer`, `endpoint_list`, `generate_payloads` |
| `test_generators_file` | CC-10 | `generators.py` has all 5 generator functions + `build_payloads_for_schema` |
| `test_adversarial_payloads_in_generators` | CC-11 | SQL injection + XSS vectors present |
| `test_runner_file` | CC-12 | `runner.py` has `FuzzRunner`, `FuzzResult`, `async def run`, `is_finding` |
| `test_cli_script_created` | CC-13 | `scripts/run_fuzz.py` has argparse, `--base-url`, `__main__` guard |
| `test_boundary_integers_in_generators` | CC-14 | `generators.py` has `2**31` or `2147483647` |
| `test_unicode_edge_cases_in_generators` | CC-15 | `generators.py` has `\x00` or `\uffff` |
| `test_huge_string_in_generators` | CC-16 | `generators.py` has `1_048_576` or `1048576` |
| `test_no_external_deps_beyond_httpx` | CC-17 | No `hypothesis`/`atheris`/`boofuzz`/`schemathesis` in generated files |
| `test_fuzz_result_finding_detection` | CC-18 | `runner.py` has `500` or `>= 500` AND `is_json` |
| `test_execution_time_recorded` | CC-N-1 | `result.execution_time_ms > 0` |
| `test_next_steps_present` | CC-N | `next_steps` non-empty; mentions `run_fuzz` or `FUZZ_ITERATIONS` or `fuzz` |
| `test_httpx_import_is_lazy` | CC-19 | `httpx` not in `tree.body` top-level imports of `runner.py` |
| `test_fuzz_runner_reads_env_vars` | CC-20 | `runner.py` has `FUZZ_ITERATIONS` and `FUZZ_TIMEOUT_S` |
| `test_notes_mention_openapi_and_schema` | CC-21 | Notes mention `openapi`/`schema` AND `fuzz`/`adversar` |
| `test_idempotent_project_still_parses` | CC-LAST | Two runs → all `.py` files remain parseable |

### Manual verification checklist

- [ ] `python scripts/run_fuzz.py --base-url http://localhost:8000` exits `0` on a clean API
- [ ] `python scripts/run_fuzz.py --base-url http://localhost:8000 --output report.json` writes valid JSON
- [ ] Report JSON has `total_requests`, `findings`, and `results` keys
- [ ] An endpoint that returns non-JSON 500 on `\x00` input appears in findings
- [ ] `FUZZ_EXCLUDE_PATHS=/docs,/openapi.json,/redoc` in `.env` prevents fuzzing those paths
- [ ] `python3 -c "import app.fuzzer"` succeeds even without httpx installed (lazy import)
- [ ] `python3 -c "import app.fuzzer.runner"` succeeds even without httpx (lazy import)
- [ ] `FUZZ_ITERATIONS=2 python scripts/run_fuzz.py --base-url http://localhost:8000` limits to 2 payloads per endpoint

---

## 15. Files Reference

| File | Role | Created/Modified |
|------|------|-----------------|
| `adapt/extend/testing_tools/add_api_fuzzer.py` | Tool entry point; orchestrates all writes and patches | Source (not generated) |
| `adapt/extend/testing_tools/test_add_api_fuzzer.py` | Test suite; 24 test functions CC-01…CC-LAST | Source (not generated) |
| `app/fuzzer/__init__.py` | `APIFuzzer` class; `endpoint_list()`; `generate_payloads()`; `_extract_body_schema()` | Created by tool |
| `app/fuzzer/generators.py` | Adversarial generators: `int_values`, `string_values`, `bool_values`, `number_values`, `array_values`; `build_payloads_for_schema()`; `_FIELD_TYPE_GENERATORS`; `_MAX_PAYLOADS_PER_SCHEMA` | Created by tool |
| `app/fuzzer/runner.py` | `FuzzResult` with `is_finding()`; `FuzzRunner` with `async run()`; lazy `import httpx` | Created by tool |
| `scripts/run_fuzz.py` | CLI runner: `argparse` with `--base-url`, `--iterations`, `--timeout`, `--output`; `if __name__ == "__main__"` | Created by tool |
| `app/core/config.py` | Receives `FUZZ_ITERATIONS: int = 10`, `FUZZ_TIMEOUT_S: int = 5`, `FUZZ_EXCLUDE_PATHS: str = "/docs,/openapi.json,/redoc"` | Modified by tool |

---

## 16. Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-04-15 | Initial spec — 24 CCs, APIFuzzer schema reader, generators with SQL/XSS/boundary/unicode/1MB payloads, FuzzRunner with lazy httpx, FuzzResult.is_finding(), scripts/run_fuzz.py CLI, no external fuzzing frameworks |
