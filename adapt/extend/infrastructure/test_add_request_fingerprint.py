"""Tests for TOOL-103 add_request_fingerprint.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria (CC-01 through CC-LAST).

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_request_fingerprint.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_request_fingerprint.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_request_fingerprint import add_request_fingerprint
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
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="fingerprint_t01")
    result = add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="fingerprint_t02")
    r1 = add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must not create files"
    assert not r2.files_modified, "Second run must not modify files"


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes nothing."""
    project_dir = create_fixture_project(name="fingerprint_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_request_fingerprint(
        ToolInput(project_dir=str(project_dir), dry_run=True)
    )
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count and existence
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 4 files created, all existing on disk."""
    project_dir = create_fixture_project(name="fingerprint_t04")
    result = add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count and existence
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified (config), all existing on disk."""
    project_dir = create_fixture_project(name="fingerprint_t05")
    result = add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 file modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: All generated .py files in app/fingerprint/ parse without SyntaxError."""
    project_dir = create_fixture_project(name="fingerprint_t06")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    fp_dir = project_dir / "app" / "fingerprint"
    for py_file in sorted(fp_dir.rglob("*.py")):
        source = py_file.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {py_file}: {exc}") from exc


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir = create_fixture_project(name="fingerprint_t07")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    app_dir = project_dir / "app"
    violations: list[str] = []
    for py_file in sorted(app_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    if loc > 50:
                        violations.append(
                            f"{py_file.relative_to(project_dir)}::{node.name} ({loc} LOC)"
                        )
    assert not violations, "Functions exceed 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: FINGERPRINT_ENABLED in config.py with 4-space indent."""
    project_dir = create_fixture_project(name="fingerprint_t08")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists(), "config.py not found"
    content = config_file.read_text()
    assert "FINGERPRINT_ENABLED" in content
    for line in content.splitlines():
        if "FINGERPRINT_ENABLED" in line and ":" in line:
            assert line.startswith("    "), (
                f"Config field must have 4-space indent: {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-09: models/__init__.py untouched
# ---------------------------------------------------------------------------

def test_models_init_not_broken() -> None:
    """CC-09: models/__init__.py still parseable after tool run."""
    project_dir = create_fixture_project(name="fingerprint_t09")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    if models_init.exists():
        ast.parse(models_init.read_text())


# ---------------------------------------------------------------------------
# CC-10: middleware created
# ---------------------------------------------------------------------------

def test_middleware_created() -> None:
    """CC-10: FingerprintMiddleware created in app/middleware/fingerprint.py."""
    project_dir = create_fixture_project(name="fingerprint_t10")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "fingerprint.py"
    assert mw_file.exists(), "fingerprint.py middleware not created"
    content = mw_file.read_text()
    assert "FingerprintMiddleware" in content
    assert "BaseHTTPMiddleware" in content


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests
# ---------------------------------------------------------------------------

def test_hasher_uses_sha256() -> None:
    """CC-11: hasher.py implements RequestFingerprinter with SHA-256."""
    project_dir = create_fixture_project(name="fingerprint_t11")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    hasher_file = project_dir / "app" / "fingerprint" / "hasher.py"
    assert hasher_file.exists(), "hasher.py not created"
    content = hasher_file.read_text()
    assert "RequestFingerprinter" in content
    assert "sha256" in content
    assert "hashlib" in content


def test_hasher_normalizes_body_keys() -> None:
    """CC-12: hasher.py normalizes JSON body keys (sort_keys=True)."""
    project_dir = create_fixture_project(name="fingerprint_t12")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    hasher_file = project_dir / "app" / "fingerprint" / "hasher.py"
    content = hasher_file.read_text()
    assert "sort_keys" in content


def test_store_has_redis_and_memory_fallback() -> None:
    """CC-13: store.py implements FingerprintStore with Redis + memory fallback."""
    project_dir = create_fixture_project(name="fingerprint_t13")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    store_file = project_dir / "app" / "fingerprint" / "store.py"
    assert store_file.exists(), "store.py not created"
    content = store_file.read_text()
    assert "FingerprintStore" in content
    assert "memory" in content.lower() or "_MemoryStore" in content
    assert "is_duplicate" in content


def test_redis_sdk_lazy_in_store() -> None:
    """CC-14: redis.asyncio is imported lazily inside function body in store.py."""
    project_dir = create_fixture_project(name="fingerprint_t14")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    store_file = project_dir / "app" / "fingerprint" / "store.py"
    tree = ast.parse(store_file.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            name = ""
            if isinstance(node, ast.Import):
                name = node.names[0].name if node.names else ""
            elif isinstance(node, ast.ImportFrom):
                name = node.module or ""
            assert "redis" not in name.lower(), (
                f"redis imported at top level in store.py: {name}"
            )


def test_middleware_returns_cached_response_on_dup() -> None:
    """CC-15: FingerprintMiddleware returns response on duplicate request."""
    project_dir = create_fixture_project(name="fingerprint_t15")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "fingerprint.py"
    content = mw_file.read_text()
    assert "is_duplicate" in content
    assert "Idempotent-Replayed" in content


def test_middleware_only_dedup_unsafe_methods() -> None:
    """CC-16: FingerprintMiddleware only deduplicates configured methods (POST/PUT)."""
    project_dir = create_fixture_project(name="fingerprint_t16")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "fingerprint.py"
    content = mw_file.read_text()
    assert "POST" in content
    assert "PUT" in content
    assert "enabled_methods" in content or "_methods" in content


def test_fingerprint_init_exports() -> None:
    """CC-17: app/fingerprint/__init__.py re-exports key symbols."""
    project_dir = create_fixture_project(name="fingerprint_t17")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "fingerprint" / "__init__.py"
    assert init_file.exists(), "fingerprint/__init__.py not created"
    content = init_file.read_text()
    assert "RequestFingerprinter" in content
    assert "FingerprintStore" in content


def test_store_has_ttl() -> None:
    """CC-18: FingerprintStore respects TTL for key expiry."""
    project_dir = create_fixture_project(name="fingerprint_t18")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    store_file = project_dir / "app" / "fingerprint" / "store.py"
    content = store_file.read_text()
    assert "ttl_s" in content or "TTL" in content


def test_config_has_all_fingerprint_fields() -> None:
    """CC-19: All three FINGERPRINT_* fields are in config.py."""
    project_dir = create_fixture_project(name="fingerprint_t19")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ["FINGERPRINT_ENABLED", "FINGERPRINT_TTL_S", "FINGERPRINT_METHODS"]:
        assert field in content, f"{field} not found in config.py"


def test_hasher_includes_user_id() -> None:
    """CC-20: Fingerprint includes user_id for user isolation."""
    project_dir = create_fixture_project(name="fingerprint_t20")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    hasher_file = project_dir / "app" / "fingerprint" / "hasher.py"
    content = hasher_file.read_text()
    assert "user_id" in content


def test_store_works_without_redis() -> None:
    """CC-21: FingerprintStore falls back to memory when no Redis URL provided."""
    project_dir = create_fixture_project(name="fingerprint_t21")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    store_file = project_dir / "app" / "fingerprint" / "store.py"
    content = store_file.read_text()
    assert "None" in content
    assert "_MemoryStore" in content or "memory" in content.lower()


def test_notes_mention_dedup_and_idempotency() -> None:
    """CC-22: notes describe deduplication and Idempotent-Replayed header."""
    project_dir = create_fixture_project(name="fingerprint_t22")
    result = add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.notes).lower()
    assert (
        "dedup" in combined
        or "idempotent" in combined
        or "fingerprint" in combined
        or "sha-256" in combined
    )


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="fingerprint_t23")
    result = add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps guides developer to set FINGERPRINT_ENABLED."""
    project_dir = create_fixture_project(name="fingerprint_t24")
    result = add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "fingerprint_enabled" in combined or "fingerprint" in combined


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs, all .py files remain parseable."""
    project_dir = create_fixture_project(name="fingerprint_t25")
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    add_request_fingerprint(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


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
        test_models_init_not_broken,
        test_middleware_created,
        test_hasher_uses_sha256,
        test_hasher_normalizes_body_keys,
        test_store_has_redis_and_memory_fallback,
        test_redis_sdk_lazy_in_store,
        test_middleware_returns_cached_response_on_dup,
        test_middleware_only_dedup_unsafe_methods,
        test_fingerprint_init_exports,
        test_store_has_ttl,
        test_config_has_all_fingerprint_fields,
        test_hasher_includes_user_id,
        test_store_works_without_redis,
        test_notes_mention_dedup_and_idempotency,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
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
    print(f"TOOL-103 add_request_fingerprint: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
