---
spec_id: "TOOL-026"
tool_name: "add_contract_tests"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-CT-01"
  - "INV-CT-02"
  - "INV-CT-03"
  - "INV-CT-04"
  - "INV-CT-05"
  - "INV-CT-06"
  - "INV-CT-07"
  - "INV-CT-08"
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
  - "CC-21"
  - "CC-22"
  - "CC-23"
  - "CC-24"
  - "CC-25"
  - "CC-26"
  - "CC-27"
  - "CC-28"
  - "CC-29"
  - "CC-30"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
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
  - "T-21"
  - "T-22"
  - "T-23"
  - "T-24"
  - "T-25"
  - "T-26"
  - "T-27"
  - "T-28"
  - "T-29"
  - "T-30"
tags:
  - "performance"
  - "payments"
  - "data"
  - "resiliency"
  - "realtime"
---
# TOOL-026: add_contract_tests

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_contract_tests` |
| Category | EXTEND > Testing |
| Complexity | High |
| Dependencies | FastAPI, OpenAPI, pytest, schemathesis |
| Signature | `add_contract_tests(project_dir: str, openapi_path: str = "/openapi.json", max_examples: int = 100, stateful: bool = False, exclude_endpoints: list[str] | None = None) -> dict` |
| Parameters | `project_dir`: Absolute path to project root (e.g. `/code/myapi`)<br>`openapi_path`: OpenAPI spec URL path (default: `/openapi.json`)<br>`max_examples`: Maximum test cases per endpoint (default: 100)<br>`stateful`: Enable state machine testing (default: False)<br>`exclude_endpoints`: Paths to skip (e.g. `["/admin/wipe"]`) |

## 2. Purpose

The `fastapi_add_contract_tests` tool generates two complementary layers of contract coverage: (1) **schemathesis**-powered property-based tests that fuzz every endpoint declared in the OpenAPI schema with hundreds of Hypothesis-generated requests per route, asserting that every response matches the declared status code, body shape, required fields, and header contracts; and (2) **Pact**-based consumer-driven contracts for every external service boundary — both when the FastAPI app is a consumer of someone else's API (we generate pact files as a consumer) and when it is a provider (we verify incoming consumer pacts against the live app). Together these catch the classes of bugs that unit tests systematically miss: undocumented optional fields that sneak into responses, status codes that drift from what the spec says, serializer outputs that look right to humans but break strict JSON schema validators, and the single most painful failure mode in microservices — a producer and consumer both passing their own tests while emitting incompatible message shapes.

The generator wires schemathesis into the existing pytest run via `schemathesis.from_pytest_fixture()`, adds stateful sequence testing (so it can validate `POST /orders` → `GET /orders/{id}` → `PATCH /orders/{id}` → `DELETE /orders/{id}` as a real workflow rather than isolated hits), and reproducible Hypothesis seeds that are printed on failure so CI flakes can be reproduced locally with a single command. For Pact, the generator creates consumer test fixtures (with `pact-python`) and a provider verifier that spins up the FastAPI `TestClient`, installs per-state DB fixtures via a `/_pact/provider_states` hook, and runs every interaction in the `pacts/` directory against it. Key design decisions: **explicit endpoint exclusions** for destructive operations (`/admin/wipe`, `/users/{id}/delete`) listed in a `.schemathesis-exclude.yaml` with justification comments; **strict-by-default** status code and response-schema conformance checks (any mismatch is a test failure, not a warning); **bounded execution time** (`max_examples=100` per endpoint with a `--hypothesis-deadline=5000` ms cap) so contract tests stay fast enough to run on every PR; and **CI integration** via GitHub Actions that uploads the Pact broker and publishes schemathesis HTML reports as artifacts so reviewers can see exactly which inputs broke.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 3s | Must not slow down CI pipeline setup |
| Files modified | ≤ 3 | Only touches pytest config and CI files |
| Files created | ≥ 5 | Generates test files, configs, and CI integration |
| Single endpoint test time | < 5s | For max_examples=100 cases |
| Full test suite time | < 60s | For 50 endpoints at max_examples=100 |
| Stateful test runtime | < 5 min | For typical API with 20 stateful endpoints |
| Memory overhead | < 50MB | From schemathesis hypothesis generation |
| Migration runtime | 0s | No database changes required |
| Test reproducibility | 100% | Via printed Hypothesis seeds on failure |

---

## 4. Code Examples (Before / After)

### 4.1 Consumer-side Pact contract test
```python
# tests/contracts/test_orders_consumer.py
"""Consumer-side Pact test — our FastAPI service consumes the Payments API.
Generated by fastapi_add_contract_tests. Run via: pytest tests/contracts/ -m pact_consumer
"""
import pytest
from pact import Consumer, Like, Provider, Term

from app.clients.payments import PaymentsClient, ChargeResult


@pytest.fixture(scope="session")
def pact():
    consumer = Consumer("OrdersService", version="1.0.0")
    pact = consumer.has_pact_with(
        Provider("PaymentsService"),
        host_name="127.0.0.1",
        port=1234,
        pact_dir="./pacts",
        log_dir="./logs",
        version="3.0.0",
    )
    pact.start_service()
    yield pact
    pact.stop_service()


@pytest.mark.pact_consumer
def test_charge_success_contract(pact):
    expected_response = {
        "charge_id": Term(r"^ch_[A-Za-z0-9]+$", "ch_abc123"),
        "amount_cents": Like(1999),
        "currency": "usd",
        "status": "succeeded",
        "created_at": Term(r"^\d{4}-\d{2}-\d{2}T", "2026-04-12T10:00:00Z"),
    }
    (
        pact.given("a valid payment method exists")
        .upon_receiving("a request to charge 1999 cents")
        .with_request(
            "POST",
            "/v1/charges",
            body={"amount_cents": 1999, "currency": "usd", "pm_id": "pm_123"},
            headers={"Content-Type": "application/json"},
        )
        .will_respond_with(200, body=expected_response)
    )
    with pact:
        client = PaymentsClient(base_url="http://127.0.0.1:1234")
        result = client.charge(amount_cents=1999, currency="usd", pm_id="pm_123")
        assert isinstance(result, ChargeResult)
        assert result.status == "succeeded"
        assert result.charge_id.startswith("ch_")
```

### 4.2 Provider-side Pact verification
```python
# tests/contracts/test_payments_provider.py
"""Provider-side Pact verification — our FastAPI service acts as the provider.
Verifies every interaction in pacts/*.json against the live app under test.
Run via: pytest tests/contracts/ -m pact_provider
"""
import os
import pytest
from pact import Verifier
from fastapi.testclient import TestClient

from app.main import app
from app.db import get_session, reset_test_database
from app.models import PaymentMethod


@pytest.fixture(scope="module")
def provider_base_url():
    client = TestClient(app)
    base_url = "http://testserver"
    yield base_url
    client.close()


@pytest.fixture(autouse=True)
def _clean_state():
    reset_test_database()
    yield
    reset_test_database()


def _provider_state(state_name: str) -> None:
    """Install DB fixtures for a Pact `given(...)` state."""
    session = next(get_session())
    if state_name == "a valid payment method exists":
        session.add(PaymentMethod(id="pm_123", brand="visa", last4="4242", valid=True))
    elif state_name == "no payment method exists":
        pass
    else:
        raise AssertionError(f"Unknown provider state: {state_name!r}")
    session.commit()


@pytest.mark.pact_provider
def test_verify_consumer_contracts(provider_base_url):
    verifier = Verifier(provider="PaymentsService", provider_base_url=provider_base_url)
    pact_files = [
        os.path.join("pacts", f)
        for f in os.listdir("pacts")
        if f.endswith(".json")
    ]
    success, logs = verifier.verify_pacts(
        *pact_files,
        provider_states_setup_url=f"{provider_base_url}/_pact/provider_states",
        verbose=True,
    )
    assert success == 0, f"Pact verification failed:\n{logs}"
```

### 4.3 Schemathesis conftest (NEW)
```python
# tests/contracts/conftest.py
import pytest
import schemathesis
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import SessionLocal
from app.models.user import User
from app.models.tenant import Tenant
import uuid
from datetime import datetime, timezone


@pytest.fixture(scope="session")
def schema():
    """Load OpenAPI schema once per test session."""
    return schemathesis.from_asgi("/openapi.json", app)


@pytest.fixture(scope="session")
def contract_test_tenant():
    """Create a dedicated tenant for contract tests."""
    tenant = Tenant(
        id=uuid.uuid4(),
        slug="contract-test-tenant",
        name="Contract Test Tenant",
        status="active",
        created_at=datetime.now(timezone.utc)
    )
    with SessionLocal() as session:
        session.add(tenant)
        session.commit()
        session.refresh(tenant)
    yield tenant
    with SessionLocal() as session:
        session.delete(session.merge(tenant))
        session.commit()


@pytest.fixture(scope="session")
def contract_test_user(contract_test_tenant):
    """Create a dedicated user for contract tests."""
    user = User(
        id=uuid.uuid4(),
        email="contract-test@example.com",
        password_hash="$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
        is_active=True,
        tenant_id=contract_test_tenant.id,
        created_at=datetime.now(timezone.utc)
    )
    with SessionLocal() as session:
        session.add(user)
        session.commit()
        session.refresh(user)
    yield user
    with SessionLocal() as session:
        session.delete(session.merge(user))
        session.commit()


@pytest.fixture
def authenticated_client(contract_test_user):
    """Test client with authentication headers for contract tests."""
    client = TestClient(app)
    # Get JWT token for the test user
    response = client.post(
        "/api/v1/auth/login",
        json={"email": contract_test_user.email, "password": "secret"}
    )
    token = response.json()["access_token"]
    client.headers.update({
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": "contract-test-tenant"
    })
    return client
```

### 4.4 Base contract test module (NEW)
```python
# tests/contracts/test_contract_base.py
import schemathesis
from schemathesis import Case
from .conftest import schema, authenticated_client
from typing import Any

# Apply custom checks and filters
schema = schemathesis.from_pytest_fixture("schema")


@schema.parametrize()
def test_api_contract(case: Case, authenticated_client):
    """
    Base contract test for all endpoints.
    Validates response status codes and body schemas.
    """
    response = case.call_and_validate(session=authenticated_client)
    
    # Additional project-specific assertions
    if response.status_code >= 500:
        # Server errors should be documented in schema
        raise AssertionError(
            f"Undocumented server error {response.status_code}: {response.text}"
        )
    
    # Ensure error responses have consistent format
    if 400 <= response.status_code < 500:
        data = response.json()
        assert "detail" in data or "errors" in data, \
            f"Error response missing detail/errors: {data}"


@schema.parametrize(method="POST", path="/api/v1/users")
def test_user_creation_contract(case: Case, authenticated_client):
    """
    Specialized contract test for user creation endpoint.
    """
    response = case.call_and_validate(session=authenticated_client)
    
    # Validate specific behaviors for user creation
    if response.status_code == 201:
        data = response.json()
        assert "id" in data, "Created user missing ID"
        assert "email" in data, "Created user missing email"
        assert "created_at" in data, "Created user missing timestamp"
    elif response.status_code == 400:
        data = response.json()
        assert "detail" in data, "Validation error missing detail"


@schema.parametrize(method="DELETE")
def test_destructive_endpoints(case: Case, authenticated_client):
    """
    Contract tests for DELETE endpoints with special handling.
    """
    # Skip if endpoint is in exclude list
    if case.endpoint.path in ["/api/v1/admin/wipe", "/api/v1/data/purge"]:
        pytest.skip("Endpoint excluded from contract tests")
    
    response = case.call_and_validate(session=authenticated_client)
    
    # DELETE endpoints should return 204, 404, or 403
    assert response.status_code in (204, 404, 403, 400), \
        f"Unexpected status for DELETE: {response.status_code}"
```

### 4.5 Stateful contract test module (NEW)
```python
# tests/contracts/test_stateful.py
import schemathesis
from schemathesis import Case
from .conftest import schema, authenticated_client
from typing import Any, Dict
import pytest

stateful_schema = schemathesis.from_pytest_fixture("schema")


@stateful_schema.parametrize(stateful=schemathesis.Stateful.links)
def test_user_lifecycle_stateful(case: Case, authenticated_client):
    """
    Stateful test that chains user creation, retrieval, update, and deletion.
    """
    response = case.call_and_validate(session=authenticated_client)
    
    # Store created resource IDs for chaining
    if (case.endpoint.path == "/api/v1/users" and 
        case.method == "POST" and 
        response.status_code == 201):
        user_data = response.json()
        case.store["created_user_id"] = user_data["id"]
    
    # Verify chained operations
    if (case.endpoint.path == "/api/v1/users/{user_id}" and 
        case.method == "GET" and
        "created_user_id" in case.store):
        assert response.status_code == 200, "Failed to retrieve created user"
        retrieved_user = response.json()
        assert retrieved_user["id"] == case.store["created_user_id"]


@stateful_schema.parametrize(stateful=schemathesis.Stateful.links)
def test_order_workflow_stateful(case: Case, authenticated_client):
    """
    Stateful test for order workflow: create cart → add items → checkout → view.
    """
    response = case.call_and_validate(session=authenticated_client)
    
    # Track cart creation
    if (case.endpoint.path == "/api/v1/carts" and 
        case.method == "POST" and 
        response.status_code == 201):
        cart_data = response.json()
        case.store["cart_id"] = cart_data["id"]
    
    # Chain cart operations
    if (case.endpoint.path == "/api/v1/carts/{cart_id}/items" and
        case.method == "POST" and
        "cart_id" in case.store):
        assert response.status_code in (200, 201), "Failed to add item to cart"
    
    # Prevent infinite loops
    if "iteration_count" not in case.store:
        case.store["iteration_count"] = 0
    case.store["iteration_count"] += 1
    assert case.store["iteration_count"] <= 10, "Stateful test stuck in loop"
```

### 4.6 Custom validation checks (NEW)
```python
# tests/contracts/custom_checks.py
from typing import Any
from fastapi.testclient import TestResponse
from schemathesis.models import Case
import schemathesis


@schemathesis.check
def validate_correlation_id(response: TestResponse, case: Case) -> None:
    """Ensure all responses include X-Correlation-ID header."""
    assert "X-Correlation-ID" in response.headers, \
        f"Missing X-Correlation-ID header in {case.endpoint.path} response"


@schemathesis.check
def validate_pagination_format(response: TestResponse, case: Case) -> None:
    """Validate paginated responses follow standard format."""
    if (case.endpoint.path.endswith("/list") or 
        "page" in case.query or 
        "limit" in case.query):
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict):
                assert "items" in data, "Paginated response missing 'items' key"
                assert "total" in data, "Paginated response missing 'total' key"
                assert "page" in data, "Paginated response missing 'page' key"
                assert "limit" in data, "Paginated response missing 'limit' key"


@schemathesis.check
def validate_error_response_structure(response: TestResponse, case: Case) -> None:
    """Ensure error responses have consistent structure."""
    if 400 <= response.status_code < 500:
        data = response.json()
        
        # FastAPI validation errors
        if "detail" in data and isinstance(data["detail"], list):
            for error in data["detail"]:
                assert "loc" in error, "Validation error missing location"
                assert "msg" in error, "Validation error missing message"
                assert "type" in error, "Validation error missing type"
        
        # Custom error format
        elif "error" in data:
            assert "code" in data, "Error response missing code"
            assert "message" in data, "Error response missing message"


@schemathesis.check  
def validate_timestamps(response: TestResponse, case: Case) -> None:
    """Ensure timestamps are ISO 8601 format in responses."""
    if response.status_code < 400:
        data = response.json()
        
        def check_timestamps(obj: Any) -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if "timestamp" in key.lower() or "at" in key.lower():
                        if isinstance(value, str):
                            # Basic ISO 8601 check
                            assert "T" in value or " " in value, \
                                f"Timestamp {key}={value} not ISO format"
                    elif isinstance(value, (dict, list)):
                        check_timestamps(value)
            elif isinstance(obj, list):
                for item in obj:
                    check_timestamps(item)
        
        check_timestamps(data)
```

### 4.7 Endpoint exclusion configuration (NEW)
```python
# tests/contracts/endpoint_exclusions.py
"""
Configuration for endpoints excluded from contract tests.
Matches the exclude_endpoints parameter of the tool.
"""

EXCLUDED_ENDPOINTS = {
    # Destructive operations
    "/api/v1/admin/wipe",
    "/api/v1/admin/reset",
    "/api/v1/data/purge",
    
    # Long-running operations
    "/api/v1/reports/generate/annual",
    "/api/v1/backup/full",
    
    # External dependencies
    "/api/v1/payments/webhook",  # Requires external service
    "/api/v1/email/send/bulk",   # Sends real emails
    
    # Known schema issues (temporary)
    "/api/v1/legacy/endpoint",   # Being refactored
}

EXCLUDED_ENDPOINT_PATTERNS = [
    # Regex patterns for endpoint exclusion
    r"^/api/v1/debug/.*",      # All debug endpoints
    r"^/internal/.*",          # All internal endpoints
    r".*/\{id\}/audit$",       # All audit endpoints
]

def should_exclude_endpoint(endpoint_path: str, endpoint_method: str) -> bool:
    """Determine if an endpoint should be excluded from contract tests."""
    # Exact path match
    if endpoint_path in EXCLUDED_ENDPOINTS:
        return True
    
    # Pattern match
    import re
    for pattern in EXCLUDED_ENDPOINT_PATTERNS:
        if re.match(pattern, endpoint_path):
            return True
    
    # Method-specific exclusions
    if endpoint_method == "DELETE" and "/bulk" in endpoint_path:
        return True
    
    return False


def get_excluded_endpoints_report() -> dict:
    """Generate report of excluded endpoints for CI output."""
    return {
        "excluded_endpoints": list(EXCLUDED_ENDPOINTS),
        "excluded_patterns": EXCLUDED_ENDPOINT_PATTERNS,
        "total_excluded": len(EXCLUDED_ENDPOINTS) + len(EXCLUDED_ENDPOINT_PATTERNS)
    }
```

### 4.8 Hypothesis configuration module (NEW)
```python
# tests/contracts/hypothesis_config.py
from hypothesis import settings, HealthCheck, Verbosity
import schemathesis


# Global hypothesis settings for contract tests
DEFAULT_HYPOTHESIS_SETTINGS = settings(
    max_examples=100,
    deadline=5000,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.filter_too_much,
        HealthCheck.data_too_large
    ],
    verbosity=Verbosity.normal,
    print_blob=True
)


# Per-endpoint overrides
ENDPOINT_SETTINGS_OVERRIDES = {
    ("/api/v1/complex/calculation", "POST"): settings(
        max_examples=20,
        deadline=10000
    ),
    ("/api/v1/search", "GET"): settings(
        max_examples=50,
        deadline=3000
    ),
    ("/api/v1/upload", "POST"): settings(
        max_examples=30,
        deadline=8000
    ),
}


def get_hypothesis_settings_for_endpoint(endpoint_path: str, endpoint_method: str):
    """Get appropriate hypothesis settings for a specific endpoint."""
    key = (endpoint_path, endpoint_method.upper())
    return ENDPOINT_SETTINGS_OVERRIDES.get(key, DEFAULT_HYPOTHESIS_SETTINGS)


@schemathesis.hooks.register
def add_hypothesis_settings(context, strategy):
    """Schemathesis hook to apply custom hypothesis settings."""
    endpoint = context.endpoint
    custom_settings = get_hypothesis_settings_for_endpoint(
        endpoint.path,
        endpoint.method
    )
    return strategy.map(lambda x: x).with_settings(custom_settings)


def reproduce_failure(seed: int, example: bytes) -> dict:
    """
    Reproduce a failing test case using hypothesis seed.
    Used in CI when contract tests fail.
    """
    return {
        "hypothesis_seed": seed,
        "reproduce_command": f"pytest --hypothesis-seed={seed}",
        "example_data": example.hex() if example else None,
        "note": "Add this seed to reproduce the failure locally"
    }
```

### 4.9 Migration for contract test data
```python
# alembic/versions/2026_04_08_0015_add_contract_test_fixtures.py
"""Add contract test fixtures

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-08 10:30:00
"""
from alembic import op
import sqlalchemy as sa
import uuid
from datetime import datetime, timezone

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create contract test tenant
    op.execute(
        sa.text("""
            INSERT INTO tenants (id, slug, name, status, created_at)
            VALUES (
                :tenant_id,
                'contract-test-tenant',
                'Contract Test Tenant',
                'active',
                :now
            )
            ON CONFLICT (slug) DO NOTHING
        """),
        {
            "tenant_id": uuid.uuid4(),
            "now": datetime.now(timezone.utc)
        }
    )

    # Create contract test user
    op.execute(
        sa.text("""
            INSERT INTO users (id, email, password_hash, is_active, tenant_id, created_at)
            SELECT
                :user_id,
                'contract-test@example.com',
                '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW',
                true,
                id,
                :now
            FROM tenants WHERE slug = 'contract-test-tenant'
            ON CONFLICT (email) DO NOTHING
        """),
        {
            "user_id": uuid.uuid4(),
            "now": datetime.now(timezone.utc)
        }
    )

    # Create test data for various endpoints
    op.execute(
        sa.text("""
            INSERT INTO products (id, name, price, tenant_id, created_at)
            SELECT
                gen_random_uuid(),
                'Contract Test Product ' || n,
                19.99 + n,
                (SELECT id FROM tenants WHERE slug = 'contract-test-tenant'),
                :now
            FROM generate_series(1, 5) AS n
            ON CONFLICT DO NOTHING
        """),
        {"now": datetime.now(timezone.utc)}
    )


def downgrade() -> None:
    # Clean up contract test data
    op.execute(
        "DELETE FROM users WHERE email = 'contract-test@example.com'"
    )
    op.execute(
        "DELETE FROM products WHERE tenant_id IN (SELECT id FROM tenants WHERE slug = 'contract-test-tenant')"
    )
    op.execute(
        "DELETE FROM tenants WHERE slug = 'contract-test-tenant'"
    )
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Every endpoint in OpenAPI spec is tested unless explicitly excluded** | `schemathesis.from_pytest_fixture()` in `tests/contracts/test_contracts.py` loads all paths and methods from schema, filtered by exclude list |
| QS-2 | **Response status codes strictly match OpenAPI declaration** | `status_code_conformance` check in `schemathesis.yml` validates against schema status codes with 100% enforcement |
| QS-3 | **Response bodies match schema for declared status codes** | `response_schema_conformance` check in `schemathesis.yml` runs jsonschema validation on all responses |
| QS-4 | **Stateful tests never mutate production data** | `test_stateful.py` fixtures use isolated test database with `autouse=True` transaction rollback |
| QS-5 | **Authentication requirements are respected in generated tests** | `auth_client` fixture in `conftest.py` automatically handles JWT tokens for protected endpoints |
| QS-6 | **Excluded endpoints are explicitly listed in configuration** | `exclude_endpoints` in `schemathesis.yml` must contain all skipped paths with justification comments |
| QS-7 | **Custom response checks are implemented for project-specific standards** | `@schemathesis.check` decorators in `test_contracts.py` enforce headers like `X-Request-ID` and `Correlation-ID` |
| QS-8 | **Test failures are reproducible via Hypothesis seeds** | `--hypothesis-seed=reproduce` in `.github/workflows/contract-tests.yml` ensures CI logs contain failure reproduction instructions |
| QS-9 | **File upload endpoints are tested with binary data strategies** | `schemathesis.from_pytest_fixture()` automatically detects `multipart/form-data` content and generates valid test cases |
| QS-10 | **Slow endpoints have extended deadlines** | `hypothesis.deadline=5000` in `schemathesis.yml` with per-endpoint overrides via `@schemathesis.override` decorator |
| QS-11 | **Schema validation errors fail the build immediately** | `pytest -x` flag in CI workflow stops on first failure to prevent masking issues |
| QS-12 | **Test data is cleaned after stateful runs** | `test_stateful.py` includes `teardown_module` function that deletes all entities created during state machine tests |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `tests/contracts/test_contracts.py` exists with schemathesis test cases | File exists, imports schemathesis |
| CC-02 | `tests/contracts/test_stateful.py` exists when stateful=True | File exists, contains state machine tests |
| CC-03 | `schemathesis.yml` config file exists in project root | File exists, contains base_url and checks |
| CC-04 | `conftest.py` contains schema fixture loading from ASGI app | grep `from_asgi("/openapi.json", app)` |
| CC-05 | `conftest.py` contains auth_client fixture for protected endpoints | grep `auth_client` fixture with JWT flow |
| CC-06 | CI workflow `.github/workflows/contract-tests.yml` exists | File exists, runs pytest on contracts dir |
| CC-07 | All non-excluded endpoints have corresponding test functions | grep `@schema.parametrize()` matches OpenAPI paths |
| CC-08 | Status code assertions cover all declared codes per endpoint | Inspect test_* functions for status code checks |
| CC-09 | Response body schemas validated for success cases (2xx) | grep `response_schema_conformance` in config |
| CC-10 | Response body schemas validated for error cases (4xx/5xx) | grep `response_schema_conformance` in config |
| CC-11 | Undocumented response fields cause test failures | T-08 verifies extra field detection |
| CC-12 | Excluded endpoints list contains all destructive operations | Inspect `exclude_endpoints` in schemathesis.yml |
| CC-13 | Stateful tests use isolated database transactions | grep `@pytest.mark.usefixtures("db")` in stateful tests |
| CC-14 | Hypothesis max_examples=100 set globally | grep `max_examples: 100` in schemathesis.yml |
| CC-15 | Custom response checks exist for project headers | grep `@schemathesis.check` in test files |
| CC-16 | CI workflow uploads hypothesis artifacts on failure | grep `actions/upload-artifact` in workflow |
| CC-17 | Test files pass flake8 linting | Run flake8 on test_contracts.py |
| CC-18 | OpenAPI spec is valid before test generation | curl `/openapi.json` returns 200 with valid JSON |
| CC-19 | Authentication fixtures cover all auth methods | Inspect auth_client for JWT, API key support |
| CC-20 | File upload endpoints have multipart test cases | grep `content_type: multipart/form-data` in OpenAPI |
| CC-21 | State machine tests cover create→read→update sequences | Inspect test_stateful.py for chain assertions |
| CC-22 | Hypothesis deadline extended for slow endpoints | grep `@schemathesis.override(deadline=)` |
| CC-23 | Test data includes edge cases (empty strings, nulls) | grep `hypothesis.strategies` in custom schemas |
| CC-24 | Error responses include proper content-type | grep `content_type_conformance` in config |
| CC-25 | 5xx errors fail tests immediately | grep `assert response.status_code < 500` |
| CC-26 | Tool execution adds no production dependencies | inspect `pyproject.toml` for new deps |
| CC-27 | Idempotent: re-run creates no duplicate tests | Run tool twice, verify no test file changes |
| CC-28 | All tests run under 60s in CI | Check workflow timing logs |
| CC-29 | Migration adds test user for auth fixtures | inspect `alembic/versions/*_add_test_fixtures.py` |
| CC-30 | Documentation includes contract test troubleshooting | grep `hypothesis seed` in project README |

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified via checks
- [ ] Contract tests pass for all non-excluded endpoints
- [ ] Stateful tests (if enabled) complete without database corruption
- [ ] CI workflow runs contract tests on every push/PR
- [ ] Hypothesis failure seeds logged in CI artifacts
- [ ] Custom response checks implemented for project standards
- [ ] OpenAPI spec covers all endpoints with response schemas
- [ ] Test coverage measured and reported in CI
- [ ] Documentation updated with contract testing guidelines
- [ ] All destructive endpoints explicitly excluded
- [ ] Authentication flows tested via auth_client fixture
- [ ] File upload endpoints validated with binary strategies
- [ ] Performance SLOs met (test runtime < 60s)

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-CT-01 | A contract test failure **always** indicates a schema mismatch | `response_schema_conformance` check in schemathesis validates every response against OpenAPI | T-07, T-08 |
| INV-CT-02 | Stateful tests **never** persist data beyond test run | `transaction.rollback()` in `conftest.py` teardown ensures database reset | T-13, T-14 |
| INV-CT-03 | Excluded endpoints **always** have explicit justification | `exclude_endpoints` list in schemathesis.yml requires comment per entry | T-25 |
| INV-CT-04 | Authentication requirements **always** enforced for protected endpoints | `auth_client` fixture injects tokens before protected endpoint tests | T-19, T-20 |
| INV-CT-05 | Schema validation **never** silently ignores undocumented fields | `not_a_server_error` check fails on 500 responses from invalid inputs | T-08, T-12 |
| INV-CT-06 | Test failures **always** include reproduction instructions | `--hypothesis-seed` printed in CI logs for every failure | T-24 |
| INV-CT-07 | File upload endpoints **always** tested with binary data | `multipart/form-data` content type detection in schemathesis strategy | T-17 |
| INV-CT-08 | Custom response checks **always** run for project standards | `@schemathesis.check` decorators executed for every response | T-09, T-10 |

---

## 9. User Stories

### 9.1 Core Test Generation (US-01 .. US-05)

**US-01: Generate tests for all endpoints**
- **As a** developer adding contract tests
- **I want** every endpoint in my OpenAPI spec to get a test
- **So that** I have complete schema coverage
- **Given:** API with `/users/`, `/items/`, `/orders/` endpoints
- **When:** I run `add_contract_tests(project_dir="/code/api")`
- **Then:**
  - `tests/contracts/test_contracts.py` contains `@schema.parametrize()` for each path (CC-07)
  - Status codes 200, 400, 404 are validated per endpoint (INV-CT-02)
  - Response body schemas are checked for all 2xx responses (CC-09)

**US-02: Exclude destructive endpoints**
- **As a** security-conscious dev
- **I want** to skip tests for dangerous endpoints
- **So that** we don't accidentally wipe production data
- **Given:** API with `/admin/wipe` endpoint
- **When:** I call `add_contract_tests(exclude_endpoints=["/admin/wipe"])`
- **Then:**
  - `schemathesis.yml` lists `/admin/wipe` under `exclude_endpoints` (INV-CT-03)
  - No test generated for `DELETE /admin/wipe` (CC-12)
  - Tool logs warning about excluded endpoint

**US-03: Validate file uploads**
- **As a** dev with multipart endpoints
- **I want** proper binary data testing
- **So that** file upload contracts are verified
- **Given:** `POST /uploads/` with `multipart/form-data`
- **When:** Contract tests run
- **Then:**
  - Schemathesis generates random binary payloads (INV-CT-07)
  - Tests validate `Content-Type: multipart/form-data` (CC-20)
  - 413 payloads fail gracefully (T-17)

**US-04: Custom response checks**
- **As a** platform engineer
- **I want** to enforce standard headers
- **So that** all responses meet our API guidelines
- **Given:** API requiring `X-Request-ID` header
- **When:** Tests run with `@schemathesis.check`
- **Then:**
  - Every response validates presence of `X-Request-ID` (INV-CT-08)
  - Missing header fails the test (T-09)
  - Check runs after schema validation (CC-15)

**US-05: Handle authentication**
- **As a** dev with protected endpoints
- **I want** tests to handle auth automatically
- **So that** protected routes get proper coverage
- **Given:** `/admin/` routes requiring JWT
- **When:** Tests execute with `auth_client` fixture
- **Then:**
  - Protected endpoints receive valid tokens (INV-CT-04)
  - 401 responses validated for missing auth (T-19)
  - Token refresh flow tested (CC-05)

### 9.2 Stateful Testing (US-06 .. US-10)

**US-06: Chain create-read-update**
- **As a** dev testing workflows
- **I want** stateful sequences
- **So that** I find bugs in call chains
- **Given:** User lifecycle endpoints
- **When:** `stateful=True` with `/users/` POST → GET → PATCH
- **Then:**
  - Tests create → read → update in sequence (CC-21)
  - State machine validates intermediate states (T-13)
  - Database rolls back after test (INV-CT-02)

**US-07: Test pagination flows**
- **As a** dev with list endpoints
- **I want** pagination tested end-to-end
- **So that** page links work correctly
- **Given:** `/items/?page=2` endpoint
- **When:** Stateful test follows `next` links
- **Then:**
  - All pages return valid items (CC-21)
  - Final page has no `next` link (T-14)
  - Total count matches header (CC-03)

**US-08: Isolate stateful runs**
- **As a** CI operator
- **I want** stateful tests isolated
- **So that** they don't corrupt state
- **Given:** test database
- **When:** Stateful tests run
- **Then:**
  - Each test starts with clean DB (CC-13)
  - `teardown_module` clears all data (CC-12)
  - Transactions roll back on failure (INV-CT-02)

**US-09: Validate stateful sequences**
- **As a** test engineer
- **I want** to verify state transitions
- **So that** workflows maintain consistency
- **Given:** Order lifecycle (draft → paid → shipped)
- **When:** State machine executes transitions
- **Then:**
  - Invalid transitions fail (e.g. draft → shipped) (T-15)
  - Status codes validated per state (CC-02)
  - Final state matches expectations (CC-21)

**US-10: Handle stateful timeouts**
- **As a** dev with slow workflows
- **I want** configurable timeouts
- **So that** tests don't hang
- **Given:** `/import/` endpoint taking 10s
- **When:** Stateful test hits deadline
- **Then:**
  - Hypothesis aborts after 5s (CC-10)
  - Timeout configurable per endpoint (CC-22)
  - CI logs show timeout reason (CC-16)

### 9.3 Error Handling (US-11 .. US-15)

**US-11: Catch schema drift**
- **As a** API maintainer
- **I want** undocumented fields to fail
- **So that** schemas stay accurate
- **Given:** Response with extra `internal_id` field
- **When:** Contract test runs
- **Then:**
  - Test fails with schema violation (INV-CT-05)
  - Error shows exact field mismatch (T-08)
  - CI blocks merge (CC-11)

**US-12: Validate error formats**
- **As a** client developer
- **I want** consistent error responses
- **So that** clients can handle them
- **Given:** 400 Bad Request cases
- **When:** Tests send invalid inputs
- **Then:**
  - All 4xx responses match error schema (CC-10)
  - Include `type`, `title`, `detail` fields (T-12)
  - Content-Type is `application/problem+json` (CC-24)

**US-13: Reproduce flaky failures**
- **As a** debugger
- **I want** reproducible test cases
- **So that** I can fix intermittent issues
- **Given:** Failing contract test
- **When:** Hypothesis finds edge case
- **Then:**
  - CI logs show exact seed (INV-CT-06)
  - Can rerun with `--hypothesis-seed=XYZ` (CC-16)
  - Failing example minimized (T-24)

**US-14: Handle missing schemas**
- **As a** dev with partial OpenAPI
- **I want** clear failures
- **So that** I know to document
- **Given:** Endpoint without response schema
- **When:** Contract test runs
- **Then:**
  - Test fails with "missing schema" (CC-18)
  - Listed in CI report (CC-16)
  - Excluded endpoints skip validation (CC-12)

**US-15: Validate 500 errors**
- **As a** reliability engineer
- **I want** to catch server errors
- **So that** we fix crashes
- **Given:** Buggy `/search/` endpoint
- **When:** Test sends malformed query
- **Then:**
  - 500 responses fail test (INV-CT-01)
  - Error includes stack trace (T-07)
  - Marked as critical in CI (CC-25)

### 9.4 CI Integration (US-16 .. US-20)

**US-16: Run on every PR**
- **As a** CI maintainer
- **I want** contract tests in CI
- **So that** we catch regressions
- **Given:** GitHub Actions workflow
- **When:** PR changes API code
- **Then:**
  - Contract tests run automatically (CC-06)
  - Failures block merge (CC-11)
  - Artifacts include hypothesis logs (CC-16)

**US-17: Upload failure reports**
- **As a** remote worker
- **I want** downloadable artifacts
- **So that** I can debug failures
- **Given:** Flaky test in CI
- **When:** Job completes
- **Then:**
  - `.hypothesis/` uploaded (CC-16)
  - Contains minimal repro example (INV-CT-06)
  - Preserved for 90 days (CC-06)

**US-18: Enforce schema coverage**
- **As a** tech lead
- **I want** coverage reports
- **So that** we don't miss endpoints
- **Given:** New `/v2/` endpoints
- **When:** Schema updates
- **Then:**
  - CI detects missing tests (CC-07)
  - Coverage report shows gaps (CC-30)
  - Fails if coverage < 100% (CC-26)

**US-19: Fast feedback**
- **As a** developer
- **I want** quick test runs
- **So that** I can iterate
- **Given:** 50 endpoints
- **When:** Full suite runs
- **Then:**
  - Completes in <60s (CC-28)
  - Per-endpoint timeout 5s (CC-10)
  - Slow endpoints flagged (CC-22)

**US-20: Isolate test data**
- **As a** database admin
- **I want** clean test state
- **So that** prod isn't affected
- **Given:** Test user fixtures
- **When:** Tests run
- **Then:**
  - Uses test database (CC-13)
  - Rolls back transactions (INV-CT-02)
  - Never touches prod (CC-04)

### 9.5 Maintenance (US-21 .. US-25)

**US-21: Idempotent tool runs**
- **As a** dev running upgrades
- **I want** no duplicate files
- **So that** I can rerun safely
- **Given:** Existing contract tests
- **When:** Tool reruns
- **Then:**
  - No file changes (CC-27)
  - Output says "already configured" (CC-01)
  - Exit code 0 (T-25)

**US-22: Handle schema updates**
- **As a** API designer
- **I want** test regeneration
- **So that** tests stay current
- **Given:** New OpenAPI version
- **When:** Schema changes
- **Then:**
  - Tests update automatically (CC-14)
  - CI detects drift (CC-18)
  - Fails if incompatible (CC-11)

**US-23: Customize test depth**
- **As a** performance engineer
- **I want** adjustable examples
- **So that** I balance coverage/speed
- **Given:** Slow `/reports/` endpoint
- **When:** `max_examples=10`
- **Then:**
  - Only 10 test cases generated (CC-14)
  - Configurable per endpoint (CC-22)
  - Still finds edge cases (T-23)

**US-24: Document troubleshooting**
- **As a** new team member
- **I want** clear docs
- **So that** I can fix test failures
- **Given:** Failing contract test
- **When:** Checking README
- **Then:**
  - Shows how to use seeds (CC-30)
  - Explains common failures (CC-25)
  - Links to schemathesis docs (CC-26)

**US-25: Validate tool install**
- **As a** release engineer
- **I want** dependency checks
- **So that** setup works
- **Given:** New environment
- **When:** Installing tool
- **Then:**
  - Verifies OpenAPI exists (CC-18)
  - Checks pytest version (CC-26)
  - Validates schemathesis (CC-01)

---

## 10. Test Plan

### 10.1 Contract Generation Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Generate tests for all endpoints | API with `/users/`, `/items/` endpoints | Run `add_contract_tests(project_dir="/code/api")` | `tests/contracts/test_contracts.py` contains `@schema.parametrize()` for `/users/` and `/items/` |
| T-02 | Respect excluded endpoints | API with `/admin/wipe` endpoint | Run `add_contract_tests(exclude_endpoints=["/admin/wipe"])` | No test generated for `DELETE /admin/wipe` |
| T-03 | Handle file upload endpoints | API with `POST /uploads/` accepting `multipart/form-data` | Run contract tests | Schemathesis generates random binary payloads |
| T-04 | Generate stateful tests | API with `/users/` POST → GET → PATCH | Run `add_contract_tests(stateful=True)` | `tests/contracts/test_stateful.py` contains state machine tests |
| T-05 | Idempotent tool execution | Existing contract tests | Run `add_contract_tests()` again | No file changes, tool logs "already configured" |
| T-06 | Handle missing OpenAPI spec | Project without `/openapi.json` | Run `add_contract_tests()` | Tool fails with "OpenAPI spec not found" |

### 10.2 Schema Validation Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Validate status codes | `/users/` endpoint declares 200, 400, 404 | Send requests to `/users/` | Responses match declared status codes (INV-CT-01) |
| T-08 | Catch undocumented fields | `/users/` response includes extra `internal_id` field | Inspect test failure | Test fails with "Undocumented field: internal_id" (INV-CT-05) |
| T-09 | Validate response headers | `/users/` requires `X-Request-ID` header | Inspect test failure | Missing header fails test (INV-CT-08) |
| T-10 | Validate error formats | `/users/` returns 400 Bad Request | Send invalid request | Response matches error schema with `type`, `title`, `detail` fields |
| T-11 | Handle missing response schema | `/search/` endpoint has no response schema | Run contract tests | Test fails with "Missing response schema" |
| T-12 | Validate 500 errors | `/search/` endpoint returns 500 | Send malformed query | Test fails with "Unexpected 500 error" (INV-CT-01) |

### 10.3 Stateful Testing Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Chain create-read-update | `/users/` POST → GET → PATCH | Run stateful tests | Tests execute sequence and validate intermediate states (INV-CT-02) |
| T-14 | Test pagination flows | `/items/?page=2` with `next` links | Run stateful tests | Tests follow links and validate final page has no `next` link |
| T-15 | Isolate stateful runs | Test database | Run stateful tests | Each test starts with clean DB, teardown clears data (INV-CT-02) |
| T-16 | Validate stateful sequences | Order lifecycle (draft → paid → shipped) | Run stateful tests | Invalid transitions fail (e.g. draft → shipped) |
| T-17 | Handle stateful timeouts | `/import/` endpoint takes 10s | Run stateful tests | Hypothesis aborts after 5s |
| T-18 | Stateful test rollback | Create user in stateful test | Inspect DB after test | User not present in DB (INV-CT-02) |

### 10.4 CI Integration Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Run on every PR | GitHub Actions workflow | Push to PR | Contract tests run automatically |
| T-20 | Upload failure reports | Flaky test in CI | Job completes | `.hypothesis/` uploaded with minimal repro example (INV-CT-06) |
| T-21 | Enforce schema coverage | New `/v2/` endpoints | Schema updates | CI detects missing tests |
| T-22 | Fast feedback | 50 endpoints | Full suite runs | Completes in <60s |
| T-23 | Isolate test data | Test user fixtures | Run tests | Uses test database, rolls back transactions (INV-CT-02) |
| T-24 | Handle schema updates | New OpenAPI version | Schema changes | Tests update automatically |

### 10.5 Edge Case Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Customize test depth | `/reports/` endpoint | Set `max_examples=10` | Only 10 test cases generated |
| T-26 | Handle flaky tests | Failing contract test | Check CI logs | Hypothesis seed printed for reproduction (INV-CT-06) |
| T-27 | Validate tool install | New environment | Install tool | Verifies OpenAPI exists, checks pytest version |
| T-28 | Handle missing schemas | Endpoint without response schema | Run contract tests | Test fails with "missing schema" |
| T-29 | Test authentication flows | `/admin/` routes requiring JWT | Run tests | Protected endpoints receive valid tokens (INV-CT-04) |
| T-30 | Validate file upload endpoints | `POST /uploads/` with `multipart/form-data` | Run contract tests | Tests validate `Content-Type: multipart/form-data` (INV-CT-07) |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Contract tests validate soft-delete endpoints return expected status codes (200 vs 404) |
| add_cursor_pagination | No | ✅ Compatible | Tests validate pagination headers and link relations in responses |
| add_search | No | ✅ Compatible | Schemathesis generates edge cases for search parameters and validates result schema |
| add_audit_log | No | ✅ Compatible | Tests verify audit log entries are created without affecting response contracts |
| add_data_export | No | ✅ Compatible | Binary response validation handles CSV/Excel export endpoints |
| add_bulk_operations | No | ✅ Compatible | Stateful tests validate bulk create→read→update sequences |
| add_multi_tenancy | No | ✅ Compatible | Tenant isolation verified via auth_client fixture with different tenant tokens |
| add_feature_flags | No | ✅ Compatible | Tests run with feature flags enabled/disabled to validate all code paths |
| add_api_key_auth | No | ✅ Compatible | API key validation integrated into auth_client fixture |
| add_oauth2_provider | No | ✅ Compatible | OAuth2 token flow tested via stateful auth sequence |
| add_rbac | No | ✅ Compatible | Role-based access control verified through permission-denied responses |
| add_mfa | No | ✅ Compatible | MFA challenge responses validated against error schema |
| add_cache_layer | No | ⚠️ Caveat | Cache headers must be explicitly validated via @schemathesis.check |
| add_outbox_pattern | No | ✅ Compatible | Asynchronous outbox processing doesn't affect immediate response contracts |
| add_sse | No | ⚠️ Caveat | Server-Sent Events require custom validation beyond standard OpenAPI |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout -- tests/conftest.py
git checkout -- tests/contracts/test_contracts.py
rm -f tests/contracts/test_stateful.py
rm -f schemathesis.yml
rm -f .github/workflows/contract-tests.yml
git checkout -- alembic/versions/*_add_test_fixtures.py
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated
by this tool. Nothing to archive.

### Failure mode: tool partially modified files
If the generator crashed halfway and left an inconsistent tree (some schemathesis tests present, others missing, conftest patched but pytest markers not registered), restore to a clean HEAD before re-running:
```bash
# 1. Inspect what changed vs HEAD
git status --short tests/ schemathesis.yml .github/

# 2. Restore any tool-modified files + drop freshly-created ones
git checkout HEAD -- tests/conftest.py schemathesis.yml pytest.ini
git clean -fd tests/contracts/ .github/workflows/contract-tests.yml

# 3. Verify clean tree before retrying
git diff HEAD --exit-code -- tests/ schemathesis.yml && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: contract tests flaky in CI
If schemathesis / Pact tests pass locally but flake on CI because Hypothesis finds different edge cases each run, the fix is to pin the Hypothesis seed to a known-good value and raise `max_examples` only for the specific endpoints that actually deserve more coverage:
```bash
# 1. Capture the seed from the last failing run
pytest tests/contracts -x --hypothesis-show-statistics 2>&1 | grep -i seed

# 2. Pin it in conftest.py (commit this change)
#    hypothesis.settings.register_profile("ci", derandomize=True, max_examples=50, deadline=5000)
#    hypothesis.settings.load_profile("ci")

# 3. Re-run twice to confirm determinism
pytest tests/contracts -x
pytest tests/contracts -x
```

### Emergency: contract tests timeout / block CI pipeline
If contract tests start consuming the CI time budget (hypothesis exploration finds a hot edge), containment:
1. Set `CONTRACT_TESTS_MAX_EXAMPLES=20` in the failing workflow — `schemathesis.yml` reads this env
2. Add the offending endpoint to `.schemathesis-exclude.yaml` with a justification + a tracking issue link
3. Roll the CI workflow; subsequent runs should finish under 5 min
4. File a ticket to investigate the root cause — the endpoint probably has a true performance or serialization bug

### Emergency: Pact broker unreachable during CI
If the Pact broker (Pactflow or self-hosted) goes down mid-deploy and you cannot publish new contracts:
1. Check broker health: `curl -I $PACT_BROKER_URL/diagnostic/status/heartbeat`
2. If down, set `PACT_VERIFY_ONLY=true` so CI only verifies local `pacts/*.json` without publishing or pulling
3. Block new consumer-side contract changes from merging until the broker recovers (the `can-i-deploy` gate depends on it)
4. Once the broker is back, republish by running `pact-broker publish pacts/ --consumer-app-version=$GIT_SHA`

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | OpenAPI spec contains no response schemas | Tool errors with message: "OpenAPI spec at /openapi.json contains no response schemas. Document responses first." |
| EC-2 | Endpoint accepts file upload via multipart/form-data | Schemathesis automatically generates binary test payloads with random file contents |
| EC-3 | Endpoint returns 500 for specific input combination | Failure captured with Hypothesis seed and exact reproduction steps logged |
| EC-4 | Response contains undocumented field not in OpenAPI | Contract test fails with "Undocumented field detected: response.data.internal_id" |
| EC-5 | Stateful test creates data that persists after run | teardown_module hook deletes all entities created during state machine tests |
| EC-6 | Authentication required but auth_client fixture missing | Test fails with "401 Unauthorized" and suggests implementing auth_client fixture |
| EC-7 | Endpoint consistently takes >5s to respond | Hypothesis aborts test after deadline and logs warning to extend timeout |
| EC-8 | Schema incorrectly marks valid request as invalid | Test fails and prompts developer to fix OpenAPI schema definition |
| EC-9 | Hypothesis finds edge case not covered by schema | Test fails and developer must either fix implementation or update schema |
| EC-10 | CI pipeline times out with max_examples=100 | Tool suggests per-endpoint override with @schemathesis.override(max_examples=20) |
| EC-11 | State machine gets stuck in infinite loop | Hypothesis timeout aborts test after 5 minutes and logs last successful state |
| EC-12 | Endpoint returns 200 with empty response body | Test passes if OpenAPI schema explicitly allows null/empty responses |
| EC-13 | Tool is re-run on already-configured project | Idempotent operation detects existing files and logs "Contract tests already configured" |
| EC-14 | OpenAPI schema version changes after test generation | CI detects schema drift and fails until tests are regenerated |
| EC-15 | New endpoint added without corresponding test | CI diff check fails with "Endpoint /v2/users/ missing contract tests" |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified via automated checks  
✅ 2. Contract tests pass for 100% of non-excluded endpoints  
✅ 3. Stateful tests (if enabled) complete without database corruption  
✅ 4. CI workflow runs contract tests on every push/PR  
✅ 5. Hypothesis failure seeds logged in CI artifacts for all failures  
✅ 6. Custom response checks implemented for project standards (X-Request-ID etc.)  
✅ 7. OpenAPI spec covers all endpoints with complete response schemas  
✅ 8. Test coverage measured and reported in CI (minimum 95% endpoint coverage)  
✅ 9. Performance SLOs met (full test suite <60s, single endpoint <5s)  
✅ 10. Developer manually verifies end-to-end flow:  
   - Runs `add_contract_tests(project_dir="/code/api")`  
   - Edits OpenAPI schema to add undocumented field  
   - Runs `pytest tests/contracts` and confirms test fails  
   - Reverts schema change and confirms tests pass  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists and contains Python project  
- [ ] Verify `openapi.json` exists at specified path (default /openapi.json)  
- [ ] Check for existing `schemathesis.yml` to prevent overwrites  
- [ ] Validate pytest is installed and configured  
- [ ] Confirm FastAPI app is importable from project root  
- [ ] Check for existing contract test files to ensure idempotency  
- [ ] Verify OpenAPI spec is valid JSON with paths and components  

### 15.2 Test directory structure
- [ ] Create `tests/contracts/` directory if missing  
- [ ] Generate `__init__.py` in contracts directory  
- [ ] Add `conftest.py` with schema and auth_client fixtures  
- [ ] Create base test file `test_contracts.py`  
- [ ] Generate stateful test file `test_stateful.py` if stateful=True  
- [ ] Add `.gitkeep` to preserve empty directories  
- [ ] Set proper permissions (755 for dirs, 644 for files)  

### 15.3 Schemathesis configuration  
- [ ] Create `schemathesis.yml` with base checks  
- [ ] Configure hypothesis deadlines and phases  
- [ ] Add excluded endpoints with comments  
- [ ] Set base_url to http://testserver  
- [ ] Configure content type validations  
- [ ] Add project-specific response checks  
- [ ] Set max_examples default to 100  

### 15.4 Core test generation  
- [ ] Generate `@schema.parametrize()` test for each endpoint  
- [ ] Add status code assertions for all declared codes  
- [ ] Include schema validation checks for 2xx responses  
- [ ] Add error schema validation for 4xx responses  
- [ ] Implement custom checks for project headers  
- [ ] Generate state machine tests for stateful=True  
- [ ] Add teardown hooks for stateful test cleanup  

### 15.5 Authentication handling  
- [ ] Add auth_client fixture to conftest.py  
- [ ] Support JWT token flow in auth_client  
- [ ] Handle API key authentication if detected  
- [ ] Implement OAuth2 token refresh flow  
- [ ] Add tests for 401/403 responses  
- [ ] Verify token expiration handling  
- [ ] Test role-based access control responses  

### 15.6 CI integration  
- [ ] Create `.github/workflows/contract-tests.yml`  
- [ ] Configure pytest with hypothesis seed reporting  
- [ ] Add artifact upload for .hypothesis/ directory  
- [ ] Set timeout for entire test suite  
- [ ] Add step to validate OpenAPI spec exists  
- [ ] Configure failure notifications  
- [ ] Add step to measure test coverage  

### 15.7 Stateful testing  
- [ ] Generate state machine test file  
- [ ] Implement create→read→update sequences  
- [ ] Add pagination flow tests  
- [ ] Include order lifecycle validations  
- [ ] Configure transaction isolation  
- [ ] Add teardown database cleanup  
- [ ] Implement timeout handling  

### 15.8 Edge case handling  
- [ ] Add tests for file upload endpoints  
- [ ] Implement binary data strategies  
- [ ] Handle null/empty response validation  
- [ ] Test maximum payload sizes  
- [ ] Validate error response formats  
- [ ] Test rate limited endpoints  
- [ ] Verify CORS header responses  

### 15.9 Performance tuning  
- [ ] Set default hypothesis deadlines  
- [ ] Add per-endpoint deadline overrides  
- [ ] Configure test parallelization  
- [ ] Implement batched test execution  
- [ ] Add CI performance budget checks  
- [ ] Log slowest test endpoints  
- [ ] Optimize hypothesis example generation  

### 15.10 Documentation  
- [ ] Update README with contract testing docs  
- [ ] Add troubleshooting guide for common failures  
- [ ] Document hypothesis seed reproduction  
- [ ] Include schema coverage reporting  
- [ ] Add examples for custom checks  
- [ ] Document stateful testing patterns  
- [ ] Note CI integration requirements  

### 15.11 Atomicity  
- [ ] Write files using temp-file + rename pattern  
- [ ] Track all modified files for rollback  
- [ ] Verify file writes complete successfully  
- [ ] Rollback on any generation failure  
- [ ] Preserve existing files on error  
- [ ] Validate file permissions post-write  
- [ ] Return detailed error report on failure  

### 15.12 Verification  
- [ ] Run `ast.parse` on all generated files  
- [ ] Execute pytest on new test files  
- [ ] Verify test coverage metrics  
- [ ] Check CI workflow syntax  
- [ ] Validate OpenAPI spec post-generation  
- [ ] Test idempotency on second run  
- [ ] Measure tool execution time  

### 15.13 Error handling  
- [ ] Handle missing OpenAPI spec  
- [ ] Catch invalid schema errors  
- [ ] Detect pytest configuration issues  
- [ ] Validate hypothesis compatibility  
- [ ] Handle filesystem permission errors  
- [ ] Catch network errors during CI setup  
- [ ] Provide clear error messages  

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "tests/contracts/__init__.py",
    "tests/contracts/test_contracts.py",
    "tests/contracts/test_stateful.py",
    "schemathesis.yml",
    ".github/workflows/contract-tests.yml",
    "tests/conftest.py",
    "alembic/versions/0009_add_test_fixtures.py",
    "docs/contract-testing.md"
  ],
  "files_modified": [
    "pyproject.toml",
    ".gitignore",
    "README.md"
  ],
  "metrics": {
    "execution_time_ms": 2847,
    "files_changed": 11,
    "lines_added": 892,
    "lines_removed": 14,
    "endpoints_tested": 42,
    "excluded_endpoints": 3,
    "stateful_chains": 7
  },
  "next_steps": [
    "Run: pytest tests/contracts -v",
    "Verify CI workflow: git push origin main",
    "Check test coverage: pytest --cov=app tests/contracts/",
    "Reproduce a failure: pytest tests/contracts/test_contracts.py::test_api -x --hypothesis-seed=last",
    "Update OpenAPI spec for any undocumented endpoints found"
  ],
  "warnings": [
    "3 endpoints excluded from testing: /admin/wipe, /admin/reset, /debug/panic",
    "File upload endpoints detected - verify binary payload handling in test runs",
    "Stateful testing enabled - ensure test database is properly isolated"
  ],
  "notes": [
    "Contract tests generated for 42 endpoints with max_examples=100",
    "Stateful testing configured with 7 endpoint chains",
    "Hypothesis deadline set to 5000ms (configurable per-endpoint)",
    "CI workflow includes failure artifact upload",
    "Authentication flows tested via auth_client fixture",
    "All generated files pass ast.parse validation",
    "Existing unit tests remain unchanged (47/47 pass)"
  ]
}
