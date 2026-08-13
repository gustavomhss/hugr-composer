"""Red Team adversarial test suite — part 1 (helpers + input fuzzing).

Internal implementation module for :mod:`audit.red_team`.  Do not run directly;
use ``PYTHONPATH=. python3 audit/red_team.py``.

Also hosts the shared bootstrap, constants, helpers, and the 27-tool importer
re-used by parts 2 and 3.
"""

from __future__ import annotations

import ast
import os
import shutil

# ---------------------------------------------------------------------------
# Bootstrap: make sure SKILL root is on sys.path
# ---------------------------------------------------------------------------
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

SKILL_ROOT = Path(__file__).parent.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from adapt.contracts import ToolInput, ToolResult  # noqa: E402
from tests.common.fixture_factory import (
    create_fixture_project,  # noqa: E402,F401  (re-exported to impl2/impl3)
)

# ---------------------------------------------------------------------------
# Attack timeout (seconds per attack)
# ---------------------------------------------------------------------------
ATTACK_TIMEOUT = 30


# ---------------------------------------------------------------------------
# All 27 EXTEND tools in dependency-safe import order
# ---------------------------------------------------------------------------
def _import_all_extend_tools() -> list[Callable[[ToolInput], ToolResult]]:
    """Import and return all 27 extend tool callables."""
    from adapt.extend.api_design.add_api_versioning import add_api_versioning
    from adapt.extend.api_design.add_batch_endpoint import add_batch_endpoint
    from adapt.extend.api_design.add_graphql import add_graphql
    from adapt.extend.api_design.add_long_running_task import add_long_running_task
    from adapt.extend.auth_access.add_api_key_auth import add_api_key_auth
    from adapt.extend.auth_access.add_feature_flags import add_feature_flags
    from adapt.extend.auth_access.add_mfa import add_mfa
    from adapt.extend.auth_access.add_multi_tenancy import add_multi_tenancy
    from adapt.extend.auth_access.add_oauth2_provider import add_oauth2_provider
    from adapt.extend.auth_access.add_rbac import add_rbac
    from adapt.extend.crud_data.add_audit_log import add_audit_log
    from adapt.extend.crud_data.add_bulk_operations import add_bulk_operations
    from adapt.extend.crud_data.add_cursor_pagination import add_cursor_pagination
    from adapt.extend.crud_data.add_data_export import add_data_export
    from adapt.extend.crud_data.add_file_upload import add_file_upload
    from adapt.extend.crud_data.add_search import add_search
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete
    from adapt.extend.infrastructure.add_cache_layer import add_cache_layer
    from adapt.extend.infrastructure.add_circuit_breaker import add_circuit_breaker
    from adapt.extend.infrastructure.add_outbox_pattern import add_outbox_pattern
    from adapt.extend.infrastructure.add_saga import add_saga
    from adapt.extend.realtime.add_sse import add_sse
    from adapt.extend.realtime.add_webhook_receiver import add_webhook_receiver
    from adapt.extend.realtime.add_webhook_sender import add_webhook_sender
    from adapt.extend.testing_tools.add_contract_tests import add_contract_tests
    from adapt.extend.testing_tools.add_factory import add_factory
    from adapt.extend.testing_tools.add_load_profile import add_load_profile

    return [
        add_soft_delete,
        add_bulk_operations,
        add_cursor_pagination,
        add_data_export,
        add_file_upload,
        add_search,
        add_audit_log,
        add_mfa,
        add_oauth2_provider,
        add_multi_tenancy,
        add_rbac,
        add_api_key_auth,
        add_feature_flags,
        add_cache_layer,
        add_circuit_breaker,
        add_outbox_pattern,
        add_saga,
        add_api_versioning,
        add_batch_endpoint,
        add_graphql,
        add_long_running_task,
        add_sse,
        add_webhook_receiver,
        add_webhook_sender,
        add_contract_tests,
        add_factory,
        add_load_profile,
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(name: str, category: str, passed: bool, notes: str) -> dict:
    return {"name": name, "category": category, "passed": passed, "notes": notes}


def _is_valid_tool_result(obj: object) -> bool:
    """Return True if obj is a well-formed ToolResult with status in {success, no_op, error}."""
    return isinstance(obj, ToolResult) and obj.status in ("success", "no_op", "error")


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
        return _make_result(
            name, "fuzzing", False, f"unexpected status={getattr(result, 'status', '?')}"
        )
    except Exception as exc:  # noqa: BLE001
        # Pydantic validation error or any clean exception is acceptable —
        # the tool must not silently succeed or produce garbage output
        if "validation" in type(exc).__name__.lower() or "value" in type(exc).__name__.lower():
            return _make_result(
                name, "fuzzing", True, f"raised clean validation error: {type(exc).__name__}"
            )
        return _make_result(
            name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}"
        )


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
        return _make_result(
            name, "fuzzing", False, f"unexpected status={getattr(result, 'status', '?')}"
        )
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (FileNotFoundError, OSError, PermissionError)):
            return _make_result(
                name, "fuzzing", True, f"raised OS-level error cleanly: {type(exc).__name__}"
            )
        return _make_result(
            name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}"
        )


def _attack_empty_string() -> dict:
    """Empty project_dir must return error or validation error."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "empty_string"
    try:
        result = _run_with_timeout(lambda: add_soft_delete(ToolInput(project_dir="")))
        if _is_valid_tool_result(result) and result.status == "error":
            return _make_result(name, "fuzzing", True, f"returned error: {result.error}")
        if _is_valid_tool_result(result) and result.status == "no_op":
            return _make_result(name, "fuzzing", True, "returned no_op for empty path")
        return _make_result(
            name, "fuzzing", False, f"unexpected status={getattr(result, 'status', '?')}"
        )
    except Exception as exc:  # noqa: BLE001
        return _make_result(
            name, "fuzzing", True, f"raised exception cleanly: {type(exc).__name__}"
        )


def _attack_unicode_bomb() -> dict:
    """Unicode bomb path must not crash."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "unicode_bomb"
    # NUL bytes are the critical case; other unicode is generally fine
    bad_path = "/tmp/\x00\x01\x02\x03\x04test"
    try:
        result = _run_with_timeout(lambda: add_soft_delete(ToolInput(project_dir=bad_path)))
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(
            name, "fuzzing", False, f"unexpected status={getattr(result, 'status', '?')}"
        )
    except Exception as exc:  # noqa: BLE001
        # ValueError / OSError for NUL bytes is correct and expected
        if isinstance(exc, (ValueError, OSError, TypeError)):
            return _make_result(name, "fuzzing", True, f"raised clean error: {type(exc).__name__}")
        return _make_result(
            name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}"
        )


def _attack_very_long_path() -> dict:
    """10,000-character path must not crash or hang."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "very_long_path"
    long_path = "/tmp/" + "a" * 9995
    try:
        result = _run_with_timeout(lambda: add_soft_delete(ToolInput(project_dir=long_path)))
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(
            name, "fuzzing", False, f"unexpected status={getattr(result, 'status', '?')}"
        )
    except _TimeoutError:
        return _make_result(name, "fuzzing", False, "timed out on long path")
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (OSError, ValueError, FileNotFoundError)):
            return _make_result(
                name, "fuzzing", True, f"raised OS error cleanly: {type(exc).__name__}"
            )
        return _make_result(
            name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}"
        )


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
        result = _run_with_timeout(lambda: add_soft_delete(ToolInput(project_dir=str(restricted))))
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(
            name, "fuzzing", False, f"unexpected status={getattr(result, 'status', '?')}"
        )
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (PermissionError, OSError)):
            return _make_result(
                name, "fuzzing", True, f"raised OS error cleanly: {type(exc).__name__}"
            )
        return _make_result(
            name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}"
        )
    finally:
        os.chmod(str(restricted), 0o755)
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_symlink_loop() -> dict:
    """Symlink loop must not hang or crash. Pass the symlink itself as project_dir."""
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
        # Pass the symlink itself (link_a) to trigger symlink loop detection
        result = _run_with_timeout(lambda: add_soft_delete(ToolInput(project_dir=str(link_a))))
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(
            name, "fuzzing", False, f"unexpected status={getattr(result, 'status', '?')}"
        )
    except _TimeoutError:
        return _make_result(name, "fuzzing", False, "hung on symlink loop")
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (OSError, RecursionError, RuntimeError)):
            return _make_result(
                name, "fuzzing", True, f"raised error cleanly: {type(exc).__name__}"
            )
        return _make_result(
            name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}"
        )
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
        result = _run_with_timeout(lambda: add_soft_delete(ToolInput(project_dir=str(fake_file))))
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(
            name, "fuzzing", False, f"unexpected status={getattr(result, 'status', '?')}"
        )
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (OSError, NotADirectoryError, ValueError)):
            return _make_result(name, "fuzzing", True, f"raised clean error: {type(exc).__name__}")
        return _make_result(
            name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _attack_null_bytes_in_path() -> dict:
    """Null byte embedded mid-path must not crash."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "null_bytes_in_path"
    path_with_null = "/tmp/valid\x00injected"
    try:
        result = _run_with_timeout(lambda: add_soft_delete(ToolInput(project_dir=path_with_null)))
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(
            name, "fuzzing", False, f"unexpected status={getattr(result, 'status', '?')}"
        )
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (ValueError, OSError, TypeError)):
            return _make_result(name, "fuzzing", True, f"raised clean error: {type(exc).__name__}")
        return _make_result(
            name, "fuzzing", False, f"unhandled exception: {type(exc).__name__}: {exc}"
        )


def _attack_space_only_path() -> dict:
    """Whitespace-only path must return error gracefully."""
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    name = "space_only_path"
    try:
        result = _run_with_timeout(lambda: add_soft_delete(ToolInput(project_dir="   ")))
        if _is_valid_tool_result(result) and result.status in ("error", "no_op"):
            return _make_result(name, "fuzzing", True, f"returned status={result.status}")
        return _make_result(
            name, "fuzzing", False, f"unexpected status={getattr(result, 'status', '?')}"
        )
    except Exception as exc:  # noqa: BLE001
        return _make_result(
            name, "fuzzing", True, f"raised exception cleanly: {type(exc).__name__}"
        )
