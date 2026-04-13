# TOOL-045: fastapi_extract_service

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_extract_service` |
| Category | EVOLVE |
| Complexity | Very High |
| Dependencies | Existing FastAPI project, git, AST parser, Docker, httpx, pact-python |
| Signature | `extract_service(project_dir: str, module_paths: list[str], new_service_name: str, new_service_port: int = 8001, communication: str = "http", generate_client: bool = True) -> dict` |
| Parameters | `project_dir`: absolute path to monolith root<br>`module_paths`: list of module paths (relative to `src/`) to carve out<br>`new_service_name`: directory name for the new service (e.g. `billing_service`)<br>`new_service_port`: TCP port for the new service container (default 8001)<br>`communication`: boundary protocol — `http` (REST+OpenAPI), `grpc`, or `events`<br>`generate_client`: if `True`, generate a fully-typed `httpx`-based Python client in the monolith |

---

## 2. Purpose

The `fastapi_extract_service` tool implements the strangler-fig pattern for FastAPI monoliths by surgically carving out a set of modules — routes, models, schemas, services, and their tests — into a standalone, independently deployable FastAPI service. The tool walks the monolith's AST to build a full dependency graph, identifies cross-cutting shared code, moves it to a `common/` package both services depend on, and rewires the monolith's call sites to use either a generated typed `httpx` client (proxy mode) or removes the routes entirely (split mode). The boundary contract is captured as an OpenAPI schema and enforced by Pact contract tests so that neither service can silently drift from the agreed API surface. Every output artefact — the new service skeleton, `Dockerfile`, `docker-compose.yml` update, GitHub Actions workflow, and the typed client — is generated in a single deterministic pass, meaning two runs on the same input produce identical file trees.

The design avoids the two most common extraction disasters: shared-code duplication (which creates silent drift between services) and big-bang DB splits (which couple schema changes to service topology changes). Shared models are moved to `common/` once; the tool refuses to copy them. Database split is opt-in and runs in a separate, documented migration step — by default both services share the same PostgreSQL instance and schema. The tool also emits a machine-readable `EXTRACTION_MANIFEST.json` recording every file moved, every import rewritten, and every dependency inferred, giving the team a complete audit trail and a rollback recipe without requiring any human to reconstruct the change history. Proxy mode is implemented as a thin `httpx` reverse-proxy middleware inserted into the monolith router, capped at 50 ms overhead, so teams can deploy the new service and migrate traffic incrementally without a flag-day cutover.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time (20 modules) | < 10s | Developer runs from CLI; longer delays break flow |
| AST walk + import resolution | < 3s | Traverses up to 50k LOC monolith |
| Dependency graph construction | < 2s | Uses `ast.walk` with memo; avoids repeated traversals |
| Files modified in monolith | ≤ 40 | One per module with replaced imports + proxy registration |
| Files created in new service | ≥ 25 | Routes, models, schemas, services, tests, Dockerfile, CI, client, docs |
| Proxy mode latency overhead (p99) | < 50 ms | Thin `httpx` call with connection pool; no serialization overhead |
| New service cold-start (Docker) | < 5s | Slim image, pre-compiled .pyc, single-worker Uvicorn |
| Contract test suite execution | < 30s | Pact consumer+provider tests run against in-process server |
| Memory used by tool process | < 200 MB | AST of 200-module monolith fits in memory comfortably |

---

## 4. Code Examples (Before / After)

### 4.1 Dependency graph builder (tool internals)

```python
# scripts/extract_service/dep_graph.py
import ast
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, Set


class DependencyGraph:
    """Walk an app directory and build a directed import graph."""

    def __init__(self, project_root: Path, src_prefix: str = "app"):
        self.project_root = project_root
        self.src_prefix = src_prefix
        self.graph: Dict[str, Set[str]] = defaultdict(set)

    def build(self) -> Dict[str, Set[str]]:
        src_dir = self.project_root / self.src_prefix
        for py_file in src_dir.rglob("*.py"):
            module_id = self._path_to_module(py_file)
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(self.src_prefix):
                            self.graph[module_id].add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith(self.src_prefix):
                        self.graph[module_id].add(node.module)
        return dict(self.graph)

    def transitive_deps(self, module_id: str, visited: set | None = None) -> Set[str]:
        """Return all transitive dependencies of module_id."""
        if visited is None:
            visited = set()
        if module_id in visited:
            return visited
        visited.add(module_id)
        for dep in self.graph.get(module_id, set()):
            self.transitive_deps(dep, visited)
        return visited

    def _path_to_module(self, path: Path) -> str:
        rel = path.relative_to(self.project_root)
        return str(rel).replace(os.sep, ".").removesuffix(".py")
```

### 4.2 Monolith route handler — BEFORE extraction

```python
# app/routes/billing.py  (monolith — BEFORE)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.db import get_db
from app.core.auth import require_auth, CurrentUser
from app.models.invoice import Invoice
from app.schemas.invoice import InvoiceCreate, InvoicePublic
from app.services.billing import BillingService

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/invoices", response_model=InvoicePublic, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    payload: InvoiceCreate,
    current_user: CurrentUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> InvoicePublic:
    """Create a new invoice for the authenticated user."""
    service = BillingService(db)
    try:
        invoice = await service.create(owner_id=current_user.id, data=payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return InvoicePublic.model_validate(invoice)


@router.get("/invoices/{invoice_id}", response_model=InvoicePublic)
async def get_invoice(
    invoice_id: UUID,
    current_user: CurrentUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> InvoicePublic:
    """Retrieve a single invoice by ID."""
    service = BillingService(db)
    invoice = await service.get(invoice_id=invoice_id, owner_id=current_user.id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return InvoicePublic.model_validate(invoice)
```

### 4.3 Monolith route handler — AFTER extraction (proxy mode)

```python
# app/routes/billing.py  (monolith — AFTER, proxy mode)
from fastapi import APIRouter, Depends, Request, Response
from uuid import UUID

from app.core.auth import require_auth, CurrentUser
from app.clients.billing_client import BillingServiceClient, get_billing_client

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/invoices", status_code=201)
async def create_invoice(
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
    client: BillingServiceClient = Depends(get_billing_client),
) -> Response:
    """Proxy: forward invoice creation to billing_service."""
    body = await request.body()
    return await client.proxy_post(
        path="/invoices",
        body=body,
        headers={"X-User-ID": str(current_user.id)},
    )


@router.get("/invoices/{invoice_id}")
async def get_invoice(
    invoice_id: UUID,
    current_user: CurrentUser = Depends(require_auth),
    client: BillingServiceClient = Depends(get_billing_client),
) -> Response:
    """Proxy: forward invoice fetch to billing_service."""
    return await client.proxy_get(
        path=f"/invoices/{invoice_id}",
        headers={"X-User-ID": str(current_user.id)},
    )
```

### 4.4 Typed HTTP client — generated by tool

```python
# app/clients/billing_client.py  (generated by extract_service tool)
import httpx
from functools import lru_cache
from typing import AsyncGenerator
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel, AnyHttpUrl

from common.schemas.invoice import InvoiceCreate, InvoicePublic


class BillingClientSettings(BaseModel):
    base_url: AnyHttpUrl = "http://billing-service:8001"
    timeout: float = 5.0
    max_retries: int = 3


class BillingServiceClient:
    """Typed async client for billing_service.  Generated — do not edit manually."""

    def __init__(self, settings: BillingClientSettings | None = None):
        self._settings = settings or BillingClientSettings()
        self._transport = httpx.AsyncHTTPTransport(retries=self._settings.max_retries)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "BillingServiceClient":
        self._client = httpx.AsyncClient(
            base_url=str(self._settings.base_url),
            timeout=self._settings.timeout,
            transport=self._transport,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client:
            await self._client.aclose()

    async def create_invoice(self, payload: InvoiceCreate, user_id: UUID) -> InvoicePublic:
        resp = await self._client.post(
            "/invoices",
            json=payload.model_dump(mode="json"),
            headers={"X-User-ID": str(user_id)},
        )
        resp.raise_for_status()
        return InvoicePublic.model_validate(resp.json())

    async def get_invoice(self, invoice_id: UUID, user_id: UUID) -> InvoicePublic:
        resp = await self._client.get(
            f"/invoices/{invoice_id}",
            headers={"X-User-ID": str(user_id)},
        )
        resp.raise_for_status()
        return InvoicePublic.model_validate(resp.json())

    async def proxy_post(self, path: str, body: bytes, headers: dict) -> httpx.Response:
        return await self._client.post(path, content=body, headers=headers)

    async def proxy_get(self, path: str, headers: dict) -> httpx.Response:
        return await self._client.get(path, headers=headers)


@lru_cache
def get_billing_client_settings() -> BillingClientSettings:
    return BillingClientSettings()


async def get_billing_client() -> AsyncGenerator[BillingServiceClient, None]:
    settings = get_billing_client_settings()
    async with BillingServiceClient(settings) as client:
        yield client
```

### 4.5 New service main.py — scaffold generated by tool

```python
# billing_service/app/main.py  (new service — generated by extract_service)
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from billing_service.app.core.config import settings
from billing_service.app.core.db import init_db_pool, close_db_pool
from billing_service.app.routes.billing import router as billing_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db_pool()
    yield
    await close_db_pool()


app = FastAPI(
    title="billing_service",
    version="0.1.0",
    description="Extracted billing domain service — generated by fastapi_extract_service",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(billing_router, prefix="/api/v1")


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok", "service": "billing_service"}


if __name__ == "__main__":
    uvicorn.run("billing_service.app.main:app", host="0.0.0.0", port=8001, reload=False)
```

### 4.6 Shared common library module

```python
# common/schemas/invoice.py  (shared between monolith + billing_service)
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class InvoiceCreate(BaseModel):
    """Schema for creating a new invoice.  Shared via common/ lib."""
    model_config = ConfigDict(str_strip_whitespace=True)

    amount: Decimal
    currency: Literal["USD", "EUR", "BRL"]
    description: str
    due_date: datetime

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Invoice amount must be positive")
        return v

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Invoice description must not be empty")
        return v


class InvoicePublic(BaseModel):
    """Public-facing invoice schema.  Shared via common/ lib."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    amount: Decimal
    currency: str
    description: str
    status: Literal["pending", "paid", "cancelled", "overdue"]
    due_date: datetime
    created_at: datetime
    updated_at: datetime | None = None
```

### 4.7 Contract test using pact-python

```python
# billing_service/tests/test_contract_billing.py
import pytest
from pact import Consumer, Provider
from httpx import AsyncClient
from billing_service.app.main import app


PACT = Consumer("monolith").has_pact_with(Provider("billing_service"), port=1234)


@pytest.fixture(scope="module", autouse=True)
def pact_setup():
    PACT.start_service()
    yield
    PACT.stop_service()


@pytest.mark.asyncio
async def test_create_invoice_contract():
    """Consumer contract: monolith expects billing_service to accept POST /invoices."""
    expected_body = {
        "id": "00000000-0000-0000-0000-000000000001",
        "owner_id": "00000000-0000-0000-0000-000000000002",
        "amount": "99.99",
        "currency": "USD",
        "description": "Monthly subscription",
        "status": "pending",
        "due_date": "2026-05-01T00:00:00Z",
        "created_at": "2026-04-12T00:00:00Z",
    }
    (
        PACT.given("billing service is healthy")
        .upon_receiving("a request to create an invoice")
        .with_request(
            method="POST",
            path="/api/v1/invoices",
            headers={"Content-Type": "application/json"},
        )
        .will_respond_with(
            status=201,
            headers={"Content-Type": "application/json"},
            body=expected_body,
        )
    )
    with PACT:
        async with AsyncClient(base_url="http://localhost:1234") as client:
            resp = await client.post(
                "/api/v1/invoices",
                json={"amount": "99.99", "currency": "USD", "description": "Monthly subscription",
                      "due_date": "2026-05-01T00:00:00Z"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["currency"] == "USD"
        assert data["status"] == "pending"
```

### 4.8 New service Dockerfile (tool-generated)

```dockerfile
# billing_service/Dockerfile  (generated by extract_service)
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY common/ /common/
COPY billing_service/pyproject.toml billing_service/uv.lock ./
RUN pip install uv && uv sync --no-dev

COPY billing_service/ ./

FROM base AS test
RUN uv sync --dev
RUN uv run pytest tests/ -x -q

FROM base AS production
EXPOSE 8001
CMD ["uv", "run", "uvicorn", "billing_service.app.main:app", \
     "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
```

### 4.9 docker-compose.yml update (tool-generated diff)

```yaml
# docker-compose.yml — services section (after extract_service)
services:
  monolith:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - BILLING_SERVICE_URL=http://billing-service:8001
    depends_on:
      - db
      - billing-service
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3

  billing-service:
    build:
      context: .
      dockerfile: billing_service/Dockerfile
      target: production
    ports:
      - "8001:8001"
    environment:
      - DATABASE_URL=${DATABASE_URL}
    depends_on:
      - db
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 10s
      timeout: 5s
      retries: 3

  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

### 4.10 GitHub Actions CI workflow (tool-generated)

```yaml
# .github/workflows/billing-service.yml  (generated by extract_service)
name: billing-service CI

on:
  push:
    branches: [main, feature/**]
    paths:
      - "billing_service/**"
      - "common/**"
  pull_request:
    paths:
      - "billing_service/**"
      - "common/**"

env:
  PYTHON_VERSION: "3.12"
  DATABASE_URL: postgresql+asyncpg://test:test@localhost:5432/test_billing

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test_billing
        options: >-
          --health-cmd pg_isready
          --health-interval 5s
          --health-timeout 3s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - name: Install uv
        run: pip install uv
      - name: Install dependencies
        run: cd billing_service && uv sync --dev
      - name: Lint
        run: cd billing_service && uv run ruff check .
      - name: Type check
        run: cd billing_service && uv run mypy . --strict
      - name: Unit + integration tests
        run: cd billing_service && uv run pytest tests/ -v --cov=app --cov-report=xml
      - name: Contract tests (Pact)
        run: cd billing_service && uv run pytest tests/test_contract*.py -v
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: billing_service/coverage.xml
```

### 4.11 Extraction idempotency guard (tool internals)

```python
# scripts/extract_service/idempotency.py
import json
import hashlib
from pathlib import Path
from typing import Any


MANIFEST_FILENAME = "EXTRACTION_MANIFEST.json"


class ExtractionManifest:
    """Track extraction state so re-runs are safe and deterministic."""

    def __init__(self, project_root: Path, service_name: str):
        self.manifest_path = project_root / service_name / MANIFEST_FILENAME
        self._data: dict[str, Any] = {}

    def load(self) -> bool:
        """Returns True if a prior manifest exists."""
        if self.manifest_path.exists():
            self._data = json.loads(self.manifest_path.read_text())
            return True
        return False

    def record_move(self, src: Path, dst: Path, checksum: str) -> None:
        self._data.setdefault("moves", []).append(
            {"src": str(src), "dst": str(dst), "checksum": checksum}
        )

    def record_rewrite(self, file: Path, old_import: str, new_import: str) -> None:
        self._data.setdefault("rewrites", []).append(
            {"file": str(file), "old": old_import, "new": new_import}
        )

    def save(self) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(self._data, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def checksum(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]

    def already_moved(self, src: Path) -> bool:
        return any(
            m["src"] == str(src)
            for m in self._data.get("moves", [])
        )
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Monolith tests always pass post-extraction** | `pytest tests/` runs automatically after every file modification; tool aborts if exit code != 0. Enforced in `extract_service/_runner.py:verify_monolith_tests()`. |
| QS-2 | **Shared code lives exclusively in `common/`, never duplicated** | `dep_graph.py:find_shared_deps()` moves cross-cutting modules to `common/`; a post-extraction grep for duplicate class names across both codebases raises `ExtractionError`. |
| QS-3 | **New service must be self-contained (build + run in isolation)** | `docker build billing_service/` and `docker run --rm billing-service curl /health` are executed as part of the tool's post-extraction validation step in `_runner.py:verify_service_builds()`. |
| QS-4 | **Proxy mode latency overhead never exceeds 50 ms** | `httpx.AsyncClient` uses a pre-warmed connection pool; integration benchmark T-20 measures p99 end-to-end latency and fails if > 50 ms. |
| QS-5 | **Generated client is fully typed — no `dict` crossing the boundary** | `generate_client.py` emits Pydantic v2 `BaseModel` request/response types for every endpoint; `mypy --strict` runs on the generated client and fails on `Any` escapes. |
| QS-6 | **Contract tests generated from actual monolith OpenAPI schema** | `contracts/generate_pact.py` reads `GET /openapi.json` from a running monolith and generates Pact contracts; contracts are committed alongside source in `billing_service/tests/contracts/`. |
| QS-7 | **Extraction is idempotent — re-run produces identical state** | `ExtractionManifest.already_moved()` prevents double-moves; file checksums are compared before writing; `T-27` re-runs the tool twice and asserts `git diff == empty`. |
| QS-8 | **Database split is opt-in, explicit, and documented** | DB split is gated behind an explicit `--db-split` flag; default is shared DB; if activated, the migration script is generated with FK removal warnings and a separate rollback procedure. |
| QS-9 | **Every generated file passes `ruff check` and `mypy --strict`** | Post-generation linting runs in `_runner.py:lint_generated_files()`; failures halt the tool with a diff showing the offending lines. |
| QS-10 | **AST rewrites never introduce import cycles** | After import rewriting, `dep_graph.py:detect_cycles()` runs; any cycle between `common/`, monolith, and new service raises `CircularDependencyError` before files are written. |
| QS-11 | **Port collision detected before container start** | `_runner.py:check_port_available(port)` calls `socket.connect_ex` before any Docker operation; if port is taken, the tool prints the occupying process and suggests `new_service_port + 1`. |
| QS-12 | **Extraction manifest committed to version control** | `EXTRACTION_MANIFEST.json` is created inside the new service directory and included in the initial `git commit` that the tool makes; it is the audit trail for rollback. |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | New service directory `{new_service_name}/` created at project root | Directory exists, contains `app/`, `tests/`, `pyproject.toml` |
| CC-02 | All specified `module_paths` moved to new service | Paths absent from monolith `src/`; present under `{service}/app/` |
| CC-03 | Shared modules moved to `common/` package | `common/` directory exists; modules referenced by both services import from `common/` |
| CC-04 | Monolith imports from extracted modules rewritten to `app.clients.{service}_client` | `grep -r "from app.{module}" app/` returns no hits for extracted module names |
| CC-05 | Typed client `app/clients/{service}_client.py` generated with all endpoints | File exists; `mypy --strict` passes; all route paths present |
| CC-06 | `EXTRACTION_MANIFEST.json` created inside new service directory | File exists, JSON parses, contains `moves` and `rewrites` keys |
| CC-07 | `Dockerfile` created in `{new_service_name}/` with multi-stage build | File exists; `docker build` exits 0 |
| CC-08 | `docker-compose.yml` updated with new service block | `docker-compose config` validates; new service name present |
| CC-09 | `.github/workflows/{service_name}.yml` CI workflow created | File exists; workflow YAML valid; runs lint + test + contract jobs |
| CC-10 | Pact contract tests generated in `{service}/tests/test_contract_{service}.py` | File exists; `pytest test_contract_*` passes against running service |
| CC-11 | Proxy middleware registered in monolith router for all extracted routes | Each extracted route path returns 200 from monolith via proxy in integration test |
| CC-12 | New service has its own `alembic.ini` or migration guide | File exists or migration doc references shared DB strategy |
| CC-13 | `common/` package has its own `pyproject.toml` so both services can depend on it | File exists; both `pyproject.toml` files list `common` as dependency |
| CC-14 | All extracted models use SQLAlchemy 2.0 `Mapped` / `mapped_column` API | `grep -r "Column(" {service}/` returns 0 hits |
| CC-15 | All extracted schemas use Pydantic v2 `model_config = ConfigDict(...)` | `grep "class Config" {service}/` returns 0 hits |
| CC-16 | New service health endpoint `GET /health` returns `{"status": "ok"}` | `curl http://localhost:{port}/health` returns 200 |
| CC-17 | Monolith test suite passes post-extraction (0 failures) | `pytest tests/ -q` exits 0 |
| CC-18 | New service test suite passes (0 failures) | `pytest {service}/tests/ -q` exits 0 |
| CC-19 | Coverage for extracted modules ≥ 90% in new service | `pytest --cov` report shows ≥ 90% for `{service}/app/` |
| CC-20 | `ruff check` passes on new service and common | `ruff check {service}/ common/` exits 0 with 0 errors |
| CC-21 | `mypy --strict` passes on new service client | `mypy app/clients/{service}_client.py --strict` exits 0 |
| CC-22 | Tool execution time ≤ 10s for 20-module extraction | Timed via `time` in T-01 |
| CC-23 | Proxy latency overhead < 50 ms (p99) measured in integration test | Benchmark T-20 passes |
| CC-24 | Tool re-run (idempotent) produces no git diff | `git diff` after second run is empty — T-27 |
| CC-25 | Split mode removes proxy and routes from monolith router entirely | `grep -r "proxy_post\|proxy_get" app/routes/{module}.py` returns 0 hits |
| CC-26 | Generated client uses `httpx.AsyncClient` with retry transport | `grep AsyncHTTPTransport` in client file; `retries=` param present |
| CC-27 | Service port `new_service_port` appears in `docker-compose.yml` | Port binding visible in `docker-compose config` output |
| CC-28 | Circular dependency detection fires and blocks extraction if cycle found | T-28 triggers cycle; tool exits non-zero with `CircularDependencyError` |
| CC-29 | `EXTRACTION_MANIFEST.json` records every file moved and every import rewritten | Manifest `moves` count equals number of moved files; `rewrites` count equals rewritten import lines |
| CC-30 | New service container image size ≤ 200 MB (slim base) | `docker image inspect {service}:latest --format '{{.Size}}'` < 209715200 |

---

## 7. Definition of Done

The tool is "done" when ALL of the following are true:

- [ ] All 30 Completeness Criteria verified passing
- [ ] All 12 Quality Standards enforced and documented
- [ ] All 8 Invariants hold under all test scenarios (see §8)
- [ ] All 25 User Stories have passing acceptance tests (see §9)
- [ ] All 30 Test Cases pass with no skips (see §10)
- [ ] Tool is idempotent: running twice on same input produces identical file tree (T-27)
- [ ] Rollback procedure documented, tested, and verified by a maintainer (see §12)
- [ ] Proxy mode latency < 50 ms confirmed via benchmark (T-20)
- [ ] Contract tests generated and passing against both monolith and new service
- [ ] New service Docker image builds and runs in isolation (`docker run` health endpoint returns 200)
- [ ] `mypy --strict` passes on generated client and new service source
- [ ] `ruff check` passes with 0 errors on all generated files
- [ ] All 15 edge cases handled correctly (see §13)
- [ ] Documentation updated: `KNOWLEDGE.md`, `manifest.yaml`, `SKILL.md`
- [ ] Tool registered in `mcp_server.py` and exposed via MCP interface

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-ES-01 | **Monolith tests ALWAYS pass after extraction completes** | `_runner.py:verify_monolith_tests()` runs `pytest tests/` and aborts with rollback if exit code != 0 | T-17 |
| INV-ES-02 | **Shared code ALWAYS lives in `common/`, never duplicated across services** | `dep_graph.py:find_shared_deps()` moves shared modules to `common/`; post-extraction check raises `ExtractionError` if identical class found in two locations | T-05 |
| INV-ES-03 | **New service ALWAYS builds and runs in isolation from the monolith** | `_runner.py:verify_service_builds()` runs `docker build` + `docker run --rm ... /health` against the new service without mounting monolith code | T-09 |
| INV-ES-04 | **Proxy mode NEVER introduces more than 50 ms latency overhead** | `httpx.AsyncClient` with connection pooling; integration benchmark T-20 measures p99 and fails hard if > 50 ms | T-20 |
| INV-ES-05 | **Client generated by tool is ALWAYS typed — no untyped `dict` at boundary** | `generate_client.py` emits Pydantic v2 models for all request/response types; `mypy --strict` enforced in CI via `.github/workflows/{service}.yml` | T-13 |
| INV-ES-06 | **Contract tests ALWAYS generated from actual monolith OpenAPI schema** | `contracts/generate_pact.py` reads live `/openapi.json`; Pact contracts are committed and must pass before merging in CI | T-15 |
| INV-ES-07 | **Extraction is ALWAYS idempotent — a second run produces no changes** | `ExtractionManifest.already_moved()` short-circuits re-moves; checksums compared before writes; `git diff` after re-run must be empty | T-27 |
| INV-ES-08 | **Database split NEVER happens in the same step as service extraction** | DB split gated behind explicit `--db-split` flag, absent by default; tool documentation states this as a separate migration phase | T-29 |

---

## 9. User Stories

### 9.1 Basic Extraction (US-01 .. US-05)

**US-01: Extract a single module into a standalone service**
- **As a** backend engineer maintaining a growing monolith
- **I want** to extract the `billing` module into its own service with one tool call
- **So that** the billing team can deploy independently without coordinating with the core team
- **Given:** a monolith with `app/routes/billing.py`, `app/services/billing.py`, `app/models/invoice.py`
- **When:** I call `extract_service(project_dir, module_paths=["routes/billing", "services/billing", "models/invoice"], new_service_name="billing_service")`
- **Then:**
  - `billing_service/` directory is created with complete scaffold (CC-01)
  - All three modules moved to `billing_service/app/` (CC-02)
  - Monolith test suite still passes (INV-ES-01)
  - Typed client `app/clients/billing_client.py` generated (CC-05)

**US-02: Extract five modules with transitive dependencies**
- **As a** tech lead planning a service boundary migration
- **I want** to extract five related modules where some import from each other
- **So that** transitive dependencies are correctly resolved and nothing is missed
- **Given:** modules A–E where A imports B, B imports C (shared with monolith), D and E are standalone
- **When:** I run `extract_service(..., module_paths=["A","B","D","E"])` (C is shared)
- **Then:**
  - Modules A, B, D, E are in new service; module C is in `common/` (CC-03)
  - Both monolith and new service import C from `common.C` (INV-ES-02)
  - Dependency graph traversal completes in < 3s (CC-22)
  - No import errors when running both services (T-03)

**US-03: Verify boundary contract is captured as OpenAPI + Pact**
- **As a** QA engineer enforcing API stability
- **I want** the tool to generate Pact contract tests from the existing monolith routes
- **So that** I can detect if either service drifts from the agreed boundary
- **Given:** monolith has `GET /billing/invoices/{id}` and `POST /billing/invoices` routes
- **When:** extraction completes with `generate_client=True`
- **Then:**
  - Pact contract file committed in `billing_service/tests/contracts/` (CC-10)
  - Contract test `test_contract_billing.py` passes against running new service (CC-10)
  - Both tests reference INV-ES-06 in comments
  - CI workflow runs contract tests on every push (CC-09)

**US-04: Extraction creates complete Docker + CI artefacts**
- **As a** DevOps engineer onboarding the new service**
- **I want** the new service to have a `Dockerfile`, a `docker-compose.yml` entry, and a GitHub Actions workflow out of the box
- **So that** CI is green from day one with no manual setup
- **Given:** extraction completes successfully
- **When:** I push the extracted code to GitHub
- **Then:**
  - `billing_service/Dockerfile` uses multi-stage build with slim image (CC-07)
  - `docker-compose.yml` has `billing-service` block with healthcheck (CC-08)
  - `.github/workflows/billing-service.yml` runs lint + tests + contract tests (CC-09)
  - `docker build billing_service/` exits 0 with image ≤ 200 MB (CC-30)

**US-05: Extraction manifest enables full audit trail**
- **As a** senior engineer reviewing the extraction after the fact
- **I want** a machine-readable manifest of every file moved and import rewritten
- **So that** I can audit the change, verify correctness, and use it as a rollback recipe
- **Given:** extraction completes for `billing` (3 files moved, 12 import rewrites)
- **When:** I read `billing_service/EXTRACTION_MANIFEST.json`
- **Then:**
  - `moves` array contains 3 entries with `src`, `dst`, and `checksum` (CC-29)
  - `rewrites` array contains 12 entries with `file`, `old`, `new` (CC-29)
  - Manifest is valid JSON and committed to git (QS-12)
  - Tool re-run with same params produces no new entries in manifest (INV-ES-07)

### 9.2 Communication Modes (US-06 .. US-10)

**US-06: REST/HTTP communication mode generates typed httpx client**
- **As a** developer extracting a service with HTTP communication**
- **I want** the monolith to call the new service via a generated typed client
- **So that** I get IDE autocomplete and compile-time type safety across the service boundary
- **Given:** `communication="http"`, `generate_client=True`
- **When:** extraction completes
- **Then:**
  - `app/clients/billing_client.py` generated with `BillingServiceClient` class (CC-05)
  - Every endpoint has a typed method using Pydantic v2 request/response models (INV-ES-05)
  - `mypy --strict` passes on the generated file (QS-9)
  - Client uses `httpx.AsyncHTTPTransport(retries=3)` for resilience (CC-26)
  - `T-13` passes confirming typed boundary

**US-07: Proxy mode serves extracted routes via monolith**
- **As a** platform engineer rolling out a zero-downtime migration
- **I want** the monolith to proxy billing requests to the new service transparently
- **So that** clients do not need to update their URLs during rollout
- **Given:** `communication="http"`, proxy mode selected
- **When:** monolith receives `POST /api/v1/billing/invoices`
- **Then:**
  - Monolith forwards request to `billing-service:8001/api/v1/invoices` (CC-11)
  - Response proxied back with original status code and headers
  - Latency overhead < 50 ms p99 (INV-ES-04, T-20)
  - No request body or header loss verified by T-21

**US-08: Split mode removes proxy routes from monolith entirely**
- **As a** engineering manager completing a migration after traffic is fully shifted
- **I want** to remove the proxy shim from the monolith so there is no dead code
- **So that** monolith has no knowledge of billing routes after cutover
- **Given:** split mode activated (`mode="split"`)
- **When:** extraction completes
- **Then:**
  - Monolith router has no route for `/billing/**` (CC-25)
  - Monolith routes file no longer imports from billing modules
  - New service serves `/api/v1/invoices` directly
  - Monolith tests still pass (INV-ES-01, T-17)

**US-09: Contract tests detect API drift between monolith and new service (INV-ES-06)**
- **As a** QA lead enforcing service contract stability
- **I want** the Pact contract tests to fail fast when either service drifts from the agreed API
- **So that** I catch breaking changes in CI before they reach production
- **Given:** `billing_service` was extracted with Pact contracts generated (T-15)
- **When:** a developer changes the response schema in `billing_service` without updating the consumer
- **Then:**
  - Pact provider test fails with clear message: "body has mismatch at `currency`"
  - CI workflow fails on the `Contract tests (Pact)` job step (CC-09)
  - INV-ES-06 is the governing invariant and referenced in the test failure output
  - Contract version is pinned and drift is caught before merge (T-15)

**US-10: gRPC communication mode scaffolds protobuf definitions**
- **As a** platform engineer preferring gRPC for internal service communication
- **I want** the extraction to scaffold `.proto` files and typed gRPC stubs
- **So that** I can use gRPC for low-latency internal calls instead of REST
- **Given:** `communication="grpc"`
- **When:** extraction completes
- **Then:**
  - `billing_service/proto/billing.proto` created from inferred service interface (CC-01)
  - Python stubs generated via `grpc_tools.protoc`
  - Monolith gRPC client stub generated in `app/clients/billing_grpc_client.py`
  - `T-14` verifies gRPC stub compiles and client method signatures are correct

### 9.3 Shared Code (US-11 .. US-15)

**US-11: Shared models moved to `common/` package (INV-ES-02)**
- **As a** developer extracting a service that shares Pydantic schemas with the monolith
- **I want** shared schemas to live in exactly one place (`common/`)
- **So that** changes propagate consistently without copy-paste drift
- **Given:** `InvoicePublic` schema used in both monolith (in response) and billing_service (in model)
- **When:** extraction completes
- **Then:**
  - `common/schemas/invoice.py` contains `InvoicePublic` (CC-03)
  - Monolith imports `from common.schemas.invoice import InvoicePublic`
  - New service imports `from common.schemas.invoice import InvoicePublic`
  - INV-ES-02 verified by T-05 (no duplicate class names across services)

**US-12: Tool rejects extraction if duplication would occur**
- **As a** developer accidentally specifying a module used by 10 other monolith modules
- **I want** the tool to block extraction and explain exactly which callers depend on that module
- **So that** I understand the impact and can decide to move the module to `common/` instead
- **Given:** `app/utils/currency.py` is imported by 10 monolith modules and 2 billing modules
- **When:** I include `utils/currency` in `module_paths`
- **Then:**
  - Tool moves `currency.py` to `common/utils/currency.py` (CC-03)
  - All 12 callers rewritten to `from common.utils.currency import ...` (CC-04)
  - Tool prints summary: "Moved 1 shared module to common/; rewrote 12 import sites"
  - T-05 verifies no duplicate class names remain

**US-13: Dependency graph shows all cross-cutting dependencies (CC-03)**
- **As a** architect planning a phased extraction over multiple sprints
- **I want** to see the full dependency graph before committing to any extraction
- **So that** I can plan the `common/` boundary correctly in advance
- **Given:** `extract_service(..., dry_run=True)` is called
- **When:** tool runs without writing any files
- **Then:**
  - Tool prints dependency graph with modules color-coded as: "extract", "shared → common/", "monolith-only"
  - Graph construction time < 3s (CC-22)
  - No files are written (dry_run respected)
  - T-04 verifies graph accuracy against known module structure

**US-14: Circular dependencies between monolith and extracted module are blocked (T-28)**
- **As a** developer trying to extract a module that has a circular import with the monolith
- **I want** the tool to detect the cycle and stop before writing any files
- **So that** I am not left in a partially-extracted broken state
- **Given:** `app/routes/billing.py` imports `app/core/notifier.py` which imports `app/routes/billing.py`
- **When:** I call `extract_service(..., module_paths=["routes/billing"])`
- **Then:**
  - Tool detects cycle `routes/billing → core/notifier → routes/billing` (T-28)
  - Tool exits with `CircularDependencyError` and cycle path printed (CC-28)
  - Zero files are written (rollback not needed — nothing changed)
  - QS-10 is the governing standard

**US-15: `common/` package has its own `pyproject.toml` (CC-13)**
- **As a** developer maintaining both services long-term
- **I want** `common/` to be an installable Python package
- **So that** both services pin it as a dependency and version bumps are explicit
- **Given:** extraction creates `common/` with shared schemas and models
- **When:** I inspect the generated file tree
- **Then:**
  - `common/pyproject.toml` exists with `name = "common"`, `version = "0.1.0"` (CC-13)
  - `monolith/pyproject.toml` has `common = { path = "../common" }` (CC-13)
  - `billing_service/pyproject.toml` has `common = { path = "../common" }` (CC-13)
  - `uv sync` succeeds in both service directories

### 9.4 Database Strategies (US-16 .. US-20)

**US-16: Default shared-DB strategy — services share same PostgreSQL instance (INV-ES-08)**
- **As a** developer doing a first extraction with minimal risk
- **I want** both services to share the same database with zero schema changes
- **So that** I can validate the new service boundary before committing to a DB split
- **Given:** `extract_service(...)` called without `--db-split` (default)
- **When:** extraction completes
- **Then:**
  - Both services connect to same `DATABASE_URL` (CC-08)
  - No migration is generated (schema unchanged)
  - `EXTRACTION_MANIFEST.json` records `db_strategy: "shared"` (CC-06)
  - INV-ES-08 confirms split did not happen (T-29)

**US-17: Explicit DB split generates migration with FK removal warnings**
- **As a** database administrator ready to fully separate billing data
- **I want** the tool to generate a migration that moves billing tables to a separate DB
- **So that** billing can have its own connection pool, backups, and failover
- **Given:** `--db-split` flag provided; billing tables are `invoices`, `payments`
- **When:** extraction completes
- **Then:**
  - Migration `alembic/versions/0045_split_billing_db.py` generated (CC-12)
  - Migration removes FKs from billing tables and adds migration doc explaining data integrity risk
  - Tool prints explicit warning: "DB split is irreversible. Review migration before applying." (QS-8)
  - T-29 verifies migration has downgrade() that re-adds FKs

**US-18: Shared DB with separate connection pools**
- **As a** performance engineer wanting billing queries isolated from core traffic
- **I want** the billing service to use a dedicated connection pool even with a shared DB
- **So that** a billing query spike does not starve the monolith's connection pool
- **Given:** `extract_service(...)` with shared DB (default)
- **When:** billing_service starts
- **Then:**
  - `billing_service/app/core/db.py` has its own `create_async_engine(DATABASE_URL, pool_size=5)` (CC-14)
  - Monolith's connection pool unchanged
  - T-16 verifies both services can execute concurrent queries without pool contention

**US-19: Transitional DB — FK constraints documented for deferred removal (CC-12)**
- **As a** DBA managing a multi-phase migration over weeks
- **I want** the extraction manifest to document which FK constraints will need removal in a future DB split
- **So that** I have a clear checklist for phase 2 of the migration
- **Given:** shared DB strategy with `invoices.owner_id → users.id` FK spanning services
- **When:** extraction manifest is read
- **Then:**
  - `EXTRACTION_MANIFEST.json` contains `cross_service_fks` array with each FK name and table (CC-06)
  - Manifest entry reads: `{"constraint": "fk_invoices_owner", "table": "invoices", "references": "users.id", "action": "deferred_removal"}`
  - T-30 verifies manifest correctly enumerates all cross-service FK dependencies

**US-20: DB split rejected if cyclic FK dependency found (CC-28)**
- **As a** DBA running the DB split on tables with mutual FK references
- **I want** the tool to detect and warn about FK cycles before generating broken migrations
- **So that** I do not apply an unrunnable migration to production
- **Given:** `invoices.subscription_id → subscriptions.id` and `subscriptions.latest_invoice_id → invoices.id`
- **When:** `--db-split` is activated
- **Then:**
  - Tool detects FK cycle and emits `FKCycleWarning` with both constraint names
  - Migration is generated with explicit `-- WARNING: FK cycle detected` comment
  - Tool suggests breaking the cycle by nullifying one FK before splitting
  - T-29 passes (migration generated but annotated, not blocked)

### 9.5 Edge Cases and Resilience (US-21 .. US-25)

**US-21: Rollback to monolith if monolith tests fail post-extraction (INV-ES-01)**
- **As a** developer whose extraction broke the monolith test suite
- **I want** the tool to automatically roll back all changes to the pre-extraction state
- **So that** the monolith is never left in a broken intermediate state
- **Given:** extraction modifies `app/routes/billing.py` but the rewrite introduces a syntax error
- **When:** `pytest tests/` fails post-extraction
- **Then:**
  - Tool restores all modified monolith files from git (`git checkout app/`) (§12 Code rollback)
  - New service directory is deleted
  - Tool exits with `ExtractionFailed: monolith tests failed; all changes reverted`
  - INV-ES-01 verified by T-17

**US-22: Tool is fully idempotent — safe to re-run after interruption (INV-ES-07)**
- **As a** developer whose extraction was interrupted mid-run by a network timeout
- **I want** to re-run the tool and get the same result without double-moves or corrupted state
- **So that** I never need to manually clean up a partial extraction
- **Given:** first run completed 60% (manifest written, some files moved, some not)
- **When:** I re-run `extract_service(...)` with identical parameters
- **Then:**
  - Tool reads `EXTRACTION_MANIFEST.json`, skips already-moved files
  - Remaining files are moved and all imports rewritten
  - `git diff` after second run shows zero new changes (CC-24, T-27)
  - INV-ES-07 confirmed by T-27

**US-23: Extraction blocked when circular dependency between service and monolith exists (CC-28)**
- **As a** developer attempting to extract a module tangled with the monolith core
- **I want** the tool to refuse extraction rather than create an unresolvable import cycle
- **So that** I am forced to untangle the dependency before proceeding
- **Given:** `billing.py` imports `core/event_bus.py` which re-imports `billing.py` for event types
- **When:** I call `extract_service(..., module_paths=["routes/billing"])`
- **Then:**
  - `dep_graph.py:detect_cycles()` fires before any file write (QS-10)
  - `CircularDependencyError` raised with full cycle path printed
  - Zero files written; monolith unchanged
  - T-28 covers this exact scenario

**US-24: Scale test — 50 modules extracted without timeout or memory failure**
- **As a** engineering lead extracting a large domain (50 modules) in one pass
- **I want** the tool to handle large extractions without running out of memory or timing out
- **So that** I can do phased extractions without being limited to tiny batches
- **Given:** `module_paths` contains 50 module paths across routes, services, models, schemas
- **When:** `extract_service(...)` runs
- **Then:**
  - Tool completes in < 10s (CC-22)
  - Memory usage < 200 MB throughout execution (QS description)
  - All 50 modules present in new service; monolith tests still pass (INV-ES-01)
  - T-01 benchmarks this scenario

**US-25: Port collision detected and alternate port suggested (CC-11)**
- **As a** developer running the extraction on a machine where port 8001 is already in use
- **I want** the tool to detect the conflict and suggest an available port
- **So that** I can continue without manually scanning for free ports
- **Given:** `new_service_port=8001` but port 8001 is occupied by another process
- **When:** I call `extract_service(..., new_service_port=8001)`
- **Then:**
  - `_runner.py:check_port_available(8001)` detects occupation (QS-11)
  - Tool prints: "Port 8001 in use by PID 12345. Suggested port: 8002."
  - Tool exits with non-zero code; no files written
  - User re-runs with `new_service_port=8002` and extraction succeeds (T-25)

---

## 10. Test Plan

### 10.1 Dependency Discovery (T-01 .. T-06)

| ID | Test Name | Method | Expected |
|----|-----------|--------|----------|
| T-01 | Benchmark 20-module extraction | Time `extract_service(20 modules)` | Completes in < 10s |
| T-02 | Direct dependency resolution | Call `dep_graph.build()` on known fixture | All direct imports resolved correctly |
| T-03 | Transitive dependency resolution | Call `dep_graph.transitive_deps("routes/billing")` | Includes all indirect imports |
| T-04 | Shared dependency detection | Module used by both monolith and extracted set | Classified as `common/` module |
| T-05 | Duplicate class name detection | Same class in two locations post-extraction | `ExtractionError` raised |
| T-06 | Dry-run mode prints graph | `dry_run=True` call | No files written; graph printed to stdout |

### 10.2 Extraction (T-07 .. T-12)

| ID | Test Name | Method | Expected |
|----|-----------|--------|----------|
| T-07 | Route file extraction | Extract `routes/billing.py` | File present in new service, absent from monolith |
| T-08 | Model file extraction | Extract `models/invoice.py` | SQLAlchemy model intact; `Mapped` API preserved |
| T-09 | New service builds in isolation | `docker build billing_service/` | Exit code 0; image ≤ 200 MB |
| T-10 | Test files co-extracted | Extract routes/billing | `billing_service/tests/test_billing.py` exists |
| T-11 | Dockerfile generated correctly | Inspect generated Dockerfile | Multi-stage, slim base, EXPOSE correct port |
| T-12 | CI workflow generated | Inspect `.github/workflows/billing-service.yml` | Valid YAML; lint + test + contract jobs present |

### 10.3 Communication (T-13 .. T-18)

| ID | Test Name | Method | Expected |
|----|-----------|--------|----------|
| T-13 | Typed client has all endpoint methods | Inspect generated client | Every route has typed method; `mypy --strict` passes |
| T-14 | gRPC stub compilation | `communication="grpc"` extraction | `billing.proto` + stubs compile without errors |
| T-15 | Pact contract generated and passes | `pytest test_contract_billing.py` | Consumer + provider tests both pass |
| T-16 | Concurrent query isolation | Simultaneous DB queries from both services | Neither pool starved; queries return correct data |
| T-17 | Monolith tests pass post-extraction | `pytest tests/` in monolith root | 0 failures, 0 errors |
| T-18 | Events communication mode | `communication="events"` | Event publisher in new service; consumer stubs in monolith |

### 10.4 Transition Modes (T-19 .. T-24)

| ID | Test Name | Method | Expected |
|----|-----------|--------|----------|
| T-19 | Proxy mode routes requests correctly | `POST /billing/invoices` via monolith | Request forwarded to billing_service; response proxied back |
| T-20 | Proxy latency benchmark | 1000-request load via `locust` | p99 overhead < 50 ms (INV-ES-04) |
| T-21 | Proxy preserves headers and body | Forward request with custom headers | All headers and full body intact in new service |
| T-22 | Split mode removes proxy from monolith | Inspect monolith router after split | No `proxy_post` or `proxy_get` calls in billing routes |
| T-23 | Rollback restores monolith | Simulate post-extraction test failure | All monolith files restored from git; new service dir deleted |
| T-24 | Proxy disabled when new service unreachable | Kill billing_service container | Monolith returns 503 with clear error; does not crash |

### 10.5 Edge Cases (T-25 .. T-30)

| ID | Test Name | Method | Expected |
|----|-----------|--------|----------|
| T-25 | Port collision detection | `new_service_port` already in use | Tool exits non-zero; alternative port suggested |
| T-26 | 1-module minimal extraction | `module_paths=["routes/health"]` | Minimal scaffold generated; no unnecessary dependencies |
| T-27 | Idempotency — second run produces no diff | Run extraction twice | `git diff` empty after second run (INV-ES-07) |
| T-28 | Circular dependency blocks extraction | Cyclic import between extracted module and monolith | `CircularDependencyError` raised; zero files written |
| T-29 | DB split is not triggered by default | Run extraction without `--db-split` | No migration generated; `db_strategy: shared` in manifest (INV-ES-08) |
| T-30 | Cross-service FK manifest entries | Shared-DB extraction with FK spanning services | Manifest `cross_service_fks` array populated correctly |

---

## 11. Interaction Matrix

| Tool | Interaction Type | Description |
|------|-----------------|-------------|
| `fastapi_add_multi_tenancy` (TOOL-008) | Data model dependency | If monolith uses multi-tenancy, extracted service inherits `tenant_id` on models and the `common/` lib must include `TenantScopedMixin`; tool detects this and copies mixin to `common/models/mixins.py` |
| `fastapi_add_outbox_pattern` (TOOL-023) | Event bus dependency | If outbox is in extracted modules, `OutboxDispatcher` worker must be started in the new service; tool generates a dedicated ARQ worker config in `billing_service/app/workers/` |
| `fastapi_event_driven_architecture` (TOOL-046) | Communication boundary | If `communication="events"`, TOOL-045 generates event publisher stubs compatible with the event schema produced by TOOL-046; consumer stubs injected into monolith |
| `fastapi_blast_radius` (TOOL-035) | Dependency analysis | TOOL-045 reuses blast-radius engine from TOOL-035 to compute which monolith modules are affected by the extraction; must be installed before running extraction |
| `fastapi_dependency_graph` (TOOL-039) | Import graph | TOOL-045 calls TOOL-039's graph builder to resolve transitive dependencies; the `DependencyGraph` class in `dep_graph.py` is derived from TOOL-039's implementation |
| `fastapi_api_spec_compliance` (TOOL-033) | OpenAPI validation | After extraction, TOOL-033 validates that the new service's OpenAPI spec matches the original monolith endpoints for the extracted routes; spec compliance gate blocks merge if schemas differ |
| `fastapi_generate_sdk` (TOOL-047) | Client generation | TOOL-045's `generate_client=True` delegates to TOOL-047's SDK generator for the HTTP client; if TOOL-047 is available, use it; otherwise fall back to built-in `generate_client.py` |
| `fastapi_add_rate_limiting` (TOOL-011) | Middleware | If rate limiting middleware is present in extracted routes, the tool replicates the rate-limit config in the new service and injects it into the new service's `main.py` |
| `fastapi_add_auth_jwt` (TOOL-004) | Authentication | If JWT auth dependencies exist in extracted routes, tool generates an identical `require_auth` dependency in the new service using the same secret and algorithm from `settings` |
| `fastapi_add_observability` (TOOL-021) | Tracing | If Langfuse/OpenTelemetry is instrumented in monolith, TOOL-045 adds equivalent tracing middleware to the new service and generates a `OTEL_SERVICE_NAME=billing_service` env var |
| `fastapi_add_caching` (TOOL-016) | Redis dependency | If extracted modules use Redis caching, tool adds `REDIS_URL` to new service env vars and replicates the cache decorator import chain from `common/core/cache.py` |
| `fastapi_database_migrations` (TOOL-006) | Alembic config | For shared-DB mode, tool generates a `billing_service/alembic.ini` pointing to the shared DB; for DB-split mode, tool generates a separate Alembic env with the split DB URL |
| `fastapi_add_background_tasks` (TOOL-020) | Worker replication | If extracted modules contain ARQ background tasks, tool generates a dedicated `worker.py` in the new service with the same task registry |
| `fastapi_health_checks` (TOOL-003) | Health endpoint | New service always gets `GET /health` endpoint generated by TOOL-045; if TOOL-003 is installed, it upgrades the health endpoint to include DB and dependency checks automatically |
| `fastapi_generate_tests` (TOOL-019) | Test scaffold | TOOL-045 generates basic route tests for the new service; if TOOL-019 is installed, it enriches the test scaffold with parametrized happy/sad path coverage |

---

## 12. Rollback Procedure

### 12.1 Code Rollback — Monolith Import Rewrites

When the extraction rewrites monolith imports and tests fail, restore in three steps:

```bash
# Step 1: identify modified files from extraction manifest
cat billing_service/EXTRACTION_MANIFEST.json | python3 -c "
import json, sys
m = json.load(sys.stdin)
for r in m.get('rewrites', []):
    print(r['file'])
" | sort -u > /tmp/rewritten_files.txt

# Step 2: restore each modified monolith file from git
while IFS= read -r f; do
  git checkout HEAD -- "$f"
  echo "Restored: $f"
done < /tmp/rewritten_files.txt

# Step 3: verify monolith tests pass
cd monolith && PYTHONPATH=src pytest tests/ -q
echo "Exit code: $?"
```

### 12.2 New Service Directory Removal

If extraction fails at any stage, remove the partially created service:

```bash
# Remove new service directory entirely
SERVICE_NAME="billing_service"
if [ -d "$SERVICE_NAME" ]; then
  rm -rf "$SERVICE_NAME"
  echo "Removed $SERVICE_NAME/"
fi

# Remove generated client from monolith
CLIENT_FILE="app/clients/${SERVICE_NAME}_client.py"
if [ -f "$CLIENT_FILE" ]; then
  git checkout HEAD -- "$CLIENT_FILE" 2>/dev/null || rm -f "$CLIENT_FILE"
  echo "Removed/restored: $CLIENT_FILE"
fi

# Verify monolith is clean
git status --short
```

### 12.3 Docker Compose Rollback

Revert `docker-compose.yml` to pre-extraction state:

```bash
# Restore docker-compose.yml from git
git checkout HEAD -- docker-compose.yml

# Verify compose config is valid
docker-compose config > /dev/null && echo "docker-compose.yml OK"

# Confirm billing-service no longer referenced
grep -c "billing-service" docker-compose.yml && echo "WARNING: still referenced" \
  || echo "OK: billing-service removed"
```

### 12.4 Database Rollback (DB Split Only)

N/A — database split does not occur by default (INV-ES-08). If `--db-split` was explicitly used and the migration was applied:

```bash
# Rollback the DB split migration
cd monolith && alembic downgrade 0044

# Verify FK constraints restored
psql "$DATABASE_URL" -c "\d+ invoices" | grep fk_invoices_owner
echo "FK restored: $?"

# Confirm both services still connect to shared DB
psql "$DATABASE_URL" -c "SELECT count(*) FROM invoices;"
```

### 12.5 Failure Mode: Monolith Tests Fail After Extraction

This is the most common failure. The tool handles it automatically, but if manual intervention is needed:

```bash
# Diagnose which test failed and why
cd monolith && PYTHONPATH=src pytest tests/ -v --tb=short 2>&1 | head -60

# Identify the first import error (usually a missing common/ dep)
python3 -c "import app.routes.billing" 2>&1

# If import fails due to missing common/ package, install it temporarily
pip install -e common/

# Re-run tests to confirm fix
PYTHONPATH=src pytest tests/ -q

# If tests pass now, the fix is adding common/ to monolith's pyproject.toml
grep -n "common" monolith/pyproject.toml || echo "Missing common dependency!"
```

### 12.6 Failure Mode: Proxy Mode Broken — Billing Service Unreachable

If the new service container crashes after extraction, re-route traffic to monolith's original handlers:

```bash
# Step 1: check service health
curl -sf http://localhost:8001/health || echo "billing-service DOWN"

# Step 2: disable proxy middleware in monolith router temporarily
# Edit app/routes/billing.py — revert to direct handlers
git checkout HEAD -- app/routes/billing.py

# Step 3: restart monolith with direct handlers
docker-compose restart monolith

# Step 4: verify monolith serves billing routes directly
curl -sf http://localhost:8000/api/v1/billing/invoices -H "Authorization: Bearer $TOKEN"
echo "Direct billing response: $?"

# Step 5: diagnose new service crash
docker logs billing_service --tail=50
docker-compose up billing-service --build
```

### 12.7 Failure Mode: CI Workflow Fails — Pact Contract Mismatch

If Pact contract tests fail after extraction due to schema drift:

```bash
# Step 1: compare OpenAPI schemas
diff <(curl -s http://localhost:8000/openapi.json | jq '.paths["/api/v1/billing/invoices"]') \
     <(curl -s http://localhost:8001/openapi.json | jq '.paths["/api/v1/invoices"]')

# Step 2: identify the drifted field
# Look for lines like: "< 'currency'" or "> 'currency_code'"

# Step 3: update the new service schema to match the contract
# Edit billing_service/app/schemas/invoice.py

# Step 4: regenerate Pact contracts
cd billing_service && python -m contracts.generate_pact

# Step 5: run contract tests locally
pytest tests/test_contract_billing.py -v

# Step 6: commit updated contracts
git add billing_service/tests/contracts/ billing_service/app/schemas/
git commit -m "fix(billing): align schema with pact contract"
```

### 12.8 Emergency: Re-Merge Extracted Service Back Into Monolith

If the extraction is abandoned entirely and the service must be merged back:

```bash
# Step 1: read manifest to know exactly what was moved
MANIFEST="billing_service/EXTRACTION_MANIFEST.json"
python3 -c "
import json
m = json.load(open('$MANIFEST'))
for move in m['moves']:
    print(f\"mv '{move['dst']}' '{move['src']}'\")
" > /tmp/reverse_moves.sh
cat /tmp/reverse_moves.sh  # review before executing

# Step 2: execute reverse moves
bash /tmp/reverse_moves.sh

# Step 3: restore original imports in monolith
python3 -c "
import json
m = json.load(open('$MANIFEST'))
for rw in m['rewrites']:
    content = open(rw['file']).read()
    content = content.replace(rw['new'], rw['old'])
    open(rw['file'], 'w').write(content)
    print(f\"Restored import in {rw['file']}\")
"

# Step 4: remove generated client and proxy routes
rm -f app/clients/billing_client.py

# Step 5: run full test suite to confirm re-merge succeeded
PYTHONPATH=src pytest tests/ -q
echo "Re-merge test result: $?"

# Step 6: delete new service directory
rm -rf billing_service/
git add -A && git commit -m "revert: re-merge billing_service into monolith"
```

---

## 13. Edge Cases

| ID | Scenario | Expected Behavior |
|----|----------|-------------------|
| EC-01 | Circular import between extracted module and monolith core | Tool raises `CircularDependencyError` with full cycle path; zero files written |
| EC-02 | Extracted module uses raw SQL referencing monolith tables | Flagged with `CrossServiceSQL` warning and manual resolution checklist |
| EC-03 | Module has private `_internal` imports across boundary | Moved to `common/_internal/` with deprecation warning added to module docstring |
| EC-04 | Single module extraction (minimal case) | Minimal scaffold generated with one route file, Dockerfile, and CI |
| EC-05 | 50-module extraction (maximum scale) | All modules processed in < 10s with < 200 MB memory |
| EC-06 | Proxy mode — new service responds slowly | Monolith proxy times out after 5s and returns 504 Gateway Timeout to client |
| EC-07 | Monolith tests fail post-extraction | All changes automatically reverted via git; tool exits with `ExtractionFailed` error |
| EC-08 | DB split activated with FK cycle in billing tables | `FKCycleWarning` emitted; migration generated with explicit warning comment; not blocked |
| EC-09 | Tool re-run after successful extraction (idempotent) | Manifest read; no files re-moved; `git diff` empty after re-run |
| EC-10 | Client generation fails — OpenAPI schema incomplete | Tool exits with `OpenAPIIncompleteError` and lists missing path items |
| EC-11 | `new_service_port` already in use on host | Tool detects via `socket.connect_ex`; prints occupying PID; suggests next available port |
| EC-12 | Contract tests fail immediately after extraction | CI fails on Pact job; tool prints schema diff between monolith and new service |
| EC-13 | Dockerfile layer cache invalidated by base image update | Multi-stage build separates dependencies from source; only source layer re-built |
| EC-14 | CI pipeline validates locally — fails on ruff or mypy | Tool runs `ruff check` and `mypy --strict` before committing; fails with diff showing offending lines |
| EC-15 | `EXTRACTION_MANIFEST.json` missing after partial extraction | Tool detects missing manifest, assumes fresh extraction, proceeds from scratch after user confirmation |

---

## 14. Acceptance Criteria

✅ 1. `extract_service(project_dir, module_paths, new_service_name)` creates a complete, runnable new service directory with routes, models, schemas, tests, Dockerfile, CI workflow, and typed client in a single invocation.

✅ 2. Monolith test suite (`pytest tests/`) passes with 0 failures immediately after extraction completes, verified by automated post-extraction check.

✅ 3. Proxy mode routes all extracted endpoints through the monolith to the new service with < 50 ms p99 latency overhead, verified by T-20 benchmark.

✅ 4. Typed client generated with Pydantic v2 models for every endpoint passes `mypy --strict` with 0 errors, confirming no untyped dicts cross the service boundary.

✅ 5. Pact contract tests are generated from the original monolith OpenAPI schema and pass against both monolith (consumer) and new service (provider), detected by CI within 30s.

✅ 6. Tool is idempotent: running extraction twice on the same input produces zero changes (`git diff` empty after second run), verified by T-27.

✅ 7. Shared modules are automatically identified and moved to `common/` package with both services correctly importing from it; no duplicate class names exist across the codebase.

✅ 8. Docker image for new service builds successfully (`docker build` exits 0), runs in isolation (health endpoint returns 200 without monolith running), and image size ≤ 200 MB.

✅ 9. Circular dependency detection fires before any file is written when an import cycle is found between extracted module and monolith, exiting with `CircularDependencyError` and zero filesystem changes.

✅ 10. Full rollback procedure documented and tested: monolith can be fully restored to pre-extraction state using `EXTRACTION_MANIFEST.json` and a sequence of git and shell commands detailed in §12.

---

## 15. Implementation Checklist

### 15.1 Project Scaffolding
- [ ] Create `scripts/extract_service/` package with `__init__.py`
- [ ] Implement `_runner.py` as main entry point orchestrating all extraction phases
- [ ] Create `dep_graph.py` with `DependencyGraph` class and `detect_cycles()` method
- [ ] Create `idempotency.py` with `ExtractionManifest` class and checksum tracking
- [ ] Create `scaffold.py` that generates new service directory tree from template
- [ ] Create `generate_client.py` that emits typed httpx client from OpenAPI schema
- [ ] Create `contracts/generate_pact.py` that reads monolith OpenAPI and emits Pact contracts

### 15.2 Dependency Graph Engine
- [ ] Implement `DependencyGraph.build()` — full AST walk of project src dir
- [ ] Implement `DependencyGraph.transitive_deps()` — recursive dep resolution with cycle detection
- [ ] Implement `find_shared_deps()` — classify modules as extract / shared (→ common/) / monolith-only
- [ ] Implement `detect_cycles()` — raises `CircularDependencyError` with full cycle path printed
- [ ] Write unit tests for graph builder against known fixture project (T-02, T-03, T-04)
- [ ] Benchmark graph build on 200-module project; assert < 3s (CC-22)
- [ ] Add `dry_run=True` mode that prints classified graph without writing files (T-06)

### 15.3 File Extraction Engine
- [ ] Implement `_move_module()` — move Python file from monolith to new service preserving structure
- [ ] Implement `_rewrite_imports()` — AST-based import rewriter for moved modules
- [ ] Implement `_move_to_common()` — move shared module to `common/` and rewrite all callers
- [ ] Implement `_extract_tests()` — co-extract test files alongside route/service/model files
- [ ] Verify all file writes use UTF-8 encoding and preserve original line endings
- [ ] After every write, run `ast.parse()` on written file to catch rewriter bugs
- [ ] Implement `_verify_monolith_tests()` — run `pytest tests/` and abort on failure

### 15.4 Client and Contract Generation
- [ ] Implement `generate_client.py:generate_typed_client()` — read OpenAPI, emit Pydantic v2 typed client
- [ ] Generated client must use `httpx.AsyncHTTPTransport(retries=N)` for resilience
- [ ] Generated client must have `proxy_post()` and `proxy_get()` methods for middleware use
- [ ] Implement `contracts/generate_pact.py` — read `/openapi.json`, emit Pact JSON consumer contracts
- [ ] Write `test_contract_{service}.py` template using `pact-python` fixtures
- [ ] Run `mypy --strict` on generated client as post-generation validation step
- [ ] Verify `ruff check` passes on generated contract test file (QS-9)

### 15.5 Docker and CI Artefact Generation
- [ ] Generate `{service}/Dockerfile` with multi-stage build (base, test, production targets)
- [ ] Generated Dockerfile must use `python:3.12-slim` base and `uv` for dependency installation
- [ ] Update `docker-compose.yml` with new service block including healthcheck config
- [ ] Generate `.github/workflows/{service_name}.yml` with lint + type-check + test + contract jobs
- [ ] Generated CI workflow must trigger on pushes to paths `{service}/**` and `common/**`
- [ ] Verify `docker-compose config` validates after update (CC-08)
- [ ] Build and run new service Docker image in post-extraction validation step (CC-07)

### 15.6 Common Library Setup
- [ ] Generate `common/__init__.py`, `common/pyproject.toml` with name and version fields
- [ ] Move all shared modules to correct `common/` subpackage preserving original namespace
- [ ] Rewrite all import sites in both monolith and new service to use `from common.X import Y`
- [ ] Add `common` as local path dependency in both `monolith/pyproject.toml` and `{service}/pyproject.toml`
- [ ] Run `uv sync` in both service directories to confirm `common/` installs correctly
- [ ] Add `ruff check common/` to both CI workflows (QS-9)
- [ ] Verify no class defined in `common/` appears elsewhere (T-05)

### 15.7 Proxy Middleware
- [ ] Implement `proxy_middleware.py` injected into monolith router for all extracted route paths
- [ ] Proxy uses `httpx.AsyncClient` with pre-warmed connection pool and `timeout=5.0`
- [ ] Proxy forwards all original headers and full request body without modification
- [ ] Proxy returns 503 when new service is unreachable (not 500) with structured error body
- [ ] Write latency benchmark using `locust`; assert p99 < 50 ms (T-20, INV-ES-04)
- [ ] Add `BILLING_SERVICE_URL` env var injection into monolith docker-compose entry
- [ ] Proxy can be disabled per-route via feature flag for gradual split mode transition

### 15.8 Split Mode
- [ ] Implement `mode="split"` that removes proxy routes from monolith router entirely
- [ ] Split mode deletes generated proxy middleware and `app/clients/{service}_client.py`
- [ ] Split mode removes `depends_on: billing-service` from monolith in docker-compose.yml
- [ ] Verify split mode passes CC-25 (no `proxy_post`/`proxy_get` in monolith routes)
- [ ] Run monolith test suite after split mode; assert 0 failures (INV-ES-01, T-17)
- [ ] Document split mode in `EXTRACTION_MANIFEST.json` under `transition_mode: "split"`
- [ ] Emit warning if split mode is run before proxy mode was validated in staging

### 15.9 Database Strategy Handling
- [ ] Default: shared DB — no migration generated; `db_strategy: shared` in manifest
- [ ] New service gets own `alembic.ini` pointing to same `DATABASE_URL`
- [ ] Detect cross-service FK dependencies and enumerate them in `manifest.cross_service_fks`
- [ ] `--db-split` flag: generate migration `alembic/versions/NNNN_split_{service}_db.py` with FK removal
- [ ] DB split migration must include `downgrade()` that re-adds FK constraints (§12.4)
- [ ] Detect FK cycles before generating split migration; emit `FKCycleWarning` (T-29)
- [ ] Document that DB split is separate phase; add `NOTE: DB split is phase 2` to manifest

### 15.10 Idempotency and Manifest
- [ ] `ExtractionManifest.load()` reads prior manifest if it exists
- [ ] `ExtractionManifest.already_moved(src)` returns True if src is in manifest `moves` array
- [ ] Checksum every file before and after write; skip if checksum unchanged
- [ ] Tool re-run: assert `git diff` empty after second run with identical parameters (T-27)
- [ ] Manifest `moves` count must equal actual number of files moved
- [ ] Manifest `rewrites` count must equal actual number of rewritten import lines
- [ ] Commit manifest to git as part of extraction commit message

### 15.11 Error Handling and Rollback
- [ ] Catch all extraction exceptions and invoke `_rollback()` before re-raising
- [ ] `_rollback()` reads manifest, restores all rewritten files via `git checkout HEAD -- {file}`
- [ ] `_rollback()` deletes new service directory with `shutil.rmtree(service_dir)`
- [ ] `_rollback()` removes generated client file from monolith
- [ ] Log every step to `extraction.log` in project root for post-mortem analysis
- [ ] `CircularDependencyError` must fire before any file write (QS-10, T-28)
- [ ] Port collision check runs before any file write (QS-11, T-25)

### 15.12 Testing Infrastructure
- [ ] Create `tests/fixtures/sample_monolith/` with a 5-module fixture project for unit tests
- [ ] Create `tests/test_dep_graph.py` covering T-02, T-03, T-04, T-05, T-06
- [ ] Create `tests/test_extraction.py` covering T-07 through T-12
- [ ] Create `tests/test_communication.py` covering T-13 through T-18
- [ ] Create `tests/test_transition_modes.py` covering T-19 through T-24
- [ ] Create `tests/test_edge_cases.py` covering T-25 through T-30
- [ ] Achieve ≥ 90% line coverage on all `scripts/extract_service/*.py` modules

### 15.13 Documentation and Registration
- [ ] Add `fastapi_extract_service` to `mcp_server.py` tool registry with full docstring
- [ ] Update `KNOWLEDGE.md` with extraction patterns, common pitfalls, and shared-code decisions
- [ ] Update `manifest.yaml` with `TOOL-045` entry including dependencies and output artefacts
- [ ] Update `SKILL.md` with `extract_service` usage example and parameter documentation
- [ ] Write `docs/EXTRACTION_GUIDE.md` covering proxy mode, split mode, DB strategies, and rollback
- [ ] Add `extract_service` to `README.md` EVOLVE tools table with link to SKILL.md
- [ ] Record `TOOL-045` in the spec factory index with SOTA reviewer score

---

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "billing_service/app/main.py",
    "billing_service/app/core/config.py",
    "billing_service/app/core/db.py",
    "billing_service/app/routes/billing.py",
    "billing_service/app/services/billing.py",
    "billing_service/app/models/invoice.py",
    "billing_service/app/schemas/invoice.py",
    "billing_service/tests/test_billing.py",
    "billing_service/tests/test_contract_billing.py",
    "billing_service/tests/contracts/monolith-billing_service.json",
    "billing_service/Dockerfile",
    "billing_service/pyproject.toml",
    "billing_service/EXTRACTION_MANIFEST.json",
    "common/__init__.py",
    "common/pyproject.toml",
    "common/schemas/invoice.py",
    ".github/workflows/billing-service.yml",
    "app/clients/billing_client.py"
  ],
  "files_modified": [
    "app/routes/billing.py",
    "app/main.py",
    "docker-compose.yml",
    "monolith/pyproject.toml"
  ],
  "metrics": {
    "modules_extracted": 3,
    "shared_modules_moved_to_common": 1,
    "import_sites_rewritten": 12,
    "tool_execution_seconds": 4.3,
    "new_service_image_mb": 148,
    "monolith_tests_post_extraction": "0 failed",
    "contract_tests": "2 passed"
  },
  "next_steps": [
    "Review EXTRACTION_MANIFEST.json to audit all moved files and rewritten imports",
    "Run `docker-compose up billing-service` and verify `GET /health` returns 200",
    "Run Pact contract tests: `pytest billing_service/tests/test_contract_billing.py -v`",
    "Run monolith integration tests in proxy mode: `pytest tests/ -k billing -v`",
    "When ready for split mode, run: `extract_service(..., mode='split')` to remove proxy shim",
    "If DB split is planned, read the `cross_service_fks` array in EXTRACTION_MANIFEST.json and schedule phase 2 migration",
    "Register new service in service registry and update load balancer routing rules"
  ],
  "warnings": [
    "Proxy mode adds ~15ms p50 latency overhead — benchmark in staging before production rollout",
    "Database split (--db-split) is a separate, irreversible operation — do not run it in the same sprint as the code extraction",
    "If `common/` grows beyond 3 modules, consider publishing it as a proper internal package instead of a local path dependency"
  ],
  "notes": [
    "EXTRACTION_MANIFEST.json is the authoritative rollback recipe — do not delete it",
    "The generated Pact contracts are committed to source control — update them when the API intentionally changes",
    "Proxy mode and split mode are mutually exclusive transition states — you must disable proxy before enabling split",
    "The typed client uses httpx.AsyncHTTPTransport(retries=3) — adjust max_retries in BillingClientSettings for your SLA",
    "All generated Python files pass `ruff check` and `mypy --strict` at generation time — if a future edit breaks type safety, the CI workflow will catch it"
  ]
}
```
