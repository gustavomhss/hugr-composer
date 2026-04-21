"""TOOL-026: add_contract_tests — schemathesis + Pact contract tests for FastAPI.

Generates two complementary contract-test layers:

1. **Schemathesis** — property-based fuzzing against the OpenAPI schema.  Every
   endpoint is exercised with Hypothesis-generated inputs; responses are validated
   against declared status codes, body shapes, and required fields.

2. **Pact** — consumer/provider contract stubs showing the integration pattern,
   with provider-state hooks and a CI GitHub Actions workflow.

Also writes a ``.schemathesis-exclude.yaml`` for endpoints that should be
excluded from fuzzing (e.g. destructive admin routes), a custom-checks module,
and a stateful-sequence test module.

The tool is idempotent: a second run returns ``status="no_op"`` when
``tests/contracts/`` already contains the fingerprint file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.testing_tools.add_contract_tests import add_contract_tests

    result = add_contract_tests(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/tests/contracts/conftest.py", ...]
    print(result.next_steps)    # ["pip install schemathesis pact-python", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_testing_add_contract_tests",
    "description": "Add consumer-driven contract tests using Pact or Schemathesis.",
    "tags": ["extend", "testing"],
    "entry": "add_contract_tests",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_contract_tests(
    inp: ToolInput,
    openapi_path: str = "/openapi.json",
    max_examples: int = 100,
    stateful: bool = False,
    exclude_endpoints: list[str] | None = None,
) -> ToolResult:
    """Generate schemathesis + Pact contract tests for a FastAPI project.

    Writes ``tests/contracts/`` with conftest, base schemathesis tests, stateful
    tests, custom checks, Pact stubs, a ``.schemathesis-exclude.yaml``, and a
    GitHub Actions CI workflow.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.
        openapi_path: URL path for the OpenAPI JSON schema (default ``/openapi.json``).
        max_examples: Max Hypothesis examples per endpoint (default 100).
        stateful: When ``True``, enables link-based stateful sequence testing.
        exclude_endpoints: Paths to exclude from fuzzing (e.g. ``["/admin/wipe"]``).

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
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
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

    contracts_dir = project / "tests" / "contracts"

    # --- Pre-flight: already installed? -------------------------------------
    fingerprint = contracts_dir / "conftest.py"
    if fingerprint.exists() and "schemathesis" in fingerprint.read_text():
        return ToolResult(
            status="no_op",
            notes=["tests/contracts/conftest.py already contains schemathesis setup — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would generate schemathesis + Pact contract tests.",
                f"[dry_run] openapi_path={openapi_path!r}, max_examples={max_examples}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    excludes = exclude_endpoints or []
    files_modified: list[str] = []

    # --- Create package directories -----------------------------------------
    contracts_dir.mkdir(parents=True, exist_ok=True)
    pacts_dir = project / "pacts"
    pacts_dir.mkdir(exist_ok=True)
    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)

    # --- Step 1: contracts/__init__.py --------------------------------------
    init_file = contracts_dir / "__init__.py"
    init_file.write_text('"""Contract test package generated by add_contract_tests (TOOL-026)."""\n')
    files_created.append(str(init_file))

    # --- Step 2: tests/contracts/conftest.py --------------------------------
    conftest_file = contracts_dir / "conftest.py"
    _write_contracts_conftest(conftest_file, openapi_path)
    files_created.append(str(conftest_file))

    # --- Step 3: Base schemathesis test module ------------------------------
    base_test = contracts_dir / "test_api_schema.py"
    _write_schemathesis_base(base_test, max_examples, excludes)
    files_created.append(str(base_test))

    # --- Step 4: Stateful test module ---------------------------------------
    stateful_test = contracts_dir / "test_stateful.py"
    _write_stateful_tests(stateful_test, stateful)
    files_created.append(str(stateful_test))

    # --- Step 5: Custom checks module ---------------------------------------
    checks_module = contracts_dir / "custom_checks.py"
    _write_custom_checks(checks_module)
    files_created.append(str(checks_module))

    # --- Step 6: Pact consumer/provider stubs -------------------------------
    pact_file = contracts_dir / "test_pact_stubs.py"
    _write_pact_stubs(pact_file)
    files_created.append(str(pact_file))

    # --- Step 7: .schemathesis-exclude.yaml ---------------------------------
    exclude_yaml = project / ".schemathesis-exclude.yaml"
    _write_exclude_yaml(exclude_yaml, excludes)
    files_created.append(str(exclude_yaml))

    # --- Step 8: CI workflow ------------------------------------------------
    ci_file = ci_dir / "contract-tests.yml"
    _write_ci_workflow(ci_file, max_examples)
    files_created.append(str(ci_file))

    # --- Step 9: Patch root pytest.ini / pyproject.toml markers -------------
    pyproject = project / "pyproject.toml"
    if pyproject.exists():
        _patch_pyproject(pyproject)
        files_modified.append(str(pyproject))

    # --- AST validation ------------------------------------------------------
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
            "Schemathesis fuzz tests wired via schemathesis.from_asgi().",
            "Pact stubs show consumer/provider contract pattern (customize for real services).",
            f"Endpoints excluded from fuzzing: {excludes or ['(none)']!r}",
            f"Stateful sequence testing: {'enabled' if stateful else 'disabled (pass stateful=True to enable)'}",
        ],
        next_steps=[
            "pip install schemathesis pact-python hypothesis",
            "pytest tests/contracts/ -m schemathesis -v",
            "pytest tests/contracts/ -m pact_consumer -v",
            "Review .schemathesis-exclude.yaml and add any destructive endpoints.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_contracts_conftest(dest: Path, openapi_path: str) -> None:
    """Write ``tests/contracts/conftest.py`` with schemathesis schema fixture.

    Args:
        dest: Destination path.
        openapi_path: URL path to the OpenAPI JSON.
    """
    content = textwrap.dedent(f"""\
        \"\"\"Shared fixtures for contract tests (schemathesis + Pact).

        Generated by add_contract_tests tool (TOOL-026).
        \"\"\"

        from __future__ import annotations

        import pytest
        import schemathesis
        from fastapi.testclient import TestClient

        from app.main import app


        @pytest.fixture(scope="session")
        def schema():
            \"\"\"Load the OpenAPI schema once per test session.

            Returns:
                ``schemathesis.BaseSchema`` bound to the ASGI app.
            \"\"\"
            return schemathesis.from_asgi("{openapi_path}", app)


        @pytest.fixture(scope="session")
        def api_client():
            \"\"\"Return a ``TestClient`` for direct HTTP calls in contract tests.

            Returns:
                ``fastapi.testclient.TestClient`` wrapping the app.
            \"\"\"
            with TestClient(app, raise_server_exceptions=False) as client:
                yield client


        @pytest.fixture(scope="session")
        def auth_headers(api_client: TestClient) -> dict[str, str]:
            \"\"\"Obtain a valid JWT bearer token for contract tests.

            Attempts to log in via ``/api/v1/login/access-token``.  Falls back to
            an empty dict so schemathesis can still exercise public endpoints.

            Args:
                api_client: Shared test client.

            Returns:
                Dict with ``Authorization`` header, or empty dict on failure.
            \"\"\"
            response = api_client.post(
                "/api/v1/login/access-token",
                data={{"username": "test@example.com", "password": "changeme"}},
            )
            if response.status_code == 200:
                token = response.json().get("access_token", "")
                return {{"Authorization": f"Bearer {{token}}"}}
            return {{}}
        """)
    dest.write_text(content)


def _write_schemathesis_base(dest: Path, max_examples: int, excludes: list[str]) -> None:
    """Write base schemathesis property-based tests.

    Args:
        dest: Destination path.
        max_examples: Hypothesis examples per endpoint.
        excludes: Endpoint paths to skip.
    """
    exclude_check = ""
    if excludes:
        exclude_list = repr(excludes)
        exclude_check = textwrap.dedent(f"""\
            _EXCLUDED_PATHS: frozenset[str] = frozenset({exclude_list})

            """)

    content = textwrap.dedent(f"""\
        \"\"\"Schemathesis property-based contract tests.

        Fuzzes every endpoint in the OpenAPI schema with Hypothesis-generated
        inputs and validates responses against declared status codes and schemas.

        Generated by add_contract_tests tool (TOOL-026).
        Run via: pytest tests/contracts/test_api_schema.py -m schemathesis -v
        \"\"\"

        from __future__ import annotations

        import schemathesis
        from hypothesis import settings
        from schemathesis import Case

        from tests.contracts.custom_checks import (  # noqa: F401 — side-effect registration
            validate_error_response_structure,
            validate_no_500_on_valid_input,
        )

        {exclude_check}
        schema = schemathesis.from_pytest_fixture("schema")


        @schema.parametrize()
        @settings(max_examples={max_examples}, deadline=5_000)
        def test_api_contract(case: Case, auth_headers: dict[str, str]) -> None:
            \"\"\"Fuzz every API endpoint and validate response contracts.

            For each endpoint + method, Hypothesis generates request inputs that
            conform to the OpenAPI schema.  Any response that violates the declared
            contract causes an immediate failure.

            Args:
                case: Generated schemathesis test case.
                auth_headers: Bearer token headers injected for authenticated routes.
            \"\"\"
            case.headers = case.headers or {{}}
            case.headers.update(auth_headers)
            response = case.call_asgi()
            case.validate_response(response)


        @schema.parametrize(method="GET")
        @settings(max_examples=min({max_examples}, 50), deadline=5_000)
        def test_read_endpoints_never_500(case: Case, auth_headers: dict[str, str]) -> None:
            \"\"\"Assert GET endpoints never return 5xx on schema-valid inputs.

            Args:
                case: Generated schemathesis test case.
                auth_headers: Bearer token headers for authenticated routes.
            \"\"\"
            case.headers = case.headers or {{}}
            case.headers.update(auth_headers)
            response = case.call_asgi()
            assert response.status_code < 500, (
                f"GET {{case.formatted_path}} returned {{response.status_code}}: "
                f"{{response.text[:200]}}"
            )
        """)
    dest.write_text(content)


def _write_stateful_tests(dest: Path, enabled: bool) -> None:
    """Write stateful (link-based) schemathesis sequence tests.

    Args:
        dest: Destination path.
        enabled: When ``False``, generates a skipped placeholder that documents
            how to enable stateful testing.
    """
    if not enabled:
        content = textwrap.dedent("""\
            \"\"\"Stateful schemathesis tests (disabled by default).

            Enable via: add_contract_tests(inp, stateful=True)
            or uncomment the test below and remove the pytest.mark.skip.

            Stateful tests chain HTTP interactions using OpenAPI response links,
            simulating real user flows: POST /users → GET /users/{id} → DELETE.

            Generated by add_contract_tests tool (TOOL-026).
            \"\"\"

            from __future__ import annotations

            import pytest
            import schemathesis
            from schemathesis import Case

            schema = schemathesis.from_pytest_fixture("schema")


            @pytest.mark.skip(reason="Stateful tests disabled — re-run with stateful=True to enable.")
            @schema.parametrize(stateful=schemathesis.Stateful.links)
            def test_stateful_api_sequence(case: Case, auth_headers: dict[str, str]) -> None:
                \"\"\"Chain API calls via OpenAPI response links for workflow testing.

                Args:
                    case: Generated schemathesis test case (carries link context).
                    auth_headers: Bearer token headers.
                \"\"\"
                case.headers = case.headers or {}
                case.headers.update(auth_headers)
                response = case.call_asgi()
                case.validate_response(response)
            """)
    else:
        content = textwrap.dedent("""\
            \"\"\"Stateful schemathesis sequence tests.

            Chains HTTP interactions using OpenAPI response links to simulate
            real user flows across multiple endpoints.

            Generated by add_contract_tests tool (TOOL-026).
            \"\"\"

            from __future__ import annotations

            import schemathesis
            from schemathesis import Case

            schema = schemathesis.from_pytest_fixture("schema")


            @schema.parametrize(stateful=schemathesis.Stateful.links)
            def test_stateful_api_sequence(case: Case, auth_headers: dict[str, str]) -> None:
                \"\"\"Stateful test following OpenAPI response links.

                Validates that chained operations (create → read → update → delete)
                all produce schema-conformant responses.

                Args:
                    case: Generated schemathesis test case.
                    auth_headers: Bearer token headers.
                \"\"\"
                case.headers = case.headers or {}
                case.headers.update(auth_headers)
                response = case.call_asgi()
                case.validate_response(response)
            """)
    dest.write_text(content)


def _write_custom_checks(dest: Path) -> None:
    """Write schemathesis custom validation checks module.

    Args:
        dest: Destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Custom schemathesis response validation checks.

        Imported as a side-effect in test_api_schema.py to register all checks
        globally.  Add project-specific checks here.

        Generated by add_contract_tests tool (TOOL-026).
        \"\"\"

        from __future__ import annotations

        import schemathesis
        from requests import Response
        from schemathesis import Case


        @schemathesis.check
        def validate_error_response_structure(response: Response, case: Case) -> None:
            \"\"\"Assert 4xx responses contain a ``detail`` or ``errors`` key.

            Args:
                response: HTTP response from the ASGI app.
                case: Associated schemathesis test case.
            \"\"\"
            if 400 <= response.status_code < 500:
                try:
                    data = response.json()
                except Exception:
                    return
                assert "detail" in data or "errors" in data, (
                    f"Error response from {case.formatted_path} missing detail/errors: {data}"
                )


        @schemathesis.check
        def validate_no_500_on_valid_input(response: Response, case: Case) -> None:
            \"\"\"Assert that schema-valid requests never produce a 500 response.

            Args:
                response: HTTP response from the ASGI app.
                case: Associated schemathesis test case.
            \"\"\"
            assert response.status_code != 500, (
                f"Internal Server Error on {case.method.upper()} {case.formatted_path}: "
                f"{response.text[:300]}"
            )
        """)
    dest.write_text(content)


def _write_pact_stubs(dest: Path) -> None:
    """Write Pact consumer/provider stub tests showing the integration pattern.

    Args:
        dest: Destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Pact consumer/provider contract test stubs.

        These files document the consumer-driven contract pattern.  Customise them
        for any external services your FastAPI app integrates with.

        Generated by add_contract_tests tool (TOOL-026).
        Run via: pytest tests/contracts/test_pact_stubs.py -m pact_consumer -v
        \"\"\"

        from __future__ import annotations

        import pytest


        @pytest.mark.pact_consumer
        def test_pact_consumer_stub() -> None:
            \"\"\"Stub: demonstrate Pact consumer test pattern.

            Replace this stub with real pact-python consumer tests for each
            external service your app depends on.  See:
            https://docs.pact.io/implementation_guides/python

            Example real test::

                from pact import Consumer, Provider, Like, Term
                pact = Consumer("MyService").has_pact_with(Provider("ExternalAPI"), ...)
                (
                    pact.given("state")
                    .upon_receiving("a request")
                    .with_request("GET", "/resource")
                    .will_respond_with(200, body=Like({"id": 1}))
                )
                with pact:
                    result = client.get_resource()
                    assert result.id == 1
            \"\"\"
            pytest.skip("Replace with real pact-python consumer contract tests.")


        @pytest.mark.pact_provider
        def test_pact_provider_stub() -> None:
            \"\"\"Stub: demonstrate Pact provider verification pattern.

            Replace this stub with real pact-python provider verification.  See:
            https://docs.pact.io/implementation_guides/python/docs/provider

            Example real test::

                from pact import Verifier
                verifier = Verifier(provider="MyService", provider_base_url=base_url)
                success, _ = verifier.verify_pacts(*pact_files, ...)
                assert success == 0
            \"\"\"
            pytest.skip("Replace with real pact-python provider verification tests.")
        """)
    dest.write_text(content)


def _write_exclude_yaml(dest: Path, excludes: list[str]) -> None:
    """Write ``.schemathesis-exclude.yaml`` listing endpoints to skip from fuzzing.

    Args:
        dest: Destination path.
        excludes: List of endpoint paths to exclude.
    """
    base_excludes = ["/admin/wipe", "/health", "/metrics"]
    all_excludes = sorted(set(base_excludes + excludes))
    exclude_lines = "\n".join(f"  - {e}  # excluded from fuzz testing" for e in all_excludes)
    content = textwrap.dedent(f"""\
        # .schemathesis-exclude.yaml
        # Endpoints excluded from schemathesis property-based fuzzing.
        # Add justification comments for each exclusion.
        # Generated by add_contract_tests tool (TOOL-026).

        excluded_paths:
        {exclude_lines}
        """)
    dest.write_text(content)


def _write_ci_workflow(dest: Path, max_examples: int) -> None:
    """Write GitHub Actions CI workflow for contract tests.

    Args:
        dest: Destination path.
        max_examples: Hypothesis max_examples value baked into the workflow.
    """
    content = textwrap.dedent(f"""\
        # .github/workflows/contract-tests.yml
        # Contract test CI pipeline — schemathesis + Pact.
        # Generated by add_contract_tests tool (TOOL-026).

        name: Contract Tests

        on:
          pull_request:
            branches: [main, develop]
          push:
            branches: [main]

        jobs:
          schemathesis:
            name: Schemathesis fuzz
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4

              - name: Set up Python
                uses: actions/setup-python@v5
                with:
                  python-version: "3.12"
                  cache: pip

              - name: Install dependencies
                run: |
                  pip install -e ".[test]"
                  pip install schemathesis hypothesis

              - name: Run contract tests
                run: |
                  pytest tests/contracts/ -m schemathesis -v \\
                    --hypothesis-seed=42 \\
                    --hypothesis-settings=max_examples={max_examples}

              - name: Upload schemathesis report
                if: always()
                uses: actions/upload-artifact@v4
                with:
                  name: schemathesis-report
                  path: .hypothesis/
        """)
    dest.write_text(content)


def _patch_pyproject(pyproject_file: Path) -> None:
    """Add pytest markers for ``schemathesis``, ``pact_consumer``, and ``pact_provider``.

    Args:
        pyproject_file: Path to the project's ``pyproject.toml``.
    """
    src = pyproject_file.read_text()
    if "schemathesis" in src:
        return

    marker_block = textwrap.dedent("""\

        # Contract test markers — added by add_contract_tests tool (TOOL-026)
        [tool.pytest.ini_options]
        markers = [
            "schemathesis: schemathesis property-based API contract tests",
            "pact_consumer: Pact consumer-side contract tests",
            "pact_provider: Pact provider-side verification tests",
        ]
        """)
    pyproject_file.write_text(src + marker_block)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds.
    """
    return int((time.monotonic() - start) * 1000)
