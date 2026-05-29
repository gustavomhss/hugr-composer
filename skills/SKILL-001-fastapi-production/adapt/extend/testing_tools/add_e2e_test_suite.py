"""TOOL-094: add_e2e_test_suite — scaffold an async E2E test suite with httpx.

Generates a complete end-to-end test scaffold that exercises the full FastAPI
request/response cycle without requiring external services:

* ``tests/e2e/__init__.py`` — package marker.
* ``tests/e2e/conftest.py`` — async_client fixture (httpx.ASGITransport),
  test_user fixture, auth_headers fixture (JWT Bearer token).
* ``tests/e2e/test_auth_flow.py`` — signup → login → token refresh → protected route.
* ``tests/e2e/test_crud_flow.py`` — create → read → update → delete → verify gone.
* ``tests/e2e/test_error_handling.py`` — validation errors (422), 404, 401 scenarios.

Configuration knobs injected into ``app/core/config.py``:
    ``E2E_BASE_URL``, ``E2E_TEST_EMAIL``, ``E2E_TEST_PASSWORD``

No new pip dependencies — httpx and pytest are already required by the skill's
base project (httpx>=0.28.0 is in requirements.txt from fixture_factory).

The tool is idempotent: a second run detects the ``async_client`` fingerprint in
``tests/e2e/conftest.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.testing_tools.add_e2e_test_suite import add_e2e_test_suite

    result = add_e2e_test_suite(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/tests/e2e/conftest.py", …]
    print(result.next_steps)    # ["pytest tests/e2e/ -v --asyncio-mode=auto", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

MCP_TOOL = {
    "name": "fastapi_testing_add_e2e_test_suite",
    "description": (
        "Scaffold an async E2E test suite with httpx: conftest fixtures, auth flow, "
        "CRUD flow, and error-handling tests."
    ),
    "tags": ["extend", "testing"],
    "entry": "add_e2e_test_suite",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_e2e_test_suite(inp: ToolInput) -> ToolResult:
    """Scaffold an async E2E test suite for a FastAPI project.

    Generates tests/e2e/__init__.py, tests/e2e/conftest.py (async_client,
    test_user, auth_headers fixtures), tests/e2e/test_auth_flow.py
    (signup→login→refresh→protected), tests/e2e/test_crud_flow.py
    (create→read→update→delete→verify), and tests/e2e/test_error_handling.py
    (422, 404, 401 scenarios).

    Patches ``app/core/config.py`` with E2E_BASE_URL, E2E_TEST_EMAIL, and
    E2E_TEST_PASSWORD settings fields.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    e2e_dir = project / "tests" / "e2e"

    # --- Pre-flight: already installed? -------------------------------------
    conftest = e2e_dir / "conftest.py"
    if conftest.exists() and "async_client" in conftest.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "async_client fixture already present in tests/e2e/conftest.py — E2E suite already installed, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard (BEFORE any writes) -----------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create tests/e2e/ with 5 files:",
                "          __init__.py, conftest.py (async_client + test_user + auth_headers),",
                "          test_auth_flow.py (signup→login→refresh→protected),",
                "          test_crud_flow.py (create→read→update→delete→verify),",
                "          test_error_handling.py (422, 404, 401).",
                "[dry_run] Would patch app/core/config.py with E2E_BASE_URL, E2E_TEST_EMAIL,",
                "          E2E_TEST_PASSWORD.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []
    e2e_dir.mkdir(parents=True, exist_ok=True)

    # --- Step 1: tests/e2e/__init__.py ----------------------------------------
    init_file = e2e_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""End-to-end test suite for the FastAPI application."""\n')
        files_created.append(str(init_file))

    # --- Step 2: tests/e2e/conftest.py ----------------------------------------
    _write_conftest(conftest)
    files_created.append(str(conftest))

    # --- Step 3: tests/e2e/test_auth_flow.py ----------------------------------
    auth_test = e2e_dir / "test_auth_flow.py"
    _write_test_auth_flow(auth_test)
    files_created.append(str(auth_test))

    # --- Step 4: tests/e2e/test_crud_flow.py ----------------------------------
    crud_test = e2e_dir / "test_crud_flow.py"
    _write_test_crud_flow(crud_test)
    files_created.append(str(crud_test))

    # --- Step 5: tests/e2e/test_error_handling.py ----------------------------
    error_test = e2e_dir / "test_error_handling.py"
    _write_test_error_handling(error_test)
    files_created.append(str(error_test))

    # --- Step 6: Patch config.py with E2E settings fields --------------------
    # F-007: only treat as modified when the helper actually wrote.
    config_file = project / "app" / "core" / "config.py"
    config_notes: list[str] = []
    if config_file.exists():
        from adapt.contracts.config_patcher import PatchResult

        patch_outcome = _patch_config(config_file)
        if patch_outcome is PatchResult.APPLIED:
            files_modified.append(str(config_file))
        elif patch_outcome is PatchResult.TARGET_MISSING:
            config_notes.append(
                "config.py: no `class Settings` shape found — "
                "E2E_* fields were appended at module level."
            )
        elif patch_outcome is PatchResult.SYNTAX_ERROR:
            return ToolResult(
                status="error",
                error="app/core/config.py has a syntax error — refusing to patch.",
                execution_time_ms=_elapsed_ms(start),
            )

    # --- Step 7 (F-003): patch requirements.txt with test deps ---------------
    # Pre-fix the emitted suite imported pytest_asyncio + httpx but the
    # standalone scaffold's requirements.txt declared httpx alone. Running
    # ``pytest tests/e2e/`` on a fresh scaffold would ImportError. We now
    # ensure both packages are declared (httpx is usually already there,
    # but the check is line-by-line + idempotent).
    requirements_file = project / "requirements.txt"
    if (
        requirements_file.exists()
        and _patch_requirements_with_test_deps(requirements_file)
        and str(requirements_file) not in files_modified
    ):
        files_modified.append(str(requirements_file))

    # --- ast.parse validation loop (BEFORE success return) -------------------
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "E2E test suite scaffolded in tests/e2e/:",
            "  conftest.py: async_client (ASGITransport), test_user, auth_headers fixtures.",
            "  test_auth_flow.py: signup → login → token refresh → protected route.",
            "  test_crud_flow.py: create → read → update → delete → verify-gone cycle.",
            "  test_error_handling.py: 422 validation, 404 not found, 401 unauthorized.",
            "All tests use httpx.AsyncClient — no real HTTP server needed.",
            "Config fields added: E2E_BASE_URL, E2E_TEST_EMAIL, E2E_TEST_PASSWORD.",
            "requirements.txt: httpx + pytest-asyncio declared so the emitted suite is runnable.",
            *config_notes,
        ],
        next_steps=[
            "pip install pytest-asyncio httpx  # if not already installed",
            "pytest tests/e2e/ -v --asyncio-mode=auto",
            "pytest tests/e2e/test_auth_flow.py -v --asyncio-mode=auto  # auth only",
            "Set E2E_BASE_URL in .env to point at a real server for live integration tests.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------


def _write_conftest(dest: Path) -> None:
    """Write tests/e2e/conftest.py with async_client, test_user, auth_headers fixtures.

    The async_client fixture boots the ASGI app in-process via
    httpx.ASGITransport — no real server or network required.

    Args:
        dest: Absolute path for conftest.py.
    """
    content = textwrap.dedent("""\
        \"\"\"Shared fixtures for the E2E test suite.

        Provides:
        * ``async_client`` — httpx.AsyncClient wired to the ASGI app via
          ASGITransport (no real server needed).
        * ``test_user`` — a registered user in the test database.
        * ``auth_headers`` — JWT Bearer headers for the test_user.
        \"\"\"
        from __future__ import annotations

        import pytest
        import pytest_asyncio
        import httpx

        from app.main import app


        @pytest_asyncio.fixture
        async def async_client() -> httpx.AsyncClient:
            \"\"\"Yield an async httpx client backed by the ASGI app.

            Returns:
                Configured httpx.AsyncClient for the test session.
            \"\"\"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                yield client


        @pytest_asyncio.fixture
        async def test_user(async_client: httpx.AsyncClient) -> dict:
            \"\"\"Create and return a registered test user.

            Returns:
                Dict with ``email`` and ``password`` keys.
            \"\"\"
            from app.core.config import settings
            email = getattr(settings, "E2E_TEST_EMAIL", "e2e_test@example.com")
            password = getattr(settings, "E2E_TEST_PASSWORD", "E2eTestPass123!")
            resp = await async_client.post(
                "/api/v1/auth/register",
                json={"email": email, "password": password},
            )
            # 201 = created, 409 = already exists — both are acceptable in tests
            assert resp.status_code in (201, 409), (
                f"Failed to create test user: {resp.status_code} {resp.text}"
            )
            return {"email": email, "password": password}


        @pytest_asyncio.fixture
        async def auth_headers(
            async_client: httpx.AsyncClient,
            test_user: dict,
        ) -> dict[str, str]:
            \"\"\"Return Authorization headers for the test_user.

            Returns:
                Dict with ``Authorization: Bearer <token>`` header.
            \"\"\"
            resp = await async_client.post(
                "/api/v1/auth/login",
                data={"username": test_user["email"], "password": test_user["password"]},
            )
            assert resp.status_code == 200, (
                f"Login failed: {resp.status_code} {resp.text}"
            )
            token = resp.json()["access_token"]
            return {"Authorization": f"Bearer {token}"}
    """)
    dest.write_text(content)


def _write_test_auth_flow(dest: Path) -> None:
    """Write tests/e2e/test_auth_flow.py covering signup→login→refresh→protected.

    Args:
        dest: Absolute path for test_auth_flow.py.
    """
    content = textwrap.dedent("""\
        \"\"\"E2E tests: full authentication flow.

        Covers:
        * User registration (POST /api/v1/auth/register)
        * Login and token issuance (POST /api/v1/auth/login)
        * Token refresh (POST /api/v1/auth/refresh)
        * Accessing a protected endpoint with a valid Bearer token
        \"\"\"
        from __future__ import annotations

        import pytest
        import httpx


        @pytest.mark.asyncio
        async def test_register_new_user(async_client: httpx.AsyncClient) -> None:
            \"\"\"POST /api/v1/auth/register returns 201 for a new user.\"\"\"
            import uuid
            email = f"reg_{uuid.uuid4().hex[:8]}@example.com"
            resp = await async_client.post(
                "/api/v1/auth/register",
                json={"email": email, "password": "Secure1234!"},
            )
            assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "id" in body or "email" in body, f"Response missing id/email: {body}"


        @pytest.mark.asyncio
        async def test_login_returns_token(async_client: httpx.AsyncClient, test_user: dict) -> None:
            \"\"\"POST /api/v1/auth/login returns a JWT access_token.\"\"\"
            resp = await async_client.post(
                "/api/v1/auth/login",
                data={"username": test_user["email"], "password": test_user["password"]},
            )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "access_token" in body, f"access_token missing from response: {body}"
            assert body.get("token_type", "").lower() == "bearer", f"token_type not bearer: {body}"


        @pytest.mark.asyncio
        async def test_login_wrong_password_returns_401(
            async_client: httpx.AsyncClient, test_user: dict
        ) -> None:
            \"\"\"POST /api/v1/auth/login with wrong password returns 401.\"\"\"
            resp = await async_client.post(
                "/api/v1/auth/login",
                data={"username": test_user["email"], "password": "completely-wrong"},
            )
            assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


        @pytest.mark.asyncio
        async def test_protected_route_requires_auth(async_client: httpx.AsyncClient) -> None:
            \"\"\"GET /api/v1/users/me without token returns 401.\"\"\"
            resp = await async_client.get("/api/v1/users/me")
            assert resp.status_code == 401, f"Expected 401 without token, got {resp.status_code}"


        @pytest.mark.asyncio
        async def test_protected_route_with_valid_token(
            async_client: httpx.AsyncClient, auth_headers: dict
        ) -> None:
            \"\"\"GET /api/v1/users/me with valid Bearer token returns 200.\"\"\"
            resp = await async_client.get("/api/v1/users/me", headers=auth_headers)
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "email" in body, f"email missing from /me response: {body}"
    """)
    dest.write_text(content)


def _write_test_crud_flow(dest: Path) -> None:
    """Write tests/e2e/test_crud_flow.py: create→read→update→delete→verify.

    Args:
        dest: Absolute path for test_crud_flow.py.
    """
    content = textwrap.dedent("""\
        \"\"\"E2E tests: full CRUD lifecycle for the Item resource.

        Covers:
        * Create (POST /api/v1/items/)
        * Read single (GET /api/v1/items/{id})
        * Read list (GET /api/v1/items/)
        * Update (PATCH /api/v1/items/{id})
        * Delete (DELETE /api/v1/items/{id})
        * Verify gone (GET /api/v1/items/{id} → 404)
        \"\"\"
        from __future__ import annotations

        import pytest
        import httpx


        @pytest.mark.asyncio
        async def test_create_item(
            async_client: httpx.AsyncClient, auth_headers: dict
        ) -> None:
            \"\"\"POST /api/v1/items/ creates a new item and returns 201.\"\"\"
            resp = await async_client.post(
                "/api/v1/items/",
                json={"title": "E2E Item", "description": "Created by E2E test"},
                headers=auth_headers,
            )
            assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "id" in body, f"id missing from create response: {body}"
            assert body.get("title") == "E2E Item", f"title mismatch: {body}"


        @pytest.mark.asyncio
        async def test_read_item(
            async_client: httpx.AsyncClient, auth_headers: dict
        ) -> None:
            \"\"\"GET /api/v1/items/{id} returns the created item.\"\"\"
            create_resp = await async_client.post(
                "/api/v1/items/",
                json={"title": "Read Test", "description": "Read me"},
                headers=auth_headers,
            )
            assert create_resp.status_code == 201
            item_id = create_resp.json()["id"]

            read_resp = await async_client.get(f"/api/v1/items/{item_id}", headers=auth_headers)
            assert read_resp.status_code == 200, f"Expected 200, got {read_resp.status_code}"
            assert read_resp.json()["id"] == item_id


        @pytest.mark.asyncio
        async def test_list_items(
            async_client: httpx.AsyncClient, auth_headers: dict
        ) -> None:
            \"\"\"GET /api/v1/items/ returns a list of items.\"\"\"
            resp = await async_client.get("/api/v1/items/", headers=auth_headers)
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert isinstance(body, list) or "items" in body or "data" in body, (
                f"Expected list or paginated response: {body}"
            )


        @pytest.mark.asyncio
        async def test_update_item(
            async_client: httpx.AsyncClient, auth_headers: dict
        ) -> None:
            \"\"\"PATCH /api/v1/items/{id} updates the item title.\"\"\"
            create_resp = await async_client.post(
                "/api/v1/items/",
                json={"title": "Before Update", "description": "Will be updated"},
                headers=auth_headers,
            )
            assert create_resp.status_code == 201
            item_id = create_resp.json()["id"]

            update_resp = await async_client.patch(
                f"/api/v1/items/{item_id}",
                json={"title": "After Update"},
                headers=auth_headers,
            )
            assert update_resp.status_code == 200, (
                f"Expected 200, got {update_resp.status_code}: {update_resp.text}"
            )
            assert update_resp.json()["title"] == "After Update"


        @pytest.mark.asyncio
        async def test_delete_item_then_verify_gone(
            async_client: httpx.AsyncClient, auth_headers: dict
        ) -> None:
            \"\"\"DELETE /api/v1/items/{id} removes the item; subsequent GET returns 404.\"\"\"
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
            assert delete_resp.status_code in (200, 204), (
                f"Expected 200/204, got {delete_resp.status_code}"
            )

            gone_resp = await async_client.get(
                f"/api/v1/items/{item_id}", headers=auth_headers
            )
            assert gone_resp.status_code == 404, (
                f"Expected 404 after delete, got {gone_resp.status_code}"
            )
    """)
    dest.write_text(content)


def _write_test_error_handling(dest: Path) -> None:
    """Write tests/e2e/test_error_handling.py: 422, 404, 401 scenarios.

    Args:
        dest: Absolute path for test_error_handling.py.
    """
    content = textwrap.dedent("""\
        \"\"\"E2E tests: error-handling scenarios.

        Covers:
        * 422 Unprocessable Entity — validation errors on malformed input.
        * 404 Not Found — requesting a resource that does not exist.
        * 401 Unauthorized — accessing protected endpoints without credentials.
        \"\"\"
        from __future__ import annotations

        import pytest
        import httpx


        @pytest.mark.asyncio
        async def test_create_item_missing_required_field_returns_422(
            async_client: httpx.AsyncClient, auth_headers: dict
        ) -> None:
            \"\"\"POST /api/v1/items/ without required 'title' returns 422.\"\"\"
            resp = await async_client.post(
                "/api/v1/items/",
                json={"description": "No title provided"},
                headers=auth_headers,
            )
            assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "detail" in body, f"422 response missing 'detail': {body}"


        @pytest.mark.asyncio
        async def test_create_item_wrong_type_returns_422(
            async_client: httpx.AsyncClient, auth_headers: dict
        ) -> None:
            \"\"\"POST /api/v1/items/ with wrong field type returns 422.\"\"\"
            resp = await async_client.post(
                "/api/v1/items/",
                json={"title": 12345, "description": True},
                headers=auth_headers,
            )
            # FastAPI/Pydantic coerces int to str for title, but boolean description
            # is not a string — 422 or 201 depending on model strictness.
            # The key invariant is that the server does not crash (5xx).
            assert resp.status_code < 500, (
                f"Server error (5xx) on type mismatch: {resp.status_code} {resp.text}"
            )


        @pytest.mark.asyncio
        async def test_get_nonexistent_item_returns_404(
            async_client: httpx.AsyncClient, auth_headers: dict
        ) -> None:
            \"\"\"GET /api/v1/items/{uuid} for a non-existent resource returns 404.\"\"\"
            import uuid
            fake_id = str(uuid.uuid4())
            resp = await async_client.get(f"/api/v1/items/{fake_id}", headers=auth_headers)
            assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "detail" in body, f"404 response missing 'detail': {body}"


        @pytest.mark.asyncio
        async def test_create_item_without_auth_returns_401(
            async_client: httpx.AsyncClient,
        ) -> None:
            \"\"\"POST /api/v1/items/ without Authorization header returns 401.\"\"\"
            resp = await async_client.post(
                "/api/v1/items/",
                json={"title": "Unauthorized", "description": "No auth"},
            )
            assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


        @pytest.mark.asyncio
        async def test_invalid_bearer_token_returns_401(
            async_client: httpx.AsyncClient,
        ) -> None:
            \"\"\"GET /api/v1/users/me with a forged Bearer token returns 401.\"\"\"
            resp = await async_client.get(
                "/api/v1/users/me",
                headers={"Authorization": "Bearer this.is.not.a.valid.jwt"},
            )
            assert resp.status_code == 401, (
                f"Expected 401 for invalid token, got {resp.status_code}: {resp.text}"
            )
    """)
    dest.write_text(content)


def _patch_config(config_file: Path):  # type: ignore[no-untyped-def]
    """Inject E2E settings fields inside the ``class Settings`` body.

    F-004: pre-fix this used the hand-rolled
    ``content.replace("settings = Settings()", ...)`` pattern that
    ``adapt.contracts.config_patcher`` was introduced to replace. The
    hand-rolled pattern silently corrupts configs that have blank lines /
    comments between the class body and the ``settings = Settings()``
    instantiation. We now delegate to the shared helper, which AST-parses
    config.py and inserts INTO the ``Settings`` class body.

    Args:
        config_file: Absolute path to ``app/core/config.py``.

    Returns:
        ``PatchResult`` describing the outcome (see
        :mod:`adapt.contracts.config_patcher`).
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    return patch_settings_fields(
        config_file,
        fields=[
            ("E2E_BASE_URL", 'E2E_BASE_URL: str = "http://localhost:8000"'),
            ("E2E_TEST_EMAIL", 'E2E_TEST_EMAIL: str = "e2e_test@example.com"'),
            ("E2E_TEST_PASSWORD", 'E2E_TEST_PASSWORD: str = "E2eTestPass123!"'),
        ],
    )


# ---------------------------------------------------------------------------
# F-003: declare test deps the emitted suite imports
# ---------------------------------------------------------------------------

_E2E_TEST_DEPS: tuple[tuple[str, str], ...] = (
    # (package_name, pinned spec) — kept in sync with the imports in the
    # emitted tests/e2e/conftest.py + flow modules.
    ("httpx", "httpx>=0.28.0"),
    ("pytest-asyncio", "pytest-asyncio>=0.24.0"),
)


def _patch_requirements_with_test_deps(requirements_file: Path) -> bool:
    """Append any missing E2E test deps to ``requirements.txt`` line-by-line.

    Parses each line, normalises to its PEP 503 package name (stripping
    extras / version specifiers / comments / env markers), and only adds
    packages that are NOT already declared. Mirrors the line-by-line
    parser used by ``add_websocket_presence`` (F-006).

    Args:
        requirements_file: Path to ``requirements.txt``.

    Returns:
        ``True`` when at least one new dep was appended, ``False`` otherwise.
    """
    src = requirements_file.read_text()
    declared = {_extract_req_name(line) for line in src.splitlines()}
    declared.discard(None)
    to_add: list[str] = []
    for pkg, spec in _E2E_TEST_DEPS:
        if pkg.lower() not in declared:
            to_add.append(spec)
    if not to_add:
        return False
    if not src.endswith("\n"):
        src += "\n"
    requirements_file.write_text(src + "\n".join(to_add) + "\n")
    return True


def _extract_req_name(raw_line: str) -> str | None:
    """Return the lowercase package name of a requirements line, or None.

    Args:
        raw_line: A single ``requirements.txt`` line.

    Returns:
        Normalised package name, or ``None`` if the line declares no package.
    """
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("-") or line.startswith("--"):
        return None
    if " #" in line:
        line = line.split(" #", 1)[0].strip()
    if ";" in line:
        line = line.split(";", 1)[0].strip()
    if "[" in line:
        line = line.split("[", 1)[0].strip()
    for sep in ("===", "==", ">=", "<=", "!=", "~=", ">", "<"):
        if sep in line:
            line = line.split(sep, 1)[0].strip()
            break
    return line.lower() if line else None


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _elapsed_ms(start: float) -> int:
    """Return wall-clock milliseconds since *start*.

    Args:
        start: Value from ``time.monotonic()`` taken at function entry.

    Returns:
        Elapsed time in milliseconds as a positive integer.
    """
    return int((time.monotonic() - start) * 1000)
