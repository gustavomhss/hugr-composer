"""Red Team adversarial test suite — part 2 (idempotency + conflicts).

Internal implementation module for :mod:`audit.red_team`.  Do not run directly;
use ``PYTHONPATH=. python3 audit/red_team.py``.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path

from audit.red_team__impl1 import (
    ATTACK_TIMEOUT,
    ToolInput,
    _TimeoutError,
    _all_py_parse_ok,
    _count_disk_files,
    _import_all_extend_tools,
    _is_valid_tool_result,
    _make_result,
    _run_with_timeout,
    create_fixture_project,
)


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
