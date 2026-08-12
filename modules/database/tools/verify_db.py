"""
SKILL-001 Database Tool: Static analysis of database code for production issues.

Performs AST-based analysis on a FastAPI/SQLAlchemy project to detect 8 common
database anti-patterns:

- DB-01: No pool_pre_ping (stale connections crash requests)
- DB-02: pool_size * workers exceeds max_connections
- DB-03: expire_on_commit not False in async sessions
- DB-04: N+1 risk (relationships without eager loading option specified)
- DB-05: No pool_recycle (connection timeout behind load balancers)
- DB-06: Sync engine used (create_engine instead of create_async_engine)
- DB-07: Raw SQL without parameterized queries (SQL injection risk)
- DB-08: No index on foreign keys (slow cascading deletes)
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_data_verify_db',
    'description': 'AST analysis of FastAPI/SQLAlchemy code for 8 DB anti-patterns (no pool_pre_ping, sync engine, N+1 risk, raw SQL, etc).',
    'tags': ['database', 'verify'],
    'entry': 'verify_db_config',
    'annotations': {'readOnlyHint': True, 'destructiveHint': False},
}

import ast
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_EXCLUDE_DIRS: set[str] = {
    ".venv", "venv", "node_modules", "__pycache__", ".git",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    "site-packages", "alembic", "migrations",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_python_files(root: Path) -> list[Path]:
    """Walk *root* and return .py files not in excluded directories."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _DEFAULT_EXCLUDE_DIRS]
        dp = Path(dirpath)
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(dp / fn)
    return files


def _resolve_call_name(node: ast.Call) -> str | None:
    """Resolve a dotted call name from an AST Call node."""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        # Nested attribute: x.y.z(...)
        parts: list[str] = []
        current = func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            return ".".join(reversed(parts))
    return None


def _get_keyword_value(node: ast.Call, keyword: str) -> ast.expr | None:
    """Get the value of a keyword argument from a Call node."""
    for kw in node.keywords:
        if kw.arg == keyword:
            return kw.value
    return None


def _get_constant_value(node: ast.expr | None) -> object:
    """Extract a constant value from an AST node, or return None."""
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    return None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_db01_no_pool_pre_ping(
    tree: ast.AST, filepath: Path,
) -> Finding | None:
    """DB-01: create_async_engine without pool_pre_ping=True."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolve_call_name(node)
        if call_name not in ("create_async_engine", "create_engine"):
            continue

        pre_ping_val = _get_keyword_value(node, "pool_pre_ping")
        if pre_ping_val is None:
            return Finding(
                rule_id="DB-01",
                severity=Severity.MEDIUM,
                title="No pool_pre_ping on database engine",
                description=(
                    "Engine created without pool_pre_ping=True. Stale connections "
                    "from the pool (e.g., after PostgreSQL restart or network blip) "
                    "will crash request handlers with 'connection was closed' errors. "
                    "pool_pre_ping issues a lightweight SELECT 1 before checkout."
                ),
                file_path=str(filepath),
                line_number=node.lineno,
                fix_suggestion=(
                    "Add pool_pre_ping=True to create_async_engine(). "
                    "Overhead is ~1ms per connection checkout."
                ),
            )
        val = _get_constant_value(pre_ping_val)
        if val is False:
            return Finding(
                rule_id="DB-01",
                severity=Severity.MEDIUM,
                title="pool_pre_ping explicitly disabled",
                description=(
                    "pool_pre_ping=False was explicitly set. Stale connections "
                    "will not be detected before checkout, leading to request "
                    "failures after database restarts or network interruptions."
                ),
                file_path=str(filepath),
                line_number=node.lineno,
                fix_suggestion="Change to pool_pre_ping=True.",
            )

    return None


def _check_db02_pool_exceeds_max(
    tree: ast.AST, source: str, filepath: Path,
) -> Finding | None:
    """DB-02: pool_size * workers may exceed PostgreSQL max_connections."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolve_call_name(node)
        if call_name not in ("create_async_engine", "create_engine"):
            continue

        pool_size_val = _get_constant_value(_get_keyword_value(node, "pool_size"))
        max_overflow_val = _get_constant_value(
            _get_keyword_value(node, "max_overflow"),
        )

        if not isinstance(pool_size_val, int):
            continue

        max_overflow = max_overflow_val if isinstance(max_overflow_val, int) else 10
        per_process = pool_size_val + max_overflow

        # Look for worker count in the file
        worker_count = 1
        worker_match = re.search(
            r"workers?\s*[:=]\s*(\d+)", source, re.IGNORECASE,
        )
        if worker_match:
            worker_count = int(worker_match.group(1))

        total = per_process * worker_count

        if total > 80:
            return Finding(
                rule_id="DB-02",
                severity=Severity.HIGH,
                title=(
                    f"Connection pool may exceed PostgreSQL max_connections: "
                    f"{per_process}/process x {worker_count} workers = {total}"
                ),
                description=(
                    f"pool_size={pool_size_val} + max_overflow={max_overflow} = "
                    f"{per_process} connections per process. With {worker_count} "
                    f"worker(s), that is {total} connections from a single pod. "
                    f"PostgreSQL default max_connections is 100. With multiple pods "
                    f"this will cause 'FATAL: too many connections' errors. "
                    f"Formula: total = workers * pods * (pool_size + max_overflow) "
                    f"<= max_connections - 20 (reserved)."
                ),
                file_path=str(filepath),
                line_number=node.lineno,
                fix_suggestion=(
                    "Reduce pool_size or max_overflow. For 4 workers, 3 pods, "
                    "max_connections=200: budget = (200-20)/(4*3) = 15/process. "
                    "Use pool_size=5, max_overflow=10."
                ),
            )

    return None


def _check_db03_expire_on_commit(
    tree: ast.AST, source: str, filepath: Path,
) -> Finding | None:
    """DB-03: async_sessionmaker without expire_on_commit=False."""
    # Only relevant if the file uses async patterns
    has_async = "async" in source.lower() and (
        "AsyncSession" in source
        or "async_sessionmaker" in source
        or "create_async_engine" in source
    )
    if not has_async:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolve_call_name(node)
        if call_name not in ("async_sessionmaker", "sessionmaker"):
            continue

        expire_val = _get_keyword_value(node, "expire_on_commit")
        if expire_val is None:
            return Finding(
                rule_id="DB-03",
                severity=Severity.HIGH,
                title="expire_on_commit not set to False in async session factory",
                description=(
                    "async_sessionmaker created without expire_on_commit=False. "
                    "In async mode, accessing attributes after commit triggers a "
                    "lazy load which raises MissingGreenlet (no event loop context "
                    "for I/O). SQLAlchemy docs: 'expire_on_commit should normally "
                    "be set to False when using asyncio.'"
                ),
                file_path=str(filepath),
                line_number=node.lineno,
                fix_suggestion=(
                    "Add expire_on_commit=False to async_sessionmaker(). "
                    "Use session.refresh(obj) when you need fresh data."
                ),
            )

        val = _get_constant_value(expire_val)
        if val is True:
            return Finding(
                rule_id="DB-03",
                severity=Severity.HIGH,
                title="expire_on_commit=True in async session factory",
                description=(
                    "expire_on_commit is explicitly True in an async session factory. "
                    "This will cause MissingGreenlet errors when accessing attributes "
                    "after commit in async code."
                ),
                file_path=str(filepath),
                line_number=node.lineno,
                fix_suggestion="Change to expire_on_commit=False.",
            )

    return None


def _check_db04_n_plus_one_risk(
    tree: ast.AST, source: str, filepath: Path,
) -> list[Finding]:
    """DB-04: Relationships without any loading strategy hint.

    Detects relationship() calls that don't specify lazy=, or don't
    appear near selectinload/joinedload usage. This is a heuristic --
    relationships with default lazy='select' are N+1 risks when accessed
    in loops.
    """
    findings: list[Finding] = []

    # Count relationship definitions without any loading hint
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolve_call_name(node)
        if call_name != "relationship":
            continue

        has_lazy = _get_keyword_value(node, "lazy") is not None
        has_loading = any(
            kw.arg in ("lazy", "viewonly", "uselist")
            for kw in node.keywords
        )

        if not has_lazy and not has_loading:
            # Check if the file mentions eager loading strategies at all
            has_strategies = any(
                s in source
                for s in (
                    "selectinload", "joinedload", "subqueryload",
                    "raiseload", "lazyload",
                )
            )

            if not has_strategies:
                findings.append(Finding(
                    rule_id="DB-04",
                    severity=Severity.MEDIUM,
                    title="Relationship without loading strategy (N+1 risk)",
                    description=(
                        "relationship() defined without lazy= parameter and no "
                        "eager loading strategies (selectinload, joinedload, "
                        "raiseload) found in this file. Default lazy='select' "
                        "triggers a separate SQL query per access in loops "
                        "(N+1 problem). In async mode, this raises MissingGreenlet."
                    ),
                    file_path=str(filepath),
                    line_number=node.lineno,
                    fix_suggestion=(
                        "Add lazy='selectin' to the relationship, or use "
                        "selectinload(Model.rel) in query options. For safety, "
                        "add raiseload('*') during development to catch all N+1."
                    ),
                ))

    return findings


def _check_db05_no_pool_recycle(
    tree: ast.AST, filepath: Path,
) -> Finding | None:
    """DB-05: No pool_recycle (connection timeout behind load balancers)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolve_call_name(node)
        if call_name not in ("create_async_engine", "create_engine"):
            continue

        recycle_val = _get_keyword_value(node, "pool_recycle")
        if recycle_val is None:
            return Finding(
                rule_id="DB-05",
                severity=Severity.LOW,
                title="No pool_recycle on database engine",
                description=(
                    "Engine created without pool_recycle. Connections in the pool "
                    "are kept open indefinitely. Behind load balancers (AWS ALB "
                    "idle timeout: 350s) or PgBouncer, idle connections may be "
                    "silently killed, causing request failures when they are "
                    "checked out from the pool."
                ),
                file_path=str(filepath),
                line_number=node.lineno,
                fix_suggestion=(
                    "Add pool_recycle=1800 (30 minutes) to create_async_engine(). "
                    "Set to less than your load balancer's idle timeout."
                ),
            )

    return None


def _check_db06_sync_engine(
    tree: ast.AST, source: str, filepath: Path,
) -> Finding | None:
    """DB-06: Sync create_engine used (blocks the event loop)."""
    # Skip files that don't look like they're in an async codebase
    has_async_context = (
        "async " in source
        or "asyncio" in source
        or "fastapi" in source.lower()
        or "uvicorn" in source.lower()
    )
    if not has_async_context:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolve_call_name(node)

        if call_name == "create_engine":
            # Check if it's from sqlalchemy (not some other library)
            return Finding(
                rule_id="DB-06",
                severity=Severity.CRITICAL,
                title="Synchronous create_engine used in async codebase",
                description=(
                    "create_engine() creates a synchronous engine that blocks "
                    "the event loop on every database call. In FastAPI/async code, "
                    "this serializes all requests through the DB — destroying "
                    "concurrency. Use create_async_engine() with asyncpg."
                ),
                file_path=str(filepath),
                line_number=node.lineno,
                fix_suggestion=(
                    "Replace: from sqlalchemy import create_engine\n"
                    "With: from sqlalchemy.ext.asyncio import create_async_engine\n"
                    "And change connection string to postgresql+asyncpg://..."
                ),
            )

    return None


def _check_db07_sql_injection(
    source: str, filepath: Path,
) -> list[Finding]:
    """DB-07: Raw SQL without parameterized queries (SQL injection risk).

    Detects f-strings and .format() calls inside text(), execute(), or
    raw SQL patterns. These are SQL injection vectors.
    """
    findings: list[Finding] = []

    # Patterns that indicate SQL string interpolation
    # Match: text(f"SELECT ... {var}") or execute(f"INSERT ... {var}")
    dangerous_patterns: list[tuple[str, re.Pattern[str]]] = [
        (
            "f-string in SQL",
            re.compile(
                r"""(?:text|execute|raw_connection)\s*\(\s*f["']""",
                re.IGNORECASE,
            ),
        ),
        (
            ".format() in SQL",
            re.compile(
                r"""(?:text|execute)\s*\(\s*["'][^"']*["']\s*\.format\s*\(""",
                re.IGNORECASE,
            ),
        ),
        (
            "% formatting in SQL",
            re.compile(
                r"""(?:text|execute)\s*\(\s*["'][^"']*%[sd][^"']*["']\s*%""",
                re.IGNORECASE,
            ),
        ),
        (
            "String concatenation in SQL",
            re.compile(
                r"""(?:text|execute)\s*\(\s*["'][^"']*["']\s*\+\s*""",
                re.IGNORECASE,
            ),
        ),
    ]

    for i, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        # Skip comments
        if stripped.startswith("#"):
            continue

        for desc, pattern in dangerous_patterns:
            if pattern.search(line):
                findings.append(Finding(
                    rule_id="DB-07",
                    severity=Severity.CRITICAL,
                    title=f"SQL injection risk: {desc}",
                    description=(
                        f"Raw SQL uses string interpolation ({desc}) which is "
                        f"vulnerable to SQL injection. An attacker can inject "
                        f"arbitrary SQL via user input."
                    ),
                    file_path=str(filepath),
                    line_number=i,
                    fix_suggestion=(
                        "Use parameterized queries: "
                        'text("SELECT * FROM users WHERE id = :id"), '
                        '{"id": user_id}'
                    ),
                ))
                break  # One finding per line

    return findings


def _check_db08_missing_fk_index(
    tree: ast.AST, source: str, filepath: Path,
) -> list[Finding]:
    """DB-08: Foreign key columns without explicit index.

    PostgreSQL does NOT automatically create indexes on foreign keys.
    Without an FK index, DELETE on the parent table triggers a sequential
    scan on the child table.
    """
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolve_call_name(node)
        if call_name != "mapped_column":
            continue

        # Check if this mapped_column has a ForeignKey argument
        has_fk = False
        for arg in node.args:
            if isinstance(arg, ast.Call):
                arg_name = _resolve_call_name(arg)
                if arg_name == "ForeignKey":
                    has_fk = True
                    break

        if not has_fk:
            continue

        # Check if index=True is set
        index_val = _get_keyword_value(node, "index")
        if index_val is None:
            val_is_true = False
        else:
            val_is_true = _get_constant_value(index_val) is True

        if not val_is_true:
            # Try to extract the column name from context
            col_name = "unknown"
            # Look at the assignment target
            parent_line = node.lineno
            lines = source.splitlines()
            if 0 < parent_line <= len(lines):
                line_text = lines[parent_line - 1]
                col_match = re.match(r"\s*(\w+)\s*[:=]", line_text)
                if col_match:
                    col_name = col_match.group(1)

            findings.append(Finding(
                rule_id="DB-08",
                severity=Severity.MEDIUM,
                title=f"No index on foreign key column: {col_name}",
                description=(
                    f"Foreign key column '{col_name}' does not have index=True. "
                    f"PostgreSQL does NOT auto-create indexes on foreign keys. "
                    f"Without an index, DELETE or UPDATE on the parent table "
                    f"triggers a sequential scan on this child table, which "
                    f"becomes very slow as the table grows."
                ),
                file_path=str(filepath),
                line_number=node.lineno,
                fix_suggestion=(
                    f"Add index=True: "
                    f"{col_name}: Mapped[int] = mapped_column("
                    f'ForeignKey("parent.id"), index=True)'
                ),
            ))

    return findings


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def verify_db_config(project_path: str) -> list[Finding]:
    """
    Statically analyze a FastAPI/SQLAlchemy project for database issues.

    Scans all Python files (excluding alembic/migrations) for 8 common
    database anti-patterns using AST analysis and regex matching. Returns
    a list of Finding objects, one per detected issue, sorted by severity
    (critical first).

    Args:
        project_path: Root directory of the project to analyze.

    Returns:
        List of Finding objects for each detected database issue.

    Example::

        findings = verify_db_config("/path/to/my-fastapi-project")
        for f in findings:
            print(f"[{f.severity.value}] {f.rule_id}: {f.title}")
        # [critical] DB-06: Synchronous create_engine used in async codebase
        # [critical] DB-07: SQL injection risk: f-string in SQL
        # [high] DB-03: expire_on_commit not set to False in async session
        # [medium] DB-08: No index on foreign key column: user_id
    """
    root = Path(project_path).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project path does not exist: {root}")

    py_files = _collect_python_files(root)
    findings: list[Finding] = []

    for filepath in py_files:
        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue

        # Parse AST (best-effort)
        tree: ast.AST | None = None
        try:
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError:
            continue

        if tree is None:
            continue

        # --- Per-file checks ---

        # DB-01: pool_pre_ping
        finding = _check_db01_no_pool_pre_ping(tree, filepath)
        if finding:
            findings.append(finding)

        # DB-02: pool exceeds max_connections
        finding = _check_db02_pool_exceeds_max(tree, source, filepath)
        if finding:
            findings.append(finding)

        # DB-03: expire_on_commit
        finding = _check_db03_expire_on_commit(tree, source, filepath)
        if finding:
            findings.append(finding)

        # DB-04: N+1 risk
        n1_findings = _check_db04_n_plus_one_risk(tree, source, filepath)
        findings.extend(n1_findings)

        # DB-05: pool_recycle
        finding = _check_db05_no_pool_recycle(tree, filepath)
        if finding:
            findings.append(finding)

        # DB-06: sync engine
        finding = _check_db06_sync_engine(tree, source, filepath)
        if finding:
            findings.append(finding)

        # DB-07: SQL injection
        injection_findings = _check_db07_sql_injection(source, filepath)
        findings.extend(injection_findings)

        # DB-08: FK without index
        fk_findings = _check_db08_missing_fk_index(tree, source, filepath)
        findings.extend(fk_findings)

    # Sort by severity (critical first)
    severity_order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
    }
    findings.sort(key=lambda f: severity_order.get(f.severity, 99))

    return findings
