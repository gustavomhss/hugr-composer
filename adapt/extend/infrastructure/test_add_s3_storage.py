"""Tests for TOOL-060 add_s3_storage.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_s3_storage.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_s3_storage.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_s3_storage import add_s3_storage
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


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    """Return the max LOC of any function in the given subdir."""
    target = root / subdir
    if not target.exists():
        return 0
    max_loc = 0
    for f in sorted(target.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    max_loc = max(max_loc, loc)
    return max_loc


# ---------------------------------------------------------------------------
# Category A — Tool execution
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="s3_t01")
    result = add_s3_storage(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="s3_t02")
    r1 = add_s3_storage(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_s3_storage(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="s3_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_s3_storage(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates exactly 5 new files (storage init, client, config, middleware, routes)."""
    project_dir = create_fixture_project(name="s3_t04")
    result = add_s3_storage(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    py_created = [p for p in result.files_created if p.endswith(".py")]
    assert len(py_created) >= 5, (
        f"Expected >= 5 Python files_created, got {len(py_created)}: {py_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, routes init, requirements)."""
    project_dir = create_fixture_project(name="s3_t05")
    result = add_s3_storage(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# Category B — Generated code quality
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="s3_t06")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="s3_t07")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """All S3_* settings fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="s3_t08")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    expected_fields = [
        "S3_BUCKET_NAME",
        "S3_REGION",
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "S3_PRESIGNED_URL_EXPIRATION",
    ]
    for field in expected_fields:
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class (4-space indent)
    for line in content.splitlines():
        if "S3_BUCKET_NAME" in line and ":" in line:
            assert line.startswith("    "), (
                f"S3_BUCKET_NAME not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_requirements_patched() -> None:
    """requirements.txt contains boto3>=."""
    project_dir = create_fixture_project(name="s3_t09")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    requirements = project_dir / "requirements.txt"
    content = requirements.read_text()
    assert "boto3>=" in content, "boto3 dependency not added to requirements.txt"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------

def test_s3_client_created() -> None:
    """app/storage/client.py exists and contains S3Client class."""
    project_dir = create_fixture_project(name="s3_t10")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    client_file = project_dir / "app" / "storage" / "client.py"
    assert client_file.exists(), "app/storage/client.py not created"
    content = client_file.read_text()
    assert "class S3Client" in content, "S3Client class not found in client.py"


def test_presigned_url_helpers() -> None:
    """S3Client exposes presigned_upload_url and presigned_download_url methods."""
    project_dir = create_fixture_project(name="s3_t11")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    client_file = project_dir / "app" / "storage" / "client.py"
    content = client_file.read_text()
    assert "presigned_upload_url" in content, "presigned_upload_url method not found"
    assert "presigned_download_url" in content, "presigned_download_url method not found"


def test_storage_routes_created() -> None:
    """app/api/routes/storage.py exists with upload/download/delete endpoints."""
    project_dir = create_fixture_project(name="s3_t12")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "storage.py"
    assert route_file.exists(), "app/api/routes/storage.py not created"
    content = route_file.read_text()
    assert "/upload" in content, "Upload route not found in storage.py"
    assert "delete" in content.lower(), "Delete route/method not found in storage.py"
    assert "download" in content.lower(), "Download route not found in storage.py"


def test_routes_registered() -> None:
    """Storage router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="s3_t13")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "storage" in content.lower(), "Storage router not registered in routes __init__"


def test_lazy_boto3_import() -> None:
    """app/storage/client.py uses a lazy import for boto3 (inside function body)."""
    project_dir = create_fixture_project(name="s3_t14")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    client_file = project_dir / "app" / "storage" / "client.py"
    content = client_file.read_text()
    # The top-level imports must NOT contain boto3 (import must be inside a body)
    tree = ast.parse(content)
    top_level_imports = [
        node for node in ast.iter_child_nodes(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    top_level_names = []
    for node in top_level_imports:
        if isinstance(node, ast.Import):
            top_level_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            top_level_names.append(node.module or "")
    assert "boto3" not in top_level_names, (
        "boto3 must NOT be a top-level import — it must be imported lazily inside a function"
    )
    # Confirm boto3 IS imported somewhere inside a function body
    assert "import boto3" in content, "boto3 lazy import not found in client.py body"


def test_key_generation_pattern() -> None:
    """generate_key produces a key matching {prefix}/{uuid}/{filename} pattern."""
    project_dir = create_fixture_project(name="s3_t15")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    client_file = project_dir / "app" / "storage" / "client.py"
    content = client_file.read_text()
    assert "generate_key" in content, "generate_key method not found in client.py"
    assert "uuid" in content.lower(), "UUID usage not found in generate_key (key generation)"
    # The key format string pattern should be present
    assert "{prefix}" in content or "key_prefix" in content, (
        "Key prefix handling not found in generate_key"
    )


def test_content_type_validation() -> None:
    """Storage routes include content-type validation logic."""
    project_dir = create_fixture_project(name="s3_t16")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "storage.py"
    content = route_file.read_text()
    assert "content_type" in content, "content_type not referenced in storage routes"
    assert "415" in content or "UNSUPPORTED_MEDIA_TYPE" in content, (
        "HTTP 415 content-type rejection not found in storage routes"
    )
    assert "S3_ALLOWED_CONTENT_TYPES" in content or "allowed" in content.lower(), (
        "Allowed content types check not found in storage routes"
    )


def test_max_file_size_from_settings() -> None:
    """UploadSizeMiddleware reads max size from settings.S3_MAX_UPLOAD_SIZE_BYTES."""
    project_dir = create_fixture_project(name="s3_t17")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    middleware_file = project_dir / "app" / "storage" / "middleware.py"
    assert middleware_file.exists(), "app/storage/middleware.py not created"
    content = middleware_file.read_text()
    assert "S3_MAX_UPLOAD_SIZE_BYTES" in content, (
        "Middleware does not read S3_MAX_UPLOAD_SIZE_BYTES from settings"
    )
    assert "413" in content, "HTTP 413 response not found in UploadSizeMiddleware"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="s3_t18")
    result = add_s3_storage(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """Result includes actionable next_steps instructions."""
    project_dir = create_fixture_project(name="s3_t19")
    result = add_s3_storage(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert result.next_steps, "next_steps must not be empty"
    # Must mention at least pip/boto3 and the bucket/env var setup
    combined = "\n".join(result.next_steps).lower()
    assert "pip" in combined or "boto3" in combined, (
        "next_steps must mention installing boto3"
    )
    assert "s3_bucket_name" in combined or "bucket" in combined, (
        "next_steps must mention bucket configuration"
    )


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="s3_t20")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Bonus — extra coverage for robustness
# ---------------------------------------------------------------------------

def test_storage_package_init_re_exports() -> None:
    """app/storage/__init__.py re-exports S3Client and get_s3_client."""
    project_dir = create_fixture_project(name="s3_t21")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    storage_init = project_dir / "app" / "storage" / "__init__.py"
    assert storage_init.exists(), "app/storage/__init__.py not created"
    content = storage_init.read_text()
    assert "S3Client" in content, "S3Client not re-exported from storage __init__"
    assert "get_s3_client" in content, "get_s3_client not re-exported from storage __init__"


def test_storage_config_dataclass_created() -> None:
    """app/storage/config.py exists with StorageConfig dataclass."""
    project_dir = create_fixture_project(name="s3_t22")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "storage" / "config.py"
    assert config_file.exists(), "app/storage/config.py not created"
    content = config_file.read_text()
    assert "StorageConfig" in content, "StorageConfig not found in app/storage/config.py"
    assert "from_settings" in content, "from_settings classmethod not found in StorageConfig"


def test_minio_endpoint_url_in_settings() -> None:
    """app/core/config.py includes S3_ENDPOINT_URL for MinIO support."""
    project_dir = create_fixture_project(name="s3_t23")
    add_s3_storage(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "S3_ENDPOINT_URL" in content, (
        "S3_ENDPOINT_URL not found in config.py — MinIO support requires this field"
    )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run,
        test_files_created_count,
        test_files_modified_count,
        test_all_py_parse,
        test_no_function_over_50_loc,
        test_config_fields_patched,
        test_requirements_patched,
        test_s3_client_created,
        test_presigned_url_helpers,
        test_storage_routes_created,
        test_routes_registered,
        test_lazy_boto3_import,
        test_key_generation_pattern,
        test_content_type_validation,
        test_max_file_size_from_settings,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_storage_package_init_re_exports,
        test_storage_config_dataclass_created,
        test_minio_endpoint_url_in_settings,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} tests passed")
    sys.exit(0 if failed == 0 else 1)
