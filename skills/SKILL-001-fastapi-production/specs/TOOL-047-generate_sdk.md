# TOOL-047: fastapi_generate_sdk

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_generate_sdk` |
| Category | EVOLVE |
| Complexity | Medium |
| Dependencies | Existing FastAPI project with OpenAPI schema, `openapi-python-client`, `openapi-typescript-codegen` or `orval`, `oapi-codegen` (Go), `openapi-generator-cli` (Rust/Java) |
| Signature | `generate_sdk(project_dir: str, languages: list[str], output_dir: str = "sdks", package_name: str \| None = None, publish: bool = False, registry: str \| None = None) -> dict` |
| Parameters | `project_dir`: project root path<br>`languages`: list of `python`, `typescript`, `go`, `rust`, `java`<br>`output_dir`: directory where generated SDKs are written (relative to project_dir)<br>`package_name`: SDK package name (default: derived from app title in OpenAPI schema)<br>`publish`: push to language-native registry after generation (default `False`)<br>`registry`: registry URL override (PyPI, npm, pkg.go.dev, crates.io, Maven Central) |

---

## 2. Purpose

`fastapi_generate_sdk` solves the "typed client desert" problem that plagues teams shipping FastAPI services: developers who consume the API write ad-hoc `httpx.get("/users")` calls with no type safety, no structured error handling, and no guarantee the call matches the current schema. When the API team renames a field or adds a required query parameter, consumer code breaks silently at runtime rather than at the type-checker level. This tool extracts the canonical OpenAPI 3.1 schema live from the running FastAPI app (never from a stale cached file), invokes the best-in-class generator for each target language (`openapi-python-client` for Python, `openapi-typescript-codegen`/`orval` for TypeScript, `oapi-codegen` for Go, `openapi-generator-cli` for Rust and Java), and produces fully typed client packages that include request/response models, a typed exception hierarchy mapped from HTTP 4xx/5xx responses, authentication helpers for all security schemes declared in the schema (Bearer, API key, OAuth2 client credentials), pagination iterators that auto-detect cursor and offset patterns, and retry/timeout/circuit-breaker wrappers using exponential backoff with jitter. The SDK version is pinned to the API semver version extracted from the OpenAPI `info.version` field, ensuring that any consumer can run `pip install myapi-client==2.3.1` and know they are talking to API 2.3.1.

The design philosophy is enforced by seven non-negotiable invariants. Schema is always extracted live because a stale JSON file drifts from reality within one sprint. Versioning is always aligned with the API version so consumers can use semver to reason about compatibility. Publishing never happens without the explicit `--publish` flag because accidental releases are catastrophic. Every SDK always includes typed exceptions because consumers who catch a bare `httpx.HTTPStatusError` lose all visibility into which operation failed and why. The CI workflow regenerates SDKs on every pull request that touches `openapi.json` (computed by diffing `app.openapi()` outputs before and after) and blocks merge if the committed `sdks/` tree drifts from what the generator would produce fresh — a byte-level idempotency check verified by hashing the generator output. This makes the SDK a first-class artifact of the API release process, not a developer's personal script.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Schema extraction time | < 500 ms | FastAPI `app.openapi()` is a pure in-process call; no network hop |
| Generation time per language (Python) | < 5 s | `openapi-python-client` is Rust-backed; 500-route schema parses in < 5 s |
| Generation time per language (TypeScript) | < 8 s | `orval` uses Node.js codegen; heavier runtime startup |
| Generation time per language (Go) | < 5 s | `oapi-codegen` is a compiled Go binary; near-instant |
| Generation time per language (Rust/Java) | < 10 s | `openapi-generator-cli` is JVM-based; includes JVM startup cost |
| Total tool execution time (all 5 languages) | < 45 s | Languages generated sequentially with progress reporting |
| Registry publish step per language | < 30 s | PyPI twine upload, npm publish, go mod proxy, cargo publish |
| Files created | ≥ 15 | Generator scripts, CI workflow, version manager, publish script, typed client wrappers, tests, Makefile targets, docs |
| Files modified | ≤ 3 | `pyproject.toml`, `.github/workflows/sdk-regen.yml`, `Makefile` |
| Idempotency check (same schema → same output) | byte-identical | SHA-256 hash of generator output must match committed SDK tree |
| Large schema (500 routes, 200 models) | < 30 s total | Verified with openapi-python-client benchmark data |

---

## 4. Code Examples

### 4.1 Schema extractor — live extraction from running FastAPI app

```python
# scripts/sdk_tools/extract_schema.py
"""Extract live OpenAPI schema from the FastAPI app.

Always imports the app object fresh; never reads from a stale JSON file.
Writes to a temp file for consumption by downstream generators.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


def extract_schema(project_dir: str, app_module: str = "app.main:app") -> dict:
    """Load the FastAPI app and call app.openapi() to get the canonical schema.

    Args:
        project_dir: Absolute path to project root (added to sys.path).
        app_module: Dotted module path + ':' + attribute name.

    Returns:
        Parsed OpenAPI schema as a dict.

    Raises:
        ImportError: If the app module cannot be imported.
        AttributeError: If the attribute is not a FastAPI app.
    """
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)

    module_path, attr = app_module.split(":", 1)
    mod = importlib.import_module(module_path)
    app = getattr(mod, attr)

    # Call FastAPI's built-in schema generator — always fresh, never cached
    schema = app.openapi()
    version = schema.get("info", {}).get("version", "0.1.0")
    title = schema.get("info", {}).get("title", "api")
    return {"schema": schema, "version": version, "title": title}


def write_schema_to_temp(schema: dict, output_path: Path) -> None:
    """Serialize schema to a temp file for generator CLI consumption."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(schema, fh, indent=2)
```

### 4.2 Python SDK generator — wrapping openapi-python-client

```python
# scripts/sdk_tools/generate_python.py
"""Generate a typed Python SDK using openapi-python-client (httpx + attrs)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def generate_python_sdk(
    schema_path: Path,
    output_dir: Path,
    package_name: str,
    api_version: str,
) -> dict:
    """Run openapi-python-client to generate a typed Python client.

    Args:
        schema_path: Path to the extracted OpenAPI JSON file.
        output_dir: Directory to write the generated Python package.
        package_name: Python package name (e.g. ``myapi_client``).
        api_version: Semver string from OpenAPI info.version.

    Returns:
        Dict with ``success``, ``package_dir``, and ``stdout``/``stderr``.
    """
    package_dir = output_dir / package_name
    cmd = [
        sys.executable, "-m", "openapi_python_client", "generate",
        "--path", str(schema_path),
        "--output-path", str(package_dir),
        "--overwrite",
        "--config", str(schema_path.parent / "python_client_config.yaml"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        return {
            "success": False,
            "package_dir": str(package_dir),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    # Stamp the version into the generated __version__.py
    version_file = package_dir / package_name / "__version__.py"
    version_file.write_text(f'__version__ = "{api_version}"\n')
    return {
        "success": True,
        "package_dir": str(package_dir),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
```

### 4.3 TypeScript SDK generator — invoking orval via Node

```python
# scripts/sdk_tools/generate_typescript.py
"""Generate a typed TypeScript SDK using orval."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def generate_typescript_sdk(
    schema_path: Path,
    output_dir: Path,
    package_name: str,
    api_version: str,
) -> dict:
    """Invoke orval to generate TypeScript client with Axios or fetch.

    Writes orval.config.ts inline so the tool is self-contained.
    Requires ``npx`` to be available in PATH.
    """
    if shutil.which("npx") is None:
        raise EnvironmentError(
            "npx not found. Install Node.js >= 18 to generate TypeScript SDKs."
        )
    ts_dir = output_dir / f"{package_name}-ts"
    ts_dir.mkdir(parents=True, exist_ok=True)

    orval_config = {
        "api": {
            "input": {"target": str(schema_path)},
            "output": {
                "target": str(ts_dir / "src" / "index.ts"),
                "schemas": str(ts_dir / "src" / "model"),
                "client": "fetch",
                "mode": "tags-split",
            },
        }
    }
    config_path = ts_dir / "orval.config.json"
    config_path.write_text(json.dumps(orval_config, indent=2))

    proc = subprocess.run(
        ["npx", "--yes", "orval", "--config", str(config_path)],
        capture_output=True, text=True, timeout=60, cwd=str(ts_dir),
    )
    # Write package.json with version aligned to API version
    pkg_json = {"name": package_name, "version": api_version, "type": "module"}
    (ts_dir / "package.json").write_text(json.dumps(pkg_json, indent=2))
    return {
        "success": proc.returncode == 0,
        "package_dir": str(ts_dir),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
```

### 4.4 Go SDK generator — invoking oapi-codegen

```python
# scripts/sdk_tools/generate_go.py
"""Generate a typed Go SDK using oapi-codegen."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def generate_go_sdk(
    schema_path: Path,
    output_dir: Path,
    package_name: str,
    module_path: str,
    api_version: str,
) -> dict:
    """Run oapi-codegen to generate a Go client.

    Args:
        schema_path: Path to extracted OpenAPI JSON.
        output_dir: Parent directory for the Go module.
        package_name: Go package name (lower_snake_case).
        module_path: Go module path (e.g. ``github.com/org/myapi-go``).
        api_version: Semver string; written to version.go constant.
    """
    if shutil.which("oapi-codegen") is None:
        raise EnvironmentError(
            "oapi-codegen not found. Run: go install github.com/deepmap/oapi-codegen/cmd/oapi-codegen@latest"
        )
    go_dir = output_dir / f"{package_name}-go"
    go_dir.mkdir(parents=True, exist_ok=True)
    client_file = go_dir / "client.gen.go"

    proc = subprocess.run(
        [
            "oapi-codegen",
            "--generate", "client,types",
            "--package", package_name,
            "--out", str(client_file),
            str(schema_path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode == 0:
        # Emit version constant
        version_go = go_dir / "version.go"
        version_go.write_text(
            f'package {package_name}\n\n// Version is the API version this client targets.\nconst Version = "{api_version}"\n'
        )
        # Emit go.mod
        go_mod = go_dir / "go.mod"
        go_mod.write_text(f"module {module_path}\n\ngo 1.21\n")
    return {
        "success": proc.returncode == 0,
        "package_dir": str(go_dir),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
```

### 4.5 Version aligner — reads API version, writes SDK version into all language outputs

```python
# scripts/sdk_tools/version_aligner.py
"""Align SDK versions with the API version extracted from OpenAPI schema.

INV-SDK-002 enforcement: SDK version ALWAYS equals API version (semver).
If the committed SDK version differs, this module raises VersionMismatchError.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path


class VersionMismatchError(ValueError):
    """Raised when SDK version diverges from API version."""


def extract_api_version(schema: dict) -> str:
    """Extract semver from OpenAPI info.version field."""
    version = schema.get("info", {}).get("version", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(
            f"OpenAPI info.version '{version}' is not valid semver (X.Y.Z). "
            "Set app.version in FastAPI constructor before calling generate_sdk."
        )
    return version


def check_python_sdk_version(package_dir: Path, expected: str) -> None:
    """Verify pyproject.toml version matches expected API version."""
    pyproject = package_dir / "pyproject.toml"
    if not pyproject.exists():
        return
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    actual = data.get("tool", {}).get("poetry", {}).get("version") or \
             data.get("project", {}).get("version", "")
    if actual != expected:
        raise VersionMismatchError(
            f"Python SDK version '{actual}' != API version '{expected}'. "
            "Run generate_sdk again to re-align."
        )


def stamp_version_in_pyproject(package_dir: Path, version: str) -> None:
    """Write version into pyproject.toml [project] table."""
    pyproject = package_dir / "pyproject.toml"
    if not pyproject.exists():
        return
    text = pyproject.read_text()
    text = re.sub(r'^(version\s*=\s*)"[^"]+"', f'\\g<1>"{version}"', text, flags=re.MULTILINE)
    pyproject.write_text(text)
```

### 4.6 Publish script — PyPI dry-run and live publish

```python
# scripts/sdk_tools/publish_python.py
"""Publish the generated Python SDK to PyPI (or a private registry).

Publishing NEVER happens without explicit publish=True flag (INV-SDK-003).
Dry-run is always performed first to validate the package before upload.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def publish_python_sdk(
    package_dir: Path,
    registry: str | None = None,
    dry_run: bool = True,
) -> dict:
    """Build the wheel and publish to PyPI or a private registry.

    Args:
        package_dir: Path to the generated Python SDK directory.
        registry: Optional PyPI-compatible registry URL.
        dry_run: If True (default), run ``twine check`` only.

    Returns:
        Dict with ``success``, ``stdout``, ``stderr``.
    """
    # Step 1: build the wheel
    build_proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", str(package_dir)],
        capture_output=True, text=True, timeout=60,
    )
    if build_proc.returncode != 0:
        return {
            "success": False,
            "stdout": build_proc.stdout,
            "stderr": build_proc.stderr,
            "phase": "build",
        }
    dist_dir = package_dir / "dist"
    wheels = list(dist_dir.glob("*.whl"))
    if not wheels:
        return {"success": False, "stderr": "No wheel found after build", "phase": "build"}

    if dry_run:
        # Step 2a: check only — never upload
        check_proc = subprocess.run(
            [sys.executable, "-m", "twine", "check", str(wheels[0])],
            capture_output=True, text=True, timeout=30,
        )
        return {
            "success": check_proc.returncode == 0,
            "stdout": check_proc.stdout,
            "stderr": check_proc.stderr,
            "phase": "dry_run",
        }

    # Step 2b: upload for real
    upload_cmd = [sys.executable, "-m", "twine", "upload", str(wheels[0])]
    if registry:
        upload_cmd.extend(["--repository-url", registry])
    upload_proc = subprocess.run(upload_cmd, capture_output=True, text=True, timeout=60)
    return {
        "success": upload_proc.returncode == 0,
        "stdout": upload_proc.stdout,
        "stderr": upload_proc.stderr,
        "phase": "upload",
    }
```

### 4.7 Typed Python client example — httpx with auth and retry

```python
# sdks/myapi_client/myapi_client/client.py
"""Auto-generated typed client for MyAPI.

Generated by fastapi_generate_sdk. Do not edit by hand.
Re-generate with: make sdk-regen
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel


class AuthConfig(BaseModel):
    """Authentication configuration for the SDK client."""

    bearer_token: str | None = None
    api_key: str | None = None
    api_key_header: str = "X-API-Key"
    base_url: str = "http://localhost:8000"
    timeout: float = 30.0
    max_retries: int = 3
    retry_backoff_base: float = 0.5


class MyApiClient:
    """Typed synchronous client for MyAPI.

    Handles authentication, retries, and typed exceptions automatically.
    """

    def __init__(self, config: AuthConfig) -> None:
        self._config = config
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout,
        )
        self._set_auth_headers()

    def _set_auth_headers(self) -> None:
        if self._config.bearer_token:
            self._client.headers["Authorization"] = f"Bearer {self._config.bearer_token}"
        elif self._config.api_key:
            self._client.headers[self._config.api_key_header] = self._config.api_key

    def _request_with_retry(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self._config.max_retries):
            try:
                response = self._client.request(method, path, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise _map_http_error(exc) from exc
                last_exc = exc
            backoff = self._config.retry_backoff_base * (2 ** attempt)
            time.sleep(backoff)
        raise last_exc  # type: ignore[misc]
```

### 4.8 Pagination iterator — async cursor and offset auto-detected

```python
# sdks/myapi_client/myapi_client/pagination.py
"""Pagination helpers for auto-generated SDK.

Supports both cursor-based and offset-based pagination detected from
the OpenAPI schema's x-pagination extension or standard Link headers.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypeVar

import httpx

T = TypeVar("T")


async def paginate_cursor(
    client: httpx.AsyncClient,
    path: str,
    response_key: str = "items",
    cursor_param: str = "cursor",
    limit: int = 100,
    **extra_params: Any,
) -> AsyncIterator[Any]:
    """Async iterator over all pages of a cursor-paginated endpoint.

    Yields individual items (not pages). Stops when ``next_cursor`` is None.

    Args:
        client: Authenticated httpx.AsyncClient.
        path: API path, e.g. ``/api/v1/users``.
        response_key: JSON key containing the items array.
        cursor_param: Query parameter name for the cursor.
        limit: Items per page.
        **extra_params: Additional query parameters.
    """
    cursor: str | None = None
    while True:
        params = {cursor_param: cursor, "limit": limit, **extra_params}
        params = {k: v for k, v in params.items() if v is not None}
        response = await client.get(path, params=params)
        response.raise_for_status()
        body = response.json()
        items = body.get(response_key, [])
        for item in items:
            yield item
        cursor = body.get("next_cursor")
        if not cursor or not items:
            break


async def paginate_offset(
    client: httpx.AsyncClient,
    path: str,
    response_key: str = "items",
    limit: int = 100,
    **extra_params: Any,
) -> AsyncIterator[Any]:
    """Async iterator over all pages of an offset-paginated endpoint.

    Yields individual items. Stops when a page returns fewer items than limit.
    """
    offset = 0
    while True:
        params = {"offset": offset, "limit": limit, **extra_params}
        response = await client.get(path, params=params)
        response.raise_for_status()
        items = response.json().get(response_key, [])
        for item in items:
            yield item
        if len(items) < limit:
            break
        offset += limit
```

### 4.9 Typed exception hierarchy — mapped from HTTP status codes

```python
# sdks/myapi_client/myapi_client/exceptions.py
"""Typed exception hierarchy for MyAPI SDK.

Every 4xx/5xx response from the API is converted to a typed exception
so consumers can use ``except NotFoundError`` instead of checking status codes.
INV-SDK-004 enforcement: every SDK always includes typed exceptions.
"""
from __future__ import annotations

import httpx


class ApiError(Exception):
    """Base class for all MyAPI SDK exceptions."""

    def __init__(self, message: str, status_code: int, response: httpx.Response) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response
        self.detail: dict = {}
        try:
            self.detail = response.json()
        except Exception:
            pass


class BadRequestError(ApiError):
    """400 — malformed request, validation failure."""


class UnauthorizedError(ApiError):
    """401 — missing or invalid credentials."""


class ForbiddenError(ApiError):
    """403 — valid credentials but insufficient permissions."""


class NotFoundError(ApiError):
    """404 — resource does not exist."""


class ConflictError(ApiError):
    """409 — state conflict (e.g., version collision, duplicate)."""


class UnprocessableEntityError(ApiError):
    """422 — FastAPI validation error; detail contains field errors."""


class RateLimitError(ApiError):
    """429 — too many requests; Retry-After header may be present."""


class ServerError(ApiError):
    """5xx — server-side failure; safe to retry with backoff."""


_STATUS_MAP: dict[int, type[ApiError]] = {
    400: BadRequestError,
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}


def _map_http_error(exc: httpx.HTTPStatusError) -> ApiError:
    """Map an httpx HTTPStatusError to a typed SDK exception."""
    status = exc.response.status_code
    cls = _STATUS_MAP.get(status, ServerError)
    return cls(
        message=f"HTTP {status}: {exc.request.method} {exc.request.url}",
        status_code=status,
        response=exc.response,
    )
```

### 4.10 Test suite — smoke tests for generated Python SDK

```python
# tests/sdk/test_python_sdk_smoke.py
"""Smoke tests for the generated Python SDK.

These tests verify that the generated client can be imported, instantiated,
and can make real calls against a running test server.
"""
from __future__ import annotations

import pytest
import httpx

from myapi_client.client import AuthConfig, MyApiClient
from myapi_client.exceptions import NotFoundError, UnauthorizedError
from myapi_client.pagination import paginate_offset


@pytest.fixture
def auth_config(test_server_url: str, test_api_key: str) -> AuthConfig:
    return AuthConfig(
        base_url=test_server_url,
        api_key=test_api_key,
        max_retries=1,
    )


@pytest.fixture
def client(auth_config: AuthConfig) -> MyApiClient:
    return MyApiClient(config=auth_config)


def test_client_can_be_instantiated(auth_config: AuthConfig) -> None:
    """Verify the generated client initialises without error."""
    c = MyApiClient(config=auth_config)
    assert c is not None
    assert c._config.api_key == auth_config.api_key


def test_get_users_returns_typed_response(client: MyApiClient) -> None:
    """GET /api/v1/users returns a list of UserPublic models."""
    response = client.get_users()
    assert isinstance(response, list)
    assert all(hasattr(u, "id") for u in response)


def test_not_found_raises_typed_exception(client: MyApiClient) -> None:
    """GET /api/v1/users/{id} with unknown ID raises NotFoundError."""
    with pytest.raises(NotFoundError) as exc_info:
        client.get_user(user_id="00000000-0000-0000-0000-000000000000")
    assert exc_info.value.status_code == 404


def test_unauthenticated_raises_unauthorized(test_server_url: str) -> None:
    """Requests without credentials raise UnauthorizedError (INV-SDK-005)."""
    unauthenticated = MyApiClient(config=AuthConfig(base_url=test_server_url))
    with pytest.raises(UnauthorizedError):
        unauthenticated.get_users()


@pytest.mark.anyio
async def test_pagination_iterator_yields_all_items(
    async_client: httpx.AsyncClient,
    seed_100_users: None,
) -> None:
    """Offset paginator yields all 100 seeded users across multiple pages."""
    collected = []
    async for user in paginate_offset(async_client, "/api/v1/users", limit=20):
        collected.append(user)
    assert len(collected) == 100
```

### 4.11 CI workflow — auto-regenerate on schema change

```yaml
# .github/workflows/sdk-regen.yml
name: SDK Regeneration

on:
  pull_request:
    paths:
      - "app/**/*.py"
      - "openapi.json"

jobs:
  check-sdk-drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -e ".[dev,sdk-tools]"

      - name: Extract schema and regenerate SDKs
        run: |
          make sdk-regen

      - name: Check for SDK drift
        run: |
          git diff --exit-code sdks/ || (
            echo "SDK drift detected — run 'make sdk-regen' locally and commit"
            exit 1
          )
```

---

## 5. Quality Standards

| ID | Standard | Enforcement |
|----|----------|-------------|
| QS-01 | Schema always extracted live — never from stale file | `extract_schema()` calls `app.openapi()` at runtime; `INV-SDK-001` CI gate blocks merge if stale file used |
| QS-02 | SDK version == API semver version | `version_aligner.stamp_version_in_pyproject()` writes version; `INV-SDK-002` check raises `VersionMismatchError` on mismatch |
| QS-03 | Publishing requires explicit flag | `publish=False` default; code path guarded by `if not publish: return` before any upload |
| QS-04 | Typed exceptions always present | `exceptions.py` generated for every language; `INV-SDK-004` asserts file exists with >= 3 exception classes |
| QS-05 | Auth helpers generated if security schemes declared | `SecuritySchemeDetector` checks `components.securitySchemes`; skips only if schema has no schemes |
| QS-06 | Generation is idempotent | SHA-256 hash of output tree compared before and after; CI fails if `sdks/` differs from fresh generation |
| QS-07 | Python SDK passes `mypy --strict` | `mypy` run in CI against `sdks/*/` with `--strict`; no `Any` leaks in public API |
| QS-08 | TypeScript SDK compiles with `tsc --strict` | `tsc --strict --noEmit` run in CI for every TypeScript SDK |
| QS-09 | Go SDK passes `go vet` and `go build` | `go vet ./...` and `go build ./...` run in SDK directory |
| QS-10 | No `pass`-only stubs in generated client | Generator template rejects empty operation bodies; test T-15 verifies all operations have real implementations |
| QS-11 | Pagination iterators yield items not pages | Unit test T-16 asserts iterator type is `AsyncIterator[Model]`, not `AsyncIterator[Page]` |
| QS-12 | Retry logic uses exponential backoff with jitter | `_request_with_retry` adds `random.uniform(0, 0.1) * backoff_base * 2**attempt` jitter |
| QS-13 | Dry-run by default for publish | `dry_run=True` default in `publish_python_sdk`; `twine check` runs but no upload occurs |
| QS-14 | Generator tool missing → informative error with install command | `EnvironmentError` raised with `go install github.com/...` instruction printed before traceback |
| QS-15 | CI blocks PR if `sdks/` out of sync | `git diff --exit-code sdks/` step in `sdk-regen.yml`; fails with human-readable message |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `extract_schema()` calls `app.openapi()` and not a file read | `grep -R "open(" scripts/sdk_tools/extract_schema.py` returns nothing |
| CC-02 | Schema version is semver-validated before generation begins | `extract_api_version()` raises `ValueError` if not `X.Y.Z` |
| CC-03 | Python SDK generated with `openapi-python-client` | `generate_python_sdk()` invokes `python -m openapi_python_client` subprocess |
| CC-04 | TypeScript SDK generated with orval or openapi-typescript-codegen | `generate_typescript_sdk()` invokes `npx orval` subprocess |
| CC-05 | Go SDK generated with `oapi-codegen` | `generate_go_sdk()` invokes `oapi-codegen` binary subprocess |
| CC-06 | Rust SDK generated with `openapi-generator-cli` | `generate_rust_sdk()` invokes `openapi-generator-cli generate -g rust` |
| CC-07 | Java SDK generated with `openapi-generator-cli` | `generate_java_sdk()` invokes `openapi-generator-cli generate -g java` |
| CC-08 | SDK version equals API version in `pyproject.toml` | `stamp_version_in_pyproject()` patches version field; T-20 asserts equality |
| CC-09 | SDK version equals API version in `package.json` (TypeScript) | `package_json["version"]` written from `api_version` in `generate_typescript_sdk()` |
| CC-10 | SDK version equals API version in `go.mod` and `version.go` (Go) | `version.go` constant written; T-21 asserts value |
| CC-11 | Typed exception hierarchy generated for Python SDK | `exceptions.py` contains `NotFoundError`, `UnauthorizedError`, `ServerError` |
| CC-12 | Typed exception hierarchy generated for TypeScript SDK | `errors.ts` contains `NotFoundError`, `UnauthorizedError`, `ServerError` |
| CC-13 | Auth helper for Bearer token generated if `BearerAuth` in schema | `AuthConfig.bearer_token` field present in client when `bearerAuth` in `securitySchemes` |
| CC-14 | Auth helper for API key generated if `ApiKeyAuth` in schema | `AuthConfig.api_key` and `api_key_header` fields present when `apiKeyAuth` in `securitySchemes` |
| CC-15 | Auth helper for OAuth2 client credentials generated | `get_oauth2_token()` function in `auth.py` when `oauth2` scheme in schema |
| CC-16 | Cursor pagination iterator generated when `x-pagination: cursor` detected | `paginate_cursor()` function present in `pagination.py` |
| CC-17 | Offset pagination iterator generated when `x-pagination: offset` detected | `paginate_offset()` function present in `pagination.py` |
| CC-18 | Retry/timeout config exposed in `AuthConfig` | `max_retries`, `retry_backoff_base`, `timeout` fields present in `AuthConfig` |
| CC-19 | `publish=False` by default | Function signature default verified in T-23 |
| CC-20 | `publish_python_sdk(dry_run=True)` runs `twine check` but not `twine upload` | T-24 mocks subprocess; asserts `twine upload` never called when `dry_run=True` |
| CC-21 | `publish_python_sdk(dry_run=False)` runs `twine upload` | T-25 mocks subprocess; asserts `twine upload` called exactly once |
| CC-22 | CI workflow file created at `.github/workflows/sdk-regen.yml` | `Path(".github/workflows/sdk-regen.yml").exists()` asserted in T-07 |
| CC-23 | CI workflow runs `git diff --exit-code sdks/` to detect drift | Workflow file contains `git diff --exit-code sdks/` verified by T-07 |
| CC-24 | Makefile targets `sdk-regen`, `sdk-publish`, `sdk-check` added | `Makefile` contains those targets; T-08 checks presence |
| CC-25 | Generator tool missing → `EnvironmentError` with install instruction | `shutil.which("oapi-codegen")` guard raises error with Go install command |
| CC-26 | `generate_sdk()` returns dict with `success`, `files_created`, `errors` | Return type verified in T-01 |
| CC-27 | `oneOf` / `anyOf` unions in schema produce union types in Python SDK | T-13 feeds schema with `oneOf` and asserts `Union[TypeA, TypeB]` in generated models |
| CC-28 | Large schema (500 routes) completes generation in < 30 s | T-30 benchmark test with synthetic 500-route schema; asserts wall time |
| CC-29 | Re-running with identical schema produces byte-identical output | T-29 asserts SHA-256 of `sdks/` tree matches after two sequential runs |
| CC-30 | Version collision on PyPI → `PublishError` with version in message | T-26 mocks `twine upload` returning exit code 1 with "version exists" in stderr |
| CC-31 | `generate_sdk()` with `publish=True` and `registry` param passes URL to upload | T-27 asserts `--repository-url registry` in subprocess call args |
| CC-32 | Schema extraction adds project_dir to sys.path non-destructively | `extract_schema()` inserts at position 0, removes after import |
| CC-33 | All generated Python files pass `ruff check` | `ruff check sdks/myapi_client/` run in CI; T-09 checks return code |

---

## 7. Definition of Done

- [ ] `scripts/sdk_tools/extract_schema.py` exists with `extract_schema()` and `write_schema_to_temp()` functions
- [ ] `scripts/sdk_tools/generate_python.py` wraps `openapi-python-client` subprocess with version stamping
- [ ] `scripts/sdk_tools/generate_typescript.py` wraps `orval` via `npx` with `package.json` version alignment
- [ ] `scripts/sdk_tools/generate_go.py` wraps `oapi-codegen` with `version.go` constant emission
- [ ] `scripts/sdk_tools/generate_rust.py` wraps `openapi-generator-cli` with rust-reqwest target
- [ ] `scripts/sdk_tools/generate_java.py` wraps `openapi-generator-cli` with java8 target
- [ ] `scripts/sdk_tools/version_aligner.py` raises `VersionMismatchError` when SDK version != API version
- [ ] `scripts/sdk_tools/publish_python.py` runs `twine check` for dry-run and `twine upload` for live
- [ ] `sdks/myapi_client/myapi_client/exceptions.py` contains full typed exception hierarchy (8+ classes)
- [ ] `sdks/myapi_client/myapi_client/pagination.py` implements `paginate_cursor` and `paginate_offset`
- [ ] `.github/workflows/sdk-regen.yml` blocks PR on `sdks/` drift
- [ ] `Makefile` contains targets `sdk-regen`, `sdk-check`, `sdk-publish`
- [ ] All 30 T-01..T-30 tests pass with zero skips
- [ ] Generated Python SDK passes `mypy --strict` and `ruff check`
- [ ] `generate_sdk()` documented in `docs/sdk/OVERVIEW.md` with usage examples

---

## 8. Invariants

| ID | Statement | Enforcement | Tests |
|----|-----------|-------------|-------|
| INV-SDK-001 | Schema is always extracted live from `app.openapi()`, never from a stale JSON file | `extract_schema()` imports the app module and calls `app.openapi()` directly; any code path reading a pre-written file is rejected in code review | T-01, T-02 |
| INV-SDK-002 | SDK version always equals API semver version | `version_aligner.check_python_sdk_version()` raises `VersionMismatchError` if pyproject.toml version differs; CI step runs this check before every publish | T-20, T-21 |
| INV-SDK-003 | Publishing never happens without explicit `publish=True` flag | `generate_sdk()` default is `publish=False`; upload subprocess is guarded by `if not publish: return` before any registry call | T-23, T-24 |
| INV-SDK-004 | Every SDK always includes typed exceptions mapped from HTTP status codes | Generator templates require `exceptions.py` / `errors.ts` / `errors.go`; CI asserts file existence and content after generation | T-14, T-15 |
| INV-SDK-005 | Auth helpers always generated when security schemes are present in schema | `SecuritySchemeDetector.has_schemes()` checked before generation; helpers omitted only when schema has zero security schemes | T-17, T-18 |
| INV-SDK-006 | Regeneration is idempotent — same schema always produces byte-identical output | SHA-256 of the entire `sdks/` directory tree compared before and after re-run; `IdempotencyError` raised on mismatch in CI | T-29 |
| INV-SDK-007 | CI job blocks PR merge if `sdks/` tree is out of sync with current schema | `git diff --exit-code sdks/` in `sdk-regen.yml` returns non-zero exit code on any diff; workflow blocks PR | T-28 |
| INV-SDK-008 | Generator tool missing produces an actionable error with install instructions | `shutil.which()` check before each generator invocation; `EnvironmentError` message includes exact `pip install` / `go install` / `npm install` command | T-06 |

---

## 9. User Stories

### 9.1 Python SDK

**US-01** — As a Python developer consuming the API, I want a typed `MyApiClient` with Pydantic models for every request and response so that my IDE autocompletes field names and `mypy` catches mistakes at development time rather than at runtime.

The developer installs the generated SDK with `pip install myapi-client==2.3.0`. They construct `MyApiClient(config=AuthConfig(base_url=..., bearer_token=...))`.
Every endpoint is a typed method: `client.create_user(user_in=UserCreate(email=..., password=...))` returns `UserPublic`.
If the API renames a field in version 2.4.0, the developer upgrades the SDK and their type checker surfaces every broken reference.
No more silent runtime `KeyError` or `AttributeError` — the compiler tells you before production does.
CC-03 mandates `openapi-python-client` with Pydantic v2 models; INV-SDK-001 ensures the schema is always fresh.
T-02 smoke-tests that a real endpoint call returns a typed model with all expected fields populated.

*References*: CC-03, CC-11, INV-SDK-001, T-02

---

**US-02** — As a Python developer, I want all 4xx and 5xx responses mapped to typed exceptions so that I can write `except NotFoundError` instead of checking `response.status_code == 404`.

When the API returns 404, the client raises `NotFoundError(status_code=404, detail={...})`.
When it returns 422, it raises `UnprocessableEntityError` with `detail["errors"]` containing FastAPI field-level validation messages.
When it returns 429, it raises `RateLimitError` and the caller can read `exc.response.headers["Retry-After"]`.
A bare `except ApiError` catches all API failures for generic logging and alerting middleware.
The developer writes exception-handling code that is self-documenting, exhaustive, and understood by other team members.
INV-SDK-004 mandates exception classes; T-14 asserts all 8 typed classes are present in `exceptions.py`.

*References*: CC-11, CC-12, INV-SDK-004, T-14

---

**US-03** — As a Python developer, I want Bearer and API key auth helpers auto-generated so that I don't need to manually set headers for every request.

`AuthConfig(bearer_token="tok_xxx")` sets `Authorization: Bearer tok_xxx` on every request automatically via `httpx.Client.headers`.
`AuthConfig(api_key="key_yyy")` sets `X-API-Key: key_yyy` using the `api_key_header` field, which is configurable for non-standard header names.
Both fields can be loaded from environment variables via `AuthConfig.from_env()`, supporting twelve-factor app configuration.
When OAuth2 is configured, `get_oauth2_token(client_id, client_secret, token_url)` fetches and caches credentials until expiry.
INV-SDK-005 requires auth helpers generated whenever `securitySchemes` is non-empty in the OpenAPI schema.
T-17 asserts `bearer_token` field present; T-18 asserts helpers absent when schema has no security schemes.

*References*: CC-13, CC-14, CC-15, INV-SDK-005, T-17

---

**US-04** — As a Python developer, I want transient failures (5xx, network timeout) retried with exponential backoff so that my application is resilient to brief server restarts.

The client retries up to `max_retries=3` times (configurable via `AuthConfig`); setting `max_retries=0` disables retry entirely.
Backoff formula is `retry_backoff_base * (2 ** attempt) + random.uniform(0, 0.1)` seconds, preventing thundering herd.
4xx errors are NOT retried — they represent client mistakes that retrying cannot fix.
On final failure after all retries, the last exception is re-raised so the caller sees the original error, not a wrapper.
Retry attempts are logged at DEBUG level with attempt number and backoff duration for observability.
QS-12 codifies the jitter requirement; T-19 asserts exactly 3 retry attempts then `ServerError` raised.

*References*: CC-18, QS-12, T-19

---

**US-05** — As a QA engineer, I want smoke tests generated alongside the Python SDK so that every CI run verifies the generated client can actually call the API.

`tests/sdk/test_python_sdk_smoke.py` is generated with at least 5 test functions covering: client instantiation, one authenticated GET call, `NotFoundError` on unknown ID, `UnauthorizedError` without credentials, and pagination across multiple pages.
These tests run against a real test server spun up as a pytest fixture via `anyio` and `httpx.AsyncClient`.
Static type checkers catch schema drift; smoke tests catch generator bugs where types parse but calls fail at runtime.
CC-03 mandates the smoke test file be created alongside the SDK; T-03 verifies the file exists with correct imports.
The fixture design seeds 100 items into the test database so pagination tests yield a realistic data volume.
Any breakage in the smoke tests blocks the CI merge check, ensuring the SDK is always usable.

*References*: CC-03, T-03, T-14, T-16

---

### 9.2 TypeScript SDK

**US-06** — As a TypeScript/React developer, I want a typed fetch-based client generated from the OpenAPI schema so that API calls in my frontend have compile-time type safety.

`orval` generates TypeScript interfaces for every schema model and typed async functions for every endpoint in the OpenAPI spec.
The developer imports `import { getUsers, UserPublic } from "@myorg/myapi-client"` and gets full IntelliSense in VS Code.
Response types are inferred automatically; no manual casting with `as UserPublic` is needed anywhere.
The SDK publishes to npm as `@myorg/myapi-client` with the `version` field in `package.json` matching the API semver version.
CC-04 mandates `orval` as the TypeScript generator; CC-09 mandates version alignment via `package.json`.
T-04 verifies that `package.json` version equals `api_version` extracted from the OpenAPI schema.

*References*: CC-04, CC-09, INV-SDK-002, T-04

---

**US-07** — As a TypeScript developer, I want dual ESM + CJS output so that the SDK works in both Node.js and bundler environments without additional configuration.

The generated `package.json` contains both `"main": "dist/cjs/index.js"` and `"module": "dist/esm/index.js"` fields.
`tsconfig.json` is generated with two separate config files: `tsconfig.cjs.json` (CommonJS) and `tsconfig.esm.json` (ESM module).
The CI step runs `tsc --strict --noEmit` for both tsconfig files and fails if either produces type errors.
Consumers using Vite, Webpack, Rollup, or plain Node can all use the same package without configuring `moduleResolution`.
QS-08 mandates `tsc --strict` compliance; T-04 verifies both `main` and `module` fields are present in `package.json`.
The orval config template in `generate_typescript.py` is parameterised to emit dual output paths.

*References*: CC-04, QS-08, T-04

---

**US-08** — As a TypeScript developer, I want pagination utilities for endpoints returning lists so that I don't need to write cursor-tracking or page-loop logic by hand.

Endpoints with the `x-pagination: cursor` extension get a typed `async function* paginate<T>()` generator using `Link` header or `next_cursor` response field.
Endpoints with `x-pagination: offset` get a generator that increments `offset` by `limit` until a short page is returned.
Consumers write `for await (const item of paginateUsers(client, { limit: 50 }))` and get all items without managing page state.
The TypeScript generator emits `AsyncGenerator<T, void, undefined>` return types so callers know the exact item type.
CC-16 and CC-17 mandate the pagination iterators; T-16 integration-tests them against 100 seeded items.
The generator stops cleanly on an empty page, preventing infinite loops on zero-item endpoints.

*References*: CC-16, CC-17, T-16

---

**US-09** — As a TypeScript developer, I want typed error classes that match the Python SDK hierarchy so that cross-language teams share a consistent mental model of API errors.

`errors.ts` exports `NotFoundError`, `UnauthorizedError`, `ForbiddenError`, `UnprocessableEntityError`, `RateLimitError`, `ServerError` extending a base `ApiError`.
Each error class carries `statusCode: number`, `detail: unknown`, and `requestId: string | undefined` fields populated from response headers.
TypeScript discriminated unions allow exhaustive `switch (err.statusCode)` handling that the compiler checks for completeness.
The class names and field names intentionally mirror the Python SDK so developers switching languages have zero learning curve.
INV-SDK-004 requires typed exceptions in every language; T-14 asserts the TypeScript `errors.ts` file exists with minimum 3 classes.
T-09 verifies the TypeScript SDK compiles with `tsc --strict --noEmit` including `errors.ts`.

*References*: CC-12, INV-SDK-004, T-14

---

**US-10** — As a frontend developer, I want the generated TypeScript SDK to compile with `tsc --strict` and satisfy `eslint` so that it integrates into strict corporate TypeScript projects without requiring suppression comments.

Generated TypeScript code uses explicit type annotations on all function parameters and return types, never relying on `any` inference.
Property accesses on optional fields use optional chaining (`?.`) rather than non-null assertions (`!`), preventing runtime errors.
`as` type casts are avoided except in well-commented narrowing scenarios (e.g., response body parsing with Zod validation).
A `tsconfig.json` with `"strict": true`, `"noImplicitAny": true`, and `"strictNullChecks": true` is generated alongside the SDK.
An `.eslintrc.json` with `@typescript-eslint/recommended` ruleset is included to enforce consistent code style.
QS-08 mandates this; T-04 and T-09 together verify the strict compilation and linting requirements.

*References*: QS-08, T-04

---

### 9.3 Multi-language

**US-11** — As a Go backend developer, I want a type-safe Go client generated from the FastAPI schema so that Go microservices calling the API get compile-time struct field guarantees.

`oapi-codegen` generates Go structs from all OpenAPI schema components and typed interface methods for every operation.
The Go module path is configurable via the `package_name` parameter (e.g., `github.com/myorg/myapi-go`), written into `go.mod`.
`go build ./...` and `go vet ./...` both pass without errors or warnings on the generated code.
The `Version` constant in `version.go` equals the API semver version (INV-SDK-002), verified by T-21.
Auth is implemented as an `httpx`-style interceptor via a custom `http.RoundTripper` for Bearer and API key schemes.
If `oapi-codegen` is missing from PATH, `EnvironmentError` with the exact `go install` command is raised (INV-SDK-008, T-06).

*References*: CC-05, CC-10, INV-SDK-002, T-05

---

**US-12** — As a Rust developer, I want a Rust SDK generated with `reqwest` so that Rust microservices can call the API with fully typed request builders and response structs.

`openapi-generator-cli -g rust-reqwest` produces a Cargo crate with `serde`-annotated structs and async `reqwest`-based operation functions.
`Cargo.toml` version field is stamped with the API version via `version_aligner` after generation (INV-SDK-002).
`cargo check` passes without errors; `cargo clippy` produces no warnings on the generated code.
Bearer token auth is implemented via `reqwest::header::AUTHORIZATION` added to the `ClientBuilder` default headers.
API key auth is implemented as a custom header added to `ClientBuilder` before the client is constructed.
If `openapi-generator-cli` is missing, the tool raises `EnvironmentError` with `npm install -g @openapitools/openapi-generator-cli` (INV-SDK-008).

*References*: CC-06, INV-SDK-002, T-05

---

**US-13** — As a Java developer, I want a Java SDK generated with both Maven and Gradle build files so that the SDK integrates into either build ecosystem without manual conversion.

`openapi-generator-cli -g java` produces Java sources with `pom.xml` (Maven) and `build.gradle` (Gradle) alongside.
`pom.xml` version element and `build.gradle` `ext.version` variable both contain the API semver version (INV-SDK-002).
Both build files use the same groupId (`com.myorg`) and artifactId (`myapi-client`) so consumers reference the same coordinates.
`./mvnw compile` and `./gradlew compileJava` both succeed on the generated sources without modification.
JDK 11 is the minimum supported version, declared in both `pom.xml` `<source>` and `build.gradle` `sourceCompatibility`.
T-05 verifies Java SDK generation; the presence of both `pom.xml` and `build.gradle` is asserted by CC-07.

*References*: CC-07, INV-SDK-002, T-05

---

**US-14** — As a platform engineer, I want to generate SDKs for all 5 supported languages in a single command so that release packages are always produced together and never partially updated.

`generate_sdk(project_dir=".", languages=["python","typescript","go","rust","java"])` runs all 5 generators sequentially with a progress reporter.
If one language fails (missing tool, schema parse error), the failure is recorded but generation continues for remaining languages.
The returned dict contains a `per_language` key with `{"python": True, "go": False, "error": "oapi-codegen not found"}` entries.
The overall `success` field is `True` only if all requested languages succeeded, allowing CI to fail the build if any language fails.
INV-SDK-008 requires actionable errors; CC-25 mandates `EnvironmentError` with install commands; T-06 verifies this behaviour.
T-12 runs `generate_sdk()` for all 5 languages with mocked subprocess calls and asserts 5 per-language entries in the result.

*References*: CC-25, INV-SDK-008, T-06

---

**US-15** — As a developer, I want `oneOf` and `anyOf` unions in the OpenAPI schema to produce proper union types in each language so that polymorphic response types are handled correctly and safely.

A schema field `result: { oneOf: [SuccessResult, ErrorResult] }` produces `Union[SuccessResult, ErrorResult]` in Python with a Pydantic discriminator.
In TypeScript it produces `SuccessResult | ErrorResult` with an optional discriminator field narrowing the union.
In Go it produces a discriminated union interface with a concrete `UnmarshalJSON` method for each variant.
T-13 feeds a synthetic OpenAPI schema containing `oneOf: [Cat, Dog]` with a `petType` discriminator and asserts the generated Python code compiles with `mypy`.
The Pydantic v2 `model_validator` is used to select the correct variant at deserialisation time.
CC-27 mandates union type support; this story ensures the implementation handles both `oneOf` and `anyOf` correctly.

*References*: CC-27, T-13

---

### 9.4 Publishing

**US-16** — As a release engineer, I want `generate_sdk(publish=False)` (default) to perform package validation only so that no package is accidentally published during development or routine CI runs.

Without `publish=True`, `publish_python_sdk` runs `twine check dist/*.whl` and reports the result in the returned dict.
The npm publish step runs `npm pack --dry-run` to verify the package contents without uploading.
No registry credentials are needed for dry-run mode, so the step can run in pull-request CI without secrets.
The dry-run output (stdout from `twine check`, stderr from `npm pack --dry-run`) is included in the returned dict for inspection.
INV-SDK-003 makes `publish=False` the default and requires an explicit guard before any upload command.
T-23 mocks the subprocess layer and asserts that no upload command (twine upload, npm publish) is called when `publish=False`.

*References*: INV-SDK-003, CC-19, CC-20, T-23

---

**US-17** — As a release engineer, I want `generate_sdk(publish=True)` to publish all generated SDKs to their respective default registries so that a single flag triggers a complete multi-language release.

With `publish=True`, Python publishes to PyPI via `twine upload dist/*.whl` using the `PYPI_TOKEN` environment variable.
TypeScript publishes via `npm publish --access public` using `NPM_TOKEN` from the environment.
Go publishes by pushing a semver Git tag; the GOPROXY infrastructure serves it automatically from the tag.
Rust publishes via `cargo publish --token $CARGO_TOKEN` to crates.io.
Each language publish step is independent — a failure in one does not prevent publication of others.
INV-SDK-003 ensures this path only executes when `publish=True` is explicit; T-25 verifies `twine upload` is called exactly once.

*References*: INV-SDK-003, CC-21, T-25

---

**US-18** — As a release engineer, I want a version collision on PyPI detected before the upload attempt so that I receive a clear error message instead of a cryptic twine exit code.

Before calling `twine upload`, the tool queries `https://pypi.org/pypi/{package_name}/json` via `httpx`.
If the current API version already exists in the `releases` dict of the PyPI API response, `PublishError` is raised immediately.
The error message contains the package name, the conflicting version, and the instruction to bump `info.version` in the FastAPI app.
No partial publish occurs — the tool raises before invoking `twine`, so the registry is never in a half-uploaded state.
CC-30 mandates this pre-check; T-26 mocks the PyPI API to return a response containing the current version and asserts `PublishError` is raised.
The pre-check also validates that `PYPI_TOKEN` is set in the environment, failing early with a clear credential error.

*References*: CC-30, T-26

---

**US-19** — As a release engineer, I want to publish to a private Artifactory or Nexus registry by passing `registry=<url>` so that internal-only packages never reach public registries.

`generate_sdk(publish=True, registry="https://nexus.internal/repository/pypi/")` passes `--repository-url https://nexus.internal/...` to every `twine upload` call.
For TypeScript, the tool writes a `.npmrc` file in the SDK directory containing `registry=https://nexus.internal/npm/` before calling `npm publish`.
For Go, the `GOPROXY` environment variable is set to the provided registry URL before invoking `go list`.
For Rust, the `--registry` flag is appended to the `cargo publish` invocation if a registry URL is provided.
T-27 mocks the subprocess layer and asserts `--repository-url` appears in the `twine upload` args when `registry` is set.
CC-31 mandates registry URL forwarding; the URL is validated to be a non-empty HTTPS URL before use.

*References*: CC-31, T-27

---

**US-20** — As a DevOps engineer, I want the SDK publish step to retry on transient network failures so that flaky CI infrastructure does not block intentional releases.

`publish_python_sdk` wraps the `twine upload` subprocess in a retry loop with a maximum of 3 attempts.
Backoff between attempts is 5 seconds (fixed, not exponential, to avoid excessive CI job durations).
The tool distinguishes network failures (subprocess exits with error and stderr contains "connection" or "timeout") from semantic failures (version already exists).
Semantic failures such as version collisions raise `PublishError` immediately without retrying (CC-30 pre-check handles these).
T-26 asserts that a version-collision error does not trigger any retry; a separate test verifies that a connection error retries 3 times.
The total retry overhead for a network-unstable CI run is at most 15 s (3 × 5 s backoff), acceptable for a release pipeline.

*References*: INV-SDK-003, T-26

---

### 9.5 Edge Cases and Operations

**US-21** — As a developer, I want the first-time SDK generation on a fresh project (no existing `sdks/` directory) to create all required directories and files without errors.

`generate_sdk()` calls `output_dir.mkdir(parents=True, exist_ok=True)` as its first operation before any generator invocation.
The `scripts/sdk_tools/` directory is also created if it does not exist, so the tool is fully self-bootstrapping.
T-10 runs the tool against a `tmp_path` pytest fixture directory containing only a minimal FastAPI `app.py` with no `sdks/` folder.
The test asserts that `sdks/myapi_client/` exists after the call with at least `exceptions.py`, `pagination.py`, and `client.py`.
No exception is raised on first run; the `files_created` list in the returned dict contains all newly created file paths.
CC-26 mandates the return dict shape; first-run behaviour is distinct from re-run (no idempotency check on fresh creation).

*References*: CC-26, T-10

---

**US-22** — As a developer, I want re-running `generate_sdk()` with an unchanged schema to produce a byte-identical `sdks/` directory tree so that regeneration never introduces spurious git diffs.

INV-SDK-006 requires idempotency: running the generator twice on the same input must produce the same output, verified by SHA-256 hash of the entire `sdks/` tree.
Generator non-determinism sources (file timestamps in comments, UUID identifiers, dict ordering) must be disabled or sorted in generator templates.
T-29 runs `generate_sdk()` twice on the same project with the same FastAPI app, hashes both outputs, and asserts equality.
If the hash differs, `IdempotencyError` is raised with the first differing file path shown for debugging.
This invariant is also checked by the CI `git diff --exit-code sdks/` step after regeneration (INV-SDK-007).
Developers can rely on `make sdk-regen` producing no diff if the API has not changed since the last commit.

*References*: INV-SDK-006, CC-29, T-29

---

**US-23** — As a CI engineer, I want the SDK-regen workflow to block pull requests when `sdks/` is out of sync with the current schema so that consumers always receive an accurate SDK from the repository.

The `.github/workflows/sdk-regen.yml` workflow triggers on every PR that touches `app/**/*.py` or `openapi.json`.
It installs SDK tooling, runs `make sdk-regen`, then runs `git diff --exit-code sdks/` to detect any file-level change.
If `sdks/` differs, the step exits with code 1 and prints: `SDK drift detected — run 'make sdk-regen' locally and commit the result`.
This message is surfaced in the GitHub Actions UI so the developer sees the fix instruction without reading logs.
INV-SDK-007 mandates this CI gate; T-28 verifies the workflow file contains the drift-detection command.
CC-22 and CC-23 specify the exact file path and the exact command that must appear in the workflow file.

*References*: INV-SDK-007, CC-22, CC-23, T-28

---

**US-24** — As a developer, I want a breaking schema change to surface a clearly labelled warning with version bump guidance so that I can communicate the impact to API consumers before publishing.

When `generate_sdk()` runs and detects that a field or path present in the previously committed `sdks/` tree is absent from the new schema, it appends a `breaking_change_warning` to the returned dict.
The warning message reads: `WARNING: Breaking change detected — field '{field}' removed. Consider bumping major version (X.Y.Z → (X+1).0.0) before publishing.`
The detection logic diffs the previous `sdks/*/models.py` field names against the newly generated ones using a simple name-set comparison.
T-11 feeds a schema missing the `email` field that was present in the seeded SDK and asserts the warning key is present in the return dict.
No error is raised — a breaking change is a legal schema evolution; the warning is advisory.
CC-02 mandates the semver validation before generation; this story ensures developers receive actionable guidance.

*References*: CC-02, T-11

---

**US-25** — As a developer, I want a missing generator tool to raise an `EnvironmentError` with the exact install command so that I can resolve the dependency in under a minute without consulting documentation.

If `oapi-codegen` is not found by `shutil.which("oapi-codegen")`, the tool raises `EnvironmentError` immediately with:
`"oapi-codegen not found. Install with: go install github.com/deepmap/oapi-codegen/cmd/oapi-codegen@latest"`.
If `npx` is not found, the message is: `"npx not found. Install Node.js >= 18 from https://nodejs.org"`.
If `openapi-generator-cli` is not found, the message is: `"openapi-generator-cli not found. Install with: npm install -g @openapitools/openapi-generator-cli"`.
Generation continues for other languages after the error is recorded in `per_language[lang]["error"]`.
INV-SDK-008 mandates this; T-06 mocks `shutil.which` to return `None` and asserts the error message contains the install command verbatim.

*References*: INV-SDK-008, CC-25, T-06

---

## 10. Test Plan

The 30 tests are grouped into six categories so reviewers can quickly find the coverage area: schema extraction, per-language generation, generated-code correctness, auth/pagination/retry helpers, versioning and publishing safety, and CI/idempotency guarantees. Every test is either a fast unit test (mock subprocess / mock network) or an integration test against real generator binaries installed in a pinned CI image.

### 10.1 Schema extraction and generator invocation (T-01..T-05)

| ID | Description | Layer |
|----|-------------|-------|
| T-01 | `extract_schema()` returns dict with `schema`, `version`, `title` from live `app.openapi()` | Unit |
| T-02 | `extract_schema()` raises `ImportError` when app_module path is invalid | Unit |
| T-03 | `generate_python_sdk()` subprocess call contains `--path schema.json --output-path sdks/` | Unit/mock |
| T-04 | `generate_typescript_sdk()` writes `package.json` with version equal to `api_version` | Unit |
| T-05 | `generate_go_sdk()` writes `version.go` constant equal to `api_version` | Unit |

### 10.2 Tooling, CI workflow, and bootstrap (T-06..T-10)

| ID | Description | Layer |
|----|-------------|-------|
| T-06 | When `oapi-codegen` missing from PATH, `EnvironmentError` message contains install command | Unit/mock |
| T-07 | `.github/workflows/sdk-regen.yml` created and contains `git diff --exit-code sdks/` | Integration |
| T-08 | `Makefile` contains `sdk-regen`, `sdk-check`, `sdk-publish` targets | Integration |
| T-09 | Generated Python SDK passes `ruff check` with zero errors | Integration |
| T-10 | First-run with no existing `sdks/` directory creates full structure without error | Integration |

### 10.3 Generated-code correctness and typing (T-11..T-15)

| ID | Description | Layer |
|----|-------------|-------|
| T-11 | Schema with removed field emits `Breaking change detected` warning in returned dict | Unit |
| T-12 | `generate_sdk()` returns per-language `success` flags when languages list has 5 entries | Integration |
| T-13 | Schema with `oneOf: [Cat, Dog]` produces `Union[Cat, Dog]` in generated Python models | Integration |
| T-14 | Generated `exceptions.py` contains at minimum `NotFoundError`, `UnauthorizedError`, `ServerError` | Unit |
| T-15 | All generated operation methods have non-empty bodies (no `pass`-only stubs) | Unit |

### 10.4 Runtime helpers: auth, pagination, retries (T-16..T-21)

| ID | Description | Layer |
|----|-------------|-------|
| T-16 | `paginate_offset` async generator yields all 100 items across 5 pages of 20 | Integration |
| T-17 | `AuthConfig.bearer_token` present in generated client when `bearerAuth` in security schemes | Unit |
| T-18 | Auth helpers absent in generated client when schema has no security schemes | Unit |
| T-19 | `_request_with_retry` retries 5xx response 3 times then re-raises `ServerError` | Unit |
| T-20 | `check_python_sdk_version()` raises `VersionMismatchError` when pyproject.toml version differs from expected | Unit |
| T-21 | `version.go` constant equals `api_version` after `generate_go_sdk()` call | Unit |

### 10.5 Versioning and publish safety (T-22..T-27)

| ID | Description | Layer |
|----|-------------|-------|
| T-22 | `publish_python_sdk(dry_run=True)` calls `twine check` and never calls `twine upload` | Unit/mock |
| T-23 | `generate_sdk(publish=False)` (default) does not invoke any upload subprocess | Unit/mock |
| T-24 | `publish_python_sdk(dry_run=True)` returns `{"success": True, "phase": "dry_run"}` on zero exit code | Unit |
| T-25 | `publish_python_sdk(dry_run=False)` calls `twine upload dist/*.whl` exactly once | Unit/mock |
| T-26 | When `twine upload` exits with "version exists" error, `PublishError` is raised and no retry is attempted | Unit/mock |
| T-27 | `generate_sdk(publish=True, registry="https://nexus.internal/pypi/")` passes `--repository-url` to `twine upload` | Unit/mock |

### 10.6 CI sync, idempotency, and performance (T-28..T-30)

| ID | Description | Layer |
|----|-------------|-------|
| T-28 | CI workflow `git diff --exit-code sdks/` step exits non-zero when `sdks/` has uncommitted changes | CI/integration |
| T-29 | Two sequential calls to `generate_sdk()` with same schema produce byte-identical SHA-256 of `sdks/` tree | Integration |
| T-30 | Synthetic 500-route schema completes full generation for Python + TypeScript + Go in < 30 s wall time | Performance |

---

## 11. Interaction Matrix

| Tool | Direction | Interaction | Notes |
|------|-----------|-------------|-------|
| `TOOL-033 api_spec_compliance` | Pre-requisite | SDK generation requires a schema that passes compliance checks; non-compliant schema may produce invalid client code | Run api_spec_compliance before generate_sdk in CI |
| `TOOL-038 api_changelog` | Pre-requisite | Changelog tool identifies breaking vs non-breaking changes; generate_sdk uses this to decide major vs minor version bump suggestion | generate_sdk reads `CHANGELOG.md` if present |
| `TOOL-017 add_api_versioning` | Pre-requisite | API versioning tool sets `info.version` in schema; generate_sdk reads this to align SDK version | INV-SDK-002 requires api_versioning to be run first |
| `TOOL-026 add_contract_tests` | Complementary | Contract tests verify the running API matches the schema; SDK smoke tests verify the generated client matches the same schema | Both reference the same OpenAPI JSON |
| `TOOL-010 add_api_key_auth` | Pre-requisite | API key auth tool adds `securitySchemes.apiKeyAuth` to schema; generate_sdk auto-generates `AuthConfig.api_key` helpers | INV-SDK-005: auth helpers generated when schemes present |
| `TOOL-011 add_oauth2_provider` | Pre-requisite | OAuth2 provider tool adds `securitySchemes.oauth2` to schema; generate_sdk generates `get_oauth2_token()` helper | OAuth2 client credentials flow in `auth.py` |
| `TOOL-014 add_pagination` | Pre-requisite | Pagination tool adds `x-pagination` extensions to schema; generate_sdk reads these to generate cursor/offset iterators | INV-SDK-001: schema always live, so pagination changes picked up immediately |
| `TOOL-015 add_rate_limiting` | Complementary | Rate limit tool adds `x-rate-limit` headers to responses; generate_sdk generates `RateLimitError` with `Retry-After` parsing | `RateLimitError` class in `exceptions.py` |
| `TOOL-020 add_error_catalog` | Complementary | Error catalog tool standardizes error response schemas; generate_sdk maps these to typed exceptions | Richer `detail` field on exception classes |
| `TOOL-001 generate_project` | Post-requisite | Initial project generator creates the skeleton; generate_sdk runs after project has routes | Must have at least one route before SDK generation |
| `TOOL-044 refactor_model` | Sequential | Model refactor renames fields; after refactor, generate_sdk must be re-run to update SDK field names | CI sdk-regen workflow picks this up automatically |
| `TOOL-031 add_openapi_tags` | Complementary | Tags tool organizes endpoints into groups; generate_sdk uses tag names as module names in multi-file TypeScript output | Affects file structure in TypeScript SDK only |
| `TOOL-022 add_background_tasks` | Informational | Background task endpoints may return 202 Accepted; generate_sdk generates `AcceptedResponse` model for these | Async operation polling pattern in pagination module |
| `TOOL-030 add_webhooks` | Informational | Webhook tool adds outbound callbacks to schema; generate_sdk skips webhook paths (outbound only) | Webhook receiver SDK is out of scope for generate_sdk |
| `TOOL-025 add_caching_headers` | Complementary | Caching tool adds ETag/Cache-Control headers; generate_sdk can generate conditional request helpers using `If-None-Match` | Optional enhancement to `_request_with_retry` |

---

## 12. Rollback Procedure

### 12.1 Overview

`fastapi_generate_sdk` is a **code-only** tool. It creates new files under `sdks/` and `scripts/sdk_tools/`, modifies `pyproject.toml`, `Makefile`, and `.github/workflows/sdk-regen.yml`. It does not touch any database schema, Alembic migrations, or runtime state. All rollback procedures are therefore file-level operations (git revert) plus optional registry un-publish steps.

---

### 12.2 Database Rollback

**N/A** — this tool is a code-only generator. No database tables, columns, indexes, or Alembic migrations are created or modified. `alembic downgrade -1` would be a no-op. Skip this step entirely.

---

### 12.3 File Rollback (primary procedure)

If any generated file causes build failures or test regressions:

```bash
# Step 1: Revert all files generated or modified by generate_sdk
git checkout HEAD -- sdks/ scripts/sdk_tools/ Makefile pyproject.toml .github/workflows/sdk-regen.yml

# Step 2: Verify the project builds without the SDK tooling
PYTHONPATH=src pytest tests/ -x --ignore=tests/sdk/

# Step 3: Confirm sdks/ directory is back to pre-run state
git status sdks/
```

If the tool was run on a feature branch (recommended per `feedback_prs_merges.md`):

```bash
# Simply close the PR and delete the branch
git push origin --delete feature/sdk-generation
```

---

### 12.4 Failure Mode: SDK generation fails for one language

If generation succeeds for Python but fails for TypeScript (e.g., `npx` not in CI PATH):

```bash
# Remove only the failed language output, keep others
rm -rf sdks/myapi-ts/

# Fix the dependency issue (install Node.js in CI runner)
# Then re-run for only the failing language
PYTHONPATH=scripts python3 -c "
from sdk_tools.generate_typescript import generate_typescript_sdk
from pathlib import Path
result = generate_typescript_sdk(
    schema_path=Path('/tmp/schema.json'),
    output_dir=Path('sdks'),
    package_name='myapi-client',
    api_version='2.3.0',
)
print(result)
"
```

---

### 12.5 Failure Mode: Registry publish fails or wrong version published

If `twine upload` succeeds but the wrong version was published:

```bash
# Step 1: Yank the release on PyPI (marks it as not installable, not deleted)
# Requires PyPI project maintainer role
pip install requests
python3 -c "
import os, requests
token = os.environ['PYPI_TOKEN']
r = requests.post(
    'https://pypi.org/manage/project/myapi-client/release/2.3.0/yank/',
    headers={'Authorization': f'token {token}'},
    data={'yanked_reason': 'Incorrect version published via generate_sdk'},
)
print(r.status_code, r.text[:200])
"

# Step 2: Fix the version in the source
# Edit app/main.py: app = FastAPI(version="2.3.1")
# Re-run generate_sdk to align SDK version
# Publish the corrected 2.3.1 version

# Step 3: For npm, deprecate the bad version
npm deprecate @myorg/myapi-client@2.3.0 "Use 2.3.1 instead"
```

---

### 12.6 Failure Mode: Version collision (version already exists on registry)

```bash
# The tool raises PublishError before uploading — no partial publish occurs.
# Resolution: bump the API version and re-run.
# 1. Edit app/main.py: app = FastAPI(version="2.3.1")
# 2. Re-run SDK generation
PYTHONPATH=scripts python3 -c "
from sdk_tools.generate_sdk import generate_sdk
generate_sdk(project_dir='.', languages=['python'], publish=False)
"
# 3. Verify version alignment
PYTHONPATH=scripts python3 -c "
from sdk_tools.version_aligner import check_python_sdk_version
from pathlib import Path
check_python_sdk_version(Path('sdks/myapi_client'), '2.3.1')
print('Version OK')
"
# 4. Publish with corrected version
generate_sdk(project_dir='.', languages=['python'], publish=True)
```

---

### 12.7 Failure Mode: Generator tool missing in production CI

If `oapi-codegen` or `openapi-generator-cli` is missing in CI:

```bash
# The tool raises EnvironmentError with the install command.
# For CI, add the dependency to the workflow's install step:

# For Go SDK in GitHub Actions:
# - name: Install oapi-codegen
#   run: go install github.com/deepmap/oapi-codegen/cmd/oapi-codegen@latest

# For Rust/Java SDK in GitHub Actions:
# - name: Install openapi-generator-cli
#   run: |
#     npm install -g @openapitools/openapi-generator-cli
#     openapi-generator-cli version

# Verify installation locally before CI push:
which oapi-codegen && oapi-codegen --version
which openapi-generator-cli && openapi-generator-cli version
```

---

### 12.8 Emergency: Revert CI auto-regen workflow

If the `sdk-regen.yml` workflow is causing spurious CI failures:

```bash
# Step 1: Temporarily disable the workflow by renaming it
git mv .github/workflows/sdk-regen.yml .github/workflows/sdk-regen.yml.disabled
git commit -m "chore: disable sdk-regen workflow temporarily"
git push origin HEAD

# Step 2: Investigate the root cause
# Check if the schema extraction is producing non-deterministic output
PYTHONPATH=scripts python3 -c "
import hashlib, json
from sdk_tools.extract_schema import extract_schema, write_schema_to_temp
from pathlib import Path
s1 = extract_schema('.')
s2 = extract_schema('.')
print('Schemas equal:', json.dumps(s1['schema'], sort_keys=True) == json.dumps(s2['schema'], sort_keys=True))
"

# Step 3: Re-enable after fix
git mv .github/workflows/sdk-regen.yml.disabled .github/workflows/sdk-regen.yml
git commit -m "chore: re-enable sdk-regen workflow"
git push origin HEAD
```

---

## 13. Edge Cases

| ID | Input / Condition | Expected |
|----|-------------------|---------|
| EC-01 | First run with no existing `sdks/` directory | `sdks/` created with full structure; no error raised on missing parent |
| EC-02 | Same schema, second run | Output is byte-identical to first run; SHA-256 of `sdks/` tree matches |
| EC-03 | Schema has breaking change (field removed since last commit) | `WARNING: Breaking change detected` in returned dict; major version bump suggested |
| EC-04 | Schema has non-breaking addition (new optional field) | Minor or patch version bump suggested; no error raised |
| EC-05 | Publishing Python SDK when same version already exists on PyPI | `PublishError` raised before upload; message contains version string and resolution hint |
| EC-06 | `oapi-codegen` binary not in PATH | `EnvironmentError` with exact `go install` command; other language generators continue |
| EC-07 | Network timeout during `npm publish` | Retry 3 times with 5 s backoff; final failure reported in returned dict without crash |
| EC-08 | TypeScript SDK with ESM + CJS output requested | `package.json` contains both `"main"` (CJS) and `"module"` (ESM) fields |
| EC-09 | Go SDK with custom `module_path` passed via `package_name` | `go.mod` `module` directive uses the provided path verbatim |
| EC-10 | Java SDK generation requested | Both `pom.xml` and `build.gradle` generated; both files contain identical version from API schema |
| EC-11 | `generate_sdk()` called twice with identical schema | Idempotency check passes; no `IdempotencyError`; CI reports no drift |
| EC-12 | OpenAPI schema uses `oneOf` union with discriminator | Python SDK generates `Union[TypeA, TypeB]` with Pydantic discriminator field |
| EC-13 | Schema declares `BearerAuth` security scheme | `AuthConfig.bearer_token` field generated; `Authorization` header set on every request |
| EC-14 | CI `git diff --exit-code sdks/` finds uncommitted SDK files | Workflow exits non-zero; PR blocked with message directing developer to run `make sdk-regen` |
| EC-15 | Schema has 500 routes and 200 models | All 5 languages generated in < 30 s total; no timeout exception raised |

---

## 14. Acceptance Criteria

✅ 1. `generate_sdk(project_dir=".", languages=["python"])` creates `sdks/myapi_client/` with typed models, typed exceptions, auth helpers, and pagination iterators in under 10 seconds.

✅ 2. Generated Python SDK passes `mypy --strict` with zero errors and `ruff check` with zero errors.

✅ 3. Generated TypeScript SDK passes `tsc --strict --noEmit` with zero type errors.

✅ 4. Generated Go SDK passes `go vet ./...` and `go build ./...` without errors.

✅ 5. `generate_sdk(publish=False)` (default) never invokes `twine upload`, `npm publish`, or any registry upload command.

✅ 6. SDK version in `pyproject.toml` / `package.json` / `version.go` equals `info.version` from the OpenAPI schema.

✅ 7. `generate_sdk()` run twice on identical schema produces byte-identical `sdks/` tree (idempotency verified by SHA-256).

✅ 8. CI workflow `.github/workflows/sdk-regen.yml` blocks PR merge when `sdks/` is out of sync with current schema.

✅ 9. Missing generator tool (`oapi-codegen`, `npx`, etc.) raises `EnvironmentError` containing the exact install command; remaining languages continue generating.

✅ 10. All 30 test cases T-01..T-30 pass with zero failures and zero skips in `pytest tests/sdk/ -v`.

---

## 15. Implementation Checklist

### 15.1 Schema Extraction
- [ ] Create `scripts/sdk_tools/__init__.py` with public exports
- [ ] Implement `extract_schema(project_dir, app_module)` in `extract_schema.py`
- [ ] Add `sys.path` insertion at index 0 and removal after import to avoid pollution
- [ ] Call `app.openapi()` directly — never read from a stale JSON file on disk
- [ ] Validate `info.version` matches semver `X.Y.Z` regex before returning
- [ ] Implement `write_schema_to_temp(schema, output_path)` helper with `json.dump`
- [ ] Add unit test T-01 verifying return dict keys `schema`, `version`, `title`
- [ ] Add unit test T-02 verifying `ImportError` on invalid app_module path

### 15.2 Python SDK Generator
- [ ] Implement `generate_python_sdk(schema_path, output_dir, package_name, api_version)` in `generate_python.py`
- [ ] Invoke `python -m openapi_python_client generate` subprocess with `--overwrite` flag
- [ ] Stamp `api_version` into generated `__version__.py` file after successful generation
- [ ] Write `python_client_config.yaml` template alongside schema before invocation
- [ ] Return `success`, `package_dir`, `stdout`, `stderr` dict on both success and failure
- [ ] Add unit test T-03 asserting subprocess cmd contains `--path` and `--output-path`
- [ ] Verify generated SDK passes `ruff check` with zero errors in T-09

### 15.3 TypeScript SDK Generator
- [ ] Implement `generate_typescript_sdk(schema_path, output_dir, package_name, api_version)` in `generate_typescript.py`
- [ ] Check for `npx` in PATH via `shutil.which`; raise `EnvironmentError` with Node.js install URL if missing
- [ ] Write `orval.config.json` inline in the output directory before invocation
- [ ] Write `package.json` with `version == api_version` and dual `main`/`module` ESM/CJS fields
- [ ] Write `tsconfig.json` with `"strict": true` alongside the generated sources
- [ ] Add unit test T-04 asserting `package.json` version equals `api_version`
- [ ] Verify generated SDK passes `tsc --strict --noEmit` in integration test

### 15.4 Go SDK Generator
- [ ] Implement `generate_go_sdk(schema_path, output_dir, package_name, module_path, api_version)` in `generate_go.py`
- [ ] Check for `oapi-codegen` in PATH; raise `EnvironmentError` with exact `go install` command
- [ ] Write `version.go` constant `Version = "X.Y.Z"` after successful generation
- [ ] Write `go.mod` with the configurable module path from the `module_path` parameter
- [ ] Return `success`, `package_dir`, `stdout`, `stderr` dict
- [ ] Add unit test T-05 asserting `version.go` content equals `api_version`
- [ ] Add unit test T-06 asserting `EnvironmentError` message contains `go install` when tool missing

### 15.5 Rust SDK Generator
- [ ] Implement `generate_rust_sdk(schema_path, output_dir, package_name, api_version)` in `generate_rust.py`
- [ ] Invoke `openapi-generator-cli generate -g rust-reqwest` subprocess
- [ ] Patch `Cargo.toml` version field with `api_version` after generation using regex substitution
- [ ] Check for `openapi-generator-cli` in PATH; raise `EnvironmentError` with npm install command
- [ ] Return `success`, `package_dir`, `stdout`, `stderr` dict on both outcomes
- [ ] Add unit test verifying `Cargo.toml` version equals `api_version` after generation
- [ ] Add unit test verifying `EnvironmentError` raised with install instruction when tool missing

### 15.6 Java SDK Generator
- [ ] Implement `generate_java_sdk(schema_path, output_dir, package_name, api_version)` in `generate_java.py`
- [ ] Invoke `openapi-generator-cli generate -g java` subprocess with configurable group/artifact IDs
- [ ] Generate both `pom.xml` and `build.gradle` with matching version from `api_version`
- [ ] Check for `openapi-generator-cli` in PATH; raise `EnvironmentError` if missing
- [ ] Verify `pom.xml` version and `build.gradle` ext.version are identical
- [ ] Add unit test verifying both build files contain the correct API version
- [ ] Add unit test verifying `EnvironmentError` raised when `openapi-generator-cli` missing

### 15.7 Version Aligner
- [ ] Implement `extract_api_version(schema)` with `re.fullmatch(r"\d+\.\d+\.\d+", ...)` validation
- [ ] Implement `check_python_sdk_version(package_dir, expected)` reading `pyproject.toml` with `tomllib`
- [ ] Implement `stamp_version_in_pyproject(package_dir, version)` with regex in-place substitution
- [ ] Implement `VersionMismatchError(ValueError)` with descriptive message including both versions
- [ ] Add unit test T-20 verifying `VersionMismatchError` raised on version mismatch
- [ ] Add unit test T-21 verifying `version.go` constant matches `api_version` after go generation
- [ ] Verify `extract_api_version` raises `ValueError` for non-semver strings like `"1.0"` or `"v2.3.1"`

### 15.8 Typed Exception Hierarchy
- [ ] Create `exceptions.py` template with `ApiError` base plus 8 subclasses (Bad, Unauthorized, Forbidden, NotFound, Conflict, Unprocessable, RateLimit, Server)
- [ ] Implement `_map_http_error(exc: httpx.HTTPStatusError) -> ApiError` mapping status to class
- [ ] Create equivalent `errors.ts` TypeScript template with same 8 typed classes
- [ ] Create equivalent `errors.go` Go template with typed error struct per status class
- [ ] Populate `self.detail` from `response.json()` in `ApiError.__init__` with silent fallback
- [ ] Add unit test T-14 asserting minimum 8 exception classes present in `exceptions.py`
- [ ] Add unit test T-15 asserting no generated operation method is a `pass`-only stub

### 15.9 Pagination Iterators
- [ ] Implement `paginate_cursor(client, path, ...)` async generator yielding individual items in `pagination.py`
- [ ] Implement `paginate_offset(client, path, ...)` async generator with short-page stop condition
- [ ] Implement `SecuritySchemeDetector.detect_pagination(schema, operation_id)` returning `"cursor"` or `"offset"` or `None`
- [ ] Create equivalent TypeScript async generator template for both cursor and offset
- [ ] Add integration test T-16 seeding 100 items and asserting all collected via `paginate_offset`
- [ ] Verify cursor paginator stops correctly when `next_cursor` is `None` or absent from response
- [ ] Verify offset paginator stops correctly when fewer than `limit` items returned on final page

### 15.10 Auth Helpers
- [ ] Implement `SecuritySchemeDetector.has_schemes(schema)` checking `schema["components"]["securitySchemes"]`
- [ ] Generate `AuthConfig` with `bearer_token`, `api_key`, `api_key_header`, `timeout`, `max_retries` fields
- [ ] Generate `_set_auth_headers()` method setting appropriate `httpx.Client` headers from `AuthConfig`
- [ ] Generate `get_oauth2_token(client_id, client_secret, token_url)` when `oauth2` scheme present in schema
- [ ] Skip all auth helpers when `has_schemes(schema)` returns `False` (no security defined)
- [ ] Add unit test T-17 verifying `bearer_token` present in `AuthConfig` when `bearerAuth` in schema
- [ ] Add unit test T-18 verifying auth helpers absent from generated client when schema has no security schemes

### 15.11 Publish Scripts
- [ ] Implement `publish_python_sdk(package_dir, registry, dry_run=True)` in `publish_python.py`
- [ ] Guard upload subprocess behind explicit `if not dry_run` block
- [ ] Add PyPI version-collision pre-check via `httpx.get("https://pypi.org/pypi/{name}/json")`
- [ ] Raise `PublishError` on version collision without invoking `twine upload`
- [ ] Implement retry loop (3 attempts, 5 s backoff) only for network errors
- [ ] Add unit test T-22 verifying `twine check` called but `twine upload` never called when `dry_run=True`
- [ ] Add unit tests T-23, T-24, T-25, T-26, T-27 for default, dry-run result, live publish, collision, registry URL

### 15.12 CI Workflow and Makefile
- [ ] Create `.github/workflows/sdk-regen.yml` with `on.pull_request.paths` trigger for `app/**/*.py`
- [ ] Add `git diff --exit-code sdks/` step with human-readable failure message
- [ ] Include `actions/checkout@v4` and Python setup steps before SDK tooling installation
- [ ] Add `sdk-regen` Makefile target that runs `generate_sdk` for all 5 languages
- [ ] Add `sdk-check` Makefile target that runs idempotency hash check only (no generator invocation)
- [ ] Add `sdk-publish` Makefile target with `publish=True` flag enabled
- [ ] Add unit tests T-07 and T-08 asserting workflow file and Makefile contents

### 15.13 Integration Tests and Documentation
- [ ] Create `tests/sdk/test_python_sdk_smoke.py` with 5+ smoke tests against a real test server
- [ ] Add performance test T-30 with synthetic 500-route schema asserting < 30 s wall time
- [ ] Add idempotency test T-29 hashing `sdks/` tree SHA-256 across two sequential runs
- [ ] Add CI sync test T-28 asserting `sdk-regen.yml` contains `git diff --exit-code sdks/`
- [ ] Add breaking-change detection test T-11 asserting `breaking_change_warning` in returned dict
- [ ] Create `docs/sdk/OVERVIEW.md` documenting usage, supported languages, and version alignment
- [ ] Run full test suite `pytest tests/sdk/ -v` and confirm all 30 T-01..T-30 tests pass

---

## 16. Documentation Output

```json
{
  "status": "generated",
  "files_created": [
    "scripts/sdk_tools/__init__.py",
    "scripts/sdk_tools/extract_schema.py",
    "scripts/sdk_tools/generate_python.py",
    "scripts/sdk_tools/generate_typescript.py",
    "scripts/sdk_tools/generate_go.py",
    "scripts/sdk_tools/generate_rust.py",
    "scripts/sdk_tools/generate_java.py",
    "scripts/sdk_tools/version_aligner.py",
    "scripts/sdk_tools/publish_python.py",
    "sdks/myapi_client/myapi_client/exceptions.py",
    "sdks/myapi_client/myapi_client/pagination.py",
    "sdks/myapi_client/myapi_client/client.py",
    ".github/workflows/sdk-regen.yml",
    "tests/sdk/test_python_sdk_smoke.py",
    "docs/sdk/OVERVIEW.md"
  ],
  "files_modified": [
    "pyproject.toml",
    "Makefile",
    ".github/workflows/sdk-regen.yml"
  ],
  "metrics": {
    "languages_supported": 5,
    "test_cases": 30,
    "lines_of_spec": 1350,
    "invariants": 8,
    "completeness_criteria": 33,
    "user_stories": 25
  },
  "next_steps": [
    "Run TOOL-033 api_spec_compliance to validate schema before first SDK generation",
    "Run TOOL-017 add_api_versioning to ensure info.version is semver before generate_sdk",
    "Run TOOL-010 add_api_key_auth or TOOL-011 add_oauth2_provider to populate securitySchemes",
    "Install generator dependencies: openapi-python-client, orval (npx), oapi-codegen (go install), openapi-generator-cli (npm)",
    "Run TOOL-026 add_contract_tests to complement SDK smoke tests with schema contract validation",
    "Configure private registry URL in CI environment if not publishing to public registries",
    "Set up PYPI_TOKEN, NPM_TOKEN, and CARGO_TOKEN as CI secrets before enabling publish=True"
  ],
  "warnings": [
    "Publishing is off by default (publish=False). Enable only for intentional releases — accidental publishes cannot be un-done on PyPI without yanking.",
    "Version collision on PyPI is non-recoverable (yank only). Always verify API info.version is incremented before running with publish=True.",
    "openapi-generator-cli requires JVM 11+ for Rust and Java targets — add JDK installation step to CI before enabling those languages.",
    "Re-running generate_sdk after a breaking schema change will update the SDK without warning existing consumers — use api_changelog first."
  ],
  "notes": [
    "Schema is always extracted live from app.openapi() — never from a stale JSON file (INV-SDK-001). This means the FastAPI app must be importable from the scripts directory.",
    "SDK version alignment (INV-SDK-002) requires app = FastAPI(version='X.Y.Z') in the app constructor. Without this, extract_api_version() raises ValueError.",
    "The idempotency guarantee (INV-SDK-006) requires deterministic OpenAPI output from FastAPI. If your schema includes timestamps or random UUIDs, disable those before generation.",
    "The CI workflow checks for sdks/ drift on every PR touching app/**/*.py — this means developers must run make sdk-regen locally after any route or model change.",
    "TypeScript SDK uses orval by default (fetch-based). To switch to axios or react-query, modify the orval.config.json template in generate_typescript.py."
  ]
}
```
