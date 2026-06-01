"""Tests for TOOL-003 add_file_upload.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/crud_data/test_add_file_upload.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/crud_data/test_add_file_upload.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_file_upload import add_file_upload
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="fu_t01_success")
    result = add_file_upload(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="fu_t02_files_exist")
    result = add_file_upload(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="fu_t03_modified_exist")
    result = add_file_upload(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_file_model_created() -> None:
    """CC-01: app/models/file.py exists with FileMetadata and all fields."""
    project_dir = create_fixture_project(name="fu_t04_model")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "file.py"
    assert model_file.exists(), "app/models/file.py not created"
    content = model_file.read_text()
    assert "FileMetadata" in content
    assert "original_filename" in content
    assert "stored_key" in content
    assert "content_type" in content
    assert "size_bytes" in content
    assert "status" in content
    assert "uploaded_by" in content
    assert "created_at" in content
    assert "confirmed_at" in content


def test_file_model_status_lifecycle() -> None:
    """CC-02: FileMetadata.status comment includes all four lifecycle states."""
    project_dir = create_fixture_project(name="fu_t05_status")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "file.py"
    content = model_file.read_text()
    assert "pending" in content
    assert "confirmed" in content
    assert "virus_detected" in content
    assert "orphaned" in content


def test_stored_key_unique() -> None:
    """CC-03: stored_key has unique=True constraint."""
    project_dir = create_fixture_project(name="fu_t06_unique")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "file.py"
    content = model_file.read_text()
    assert "unique=True" in content, "stored_key must have unique=True"


def test_uploaded_by_fk_set_null() -> None:
    """CC-04: uploaded_by FK uses ondelete='SET NULL'."""
    project_dir = create_fixture_project(name="fu_t07_fk")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "file.py"
    content = model_file.read_text()
    assert "SET NULL" in content, "uploaded_by FK must use ondelete='SET NULL'"


def test_resource_composite_index() -> None:
    """CC-05: Composite index (resource_type, resource_id) exists."""
    project_dir = create_fixture_project(name="fu_t08_resource_idx")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "file.py"
    content = model_file.read_text()
    assert "resource_type" in content and "resource_id" in content
    assert "ix_files_resource" in content


def test_storage_backend_abc_created() -> None:
    """CC-06: app/core/storage.py exists with StorageBackend ABC."""
    project_dir = create_fixture_project(name="fu_t09_storage_abc")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    storage_file = project_dir / "app" / "core" / "storage.py"
    assert storage_file.exists(), "app/core/storage.py not created"
    content = storage_file.read_text()
    assert "StorageBackend" in content
    assert "LocalStorage" in content
    assert "S3Storage" in content


def test_local_storage_path_traversal_guard() -> None:
    """CC-07: LocalStorage rejects path traversal via startswith check."""
    project_dir = create_fixture_project(name="fu_t10_traversal")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    storage_file = project_dir / "app" / "core" / "storage.py"
    content = storage_file.read_text()
    assert "startswith" in content, "LocalStorage must guard against path traversal"


def test_s3_storage_aes256_encryption() -> None:
    """CC-08: S3Storage uses AES256 server-side encryption."""
    project_dir = create_fixture_project(name="fu_t11_aes256")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    storage_file = project_dir / "app" / "core" / "storage.py"
    content = storage_file.read_text()
    assert "AES256" in content, "S3Storage must use ServerSideEncryption AES256"


def test_get_storage_factory_created() -> None:
    """CC-09: get_storage() factory reads STORAGE_BACKEND setting."""
    project_dir = create_fixture_project(name="fu_t12_factory")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    storage_file = project_dir / "app" / "core" / "storage.py"
    content = storage_file.read_text()
    assert "def get_storage" in content
    assert "STORAGE_BACKEND" in content


def test_file_validator_created() -> None:
    """CC-10: app/core/file_validator.py with detect_mime, validate_file, SAFE_DEFAULTS."""
    project_dir = create_fixture_project(name="fu_t13_validator")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    validator_file = project_dir / "app" / "core" / "file_validator.py"
    assert validator_file.exists(), "app/core/file_validator.py not created"
    content = validator_file.read_text()
    assert "detect_mime" in content
    assert "validate_file" in content
    assert "SAFE_DEFAULTS" in content
    assert "ALWAYS_BLOCKED" in content


def test_file_validator_uses_magic_from_buffer() -> None:
    """CC-11: validate_file reads max 8 KB via magic.from_buffer."""
    project_dir = create_fixture_project(name="fu_t14_magic")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    validator_file = project_dir / "app" / "core" / "file_validator.py"
    content = validator_file.read_text()
    assert "from_buffer" in content, "must use magic.from_buffer"
    assert "8192" in content, "must read only 8192 bytes (8 KB)"


def test_presign_route_exists() -> None:
    """CC-12: POST /files/presign endpoint exists."""
    project_dir = create_fixture_project(name="fu_t15_presign")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "files.py"
    assert route_file.exists(), "app/api/routes/files.py not created"
    content = route_file.read_text()
    assert "/presign" in content


def test_confirm_route_exists() -> None:
    """CC-13: POST /files/{id}/confirm endpoint exists."""
    project_dir = create_fixture_project(name="fu_t16_confirm")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "files.py"
    content = route_file.read_text()
    assert "confirm" in content, "confirm endpoint must exist"


def test_direct_upload_route_exists() -> None:
    """CC-14: POST /files/ direct upload endpoint exists for local storage."""
    project_dir = create_fixture_project(name="fu_t17_direct")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "files.py"
    content = route_file.read_text()
    assert "UploadFile" in content, "direct upload route must accept UploadFile"


def test_download_route_with_ownership_check() -> None:
    """CC-15: GET /files/{id} exists with ownership check."""
    project_dir = create_fixture_project(name="fu_t18_download")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "files.py"
    content = route_file.read_text()
    assert "download_file" in content or "GET" in content
    assert "403" in content, "download must check ownership (403 Forbidden)"


def test_delete_route_with_ownership_check() -> None:
    """CC-16: DELETE /files/{id} with ownership check + storage delete."""
    project_dir = create_fixture_project(name="fu_t19_delete")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "files.py"
    content = route_file.read_text()
    assert "storage.delete" in content or "delete_file" in content
    assert "204" in content or "NO_CONTENT" in content


def test_upload_checks_content_length() -> None:
    """CC-17: Upload handler checks size before body is read."""
    project_dir = create_fixture_project(name="fu_t20_content_length")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "files.py"
    content = route_file.read_text()
    assert "413" in content, "upload must reject oversized files with 413"


def test_upload_validates_magic_bytes() -> None:
    """CC-18: Upload handler calls validate_file (magic bytes)."""
    project_dir = create_fixture_project(name="fu_t21_magic_call")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "files.py"
    content = route_file.read_text()
    assert "validate_file" in content, "upload handler must call validate_file"


def test_upload_atomic_storage_delete_on_failure() -> None:
    """CC-19: Upload handler calls storage.delete in except block on DB failure."""
    project_dir = create_fixture_project(name="fu_t22_atomic")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "files.py"
    content = route_file.read_text()
    assert "storage.delete" in content, "upload must delete storage object on DB failure"


def test_public_schema_excludes_stored_key() -> None:
    """CC-21: FileMetadataPublic schema does NOT declare stored_key or tenant_id fields.

    The docstring may mention them as excluded fields; we check that no field
    declaration (``name: type``) for stored_key or tenant_id exists in the class body.
    """
    project_dir = create_fixture_project(name="fu_t23_public_schema")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "file.py"
    assert schema_file.exists(), "app/schemas/file.py not created"

    import ast as _ast

    tree = _ast.parse(schema_file.read_text())
    field_names: list[str] = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ClassDef) and node.name == "FileMetadataPublic":
            for item in node.body:
                if isinstance(item, _ast.AnnAssign) and isinstance(item.target, _ast.Name):
                    field_names.append(item.target.id)

    assert field_names, "FileMetadataPublic must have field declarations"
    assert "stored_key" not in field_names, "FileMetadataPublic must NOT declare stored_key field"
    assert "tenant_id" not in field_names, "FileMetadataPublic must NOT declare tenant_id field"


def test_presign_response_excludes_stored_key() -> None:
    """R5-S1-F8: PresignedUploadResponse must NOT expose the internal stored_key.

    Mirrors FileMetadataPublic's exclusion. The client uploads via ``fields``
    (S3 injects the object key there) and confirms via ``file_id`` (the server
    re-derives the key from the owned row), so the storage path must never be a
    first-class response field. The route must also not spread it back via
    ``**result``.
    """
    project_dir = create_fixture_project(name="fu_presign_no_key")
    add_file_upload(ToolInput(project_dir=str(project_dir)))

    import ast as _ast

    schema_src = (project_dir / "app" / "schemas" / "file.py").read_text()
    tree = _ast.parse(schema_src)
    field_names: list[str] = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ClassDef) and node.name == "PresignedUploadResponse":
            for item in node.body:
                if isinstance(item, _ast.AnnAssign) and isinstance(item.target, _ast.Name):
                    field_names.append(item.target.id)
    assert field_names, "PresignedUploadResponse must have field declarations"
    assert "stored_key" not in field_names, (
        "PresignedUploadResponse must NOT declare stored_key (R5-S1-F8 leak)"
    )
    # The route must build the response explicitly, not spread result (which
    # still carries stored_key for the internal create_pending call).
    routes_src = (project_dir / "app" / "api" / "routes" / "files.py").read_text()
    assert "PresignedUploadResponse(file_id=file_id, **result)" not in routes_src, (
        "route still spreads stored_key into the presign response via **result"
    )


def test_presigned_urls_module_created() -> None:
    """CC: app/core/presigned_urls.py exists with generate_upload_url."""
    project_dir = create_fixture_project(name="fu_t24_presigned")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    presigned_file = project_dir / "app" / "core" / "presigned_urls.py"
    assert presigned_file.exists(), "presigned_urls.py not created"
    content = presigned_file.read_text()
    assert "generate_upload_url" in content
    assert "generate_download_url" in content


def test_quota_module_created() -> None:
    """CC-28: app/core/upload_quota.py exists with check_quota and quota_lock."""
    project_dir = create_fixture_project(name="fu_t25_quota")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    quota_file = project_dir / "app" / "core" / "upload_quota.py"
    assert quota_file.exists(), "upload_quota.py not created"
    content = quota_file.read_text()
    assert "check_quota" in content
    assert "quota_lock" in content
    assert "Redis" in content or "redis" in content


def test_multipart_upload_module_created() -> None:
    """CC-30: app/core/multipart_upload.py exists with upload_multipart."""
    project_dir = create_fixture_project(name="fu_t26_multipart")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    multipart_file = project_dir / "app" / "core" / "multipart_upload.py"
    assert multipart_file.exists(), "multipart_upload.py not created"
    content = multipart_file.read_text()
    assert "upload_multipart" in content
    assert "abort_multipart_upload" in content


def test_cleanup_orphans_created() -> None:
    """CC-29: app/tasks/cleanup_orphans.py with cleanup_orphaned_uploads."""
    project_dir = create_fixture_project(name="fu_t27_cleanup")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    cleanup_file = project_dir / "app" / "tasks" / "cleanup_orphans.py"
    assert cleanup_file.exists(), "cleanup_orphans.py not created"
    content = cleanup_file.read_text()
    assert "cleanup_orphaned_uploads" in content
    assert "pending" in content
    assert "BATCH_SIZE" in content


def test_migration_file_created() -> None:
    """CC-23: Alembic migration creates files table with all indexes."""
    project_dir = create_fixture_project(name="fu_t28_migration")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*create_files*"))
    assert len(migration_files) >= 1, "No files table migration created"
    content = migration_files[0].read_text()
    assert "files" in content
    assert "stored_key" in content
    assert "ix_files_resource" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_requirements_patched() -> None:
    """CC-24/25: python-magic and boto3 added to requirements.txt."""
    project_dir = create_fixture_project(name="fu_t29_requirements")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    req_file = project_dir / "requirements.txt"
    if req_file.exists():
        content = req_file.read_text()
        assert "python-magic" in content, "python-magic must be in requirements.txt"
        assert "boto3" in content, "boto3 must be in requirements.txt"


def test_all_py_files_parse() -> None:
    """CC-33: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="fu_t30_parse_all")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """QS-09: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="fu_t31_idempotent")
    r1 = add_file_upload(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_file_upload(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="fu_t32_idem_parse")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="fu_t33_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_file_upload(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="fu_t34_timing")
    result = add_file_upload(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps should guide the developer after a successful run."""
    project_dir = create_fixture_project(name="fu_t35_next_steps")
    result = add_file_upload(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty on success"
    assert any("alembic" in s for s in result.next_steps), "Should mention alembic upgrade"


def test_crud_file_module_created() -> None:
    """app/crud/file.py exists with create_pending, confirm, get, delete."""
    project_dir = create_fixture_project(name="fu_t36_crud")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "file.py"
    assert crud_file.exists(), "app/crud/file.py not created"
    content = crud_file.read_text()
    for fn in ("create_pending", "confirm", "get_pending", "get_confirmed", "delete"):
        assert f"async def {fn}" in content, f"Missing function: {fn}"


def test_virus_detected_returns_451() -> None:
    """Download of a virus_detected file returns HTTP 451."""
    project_dir = create_fixture_project(name="fu_t37_451")
    add_file_upload(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "files.py"
    content = route_file.read_text()
    assert "451" in content, "Virus-detected file download must return 451"
    assert "virus_detected" in content


# ---------------------------------------------------------------------------
# Standalone runner (fallback when pytest is unavailable)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_file_model_created,
        test_file_model_status_lifecycle,
        test_stored_key_unique,
        test_uploaded_by_fk_set_null,
        test_resource_composite_index,
        test_storage_backend_abc_created,
        test_local_storage_path_traversal_guard,
        test_s3_storage_aes256_encryption,
        test_get_storage_factory_created,
        test_file_validator_created,
        test_file_validator_uses_magic_from_buffer,
        test_presign_route_exists,
        test_confirm_route_exists,
        test_direct_upload_route_exists,
        test_download_route_with_ownership_check,
        test_delete_route_with_ownership_check,
        test_upload_checks_content_length,
        test_upload_validates_magic_bytes,
        test_upload_atomic_storage_delete_on_failure,
        test_public_schema_excludes_stored_key,
        test_presigned_urls_module_created,
        test_quota_module_created,
        test_multipart_upload_module_created,
        test_cleanup_orphans_created,
        test_migration_file_created,
        test_requirements_patched,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
        test_crud_file_module_created,
        test_virus_detected_returns_451,
    ]

    passed = 0
    failed = 0
    errors: list[str] = []

    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            errors.append(f"{t.__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
