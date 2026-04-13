"""Red Team adversarial test suite for SKILL-001 adapt tools.

Every attack is a self-contained function.  Each returns a dict::

    {"name": str, "category": str, "passed": bool, "notes": str}

``passed=True`` means the tool handled the adversarial input *gracefully*
(returned a well-formed ``ToolResult`` or raised a clean validation error
without crashing, corrupting files, or producing incorrect behaviour).

Run::

    PYTHONPATH=. python3 audit/red_team.py
"""

from __future__ import annotations

import ast
import concurrent.futures
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Bootstrap: make sure SKILL root is on sys.path
# ---------------------------------------------------------------------------
SKILL_ROOT = Path(__file__).parent.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from adapt.contracts import ToolInput, ToolResult  # noqa: E402
from tests.common.fixture_factory import create_fixture_project  # noqa: E402

# ---------------------------------------------------------------------------
# Attack timeout (seconds per attack)
# ---------------------------------------------------------------------------
ATTACK_TIMEOUT = 30

# ---------------------------------------------------------------------------
# All 27 EXTEND tools in dependency-safe import order
# ---------------------------------------------------------------------------
def _import_all_extend_tools() -> list[Callable[[ToolInput], ToolResult]]:
    """Import and return all 27 extend tool callables."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete
    from adapt.extend.crud_data.add_bulk_operations import add_bulk_operations
    from adapt.extend.crud_data.add_cursor_pagination import add_cursor_pagination
    from adapt.extend.crud_data.add_data_export import add_data_export
    from adapt.extend.crud_data.add_file_upload import add_file_upload
    from adapt.extend.crud_data.add_search import add_search
    from adapt.extend.crud_data.add_audit_log import add_audit_log
    from adapt.extend.auth_access.add_mfa import add_mfa
    from adapt.extend.auth_access.add_oauth2_provider import add_oauth2_provider
    from adapt.extend.auth_access.add_multi_tenancy import add_multi_tenancy
    from adapt.extend.auth_access.add_rbac import add_rbac
    from adapt.extend.auth_access.add_api_key_auth import add_api_key_auth
    from adapt.extend.auth_access.add_feature_flags import add_feature_flags
    from adapt.extend.infrastructure.add_cache_layer import add_cache_layer
    from adapt.extend.infrastructure.add_circuit_breaker import add_circuit_breaker
    from adapt.extend.infrastructure.add_outbox_pattern import add_outbox_pattern
    from adapt.extend.infrastructure.add_saga import add_saga
    from adapt.extend.api_design.add_api_versioning import add_api_versioning
    from adapt.extend.api_design.add_batch_endpoint import add_batch_endpoint
    from adapt.extend.api_design.add_graphql import add_graphql
    from adapt.extend.api_design.add_long_running_task import add_long_running_task
    from adapt.extend.realtime.add_sse import add_sse
    from adapt.extend.realtime.add_webhook_receiver import add_webhook_receiver
    from adapt.extend.realtime.add_webhook_sender import add_webhook_sender
    from adapt.extend.testing_tools.add_contract_tests import add_contract_tests
    from adapt.extend.testing_tools.add_factory import add_factory
    from adapt.extend.testing_tools.add_load_profile import add_load_profile

    return [
        add_soft_delete, add_bulk_operations, add_cursor_pagination,
        add_data_export, add_file_upload, add_search, add_audit_log,
        add_mfa, add_oauth2_provider, add_multi_tenancy, add_rbac,
        add_api_key_auth, add_feature_flags,
        add_cache_layer, add_circuit_breaker, add_outbox_pattern, add_saga,
        add_api_versioning, add_batch_endpoint, add_graphql, add_long_running_task,
        add_sse, add_webhook_receiver, add_webhook_sender,
        add_contract_tests, add_factory, add_load_profile,
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(name: str, category: str, passed: bool, notes: str) -> dict:
    return {"name": name, "category": category, "passed": passed, "notes": notes}


def _is_valid_tool_result(obj: object) -> bool:
    """Return True if obj is a well-formed ToolResult with status in {success, no_op, error}."""
    return (
        isinstance(obj, ToolResult)
        and obj.status in ("success", "no_op", "error")
    )


class _TimeoutError(Exception):
    pass


def _run_with_timeout(fn: Callable, timeout: int = ATTACK_TIMEOUT):
    """Run fn() in a thread; raise _TimeoutError if it exceeds *timeout* seconds."""
    result_holder: list = [None]
    exc_holder: list = [None]

    def target():
        try:
            result_holder[0] = fn()
        except Exception as exc:  # noqa: BLE001
            exc_holder[0] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise _TimeoutError(f"attack timed out after {timeout}s")
    if exc_holder[0] is not None:
        raise exc_holder[0]
    return result_holder[0]


def _all_py_parse_ok(root: Path) -> tuple[bool, str]:
    """Return (True, '') if all .py files parse; (False, reason) otherwise."""
    for py_file in sorted(root.rglob("*.py")):
        try:
            ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            return False, f"SyntaxError in {py_file.name}: {exc}"
    return True, ""


def _count_disk_files(root: Path) -> int:
    return sum(1 for _ in root.rglob("*") if _.is_file())


# ===========================================================================
# CATEGORY 1 — Input Fuzzing (10 attacks)
# ===========================================================================

def _attack_path_traversal() -> dict:
    """Path traversal: project_dir='../../etc/passwd' must not crash."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "path_traversal"
    try:
        result = _run_with_timeout(
            lambda: add_soft_delete(ToolInput(project_dir="../../etc/passwd"))
        )
        if _is_valid_tool_result(result) and result.status == "error":
            return _make_result(name, "fuzzing", True, f"returned error: {result.error}")
        # status='no_op' is also acceptable — the path exists but has no models
        if _is_valid_tool_result(result) and result.status == "no_op":
            return _make_result(name, "fuzzing", True, "returned no_op (no models found)")
        return _make_result(name, "fuzzing", False, f"unexpected status={getattr(result,'status','?')}")
    except Exception as exc:  # noqa: BLE001
        # Pydantic validation error or any clean exception is acceptable —
        # the tool must not silently succeed or produce garbage output
        if "validation" in type(exc).__name__.lower() or "value" in type(exc).__name__.lower():
            return _make_result(name, "fuzzing", True, f"raised clean validation error: {type(exc).__name__}")
        return _make_result(name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}")


def _attack_nonexistent_dir() -> dict:
    """Non-existent directory must return error, not crash."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "nonexistent_dir"
    try:
        result = _run_with_timeout(
            lambda: add_soft_delete(ToolInput(project_dir="/nonexistent/path/does/not/exist"))
        )
        if _is_valid_tool_result(result) and result.status == "error":
            return _make_result(name, "fuzzing", True, f"returned error: {result.error}")
        # no_op is acceptable if discovery simply finds no models
        if _is_valid_tool_result(result) and result.status == "no_op":
            return _make_result(name, "fuzzing", True, "returned no_op (no models in missing dir)")
        return _make_result(name, "fuzzing", False, f"unexpected status={getattr(result,'status','?')}")
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (FileNotFoundError, OSError, PermissionError)):
            return _make_result(name, "fuzzing", True, f"raised OS-level error cleanly: {type(exc).__name__}")
        return _make_result(name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}")


def _attack_empty_string() -> dict:
    """Empty project_dir must return error or validation error."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "empty_string"
    try:
        result = _run_with_timeout(
            lambda: add_soft_delete(ToolInput(project_dir=""))
        )
        if _is_valid_tool_result(result) and result.status == "error":
            return _make_result(name, "fuzzing", True, f"returned error: {result.error}")
        if _is_valid_tool_result(result) and result.status == "no_op":
            return _make_result(name, "fuzzing", True, "returned no_op for empty path")
        return _make_result(name, "fuzzing", False, f"unexpected status={getattr(result,'status','?')}")
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "fuzzing", True, f"raised exception cleanly: {type(exc).__name__}")


def _attack_unicode_bomb() -> dict:
    """Unicode bomb path must not crash."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "unicode_bomb"
    # NUL bytes are the critical case; other unicode is generally fine
    bad_path = "/tmp/\x00\x01\x02\x03\x04test"
    try:
        result = _run_with_timeout(
            lambda: add_soft_delete(ToolInput(project_dir=bad_path))
        )
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(name, "fuzzing", False, f"unexpected status={getattr(result,'status','?')}")
    except Exception as exc:  # noqa: BLE001
        # ValueError / OSError for NUL bytes is correct and expected
        if isinstance(exc, (ValueError, OSError, TypeError)):
            return _make_result(name, "fuzzing", True, f"raised clean error: {type(exc).__name__}")
        return _make_result(name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}")


def _attack_very_long_path() -> dict:
    """10,000-character path must not crash or hang."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "very_long_path"
    long_path = "/tmp/" + "a" * 9995
    try:
        result = _run_with_timeout(
            lambda: add_soft_delete(ToolInput(project_dir=long_path))
        )
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(name, "fuzzing", False, f"unexpected status={getattr(result,'status','?')}")
    except _TimeoutError:
        return _make_result(name, "fuzzing", False, "timed out on long path")
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (OSError, ValueError, FileNotFoundError)):
            return _make_result(name, "fuzzing", True, f"raised OS error cleanly: {type(exc).__name__}")
        return _make_result(name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}")


def _attack_permission_denied() -> dict:
    """Permission-denied directory must return error, not crash."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "permission_denied"
    # /root is readable-restricted on macOS/Linux; /private/etc/root on macOS
    # Use a temp dir with 000 permissions for reliable cross-platform behaviour
    tmp = tempfile.mkdtemp(prefix="rt_perms_")
    restricted = Path(tmp) / "noaccess"
    restricted.mkdir()
    try:
        os.chmod(str(restricted), 0o000)
        result = _run_with_timeout(
            lambda: add_soft_delete(ToolInput(project_dir=str(restricted)))
        )
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(name, "fuzzing", False, f"unexpected status={getattr(result,'status','?')}")
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (PermissionError, OSError)):
            return _make_result(name, "fuzzing", True, f"raised OS error cleanly: {type(exc).__name__}")
        return _make_result(name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}")
    finally:
        os.chmod(str(restricted), 0o755)
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_symlink_loop() -> dict:
    """Symlink loop directory must not hang or crash."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "symlink_loop"
    tmp = tempfile.mkdtemp(prefix="rt_symloop_")
    loop_dir = Path(tmp) / "loop"
    loop_dir.mkdir()
    # Create a → loop/b → loop/a (cycle)
    link_a = loop_dir / "a"
    link_b = loop_dir / "b"
    link_a.symlink_to(link_b)
    link_b.symlink_to(link_a)
    try:
        result = _run_with_timeout(
            lambda: add_soft_delete(ToolInput(project_dir=str(loop_dir)))
        )
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(name, "fuzzing", False, f"unexpected status={getattr(result,'status','?')}")
    except _TimeoutError:
        return _make_result(name, "fuzzing", False, "hung on symlink loop")
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (OSError, RecursionError)):
            return _make_result(name, "fuzzing", True, f"raised OS/recursion error cleanly: {type(exc).__name__}")
        return _make_result(name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}")
    finally:
        # Unlink to avoid cleanup issues
        try:
            link_a.unlink(missing_ok=True)
            link_b.unlink(missing_ok=True)
        except OSError:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_file_instead_of_dir() -> dict:
    """Pass a file path (not a directory) as project_dir."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "file_instead_of_dir"
    tmp = tempfile.mkdtemp(prefix="rt_file_")
    fake_file = Path(tmp) / "not_a_dir.py"
    fake_file.write_text("# not a project\n")
    try:
        result = _run_with_timeout(
            lambda: add_soft_delete(ToolInput(project_dir=str(fake_file)))
        )
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(name, "fuzzing", False, f"unexpected status={getattr(result,'status','?')}")
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (OSError, NotADirectoryError, ValueError)):
            return _make_result(name, "fuzzing", True, f"raised clean error: {type(exc).__name__}")
        return _make_result(name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_null_bytes_in_path() -> dict:
    """Null byte embedded mid-path must not crash."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "null_bytes_in_path"
    path_with_null = "/tmp/valid\x00injected"
    try:
        result = _run_with_timeout(
            lambda: add_soft_delete(ToolInput(project_dir=path_with_null))
        )
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(name, "fuzzing", False, f"unexpected status={getattr(result,'status','?')}")
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (ValueError, OSError, TypeError)):
            return _make_result(name, "fuzzing", True, f"raised clean error: {type(exc).__name__}")
        return _make_result(name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}")


def _attack_space_only_path() -> dict:
    """Whitespace-only path must return error gracefully."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "space_only_path"
    try:
        result = _run_with_timeout(
            lambda: add_soft_delete(ToolInput(project_dir="   "))
        )
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(name, "fuzzing", False, f"unexpected status={getattr(result,'status','?')}")
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "fuzzing", True, f"raised exception cleanly: {type(exc).__name__}")


# ===========================================================================
# CATEGORY 2 — Idempotency Stress (5 attacks)
# ===========================================================================

def _attack_idempotency_100x() -> dict:
    """Run add_soft_delete 100x on same project — all after the first must be no_op."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "idempotency_100x"
    tmp = tempfile.mkdtemp(prefix="rt_idem_")
    try:
        project_dir = create_fixture_project(name="idem100x", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir))

        def _run():
            first = add_soft_delete(inp)
            if first.status != "success":
                return False, f"first run was {first.status}"
            file_count_after_first = _count_disk_files(project_dir)

            for i in range(99):
                r = add_soft_delete(inp)
                if r.status != "no_op":
                    return False, f"run {i+2} returned {r.status} (expected no_op)"
                if _count_disk_files(project_dir) != file_count_after_first:
                    return False, f"run {i+2} changed file count"
            return True, "100 runs: first=success, remaining 99=no_op, file count stable"

        ok, msg = _run_with_timeout(_run, timeout=60)
        return _make_result(name, "idempotency", ok, msg)
    except _TimeoutError:
        return _make_result(name, "idempotency", False, "timed out during 100 runs")
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "idempotency", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_delete_and_rerun() -> dict:
    """Run tool, delete one created file, run again — must detect and handle gracefully."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "delete_and_rerun"
    tmp = tempfile.mkdtemp(prefix="rt_delrerun_")
    try:
        project_dir = create_fixture_project(name="delrerun", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir))

        def _run():
            r1 = add_soft_delete(inp)
            if r1.status != "success":
                return False, f"first run returned {r1.status}"
            # Delete the first created file
            if not r1.files_created:
                return False, "no files_created to delete"
            target = Path(r1.files_created[0])
            if target.exists():
                target.unlink()
            # Second run: must not crash
            r2 = add_soft_delete(inp)
            if not _is_valid_tool_result(r2):
                return False, "second run returned invalid ToolResult"
            return True, f"second run after deletion returned status={r2.status}"

        ok, msg = _run_with_timeout(_run)
        return _make_result(name, "idempotency", ok, msg)
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "idempotency", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_concurrent_tools_same_project() -> dict:
    """Run add_soft_delete + add_bulk_operations concurrently on the same project."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete
    from adapt.extend.crud_data.add_bulk_operations import add_bulk_operations

    name = "concurrent_tools_same_project"
    tmp = tempfile.mkdtemp(prefix="rt_concurrent_")
    try:
        project_dir = create_fixture_project(name="concurrent_proj", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir))

        def _run():
            results = []
            exceptions = []

            def run_tool(fn):
                try:
                    results.append(fn(inp))
                except Exception as exc:  # noqa: BLE001
                    exceptions.append(exc)

            t1 = threading.Thread(target=run_tool, args=(add_soft_delete,))
            t2 = threading.Thread(target=run_tool, args=(add_bulk_operations,))
            t1.start()
            t2.start()
            t1.join(timeout=ATTACK_TIMEOUT)
            t2.join(timeout=ATTACK_TIMEOUT)

            if exceptions:
                return False, f"concurrent run raised: {exceptions[0]}"
            if len(results) != 2:
                return False, f"expected 2 results, got {len(results)}"
            # Both must return valid ToolResults (any status acceptable)
            for r in results:
                if not _is_valid_tool_result(r):
                    return False, f"invalid ToolResult: {r}"
            # Project must still parse after concurrent writes
            ok, reason = _all_py_parse_ok(project_dir)
            if not ok:
                return False, f"post-concurrent parse failed: {reason}"
            return True, f"both tools completed; statuses={[r.status for r in results]}"

        ok, msg = _run_with_timeout(_run, timeout=60)
        return _make_result(name, "idempotency", ok, msg)
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "idempotency", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_dry_run_50x_no_writes() -> dict:
    """dry_run=True 50x must produce zero disk writes."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "dry_run_50x_no_writes"
    tmp = tempfile.mkdtemp(prefix="rt_dryrun_")
    try:
        project_dir = create_fixture_project(name="dryrun50x", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir), dry_run=True)

        def _run():
            baseline = _count_disk_files(project_dir)
            for i in range(50):
                r = add_soft_delete(inp)
                if not _is_valid_tool_result(r):
                    return False, f"run {i+1} returned invalid ToolResult"
                if r.files_created or r.files_modified:
                    return False, f"run {i+1} reported file changes during dry_run"
            after = _count_disk_files(project_dir)
            if after != baseline:
                return False, f"file count changed: {baseline} → {after}"
            return True, f"50 dry_run passes; file count stable at {baseline}"

        ok, msg = _run_with_timeout(_run)
        return _make_result(name, "idempotency", ok, msg)
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "idempotency", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_corrupt_then_rerun() -> dict:
    """Run tool, manually corrupt a generated file, run again — must not crash."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "corrupt_then_rerun"
    tmp = tempfile.mkdtemp(prefix="rt_corrupt_")
    try:
        project_dir = create_fixture_project(name="corrupt_proj", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir))

        def _run():
            r1 = add_soft_delete(inp)
            if r1.status != "success":
                return False, f"first run returned {r1.status}"
            # Corrupt the mixin file with invalid Python
            mixin_file = project_dir / "app" / "models" / "mixins.py"
            if mixin_file.exists():
                mixin_file.write_text("CORRUPTED === invalid python &&& syntax\n")
            # Second run must not crash — any valid ToolResult is fine
            r2 = add_soft_delete(inp)
            if not _is_valid_tool_result(r2):
                return False, f"second run after corruption returned invalid ToolResult: {r2}"
            return True, f"second run after corruption returned status={r2.status}"

        ok, msg = _run_with_timeout(_run)
        return _make_result(name, "idempotency", ok, msg)
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "idempotency", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# CATEGORY 3 — Tool Interaction Conflicts (5 attacks)
# ===========================================================================

def _attack_soft_delete_plus_bulk_operations() -> dict:
    """add_soft_delete + add_bulk_operations on same project — no file corruption."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete
    from adapt.extend.crud_data.add_bulk_operations import add_bulk_operations

    name = "soft_delete_plus_bulk_ops"
    tmp = tempfile.mkdtemp(prefix="rt_sd_bulk_")
    try:
        project_dir = create_fixture_project(name="sd_bulk", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir))

        def _run():
            r1 = add_soft_delete(inp)
            if r1.status not in ("success", "no_op"):
                return False, f"add_soft_delete returned {r1.status}: {r1.error}"
            r2 = add_bulk_operations(inp)
            if r2.status not in ("success", "no_op"):
                return False, f"add_bulk_operations returned {r2.status}: {r2.error}"
            ok, reason = _all_py_parse_ok(project_dir)
            if not ok:
                return False, f"parse failed after both tools: {reason}"
            return True, f"sd={r1.status}, bulk={r2.status}; all .py files parse"

        ok, msg = _run_with_timeout(_run)
        return _make_result(name, "conflicts", ok, msg)
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "conflicts", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_mfa_plus_oauth2() -> dict:
    """add_mfa + add_oauth2_provider — both modify login flow, no crash."""
    from adapt.extend.auth_access.add_mfa import add_mfa
    from adapt.extend.auth_access.add_oauth2_provider import add_oauth2_provider

    name = "mfa_plus_oauth2"
    tmp = tempfile.mkdtemp(prefix="rt_mfa_oauth_")
    try:
        project_dir = create_fixture_project(name="mfa_oauth", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir))

        def _run():
            r1 = add_mfa(inp)
            if r1.status not in ("success", "no_op"):
                return False, f"add_mfa returned {r1.status}: {r1.error}"
            r2 = add_oauth2_provider(inp)
            if r2.status not in ("success", "no_op"):
                return False, f"add_oauth2_provider returned {r2.status}: {r2.error}"
            ok, reason = _all_py_parse_ok(project_dir)
            if not ok:
                return False, f"parse failed: {reason}"
            return True, f"mfa={r1.status}, oauth2={r2.status}; all .py files parse"

        ok, msg = _run_with_timeout(_run, timeout=45)
        return _make_result(name, "conflicts", ok, msg)
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "conflicts", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_search_plus_cursor_pagination() -> dict:
    """add_search + add_cursor_pagination — both modify routes, no corruption."""
    from adapt.extend.crud_data.add_search import add_search
    from adapt.extend.crud_data.add_cursor_pagination import add_cursor_pagination

    name = "search_plus_cursor_pagination"
    tmp = tempfile.mkdtemp(prefix="rt_srch_cursor_")
    try:
        project_dir = create_fixture_project(name="srch_cursor", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir))

        def _run():
            r1 = add_search(inp)
            if r1.status not in ("success", "no_op"):
                return False, f"add_search returned {r1.status}: {r1.error}"
            r2 = add_cursor_pagination(inp)
            if r2.status not in ("success", "no_op"):
                return False, f"add_cursor_pagination returned {r2.status}: {r2.error}"
            ok, reason = _all_py_parse_ok(project_dir)
            if not ok:
                return False, f"parse failed: {reason}"
            return True, f"search={r1.status}, cursor={r2.status}; all .py files parse"

        ok, msg = _run_with_timeout(_run)
        return _make_result(name, "conflicts", ok, msg)
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "conflicts", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_multi_tenancy_after_audit_log() -> dict:
    """add_audit_log then add_multi_tenancy — tenant_id context should not break audit."""
    from adapt.extend.crud_data.add_audit_log import add_audit_log
    from adapt.extend.auth_access.add_multi_tenancy import add_multi_tenancy

    name = "multi_tenancy_after_audit_log"
    tmp = tempfile.mkdtemp(prefix="rt_mt_audit_")
    try:
        project_dir = create_fixture_project(name="mt_audit", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir))

        def _run():
            r1 = add_audit_log(inp)
            if r1.status not in ("success", "no_op"):
                return False, f"add_audit_log returned {r1.status}: {r1.error}"
            r2 = add_multi_tenancy(inp)
            if r2.status not in ("success", "no_op"):
                return False, f"add_multi_tenancy returned {r2.status}: {r2.error}"
            ok, reason = _all_py_parse_ok(project_dir)
            if not ok:
                return False, f"parse failed: {reason}"
            return True, f"audit={r1.status}, tenancy={r2.status}; all .py files parse"

        ok, msg = _run_with_timeout(_run)
        return _make_result(name, "conflicts", ok, msg)
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "conflicts", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_all_27_extend_tools() -> dict:
    """Run all 27 EXTEND tools sequentially on one project — project still parses."""
    name = "all_27_extend_tools"
    tmp = tempfile.mkdtemp(prefix="rt_all27_")
    try:
        project_dir = create_fixture_project(name="all27", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir))

        def _run():
            tools = _import_all_extend_tools()
            results = []
            for tool in tools:
                try:
                    r = tool(inp)
                    results.append((tool.__name__, r.status))
                except Exception as exc:  # noqa: BLE001
                    results.append((tool.__name__, f"EXCEPTION:{type(exc).__name__}"))

            # Every tool must have returned a valid status (no raw exceptions)
            bad = [(n, s) for n, s in results if s.startswith("EXCEPTION")]
            if bad:
                return False, f"tools crashed: {bad}"

            ok, reason = _all_py_parse_ok(project_dir)
            if not ok:
                return False, f"parse failed after all 27 tools: {reason}"

            summary = ", ".join(f"{n}={s}" for n, s in results)
            return True, f"all 27 tools completed; project parses. Statuses: {summary}"

        ok, msg = _run_with_timeout(_run, timeout=300)
        return _make_result(name, "conflicts", ok, msg)
    except _TimeoutError:
        return _make_result(name, "conflicts", False, "timed out running all 27 tools")
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "conflicts", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# CATEGORY 4 — Generated Code Quality (5 attacks)
# ===========================================================================

def _attack_ruff_clean_after_soft_delete() -> dict:
    """Generate project + add_soft_delete → tool must not introduce new ruff E/F violations.

    Strategy: capture the set of ruff violations *before* running the tool, then
    after.  Only violations that appear in the post-run set but not the pre-run
    set are attributed to the tool.  Pre-existing generator issues are ignored.
    """
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "ruff_clean_after_soft_delete"
    tmp = tempfile.mkdtemp(prefix="rt_ruff_sd_")

    def _ruff_violation_set(project: Path) -> set[str]:
        """Return a frozenset of '<file>:<line>:<col>: <code>' strings."""
        proc = subprocess.run(
            ["ruff", "check", str(project), "--select=E,F", "--ignore=E501",
             "--output-format=text"],
            capture_output=True, text=True, timeout=30,
        )
        violations: set[str] = set()
        for line in proc.stdout.splitlines():
            # Lines look like: "path/file.py:10:5: F401 ..."
            # Normalise to relative path so temp dirs don't affect comparison
            if ":" in line and (line.strip().startswith("/") or line.strip()[1:3] == ":/"):
                try:
                    rel = line.split(str(project))[-1]
                    violations.add(rel.strip())
                except Exception:  # noqa: BLE001
                    violations.add(line.strip())
        return violations

    try:
        project_dir = create_fixture_project(name="ruff_sd", tmp_dir=Path(tmp))

        def _run():
            before = _ruff_violation_set(project_dir)
            r = add_soft_delete(ToolInput(project_dir=str(project_dir)))
            if r.status not in ("success", "no_op"):
                return False, f"tool returned {r.status}: {r.error}"
            after = _ruff_violation_set(project_dir)
            new_violations = after - before
            if new_violations:
                sample = list(new_violations)[:3]
                return False, f"tool introduced {len(new_violations)} new ruff violation(s): " + "; ".join(sample)
            return True, f"no new ruff E/F violations introduced by add_soft_delete (pre={len(before)}, post={len(after)})"

        ok, msg = _run_with_timeout(_run)
        return _make_result(name, "code_quality", ok, msg)
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "code_quality", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_no_duplicate_imports_after_5_tools() -> dict:
    """Generate + run 5 tools → no duplicate import lines in any single file."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete
    from adapt.extend.crud_data.add_cursor_pagination import add_cursor_pagination
    from adapt.extend.crud_data.add_search import add_search
    from adapt.extend.auth_access.add_rbac import add_rbac
    from adapt.extend.infrastructure.add_cache_layer import add_cache_layer

    name = "no_duplicate_imports_after_5_tools"
    tmp = tempfile.mkdtemp(prefix="rt_dupimport_")
    try:
        project_dir = create_fixture_project(name="dup_imports", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir))

        for fn in [add_soft_delete, add_cursor_pagination, add_search, add_rbac, add_cache_layer]:
            r = fn(inp)
            if r.status not in ("success", "no_op"):
                return _make_result(name, "code_quality", False, f"{fn.__name__} returned {r.status}: {r.error}")

        def _run():
            duplicates = []
            for py_file in sorted(project_dir.rglob("*.py")):
                lines = py_file.read_text(encoding="utf-8").splitlines()
                import_lines = [l.strip() for l in lines if l.strip().startswith(("import ", "from "))]
                seen: set[str] = set()
                for line in import_lines:
                    if line in seen:
                        duplicates.append(f"{py_file.name}: {line!r}")
                    seen.add(line)
            if duplicates:
                return False, f"duplicate imports found ({len(duplicates)}): " + "; ".join(duplicates[:3])
            return True, "no duplicate import lines found in any generated file"

        ok, msg = _run_with_timeout(_run)
        return _make_result(name, "code_quality", ok, msg)
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "code_quality", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_no_fstring_sql() -> dict:
    """Generated code must contain no f-string SQL interpolation."""
    from adapt.extend.crud_data.add_search import add_search
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete
    from adapt.extend.crud_data.add_audit_log import add_audit_log

    name = "no_fstring_sql"
    tmp = tempfile.mkdtemp(prefix="rt_fsql_")
    try:
        project_dir = create_fixture_project(name="fstring_sql", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir))

        for fn in [add_search, add_soft_delete, add_audit_log]:
            r = fn(inp)
            if r.status not in ("success", "no_op"):
                return _make_result(name, "code_quality", False, f"{fn.__name__} returned {r.status}: {r.error}")

        def _run():
            # Detect f-strings that interpolate a variable directly into a SQL
            # keyword context.  The pattern requires the SQL keyword to appear as
            # a word boundary token (not mid-identifier like EMAILS_FROM_NAME)
            # and be immediately followed by a variable interpolation {…}.
            # Examples that SHOULD match:
            #   f"SELECT * FROM {table}"
            #   f"WHERE {column} ="
            # Examples that must NOT match:
            #   f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"  (FROM mid-word)
            import re
            # \b ensures the keyword is a standalone token, not a substring of an identifier.
            sql_keywords = re.compile(
                r'f["\'](?:[^"\'\\]|\\.)*?\b(SELECT|INSERT|UPDATE|DELETE|WHERE|JOIN)\b'
                r'(?:[^"\'\\]|\\.)*?\{',
                re.IGNORECASE,
            )
            hits = []
            for py_file in sorted(project_dir.rglob("*.py")):
                content = py_file.read_text(encoding="utf-8")
                for m in sql_keywords.finditer(content):
                    hits.append(f"{py_file.name}: {m.group()[:80]!r}")
            if hits:
                return False, "f-string SQL found: " + "; ".join(hits[:3])
            return True, "no f-string SQL interpolation found"

        ok, msg = _run_with_timeout(_run)
        return _make_result(name, "code_quality", ok, msg)
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "code_quality", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_migrations_have_downgrade() -> dict:
    """All generated Alembic migrations must define a downgrade() function."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete
    from adapt.extend.crud_data.add_bulk_operations import add_bulk_operations
    from adapt.extend.auth_access.add_mfa import add_mfa

    name = "migrations_have_downgrade"
    tmp = tempfile.mkdtemp(prefix="rt_downgrade_")
    try:
        project_dir = create_fixture_project(name="migrations_dg", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir))

        for fn in [add_soft_delete, add_bulk_operations, add_mfa]:
            r = fn(inp)
            if r.status not in ("success", "no_op"):
                return _make_result(name, "code_quality", False, f"{fn.__name__} returned {r.status}: {r.error}")

        def _run():
            versions_dir = project_dir / "alembic" / "versions"
            if not versions_dir.exists():
                return False, "alembic/versions/ directory not found"
            migration_files = list(versions_dir.glob("*.py"))
            if not migration_files:
                return False, "no migration files found in alembic/versions/"
            missing_downgrade = []
            for mf in migration_files:
                content = mf.read_text(encoding="utf-8")
                if "def downgrade" not in content:
                    missing_downgrade.append(mf.name)
            if missing_downgrade:
                return False, f"missing downgrade(): {missing_downgrade}"
            return True, f"all {len(migration_files)} migration(s) have downgrade()"

        ok, msg = _run_with_timeout(_run)
        return _make_result(name, "code_quality", ok, msg)
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "code_quality", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_routes_have_auth_deps() -> dict:
    """Generated CRUD route files must include at least one auth dependency reference."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete
    from adapt.extend.auth_access.add_rbac import add_rbac

    name = "routes_have_auth_deps"
    tmp = tempfile.mkdtemp(prefix="rt_auth_deps_")
    try:
        project_dir = create_fixture_project(name="auth_deps_proj", tmp_dir=Path(tmp))
        inp = ToolInput(project_dir=str(project_dir))

        for fn in [add_soft_delete, add_rbac]:
            r = fn(inp)
            if r.status not in ("success", "no_op"):
                return _make_result(name, "code_quality", False, f"{fn.__name__} returned {r.status}: {r.error}")

        def _run():
            routes_dir = project_dir / "app" / "api" / "routes"
            if not routes_dir.exists():
                return False, "app/api/routes/ not found"
            route_files = [f for f in routes_dir.glob("*.py") if f.name != "__init__.py"]
            if not route_files:
                return False, "no route files found"

            # Auth deps: CurrentUser, current_user, get_current_user, Depends(get_current_active_user)
            import re
            auth_pattern = re.compile(
                r"CurrentUser|current_user|get_current_active_user|CurrentSuperuser"
            )
            unauthenticated = []
            for rf in route_files:
                if rf.name in ("login.py", "oauth.py", "health.py"):
                    continue  # public routes are expected to be unauthenticated
                content = rf.read_text(encoding="utf-8")
                if not auth_pattern.search(content):
                    unauthenticated.append(rf.name)
            if unauthenticated:
                return False, f"route files without auth deps: {unauthenticated}"
            return True, f"all {len(route_files)} route file(s) reference auth deps"

        ok, msg = _run_with_timeout(_run)
        return _make_result(name, "code_quality", ok, msg)
    except Exception as exc:  # noqa: BLE001
        return _make_result(name, "code_quality", False, f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# Attack registry
# ===========================================================================

ALL_ATTACKS: list[Callable[[], dict]] = [
    # Fuzzing (10)
    _attack_path_traversal,
    _attack_nonexistent_dir,
    _attack_empty_string,
    _attack_unicode_bomb,
    _attack_very_long_path,
    _attack_permission_denied,
    _attack_symlink_loop,
    _attack_file_instead_of_dir,
    _attack_null_bytes_in_path,
    _attack_space_only_path,
    # Idempotency (5)
    _attack_idempotency_100x,
    _attack_delete_and_rerun,
    _attack_concurrent_tools_same_project,
    _attack_dry_run_50x_no_writes,
    _attack_corrupt_then_rerun,
    # Conflicts (5)
    _attack_soft_delete_plus_bulk_operations,
    _attack_mfa_plus_oauth2,
    _attack_search_plus_cursor_pagination,
    _attack_multi_tenancy_after_audit_log,
    _attack_all_27_extend_tools,
    # Code quality (5)
    _attack_ruff_clean_after_soft_delete,
    _attack_no_duplicate_imports_after_5_tools,
    _attack_no_fstring_sql,
    _attack_migrations_have_downgrade,
    _attack_routes_have_auth_deps,
]


# ===========================================================================
# Runner
# ===========================================================================

def run_red_team() -> dict:
    """Run all adversarial attacks and return aggregated results.

    Returns:
        dict with keys ``total_attacks``, ``passed``, ``failed``, ``details``.
        ``passed`` counts attacks where the tool behaved correctly under stress.
        ``failed`` counts attacks where the tool misbehaved or crashed
        unexpectedly — these are diagnostic findings, not fixed here.
    """
    details: list[dict] = []
    for attack_fn in ALL_ATTACKS:
        label = attack_fn.__name__.lstrip("_attack_")
        print(f"  [{label}] ...", end="", flush=True)
        try:
            result = _run_with_timeout(attack_fn, timeout=ATTACK_TIMEOUT + 5)
        except _TimeoutError:
            result = _make_result(
                label, "unknown", False, f"outer timeout after {ATTACK_TIMEOUT + 5}s"
            )
        except Exception as exc:  # noqa: BLE001
            result = _make_result(
                label, "unknown", False, f"runner exception: {type(exc).__name__}: {exc}"
            )
        icon = "PASS" if result["passed"] else "FAIL"
        print(f" {icon} — {result['notes'][:100]}")
        details.append(result)

    passed = sum(1 for d in details if d["passed"])
    failed = len(details) - passed
    return {
        "total_attacks": len(details),
        "passed": passed,
        "failed": failed,
        "details": details,
    }


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("SKILL-001 Red Team — Adversarial Test Suite")
    print("=" * 70)
    print()

    report = run_red_team()

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total attacks : {report['total_attacks']}")
    print(f"Passed        : {report['passed']}")
    print(f"Failed        : {report['failed']}")
    print()

    if report["failed"]:
        print("FAILED attacks (diagnostic — tools need attention):")
        for d in report["details"]:
            if not d["passed"]:
                print(f"  [{d['category']}] {d['name']}: {d['notes']}")
        print()

    pct = report["passed"] / report["total_attacks"] * 100
    if report["failed"] == 0:
        verdict = "Red team: PASS"
    else:
        verdict = "Red team: FAIL"
    print(f"{verdict} — {report['passed']}/{report['total_attacks']} attacks passed ({pct:.0f}%)")

    sys.exit(0 if report["failed"] == 0 else 1)
