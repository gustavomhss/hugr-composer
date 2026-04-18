# TOOL-094: `fastapi_add_e2e_test_suite`

**Skill:** SKILL-001-fastapi-production
**Category:** extend / testing
**Source:** `adapt/extend/testing_tools/add_e2e_test_suite.py`
**Test file:** `adapt/extend/testing_tools/test_add_e2e_test_suite.py`
**MCP name:** `fastapi_add_e2e_test_suite`

---

## 1. Overview

`fastapi_add_e2e_test_suite` scaffolds a complete async end-to-end test suite
for any FastAPI project. It creates a `tests/e2e/` package with five files and
patches one existing file:

| File | Purpose |
|---|---|
| `tests/e2e/__init__.py` | Package marker |
| `tests/e2e/conftest.py` | Three shared async fixtures: `async_client` (httpx.ASGITransport), `test_user` (registers a user), `auth_headers` (JWT Bearer token) |
| `tests/e2e/test_auth_flow.py` | Registration → login → wrong-password 401 → protected route without auth → protected route with valid token |
| `tests/e2e/test_crud_flow.py` | Create → read single → list → update (PATCH) → delete → verify-gone (404) |
| `tests/e2e/test_error_handling.py` | 422 missing field → 422 wrong type (no 5xx) → 404 nonexistent → 401 no auth → 401 forged JWT |
| `app/core/config.py` *(patch)* | Inserts `E2E_BASE_URL`, `E2E_TEST_EMAIL`, `E2E_TEST_PASSWORD` inside `class Settings` |

The tool is **idempotent**: a second invocation on a project where
`tests/e2e/conftest.py` already exists and contains `async_client` returns
`status="no_op"` and writes nothing.

No new pip dependencies are introduced — `httpx` and `pytest` are already
listed in the base project's `requirements.txt`.

---

## 2. Purpose & Problem Solved

FastAPI projects routinely ship with only unit tests. E2E tests that exercise
the full request/response cycle — including auth middleware, DB round-trips,
and HTTP status codes — are either absent or require a running server. This
tool solves both problems:

- **In-process ASGI transport:** `httpx.ASGITransport(app=app)` drives the
  FastAPI app directly in the test process — no `uvicorn`, no network port,
  no `docker-compose up` required.
- **Realistic auth fixtures:** `test_user` calls `/api/v1/auth/register`;
  `auth_headers` calls `/api/v1/auth/login` and extracts the JWT — the exact
  flow real clients use.
- **Three coverage tiers:**
  - `test_auth_flow.py` — identity and authentication paths
  - `test_crud_flow.py` — data lifecycle correctness
  - `test_error_handling.py` — resilience and proper HTTP semantics
- **Async-native:** every test function is decorated with
  `@pytest.mark.asyncio` and uses `async def` — compatible with
  `pytest-asyncio` `--asyncio-mode=auto`.

---

## 3. Performance SLOs

| Metric | Target |
|---|---|
| `execution_time_ms` | < 300 ms on cold filesystem |
| Files created | 5 (in `tests/e2e/`) |
| Files modified | 1 (`app/core/config.py`) |
| Config fields injected | 3 (`E2E_BASE_URL`, `E2E_TEST_EMAIL`, `E2E_TEST_PASSWORD`) |
| Maximum function LOC (`tests/`) | ≤ 50 |
| `no_op` detection cost | O(1) — single file existence + string check |

---

## 4. Code Examples

### 4.1 Before (project without E2E tests)

```
my_project/
├── app/
│   ├── main.py
│   └── core/
│       └── config.py
├── tests/
│   └── test_unit.py
└── requirements.txt
```

`app/core/config.py` before:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost/db"
    SECRET_KEY: str = "change-me"

settings = Settings()
```

### 4.2 After (tool applied)

```
my_project/
├── app/
│   └── core/
│       └── config.py          # E2E_BASE_URL, E2E_TEST_EMAIL, E2E_TEST_PASSWORD added
└── tests/
    ├── test_unit.py
    └── e2e/
        ├── __init__.py
        ├── conftest.py
        ├── test_auth_flow.py
        ├── test_crud_flow.py
        └── test_error_handling.py
```

`app/core/config.py` after (injected block):

```python
    E2E_BASE_URL: str = "http://localhost:8000"
    E2E_TEST_EMAIL: str = "e2e_test@example.com"
    E2E_TEST_PASSWORD: str = "E2eTestPass123!"

settings = Settings()
```

### 4.3 `tests/e2e/conftest.py` — the three fixtures

```python
@pytest_asyncio.fixture
async def async_client() -> httpx.AsyncClient:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest_asyncio.fixture
async def test_user(async_client: httpx.AsyncClient) -> dict:
    from app.core.config import settings
    email = getattr(settings, "E2E_TEST_EMAIL", "e2e_test@example.com")
    password = getattr(settings, "E2E_TEST_PASSWORD", "E2eTestPass123!")
    resp = await async_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert resp.status_code in (201, 409), (
        f"Failed to create test user: {resp.status_code} {resp.text}"
    )
    return {"email": email, "password": password}


@pytest_asyncio.fixture
async def auth_headers(
    async_client: httpx.AsyncClient,
    test_user: dict,
) -> dict[str, str]:
    resp = await async_client.post(
        "/api/v1/auth/login",
        data={"username": test_user["email"], "password": test_user["password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
```

### 4.4 `tests/e2e/test_auth_flow.py` (key tests)

```python
@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(
    async_client: httpx.AsyncClient, test_user: dict
) -> None:
    resp = await async_client.post(
        "/api/v1/auth/login",
        data={"username": test_user["email"], "password": "completely-wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_with_valid_token(
    async_client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await async_client.get("/api/v1/users/me", headers=auth_headers)
    assert resp.status_code == 200
    assert "email" in resp.json()
```

### 4.5 `tests/e2e/test_crud_flow.py` (key test)

```python
@pytest.mark.asyncio
async def test_delete_item_then_verify_gone(
    async_client: httpx.AsyncClient, auth_headers: dict
) -> None:
    create_resp = await async_client.post(
        "/api/v1/items/",
        json={"title": "To Delete", "description": "Delete me"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    item_id = create_resp.json()["id"]

    delete_resp = await async_client.delete(
        f"/api/v1/items/{item_id}", headers=auth_headers
    )
    assert delete_resp.status_code in (200, 204)

    gone_resp = await async_client.get(
        f"/api/v1/items/{item_id}", headers=auth_headers
    )
    assert gone_resp.status_code == 404
```

### 4.6 `tests/e2e/test_error_handling.py` (key tests)

```python
@pytest.mark.asyncio
async def test_create_item_wrong_type_returns_422(
    async_client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await async_client.post(
        "/api/v1/items/",
        json={"title": 12345, "description": True},
        headers=auth_headers,
    )
    # Key invariant: server must not crash (no 5xx)
    assert resp.status_code < 500


@pytest.mark.asyncio
async def test_invalid_bearer_token_returns_401(
    async_client: httpx.AsyncClient,
) -> None:
    resp = await async_client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer this.is.not.a.valid.jwt"},
    )
    assert resp.status_code == 401
```

### 4.7 `_patch_config` implementation

```python
def _patch_config(config_file: Path) -> None:
    content = config_file.read_text()
    fields_needed = [
        '    E2E_BASE_URL: str = "http://localhost:8000"',
        '    E2E_TEST_EMAIL: str = "e2e_test@example.com"',
        '    E2E_TEST_PASSWORD: str = "E2eTestPass123!"',
    ]
    new_lines = [line for line in fields_needed
                 if line.strip().split(":")[0] not in content]
    if not new_lines:
        return
    insertion = "\n".join(new_lines) + "\n"
    marker = "settings = Settings()"
    if marker in content:
        content = content.replace(marker, insertion + "\n" + marker, 1)
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += "\n" + insertion
    config_file.write_text(content)
```

### 4.8 Idempotency guard

```python
conftest = e2e_dir / "conftest.py"
if conftest.exists() and "async_client" in conftest.read_text():
    return ToolResult(
        status="no_op",
        notes=["async_client fixture already present — E2E suite already installed, skipped."],
        execution_time_ms=_elapsed_ms(start),
    )
```

### 4.9 MCP descriptor

```python
MCP_TOOL = {
    "name": "fastapi_add_e2e_test_suite",
    "description": (
        "Scaffold an async E2E test suite with httpx: conftest fixtures, auth flow, "
        "CRUD flow, and error-handling tests."
    ),
    "tags": ["extend", "testing"],
    "entry": "add_e2e_test_suite",
}
```

---

## 5. Quality Standards

| Standard | Requirement |
|---|---|
| Function size | No function in generated `tests/` code exceeds 50 LOC (AST-enforced) |
| Python validity | Every generated `.py` file passes `ast.parse()` before `status="success"` |
| Async markers | All test functions decorated with `@pytest.mark.asyncio` |
| No real server | `httpx.ASGITransport(app=app)` used throughout — no external server |
| Auth fixture chain | `auth_headers` depends on `test_user` which depends on `async_client` |
| Test file count | Exactly 5 files in `tests/e2e/` |
| Config hygiene | Fields 4-space indented inside `class Settings` body |
| Zero new deps | `httpx` and `pytest-asyncio` already in base requirements |

---

## 6. Completeness Criteria

| CC | Criterion | Verification | Test |
|---|---|---|---|
| CC-01 | `status="success"` on fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `no_op`, zero writes | `r2.status == "no_op"` and `not r2.files_created` | `test_idempotent` |
| CC-03 | `dry_run=True` returns `success` with zero writes | No files changed | `test_dry_run` |
| CC-04 | At least 5 files in `tests/e2e/` reported in `files_created` | `len(e2e_files) >= 5` | `test_files_created_count` |
| CC-05 | At least 1 file modified (`config.py`) | `len(result.files_modified) >= 1` | `test_files_modified_count` |
| CC-06 | All generated `.py` files parse without `SyntaxError` | `ast.parse()` on every `.py` | `test_all_py_parse` |
| CC-07 | No function in `tests/` exceeds 50 LOC | AST walk | `test_no_function_over_50_loc` |
| CC-08 | `E2E_BASE_URL`, `E2E_TEST_EMAIL`, `E2E_TEST_PASSWORD` inside `class Settings` | 4-space indent check | `test_config_fields_patched` |
| CC-09 | `conftest.py` contains `async_client` fixture using `ASGITransport` | Content check | `test_conftest_has_async_client_fixture` |
| CC-10 | `conftest.py` contains `test_user` and `auth_headers` fixtures | Content check | `test_conftest_has_auth_fixtures` |
| CC-11 | `test_auth_flow.py` has login and registration tests | `"login"` and `"register"` in content | `test_auth_flow_test_created` |
| CC-12 | `test_crud_flow.py` covers create, delete, and 404-verify | Content check | `test_crud_flow_test_created` |
| CC-13 | `test_error_handling.py` covers 422, 404, and 401 | Content check | `test_error_handling_test_created` |
| CC-14 | All three test files use `@pytest.mark.asyncio` | Content check on all three | `test_tests_use_asyncio_marker` |
| CC-15 | `conftest.py` uses `ASGITransport` (no real server) | `"ASGITransport" in content` | `test_no_real_server_needed` |
| CC-16 | `tests/e2e/__init__.py` created | File exists | `test_e2e_init_created` |
| CC-17 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-18 | `next_steps` non-empty and mentions `pytest` | `"pytest" in combined` | `test_next_steps_present` |
| CC-19 | Project still parses after two consecutive runs | `ast.parse()` on all `.py` | `test_idempotent_project_still_parses` |
| CC-20 | `conftest.py` imports from `app.main` | `"app.main" in content or "from app" in content` | `test_conftest_imports_app_main` |
| CC-21 | `test_crud_flow.py` has PATCH/update test | `"patch" or "update"` in content | `test_crud_test_has_update_case` |
| CC-22 | `test_auth_flow.py` has wrong-password → 401 test | `"401" in content` | `test_auth_test_has_wrong_password_case` |

---

## 7. Definition of Done

- [ ] All 22 tests in `test_add_e2e_test_suite.py` pass
- [ ] `tests/e2e/__init__.py` created
- [ ] `tests/e2e/conftest.py` contains `async_client`, `test_user`, `auth_headers` fixtures
- [ ] `async_client` uses `httpx.ASGITransport(app=app)` with `base_url="http://test"`
- [ ] `test_user` accepts 201 or 409 response codes (idempotent registration)
- [ ] `auth_headers` extracts `access_token` from login response and formats as `Bearer`
- [ ] `test_auth_flow.py` covers: register 201, login + token, wrong password 401, no-auth 401, valid token 200 `/me`
- [ ] `test_crud_flow.py` covers: create 201, read 200, list 200, update PATCH, delete + verify 404
- [ ] `test_error_handling.py` covers: 422 missing field, type mismatch (no 5xx), 404 nonexistent, no-auth 401, forged JWT 401
- [ ] All test functions decorated with `@pytest.mark.asyncio`
- [ ] `config.py` receives `E2E_BASE_URL`, `E2E_TEST_EMAIL`, `E2E_TEST_PASSWORD` at 4-space indent
- [ ] Second invocation returns `no_op` without writing any file
- [ ] `dry_run=True` returns `success` without writing any file
- [ ] `execution_time_ms` is a positive integer on every return path
- [ ] `next_steps` mentions `pytest tests/e2e/`
- [ ] No function in generated test code exceeds 50 LOC

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|---|---|---|---|
| INV-E2E-01 | Fingerprint is `"async_client"` in `tests/e2e/conftest.py` | Only `_write_conftest` writes this string | `test_idempotent` |
| INV-E2E-02 | `httpx.ASGITransport(app=app)` is always used — never `httpx.AsyncClient(base_url="http://real-server")` | Hardcoded in `_write_conftest` | `test_conftest_has_async_client_fixture`, `test_no_real_server_needed` |
| INV-E2E-03 | `test_user` fixture accepts both 201 and 409 to be re-entrant across test runs | `assert resp.status_code in (201, 409)` in generated conftest | `test_conftest_has_auth_fixtures` |
| INV-E2E-04 | All three test files use `@pytest.mark.asyncio` — sync test functions are not generated | `@pytest.mark.asyncio` on every `async def test_*` | `test_tests_use_asyncio_marker` |
| INV-E2E-05 | `_patch_config` skips fields already present in `config.py` | `line.strip().split(":")[0] not in content` guard | `test_config_fields_patched` + `test_idempotent_project_still_parses` |
| INV-E2E-06 | `dry_run=True` check is after the idempotency check and before all `Path.write_text()` calls | Code order in `add_e2e_test_suite` | `test_dry_run` |
| INV-E2E-07 | `ast.parse()` validation runs only on `.py` files | `if p.suffix == ".py"` guard | `test_all_py_parse` |
| INV-E2E-08 | `test_error_handling.py` uses `< 500` for type-mismatch test — not `== 422` — to accommodate strict/coercive Pydantic models | `assert resp.status_code < 500` in generated test | `test_error_handling_test_created` |

---

## 9. User Stories

**US-1 — First E2E test coverage**
> As a developer whose FastAPI project only has unit tests, I run
> `fastapi_add_e2e_test_suite` and immediately have a realistic test suite
> that exercises auth, CRUD, and error handling end-to-end without spinning
> up any external services.

**US-2 — CI/CD integration**
> As a DevOps engineer, I add `pytest tests/e2e/ --asyncio-mode=auto` to the
> CI pipeline — the suite runs in CI with no infrastructure dependencies.

**US-3 — Safe re-run after branch switch**
> As a developer who already ran the tool, I can run it again — it returns
> `no_op` and leaves all existing test files unchanged.

**US-4 — Preview before writing**
> As a developer in a code-review workflow, I use `dry_run=True` to see what
> would be created without touching the filesystem.

**US-5 — Live integration testing**
> As a QA engineer, I set `E2E_BASE_URL` in `.env` to point at a staging
> server and run the same test suite against the live deployment by swapping
> the `ASGITransport` for a real base URL.

---

## 10. Edge Cases

| Edge Case | Expected Behaviour |
|---|---|
| `tests/e2e/conftest.py` already has `async_client` | `status="no_op"`, zero writes |
| `tests/e2e/` directory already exists | `mkdir(parents=True, exist_ok=True)` is a no-op |
| `tests/e2e/__init__.py` already exists | `if not init_file.exists():` guard skips creation |
| `app/core/config.py` missing | Config patch skipped silently; five E2E files still created |
| `E2E_BASE_URL` already in `config.py` | `_patch_config` skip-guard prevents duplicate |
| `settings = Settings()` absent from `config.py` | Fields appended to end of file |
| Test database not running | `test_user` fixture will fail at runtime; scaffold is still written cleanly |
| Pydantic v2 strict mode on `title` field | `test_create_item_wrong_type_returns_422` uses `< 500` guard to handle both strict (422) and coercive (201) modes |

---

## 11. Dependencies

| Dependency | Type | Version / Notes |
|---|---|---|
| `adapt.contracts.ToolInput` | Internal | `project_dir`, `dry_run` |
| `adapt.contracts.ToolResult` | Internal | `status`, `files_created`, `files_modified`, `notes`, `next_steps`, `execution_time_ms` |
| `adapt.contracts.validate_project_dir` | Internal | Returns error string if invalid |
| `adapt.contracts.prerequisites.ensure_prerequisites` | Internal | Checks `CONFIG_SETTINGS`, `REQUIREMENTS_TXT`; auto-scaffolds |
| `adapt.contracts.prerequisites.Prereq` | Internal | Enum: `CONFIG_SETTINGS`, `REQUIREMENTS_TXT` |
| `ast` | stdlib | AST parse validation |
| `textwrap` | stdlib | `dedent` for multi-line file templates |
| `time` | stdlib | `time.monotonic()` for `execution_time_ms` |
| `pathlib.Path` | stdlib | All file I/O |
| **httpx ≥ 0.28** | Runtime (project) | `httpx.ASGITransport` available from 0.20+; already in base requirements |
| **pytest-asyncio** | Runtime (project) | `@pytest.mark.asyncio` and `pytest_asyncio.fixture`; already in base requirements |

---

## 12. File Map

```
{project_dir}/
├── tests/
│   └── e2e/
│       ├── __init__.py            # CREATED — package marker
│       ├── conftest.py            # CREATED — async_client, test_user, auth_headers
│       ├── test_auth_flow.py      # CREATED — register, login, 401 paths, protected route
│       ├── test_crud_flow.py      # CREATED — create, read, list, update, delete, 404
│       └── test_error_handling.py # CREATED — 422, type error, 404, no-auth 401, forged JWT 401
└── app/
    └── core/
        └── config.py              # MODIFIED — E2E_BASE_URL, E2E_TEST_EMAIL, E2E_TEST_PASSWORD
```

Source module: `adapt/extend/testing_tools/add_e2e_test_suite.py`
Test module: `adapt/extend/testing_tools/test_add_e2e_test_suite.py`

---

## 13. Rollback

```bash
# Remove the entire e2e package
rm -rf tests/e2e/

# Undo config.py patch (remove the three E2E_* lines)
git checkout app/core/config.py
```

No database migrations, schema changes, or destructive filesystem operations
are performed. The only files changed are new test files and a config patch.

---

## 14. Security Considerations

| Concern | Mitigation |
|---|---|
| Test credentials in source | `E2E_TEST_EMAIL` and `E2E_TEST_PASSWORD` default values are clearly test-only (`e2e_test@example.com`, `E2eTestPass123!`); override via `.env` |
| Forged JWT test | `test_invalid_bearer_token_returns_401` validates that the app rejects malformed tokens; prevents accidental auth bypass in the app |
| No-auth 401 test | `test_protected_route_requires_auth` and `test_create_item_without_auth_returns_401` ensure auth guards are not accidentally removed |
| `ASGITransport` scope | Tests run against the in-process app instance; no external network access; no risk of hitting production endpoints |
| Test isolation | Each `test_user` fixture call uses settings-configured credentials; no hardcoded secrets in test function bodies |

---

## 15. Observability

| Signal | Where |
|---|---|
| `execution_time_ms` | `ToolResult.execution_time_ms` — wall-clock ms |
| `files_created` | Absolute paths of all 5 files in `tests/e2e/` |
| `files_modified` | Absolute path of patched `config.py` |
| `notes` | Summary: fixture descriptions, test module purpose, "no real HTTP server needed" |
| `next_steps` | `pip install pytest-asyncio httpx`, `pytest tests/e2e/ -v --asyncio-mode=auto`, auth-only variant, live-server override |
| Test results | Visible via `pytest -v` output; each test function name reflects its CC |

---

## 16. Test Coverage Map

| Test function | CC | What it proves |
|---|---|---|
| `test_success_status` | CC-01 | Happy path returns `status="success"` |
| `test_idempotent` | CC-02 | Second run returns `no_op` without writing files |
| `test_dry_run` | CC-03 | `dry_run=True` writes nothing |
| `test_files_created_count` | CC-04 | At least 5 E2E files created and exist on disk |
| `test_files_modified_count` | CC-05 | `config.py` reported as modified |
| `test_all_py_parse` | CC-06 | All generated `.py` files parse cleanly |
| `test_no_function_over_50_loc` | CC-07 | 50-LOC function limit enforced in `tests/` |
| `test_config_fields_patched` | CC-08 | Three `E2E_*` fields inside `class Settings` at 4-space indent |
| `test_conftest_has_async_client_fixture` | CC-09 | `async_client` fixture and `ASGITransport` present |
| `test_conftest_has_auth_fixtures` | CC-10 | `test_user` and `auth_headers` fixtures present |
| `test_auth_flow_test_created` | CC-11 | `test_auth_flow.py` has login and register coverage |
| `test_crud_flow_test_created` | CC-12 | `test_crud_flow.py` has create, delete, 404 coverage |
| `test_error_handling_test_created` | CC-13 | `test_error_handling.py` has 422, 404, 401 coverage |
| `test_tests_use_asyncio_marker` | CC-14 | All three test files have `@pytest.mark.asyncio` |
| `test_no_real_server_needed` | CC-15 | `ASGITransport` used in conftest (no real server) |
| `test_e2e_init_created` | CC-16 | `tests/e2e/__init__.py` exists |
| `test_execution_time_recorded` | CC-17 | `execution_time_ms > 0` |
| `test_next_steps_present` | CC-18 | `next_steps` non-empty and mentions `pytest` |
| `test_idempotent_project_still_parses` | CC-19 | Two runs leave all `.py` files parseable |
| `test_conftest_imports_app_main` | CC-20 | `conftest.py` imports from `app.main` |
| `test_crud_test_has_update_case` | CC-21 | `test_crud_flow.py` includes PATCH/update test |
| `test_auth_test_has_wrong_password_case` | CC-22 | `test_auth_flow.py` has wrong-password → 401 test |
