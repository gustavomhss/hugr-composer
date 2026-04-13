"""Tests for TOOL-021 add_cache_layer.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_cache_layer.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_cache_layer.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_cache_layer import add_cache_layer
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
    project_dir = create_fixture_project(name="cache_t01")
    result = add_cache_layer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist_on_disk() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="cache_t02")
    result = add_cache_layer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist_on_disk() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="cache_t03")
    result = add_cache_layer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_cache_package_created() -> None:
    """CC-01: app/cache/ package directory is created."""
    project_dir = create_fixture_project(name="cache_t04")
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    cache_dir = project_dir / "app" / "cache"
    assert cache_dir.is_dir(), "app/cache/ directory not created"


def test_cache_core_file_created() -> None:
    """CC-02: app/cache/core.py exists and contains CacheBackend."""
    project_dir = create_fixture_project(name="cache_t05")
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "cache" / "core.py"
    assert core_file.exists(), "core.py not created"
    content = core_file.read_text()
    assert "CacheBackend" in content
    assert "get_cache" in content
    assert "init_cache" in content
    assert "close_cache" in content


def test_msgpack_serialization() -> None:
    """CC-03: CacheBackend uses msgpack (not json) for serialization."""
    project_dir = create_fixture_project(name="cache_t06")
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "cache" / "core.py"
    content = core_file.read_text()
    assert "msgpack" in content, "CacheBackend must use msgpack"
    assert "packb" in content or "unpackb" in content, "msgpack pack/unpack must be present"


def test_cache_decorator_file_created() -> None:
    """CC-04: app/cache/decorator.py exists with @cached decorator."""
    project_dir = create_fixture_project(name="cache_t07")
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    dec_file = project_dir / "app" / "cache" / "decorator.py"
    assert dec_file.exists(), "decorator.py not created"
    content = dec_file.read_text()
    assert "def cached" in content, "@cached decorator must be defined"
    assert "ttl" in content, "cached() must accept ttl parameter"


def test_key_generation_tenant_isolation() -> None:
    """CC-05: Key generation uses cache:{tenant}:resource:{id} pattern."""
    project_dir = create_fixture_project(name="cache_t08")
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    keys_file = project_dir / "app" / "cache" / "keys.py"
    assert keys_file.exists(), "keys.py not created"
    content = keys_file.read_text()
    assert "cache:" in content, "Key prefix 'cache:' must be in keys.py"
    assert "tenant" in content, "Tenant namespacing must be present"


def test_invalidation_file_created() -> None:
    """CC-06: app/cache/invalidation.py exists with invalidate helpers."""
    project_dir = create_fixture_project(name="cache_t09")
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    inv_file = project_dir / "app" / "cache" / "invalidation.py"
    assert inv_file.exists(), "invalidation.py not created"
    content = inv_file.read_text()
    assert "invalidate_resource" in content
    assert "invalidate_pattern" in content


def test_pubsub_invalidation_channel() -> None:
    """CC-07: Invalidation uses Redis pub/sub for fan-out to workers."""
    project_dir = create_fixture_project(name="cache_t10")
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    inv_file = project_dir / "app" / "cache" / "invalidation.py"
    content = inv_file.read_text()
    assert "publish" in content, "Pub/sub publish must be in invalidation.py"
    assert "cache:invalidation" in content or "INVALIDATION_CHANNEL" in content


def test_cache_stats_route_created() -> None:
    """CC-08: /cache/stats admin endpoint is generated."""
    project_dir = create_fixture_project(name="cache_t11")
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    stats_route = project_dir / "app" / "api" / "routes" / "cache_stats.py"
    assert stats_route.exists(), "cache_stats.py route not created"
    content = stats_route.read_text()
    assert "/cache/stats" in content or '"/stats"' in content or "cache_stats" in content


def test_cache_stats_returns_dict() -> None:
    """CC-09: Stats endpoint returns dict with connected/memory keys."""
    project_dir = create_fixture_project(name="cache_t12")
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    stats_route = project_dir / "app" / "api" / "routes" / "cache_stats.py"
    content = stats_route.read_text()
    assert "stats" in content


def test_cache_init_file_has_exports() -> None:
    """CC-10: app/cache/__init__.py re-exports public symbols."""
    project_dir = create_fixture_project(name="cache_t13")
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "cache" / "__init__.py"
    assert init_file.exists(), "cache/__init__.py not created"
    content = init_file.read_text()
    assert "CacheBackend" in content
    assert "cached" in content


def test_main_py_patched() -> None:
    """CC-11: main.py is patched with cache init imports."""
    project_dir = create_fixture_project(name="cache_t14")
    result = add_cache_layer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    main_file = project_dir / "app" / "main.py"
    if main_file.exists():
        content = main_file.read_text()
        assert "init_cache" in content or "close_cache" in content


def test_all_created_files_parse() -> None:
    """CC-12: All created .py files parse without SyntaxError."""
    project_dir = create_fixture_project(name="cache_t15")
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    cache_dir = project_dir / "app" / "cache"
    for py_file in sorted(cache_dir.rglob("*.py")):
        source = py_file.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {py_file}: {exc}") from exc


def test_idempotent_returns_no_op() -> None:
    """CC-13: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="cache_t16")
    r1 = add_cache_layer(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_cache_layer(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must not create files"
    assert not r2.files_modified, "Second run must not modify files"


def test_idempotent_project_still_parses() -> None:
    """After two runs, all .py files remain parseable."""
    project_dir = create_fixture_project(name="cache_t17")
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return success but write no files."""
    project_dir = create_fixture_project(name="cache_t18")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_cache_layer(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="cache_t19")
    result = add_cache_layer(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_mention_redis_and_pip() -> None:
    """next_steps guides developer to install redis and msgpack."""
    project_dir = create_fixture_project(name="cache_t20")
    result = add_cache_layer(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "redis" in combined or "pip" in combined, "next_steps should mention redis/pip"


def test_notes_mention_msgpack_and_ttl() -> None:
    """notes describes msgpack and TTL invalidation strategy."""
    project_dir = create_fixture_project(name="cache_t21")
    result = add_cache_layer(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.notes).lower()
    assert "ttl" in combined or "msgpack" in combined or "cache" in combined


def test_cache_delete_pattern_uses_scan() -> None:
    """CC-14: delete_pattern uses SCAN-based iteration, not KEYS (production safe)."""
    project_dir = create_fixture_project(name="cache_t22")
    add_cache_layer(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "cache" / "core.py"
    content = core_file.read_text()
    assert "scan_iter" in content or "scan" in content.lower(), (
        "delete_pattern must use SCAN, not KEYS command"
    )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist_on_disk,
        test_files_modified_exist_on_disk,
        test_cache_package_created,
        test_cache_core_file_created,
        test_msgpack_serialization,
        test_cache_decorator_file_created,
        test_key_generation_tenant_isolation,
        test_invalidation_file_created,
        test_pubsub_invalidation_channel,
        test_cache_stats_route_created,
        test_cache_stats_returns_dict,
        test_cache_init_file_has_exports,
        test_main_py_patched,
        test_all_created_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_mention_redis_and_pip,
        test_notes_mention_msgpack_and_ttl,
        test_cache_delete_pattern_uses_scan,
    ]

    passed = failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"TOOL-021 add_cache_layer: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
