"""BEHAVIOR TEST — TOOL-003 add_file_upload.

Proves that the code emitted by ``add_file_upload`` works at **runtime**:

* boots a real ASGI app with the file upload routes wired in,
* asserts /files routes are reachable (not 404),
* asserts LocalStorage streams chunked (no full-file buffering — DoD multipart),
* asserts FileMetadataPublic does NOT carry stored_key/tenant_id at import,
* asserts the validator path traversal guard fires at runtime.

Patches applied (so tests run without Docker):
- ``app/core/db.py``                → SQLite + aiosqlite (no Postgres)
- ``app/middleware/idempotency.py`` → pass-through stub (no Redis)
- ``REDIS_URL`` env var              → removed
"""

from __future__ import annotations

import os

os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SECRET_KEY", "behavior-test-file-upload-secret-key-32+!")
os.environ.pop("REDIS_URL", None)

import asyncio
import importlib
import io
import sys
import textwrap
from pathlib import Path
from typing import Any

import httpx
import pytest

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_file_upload import add_file_upload
from tests.common.fixture_factory import create_fixture_project

_SQLITE_DB_PY = textwrap.dedent("""\
    \"\"\"Patched db.py — SQLite+aiosqlite, no Docker required.\"\"\"

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )


    async def init_db() -> None:
        \"\"\"Run startup checks (connection test).\"\"\"
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))


    __all__ = ["engine", "init_db"]
""")

_PASSTHROUGH_IDEMPOTENCY_PY = textwrap.dedent("""\
    \"\"\"Patched idempotency.py — pass-through stub (no Redis).\"\"\"

    from __future__ import annotations

    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import Response


    class IdempotencyMiddleware(BaseHTTPMiddleware):
        \"\"\"No-op pass-through stub for testing without Redis.\"\"\"

        async def dispatch(
            self,
            request: Request,
            call_next: RequestResponseEndpoint,
        ) -> Response:
            return await call_next(request)
""")


def _patch_project(project_dir: Path) -> None:
    (project_dir / "app" / "core" / "db.py").write_text(_SQLITE_DB_PY)
    idempotency_path = project_dir / "app" / "middleware" / "idempotency.py"
    if idempotency_path.exists():
        idempotency_path.write_text(_PASSTHROUGH_IDEMPOTENCY_PY)


def _load_app(project_dir: Path) -> Any:
    _orig_path = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    stale = [k for k in sys.modules if k == "app" or k.startswith("app.")]
    for key in stale:
        del sys.modules[key]
    try:
        app_module = importlib.import_module("app.main")
    finally:
        sys.path[:] = _orig_path
    return app_module.app


def _setup_project() -> tuple[Path, Any]:
    project_dir = create_fixture_project(name="file_upload_behavior")
    result = add_file_upload(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"add_file_upload failed: {result.error}\nnotes: {result.notes}"
    )
    _patch_project(project_dir)
    return project_dir, _load_app(project_dir)


_PROJECT_DIR: Path | None = None
_ASGI_APP: Any = None


def _get_shared_app() -> tuple[Path, Any]:
    global _PROJECT_DIR, _ASGI_APP
    if _PROJECT_DIR is None:
        _PROJECT_DIR, _ASGI_APP = _setup_project()
    return _PROJECT_DIR, _ASGI_APP


@pytest.fixture(scope="module")
def project_dir_and_app() -> tuple[Path, Any]:
    return _get_shared_app()


@pytest.fixture(scope="module")
def project_dir(project_dir_and_app: tuple[Path, Any]) -> Path:
    return project_dir_and_app[0]


@pytest.fixture(scope="module")
def asgi_app(project_dir_and_app: tuple[Path, Any]) -> Any:
    return project_dir_and_app[1]


# ---------------------------------------------------------------------------
# B-01: App boots after files router installed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_b01_healthz_returns_200(asgi_app: Any) -> None:
    """B-01: GET /healthz returns 200 after add_file_upload wired."""
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}; body: {response.text}"
    )


# ---------------------------------------------------------------------------
# B-02: /files/presign route is wired (no 404)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_b02_files_presign_route_registered(asgi_app: Any) -> None:
    """B-02: POST /files/presign is wired (response != 404)."""
    transport = httpx.ASGITransport(app=asgi_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/files/presign",
            json={"filename": "x.txt", "content_type": "text/plain", "size_bytes": 1},
        )
    assert response.status_code != 404, (
        f"/files/presign not registered: {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# B-03: LocalStorage streams chunked (no full-file buffering)
# ---------------------------------------------------------------------------


def test_b03_local_storage_streams_chunked(project_dir: Path, tmp_path: Path) -> None:
    """B-03: DoD multipart streaming — LocalStorage.save reads CHUNK_SIZE bytes at a time.

    Confirms (a) the CHUNK_SIZE constant is exposed, and (b) writing a buffer
    larger than CHUNK_SIZE actually calls .read() multiple times — proving the
    save loop does NOT buffer the whole file in memory.
    """
    _orig_path = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    stale = [k for k in sys.modules if k == "app" or k.startswith("app.")]
    for key in stale:
        del sys.modules[key]
    try:
        from app.core import storage as storage_mod

        chunk = storage_mod.CHUNK_SIZE
        assert chunk == 65536, f"CHUNK_SIZE drifted: {chunk}"

        class _CountingReader:
            def __init__(self, blob: bytes) -> None:
                self._buf = io.BytesIO(blob)
                self.read_calls: list[int] = []

            def read(self, n: int = -1) -> bytes:
                data = self._buf.read(n)
                self.read_calls.append(len(data))
                return data

        # 3 chunks worth of bytes + a tail
        reader = _CountingReader(b"A" * (chunk * 3 + 17))
        local = storage_mod.LocalStorage(str(tmp_path))
        key, size = asyncio.run(local.save(reader, "application/octet-stream"))
        assert size == chunk * 3 + 17, f"size mismatch: {size}"
        # MUST have made multiple .read() calls (streaming proof) — not a single read.
        assert len(reader.read_calls) >= 3, (
            f"LocalStorage.save did not stream; read calls: {reader.read_calls}"
        )
        assert (tmp_path / key).exists(), "stored file missing"
    finally:
        sys.path[:] = _orig_path


# ---------------------------------------------------------------------------
# B-04: FileMetadataPublic must NOT expose stored_key/tenant_id at runtime
# ---------------------------------------------------------------------------


def test_b04_public_schema_excludes_stored_key(project_dir: Path) -> None:
    """B-04: Pydantic FileMetadataPublic has no stored_key / tenant_id fields."""
    _orig_path = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    stale = [k for k in sys.modules if k == "app" or k.startswith("app.")]
    for key in stale:
        del sys.modules[key]
    try:
        from app.schemas.file import FileMetadataPublic

        field_names = set(FileMetadataPublic.model_fields.keys())
        assert "stored_key" not in field_names, (
            "FileMetadataPublic leaks stored_key — S3 path exposure"
        )
        assert "tenant_id" not in field_names, "FileMetadataPublic leaks tenant_id"
    finally:
        sys.path[:] = _orig_path


# ---------------------------------------------------------------------------
# B-05: Path traversal guard fires at runtime
# ---------------------------------------------------------------------------


def test_b05_local_storage_rejects_path_traversal(project_dir: Path, tmp_path: Path) -> None:
    """B-05: LocalStorage.get_url raises ValueError on traversal attempts."""
    _orig_path = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    stale = [k for k in sys.modules if k == "app" or k.startswith("app.")]
    for key in stale:
        del sys.modules[key]
    try:
        from app.core import storage as storage_mod

        local = storage_mod.LocalStorage(str(tmp_path / "uploads"))
        with pytest.raises(ValueError, match="traversal"):
            asyncio.run(local.get_url("../../etc/passwd"))
    finally:
        sys.path[:] = _orig_path
