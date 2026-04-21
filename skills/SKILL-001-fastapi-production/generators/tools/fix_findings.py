"""Auto-fix tool for FastAPI production benchmark findings.

Takes the output of ``analyze()`` (or runs it internally) and attempts to
fix every failing check automatically.  Returns a structured report of
what was fixed, what needs manual intervention, and the before/after score.
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_meta_analyze_fix_findings',
    'description': 'Auto-fix production readiness findings in an existing project.',
    'tags': ['operate', 'refactor'],
    'entry': 'fix_findings',
    'annotations': {'readOnlyHint': False},
}

import re
from pathlib import Path

from generators.tools._layout import resolve_app_root


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_py_files(root: Path) -> list[Path]:
    """Return all .py files under *root*, sorted."""
    return sorted(root.rglob("*.py"))


def _read_requirements(root: Path) -> tuple[Path | None, list[str]]:
    """Return (path, lines) for the first requirements*.txt found."""
    for candidate in sorted(root.rglob("requirements*.txt")):
        return candidate, candidate.read_text().splitlines()
    return None, []


def _write_requirements(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n")


def _remove_dep(lines: list[str], pattern: str) -> list[str]:
    """Remove lines matching *pattern* (case-insensitive)."""
    rx = re.compile(pattern, re.IGNORECASE)
    return [l for l in lines if not rx.search(l)]


def _ensure_dep(lines: list[str], dep: str) -> list[str]:
    """Append *dep* if it is not already present (case-insensitive match)."""
    name = dep.split("[")[0].split("=")[0].split(">")[0].split("<")[0].strip().lower()
    for l in lines:
        if name in l.lower():
            return lines
    lines.append(dep)
    return lines


def _find_routes_init(root: Path) -> Path | None:
    """Locate routes/__init__.py (or api/routes/__init__.py, etc.)."""
    for candidate in root.rglob("routes/__init__.py"):
        return candidate
    return None


def _find_main_py(root: Path) -> Path | None:
    """Locate the FastAPI app entrypoint (main.py)."""
    for candidate in root.rglob("main.py"):
        content = candidate.read_text()
        if "FastAPI" in content:
            return candidate
    return None


def _inject_import(content: str, import_line: str) -> str:
    """Insert *import_line* after the last import statement in *content*."""
    lines = content.splitlines(keepends=True)
    last_import_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("from ", "import ")) and not stripped.startswith("# "):
            last_import_idx = i
    lines.insert(last_import_idx + 1, import_line if import_line.endswith("\n") else import_line + "\n")
    return "".join(lines)


def _inject_middleware_after_app(content: str, middleware_line: str) -> str:
    """Insert *middleware_line* after the ``app = FastAPI(...)`` declaration."""
    return re.sub(
        r"(app\s*=\s*FastAPI\([^)]*\)\s*\n)",
        r"\1\n" + (middleware_line if middleware_line.endswith("\n") else middleware_line + "\n"),
        content,
        count=1,
    )


# ---------------------------------------------------------------------------
# Individual fixers
# ---------------------------------------------------------------------------

def _fix_password_hashing(root: Path, req_path: Path | None, req_lines: list[str]) -> dict | None:
    """Fix: generate argon2id hasher, replace passlib imports everywhere, update requirements."""
    from ..auth.hasher import generate_password_hasher

    result = generate_password_hasher(str(root))
    files_modified = list(result["files_created"])

    # --- Update requirements: remove passlib/bcrypt, add pwdlib ---
    if req_path is not None:
        req_lines[:] = _remove_dep(req_lines, r"passlib")
        req_lines[:] = _remove_dep(req_lines, r"bcrypt")
        req_lines[:] = _ensure_dep(req_lines, "pwdlib[argon2]>=0.4.0")
        _write_requirements(req_path, req_lines)
        files_modified.append(str(req_path))

    # --- Replace passlib imports across ALL .py files ---
    for py_file in _find_py_files(root):
        try:
            content = py_file.read_text()
        except Exception:
            continue

        original = content

        # from passlib.context import CryptContext  ->  from pwdlib import PasswordHash
        content = re.sub(
            r"^from\s+passlib\.context\s+import\s+CryptContext\b.*$",
            "from pwdlib import PasswordHash\n"
            "from pwdlib.hashers.argon2 import Argon2Hasher",
            content,
            flags=re.MULTILINE,
        )
        # from passlib.hash import ...  ->  remove
        content = re.sub(
            r"^from\s+passlib\.hash\s+import\b.*\n",
            "",
            content,
            flags=re.MULTILINE,
        )
        # from passlib import ...  ->  remove
        content = re.sub(
            r"^from\s+passlib\b.*\n",
            "",
            content,
            flags=re.MULTILINE,
        )
        # import passlib  ->  remove
        content = re.sub(
            r"^import\s+passlib\b.*\n",
            "",
            content,
            flags=re.MULTILINE,
        )

        # CryptContext(schemes=["bcrypt"], ...)  ->  PasswordHash((Argon2Hasher(),))
        content = re.sub(
            r"CryptContext\s*\([^)]*\)",
            "PasswordHash((Argon2Hasher(),))",
            content,
        )

        # pwd_context.verify(...)  ->  password_hash.verify(...)
        content = re.sub(r"\bpwd_context\.verify\b", "password_hash.verify", content)
        # pwd_context.hash(...)  ->  password_hash.hash(...)
        content = re.sub(r"\bpwd_context\.hash\b", "password_hash.hash", content)

        if content != original:
            py_file.write_text(content)
            files_modified.append(str(py_file))

    return {
        "finding": "Modern password hashing (argon2id)",
        "action": "Generated core/security.py with argon2id via pwdlib; replaced passlib imports everywhere; updated requirements",
        "files_modified": files_modified,
    }


def _fix_jwt(root: Path, req_path: Path | None, req_lines: list[str]) -> dict | None:
    """Fix: generate PyJWT module, update requirements, fix jose imports."""
    from ..auth.jwt import generate_jwt

    result = generate_jwt(str(root))
    files_modified = list(result["files_created"])

    # Update requirements
    if req_path is not None:
        req_lines[:] = _remove_dep(req_lines, r"python-jose")
        req_lines[:] = _ensure_dep(req_lines, "PyJWT>=2.8.0")
        _write_requirements(req_path, req_lines)
        files_modified.append(str(req_path))

    # Fix imports across all .py files: from jose import jwt -> import jwt
    for py_file in _find_py_files(root):
        try:
            content = py_file.read_text()
        except Exception:
            continue

        original = content
        # from jose import jwt  ->  import jwt
        content = re.sub(
            r"^from\s+jose\s+import\s+jwt\b",
            "import jwt",
            content,
            flags=re.MULTILINE,
        )
        # from jose import ...  ->  remove line (other jose imports)
        content = re.sub(
            r"^from\s+jose\b.*\n",
            "",
            content,
            flags=re.MULTILINE,
        )
        # import jose  ->  import jwt
        content = re.sub(
            r"^import\s+jose\b",
            "import jwt",
            content,
            flags=re.MULTILINE,
        )

        if content != original:
            py_file.write_text(content)
            files_modified.append(str(py_file))

    return {
        "finding": "Uses PyJWT (not python-jose with CVE)",
        "action": "Generated core/jwt.py with PyJWT; replaced jose imports; updated requirements",
        "files_modified": files_modified,
    }


def _fix_timing_attack(root: Path) -> dict | None:
    """Fix: ensure login route uses DUMMY_HASH pattern.

    The hasher generator already creates DUMMY_HASH. This fixer patches
    any login/auth route that does a plain 'user not found -> 401' without
    running the dummy verification.
    """
    files_modified: list[str] = []

    for py_file in _find_py_files(root):
        try:
            content = py_file.read_text()
        except Exception:
            continue

        # Skip files that already use DUMMY_HASH
        if "DUMMY_HASH" in content:
            continue

        # Look for login patterns: authenticate_user, login, or verify_password usage
        # near "user not found" or "user is None" patterns
        if not re.search(r"(login|authenticate|verify_password)", content, re.IGNORECASE):
            continue
        if not re.search(r"(user\s*(is\s*None|not\s*found|==\s*None|\s*is\s+None))", content, re.IGNORECASE):
            continue

        # Add DUMMY_HASH import if core/security.py pattern is used
        if "from" in content and "security" in content and "verify_password" in content:
            # Add DUMMY_HASH to the import
            content = re.sub(
                r"(from\s+\S*security\s+import\s+)(verify_password|get_password_hash)",
                r"\1DUMMY_HASH, \2",
                content,
                count=1,
            )

            # Add dummy verification before the "user is None" return
            # Pattern: if user is None -> raise/return 401
            content = re.sub(
                r"(if\s+(?:not\s+)?user\b[^:]*:)\s*\n(\s+)(raise\s+HTTPException|return)",
                r"\1\n\2verify_password('dummy', DUMMY_HASH)  # timing-attack prevention\n\2\3",
                content,
            )

            if "DUMMY_HASH" in content:
                py_file.write_text(content)
                files_modified.append(str(py_file))

    if not files_modified:
        return None

    return {
        "finding": "Timing attack prevention (DUMMY_HASH or constant-time)",
        "action": "Patched login route(s) to use DUMMY_HASH for timing-attack prevention",
        "files_modified": files_modified,
    }


def _fix_security_headers(root: Path) -> dict | None:
    """Fix: generate security headers middleware and wire into app."""
    from ..middleware.security_headers import generate_security_headers

    result = generate_security_headers(str(root))
    files_modified = list(result["files_created"])

    # Try to add middleware to main.py
    main_py = _find_main_py(root)
    if main_py is not None:
        content = main_py.read_text()
        if "SecurityHeadersMiddleware" not in content:
            content = _inject_import(content, "from app.middleware.security_headers import SecurityHeadersMiddleware\n")
            content = _inject_middleware_after_app(content, "app.add_middleware(SecurityHeadersMiddleware)\n")
            main_py.write_text(content)
            files_modified.append(str(main_py))

    return {
        "finding": "Security headers",
        "action": "Generated SecurityHeadersMiddleware with 7 headers; wired into main.py",
        "files_modified": files_modified,
    }


def _fix_structured_logging(
    root: Path, req_path: Path | None, req_lines: list[str],
) -> dict | None:
    """Fix: generate correlation ID + request logging middleware."""
    from ..middleware.correlation import generate_correlation_id
    from ..middleware.request_logging import generate_request_logging

    files_modified: list[str] = []

    r1 = generate_correlation_id(str(root))
    files_modified.extend(r1["files_created"])

    r2 = generate_request_logging(str(root))
    files_modified.extend(r2["files_created"])

    # Add structlog to requirements
    if req_path is not None:
        req_lines[:] = _ensure_dep(req_lines, "structlog>=24.1.0")
        _write_requirements(req_path, req_lines)
        if str(req_path) not in files_modified:
            files_modified.append(str(req_path))

    # Wire into main.py
    main_py = _find_main_py(root)
    if main_py is not None:
        content = main_py.read_text()
        changed = False
        if "CorrelationMiddleware" not in content:
            content = _inject_import(content, "from app.middleware.correlation import CorrelationMiddleware\n")
            content = _inject_middleware_after_app(content, "app.add_middleware(CorrelationMiddleware)\n")
            changed = True
        if "RequestLoggingMiddleware" not in content:
            content = _inject_import(content, "from app.middleware.request_logging import RequestLoggingMiddleware\n")
            content = _inject_middleware_after_app(content, "app.add_middleware(RequestLoggingMiddleware)\n")
            changed = True
        if changed:
            main_py.write_text(content)
            files_modified.append(str(main_py))

    return {
        "finding": "Structured logging (structlog)",
        "action": "Generated CorrelationMiddleware + RequestLoggingMiddleware; added structlog dep",
        "files_modified": files_modified,
    }


def _fix_correlation_id(root: Path) -> dict | None:
    """Fix: ensure CorrelationMiddleware is generated AND wired into main.py.

    This runs as a standalone fixer to guarantee the correlation ID check
    passes even if main.py was regenerated or doesn't use register_middleware.
    """
    from ..middleware.correlation import generate_correlation_id

    files_modified: list[str] = []

    r1 = generate_correlation_id(str(root))
    files_modified.extend(r1["files_created"])

    main_py = _find_main_py(root)
    if main_py is not None:
        content = main_py.read_text()

        # If main.py uses register_middleware(), it already wires correlation.
        # But if NOT, we need to inject CorrelationMiddleware directly.
        if "register_middleware" not in content and "CorrelationMiddleware" not in content:
            content = _inject_import(content, "from app.middleware.correlation import CorrelationMiddleware\n")
            content = _inject_middleware_after_app(content, "app.add_middleware(CorrelationMiddleware)\n")
            main_py.write_text(content)
            files_modified.append(str(main_py))

    return {
        "finding": "Correlation ID middleware",
        "action": "Generated CorrelationMiddleware and ensured it is wired into main.py",
        "files_modified": files_modified,
    }


def _fix_health_checks(root: Path) -> dict | None:
    """Fix: generate health endpoints and register the router."""
    from ..endpoints.health import generate_health_checks

    result = generate_health_checks(str(root))
    files_modified = list(result["files_created"])

    # Try to register health router in routes/__init__.py
    routes_init = _find_routes_init(root)
    if routes_init is not None:
        content = routes_init.read_text()
        if "health" not in content.lower():
            content += (
                "\nfrom app.routes.health import router as health_router  # noqa: E402\n"
            )
            routes_init.write_text(content)
            files_modified.append(str(routes_init))

    # Also try wiring into main.py directly
    main_py = _find_main_py(root)
    if main_py is not None:
        content = main_py.read_text()
        if "health" not in content.lower() or "/healthz" not in content:
            content = _inject_import(content, "from app.routes.health import router as health_router\n")
            content = _inject_middleware_after_app(content, "app.include_router(health_router)\n")
            main_py.write_text(content)
            files_modified.append(str(main_py))

    return {
        "finding": "Health checks (liveness + readiness)",
        "action": "Generated /healthz, /readyz, /startupz endpoints; registered router",
        "files_modified": files_modified,
    }


def _fix_dockerfile(root: Path) -> dict | None:
    """Fix: generate multi-stage Dockerfile (also fixes non-root + HEALTHCHECK)."""
    from ..infra.dockerfile import generate_dockerfile

    result = generate_dockerfile(str(root))
    return {
        "finding": "Multi-stage Docker build + non-root user + HEALTHCHECK",
        "action": "Generated multi-stage Dockerfile with non-root appuser and HEALTHCHECK",
        "files_modified": result["files_created"],
    }


def _fix_utcnow(root: Path) -> dict | None:
    """Fix: replace datetime.utcnow() with datetime.now(timezone.utc)."""
    files_modified: list[str] = []

    for py_file in _find_py_files(root):
        try:
            content = py_file.read_text()
        except Exception:
            continue

        if ".utcnow()" not in content:
            continue

        original = content

        # Replace datetime.utcnow() -> datetime.now(timezone.utc)
        content = content.replace("datetime.utcnow()", "datetime.now(timezone.utc)")

        # Also handle: datetime.datetime.utcnow()
        content = content.replace("datetime.datetime.utcnow()", "datetime.datetime.now(datetime.timezone.utc)")

        # Ensure 'from datetime import timezone' is present if we use timezone.utc
        if "timezone.utc" in content and "datetime.timezone.utc" not in content:
            if "from datetime import" in content:
                # Add timezone to existing import if missing
                if "timezone" not in content:
                    content = re.sub(
                        r"(from\s+datetime\s+import\s+)([^\n]+)",
                        r"\1\2, timezone",
                        content,
                        count=1,
                    )
            else:
                # Add a new import line
                content = "from datetime import timezone\n" + content

        if content != original:
            py_file.write_text(content)
            files_modified.append(str(py_file))

    if not files_modified:
        return None

    return {
        "finding": "No deprecated datetime.utcnow()",
        "action": "Replaced datetime.utcnow() with datetime.now(timezone.utc) across all .py files",
        "files_modified": files_modified,
    }


def _fix_async_engine(root: Path) -> dict | None:
    """Fix: generate core/db.py with async engine + pool configuration.

    This single fixer resolves both the 'Async database engine' check
    and the 'Pool configuration' check in one shot.
    """
    from ..database.engine import generate_engine

    result = generate_engine(str(root))
    return {
        "finding": "Async database engine + Pool configuration",
        "action": "Generated core/db.py with create_async_engine, pool_size, pool_pre_ping, pool_recycle",
        "files_modified": result["files_created"],
    }


def _fix_session(root: Path) -> dict | None:
    """Fix: generate core/session.py with async session factory."""
    from ..database.session import generate_session

    result = generate_session(str(root))
    return {
        "finding": "Session dependency injection",
        "action": "Generated core/session.py with async_sessionmaker and get_session dependency",
        "files_modified": result["files_created"],
    }


def _fix_lifespan(root: Path) -> dict | None:
    """Fix: generate main.py with lifespan pattern, replacing @app.on_event.

    This is aggressive (overwrites main.py) but produces a correct file
    with the lifespan async context manager, middleware registration, and
    router inclusion.  Also cleans any remaining @app.on_event decorators
    across the project.
    """
    from ..infra.app import generate_app

    result = generate_app(str(root))
    files_modified = list(result["files_created"])

    # Also scan all other .py files for leftover @app.on_event decorators
    # and remove them (they may exist in routers or other modules).
    for py_file in _find_py_files(root):
        try:
            content = py_file.read_text()
        except Exception:
            continue

        if "@app.on_event" not in content and "@app.on_event" not in content:
            continue

        # Skip the main.py we just generated
        if py_file.name == "main.py" and "lifespan" in content:
            continue

        original = content

        # Remove @app.on_event("startup") / @app.on_event("shutdown") decorators
        # and the async def that follows them
        content = re.sub(
            r"@app\.on_event\(['\"](?:startup|shutdown)['\"]\)\s*\n"
            r"(?:async\s+)?def\s+\w+\([^)]*\)[^:]*:\s*\n"
            r"(?:(?:    .*\n)*)",
            "",
            content,
        )

        if content != original:
            py_file.write_text(content)
            files_modified.append(str(py_file))

    return {
        "finding": "Lifespan pattern (not deprecated on_event)",
        "action": "Generated main.py with lifespan context manager; removed @app.on_event decorators",
        "files_modified": files_modified,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def fix_findings(
    project_dir: str,
    findings: dict | None = None,
) -> dict:
    """Automatically fix failing benchmark findings.

    If *findings* is ``None``, runs ``analyzer.analyze()`` first to
    discover what needs fixing.

    Args:
        project_dir: Root directory of the FastAPI project.
        findings: Optional pre-computed ``BenchmarkResult`` from
            ``analyzer.analyze()``.  When ``None`` the analyzer is
            invoked internally.

    Returns:
        Dict with ``fixed``, ``manual_required``, ``already_passing``,
        ``score_before``, and ``score_after`` keys.
    """
    import sys
    from pathlib import Path

    root = resolve_app_root(project_dir)

    # Import the analyzer -- it lives next to the generators package
    analyzer_path = Path(__file__).resolve().parent.parent.parent / "benchmark"
    sys.path.insert(0, str(analyzer_path.parent))
    from benchmark.analyzer import analyze

    # -- Before score ---------------------------------------------------
    before = analyze(root)
    score_before = f"{before.passed}/{before.total}"

    # Build a lookup: check_name -> passed
    check_status: dict[str, bool] = {}
    for c in before.checks:
        check_status[c.name] = c.passed

    # -- Requirements bookkeeping (shared across fixers) ----------------
    req_path, req_lines = _read_requirements(root)

    fixed: list[dict] = []
    manual_required: list[dict] = []
    already_passing: list[str] = []

    # -------------------------------------------------------------------
    # 1. Password hashing (argon2id) + pwdlib (replaces passlib everywhere)
    # -------------------------------------------------------------------
    chk_argon = "Modern password hashing (argon2id)"
    chk_pwdlib = "Uses pwdlib (not deprecated passlib)"
    if check_status.get(chk_argon, True) and check_status.get(chk_pwdlib, True):
        already_passing.append(chk_argon)
        already_passing.append(chk_pwdlib)
    else:
        result = _fix_password_hashing(root, req_path, req_lines)
        if result:
            fixed.append(result)

    # -------------------------------------------------------------------
    # 2. PyJWT (not python-jose)
    # -------------------------------------------------------------------
    chk = "Uses PyJWT (not python-jose with CVE)"
    if check_status.get(chk, True):
        already_passing.append(chk)
    else:
        result = _fix_jwt(root, req_path, req_lines)
        if result:
            fixed.append(result)

    # -------------------------------------------------------------------
    # 3. JWT algorithm whitelist -- covered by #2 (generate_jwt adds it)
    # -------------------------------------------------------------------
    chk = "JWT algorithm whitelist (algorithms=[...])"
    if check_status.get(chk, True):
        already_passing.append(chk)
    # else: already fixed by _fix_jwt

    # -------------------------------------------------------------------
    # 4. Timing attack prevention
    # -------------------------------------------------------------------
    chk = "Timing attack prevention (DUMMY_HASH or constant-time)"
    if check_status.get(chk, True):
        already_passing.append(chk)
    else:
        # The hasher fix (#1) generates DUMMY_HASH.
        # Also try to patch login routes.
        result = _fix_timing_attack(root)
        if result:
            fixed.append(result)
        # If the hasher was already generated above, DUMMY_HASH exists
        # and the analyzer will find it on re-check.

    # -------------------------------------------------------------------
    # 5. Security headers
    # -------------------------------------------------------------------
    # The analyzer check name includes the count, e.g. "Security headers (3/5)"
    # so we need a prefix match.
    sec_hdr_check = next(
        (c for c in before.checks if c.name.startswith("Security headers")),
        None,
    )
    if sec_hdr_check and sec_hdr_check.passed:
        already_passing.append(sec_hdr_check.name)
    elif sec_hdr_check:
        result = _fix_security_headers(root)
        if result:
            fixed.append(result)

    # -------------------------------------------------------------------
    # 6. Structured logging
    # -------------------------------------------------------------------
    chk = "Structured logging (structlog)"
    if check_status.get(chk, True):
        already_passing.append(chk)
    else:
        result = _fix_structured_logging(root, req_path, req_lines)
        if result:
            fixed.append(result)

    # -------------------------------------------------------------------
    # 7. Correlation ID -- standalone fixer to ensure it is wired
    # -------------------------------------------------------------------
    chk = "Correlation ID middleware"
    if check_status.get(chk, True):
        already_passing.append(chk)
    else:
        result = _fix_correlation_id(root)
        if result:
            fixed.append(result)

    # -------------------------------------------------------------------
    # 8. Health checks
    # -------------------------------------------------------------------
    chk = "Health checks (liveness + readiness)"
    if check_status.get(chk, True):
        already_passing.append(chk)
    else:
        result = _fix_health_checks(root)
        if result:
            fixed.append(result)

    # -------------------------------------------------------------------
    # 9. Dockerfile (multi-stage + non-root + HEALTHCHECK)
    # -------------------------------------------------------------------
    dockerfile_checks = [
        "Multi-stage Docker build",
        "Non-root container user",
        "Docker HEALTHCHECK",
    ]
    all_docker_pass = all(check_status.get(c, True) for c in dockerfile_checks)
    if all_docker_pass:
        for c in dockerfile_checks:
            if check_status.get(c, True):
                already_passing.append(c)
    else:
        result = _fix_dockerfile(root)
        if result:
            fixed.append(result)

    # -------------------------------------------------------------------
    # 10. datetime.utcnow() deprecation
    # -------------------------------------------------------------------
    chk = "No deprecated datetime.utcnow()"
    if check_status.get(chk, True):
        already_passing.append(chk)
    else:
        result = _fix_utcnow(root)
        if result:
            fixed.append(result)

    # -------------------------------------------------------------------
    # 11. Async database engine + Pool configuration
    # -------------------------------------------------------------------
    chk_engine = "Async database engine"
    chk_pool = "Pool configuration (size + recycle + pre_ping)"
    if check_status.get(chk_engine, True) and check_status.get(chk_pool, True):
        already_passing.append(chk_engine)
        already_passing.append(chk_pool)
    else:
        result = _fix_async_engine(root)
        if result:
            fixed.append(result)

    # -------------------------------------------------------------------
    # 12. Session dependency injection
    # -------------------------------------------------------------------
    chk = "Session dependency injection"
    if check_status.get(chk, True):
        already_passing.append(chk)
    else:
        result = _fix_session(root)
        if result:
            fixed.append(result)

    # -------------------------------------------------------------------
    # 13. Lifespan + @app.on_event deprecation
    #
    #     generate_app() produces main.py with lifespan pattern AND
    #     no @app.on_event.  This fixes BOTH checks in one shot.
    #     Because it overwrites main.py, it runs LAST so that all
    #     middleware/router wiring from earlier fixers is superseded
    #     by the canonical main.py produced by generate_app().
    # -------------------------------------------------------------------
    chk_lifespan = "Lifespan pattern (not deprecated on_event)"
    chk_on_event = "No deprecated @app.on_event"
    if check_status.get(chk_lifespan, True) and check_status.get(chk_on_event, True):
        already_passing.append(chk_lifespan)
        already_passing.append(chk_on_event)
    else:
        result = _fix_lifespan(root)
        if result:
            fixed.append(result)

    # -- Remaining checks not handled above (mark as already passing) ---
    handled_names = set()
    for entry in fixed:
        handled_names.add(entry["finding"])
    for entry in manual_required:
        handled_names.add(entry["finding"])
    handled_names.update(already_passing)

    for c in before.checks:
        name = c.name
        if name in handled_names:
            continue
        # Check names that vary (like "Security headers (3/5)")
        if any(name.startswith(h) for h in [n for n in handled_names]):
            continue
        if c.passed:
            already_passing.append(name)
        else:
            manual_required.append({
                "finding": name,
                "guidance": (
                    f"This check ({name}) is not auto-fixable. "
                    f"Detail: {c.detail}. See: {c.reference}"
                ),
            })

    # -- After score ----------------------------------------------------
    after = analyze(root)
    score_after = f"{after.passed}/{after.total}"

    return {
        "fixed": fixed,
        "manual_required": manual_required,
        "already_passing": already_passing,
        "score_before": score_before,
        "score_after": score_after,
    }
