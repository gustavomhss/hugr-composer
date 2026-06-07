"""Red Team adversarial test suite — part 3 (code quality + registry + runner).

Internal implementation module for :mod:`audit.red_team`.  Do not run directly;
use ``PYTHONPATH=. python3 audit/red_team.py``.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from audit.red_team__impl1 import (
    ATTACK_TIMEOUT,
    ToolInput,
    _TimeoutError,
    _make_result,
    _run_with_timeout,
    create_fixture_project,
)

# Category 1 + 2 attacks live in impl1; Category 3 attacks live in impl2.
# They are imported here so ALL_ATTACKS stays a single ordered registry.
from audit.red_team__impl1 import (
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
)
from audit.red_team__impl2 import (
    _attack_idempotency_100x,
    _attack_delete_and_rerun,
    _attack_concurrent_tools_same_project,
    _attack_dry_run_50x_no_writes,
    _attack_corrupt_then_rerun,
    _attack_soft_delete_plus_bulk_operations,
    _attack_mfa_plus_oauth2,
    _attack_search_plus_cursor_pagination,
    _attack_multi_tenancy_after_audit_log,
    _attack_all_27_extend_tools,
)


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
