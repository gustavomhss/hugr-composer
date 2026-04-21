"""
SKILL-001 Core Tool: Static AST Analysis for FastAPI Projects.

Scans a FastAPI project for 8 production-readiness patterns, detects
sync-in-async violations, deprecated patterns, and pool misconfigurations.

FP fixes applied (v2):
  FP-001: Only pybreaker/circuitbreaker count as circuit breaker.
  FP-002: Health check regex matches /health, /api/health, /health-check.
  FP-003: Files in tests/, examples/, docs/ excluded from boolean flags.
  FP-004: has_graceful_shutdown checked independently (not cascaded from lifespan).
  FP-005: __init__.py files skipped for content analysis.
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_meta_analyze_project_v2',
    'description': '[Legacy v2] AST-based analysis of 8 core patterns. Use fastapi_analyze for the 35-check v3 audit.',
    'tags': ['legacy', 'verify'],
    'entry': 'mcp_fastapi_analyze_project_v2',
    'annotations': {'readOnlyHint': True},
}

import ast
import os
import re
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.models import (
    CoreAnalysisResult,
    DeprecatedPattern,
    Finding,
    HealthLevel,
    PoolAnalysis,
    Severity,
    SyncInAsyncViolation,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_EXCLUDE_DIRS: set[str] = {
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "site-packages",
}

# Directories whose files should NOT influence boolean flags (FP-003)
_NON_PRODUCTION_DIRS: set[str] = {"tests", "test", "examples", "docs", "benchmarks"}

# Blocking calls that must never appear inside ``async def`` bodies
_SYNC_BLOCKING_CALLS: dict[str, str] = {
    "requests.get": "Use httpx.AsyncClient().get()",
    "requests.post": "Use httpx.AsyncClient().post()",
    "requests.put": "Use httpx.AsyncClient().put()",
    "requests.delete": "Use httpx.AsyncClient().delete()",
    "requests.patch": "Use httpx.AsyncClient().patch()",
    "requests.head": "Use httpx.AsyncClient().head()",
    "requests.request": "Use httpx.AsyncClient().request()",
    "time.sleep": "Use asyncio.sleep()",
    "subprocess.run": "Use asyncio.create_subprocess_exec()",
    "subprocess.call": "Use asyncio.create_subprocess_exec()",
    "subprocess.check_output": "Use asyncio.create_subprocess_exec()",
    "subprocess.check_call": "Use asyncio.create_subprocess_exec()",
    "os.system": "Use asyncio.create_subprocess_shell()",
}

# Required security headers (for source-level detection)
_SECURITY_HEADERS: list[str] = [
    "X-Content-Type-Options",
    "X-Frame-Options",
    "X-XSS-Protection",
    "Strict-Transport-Security",
    "Referrer-Policy",
    "Permissions-Policy",
]

# Health-check endpoint patterns per level
_HEALTH_PATTERNS: dict[HealthLevel, list[re.Pattern[str]]] = {
    HealthLevel.LIVENESS: [
        re.compile(r"""["']/healthz["']"""),
        re.compile(r"""["']/health["']"""),
        re.compile(r"""["']/api/health["']"""),
        re.compile(r"""["']/health-check["']"""),
    ],
    HealthLevel.READINESS: [
        re.compile(r"""["']/readyz["']"""),
        re.compile(r"""["']/ready["']"""),
        re.compile(r"""["']/api/ready["']"""),
    ],
    HealthLevel.STARTUP: [
        re.compile(r"""["']/startupz["']"""),
        re.compile(r"""["']/startup["']"""),
        re.compile(r"""["']/api/startup["']"""),
    ],
}

# Pool configuration keys to extract from SQLAlchemy create_engine calls
_POOL_KEYS: list[str] = [
    "pool_size",
    "max_overflow",
    "pool_recycle",
    "pool_pre_ping",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_python_files(
    root: Path,
    exclude_dirs: set[str],
) -> list[Path]:
    """Walk *root* and return .py files not in excluded directories."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded directories in-place
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        dp = Path(dirpath)
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(dp / fn)
    return files


def _is_non_production(filepath: Path, project_root: Path) -> bool:
    """Return True if *filepath* lives under a non-production directory (FP-003)."""
    try:
        rel = filepath.relative_to(project_root)
    except ValueError:
        return False
    parts = rel.parts
    return any(p.lower() in _NON_PRODUCTION_DIRS for p in parts)


def _is_init_file(filepath: Path) -> bool:
    """Return True for __init__.py (FP-005)."""
    return filepath.name == "__init__.py"


def _should_skip_for_content(filepath: Path, project_root: Path) -> bool:
    """Return True if the file should be skipped for content-based analysis."""
    return _is_non_production(filepath, project_root) or _is_init_file(filepath)


# ---------------------------------------------------------------------------
# AST-level detectors
# ---------------------------------------------------------------------------


def _detect_sync_in_async(tree: ast.AST, filepath: Path) -> list[SyncInAsyncViolation]:
    """Find blocking calls inside ``async def`` bodies."""
    violations: list[SyncInAsyncViolation] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for child in ast.walk(node):
            call_name: str | None = None
            if isinstance(child, ast.Call):
                call_name = _resolve_call_name(child)
            if call_name and call_name in _SYNC_BLOCKING_CALLS:
                violations.append(
                    SyncInAsyncViolation(
                        file_path=str(filepath),
                        line_number=child.lineno,
                        function_name=node.name,
                        blocking_call=call_name,
                    )
                )
    return violations


def _resolve_call_name(node: ast.Call) -> str | None:
    """Resolve a dotted call name like ``requests.get``."""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    if isinstance(func, ast.Name):
        return func.id
    return None


def _detect_deprecated_on_event(tree: ast.AST, filepath: Path) -> list[DeprecatedPattern]:
    """Detect ``@app.on_event("startup"/"shutdown")`` decorators."""
    deprecated: list[DeprecatedPattern] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            if not isinstance(dec.func, ast.Attribute):
                continue
            if dec.func.attr != "on_event":
                continue
            if dec.args and isinstance(dec.args[0], ast.Constant):
                event_name = dec.args[0].value
                if event_name in ("startup", "shutdown"):
                    deprecated.append(
                        DeprecatedPattern(
                            file_path=str(filepath),
                            line_number=dec.lineno,
                            pattern=f'@app.on_event("{event_name}")',
                            replacement="Use lifespan context manager (asynccontextmanager)",
                        )
                    )
    return deprecated


def _detect_pool_config(tree: ast.AST) -> PoolAnalysis | None:
    """Extract SQLAlchemy pool configuration from create_engine / create_async_engine calls."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolve_call_name(node)
        if call_name and "create" in call_name and "engine" in call_name.lower():
            pass  # matched
        elif isinstance(node.func, ast.Name) and node.func.id in (
            "create_engine",
            "create_async_engine",
        ):
            pass  # matched
        elif isinstance(node.func, ast.Attribute) and node.func.attr in (
            "create_engine",
            "create_async_engine",
        ):
            pass  # matched
        else:
            continue

        kwargs: dict[str, object] = {}
        for kw in node.keywords:
            if kw.arg in _POOL_KEYS and isinstance(kw.value, ast.Constant):
                kwargs[kw.arg] = kw.value.value

        if not kwargs:
            continue

        pool_size = kwargs.get("pool_size")
        max_overflow = kwargs.get("max_overflow")
        estimated_max: int | None = None
        exceeds: bool | None = None
        if isinstance(pool_size, int) and isinstance(max_overflow, int):
            estimated_max = pool_size + max_overflow
            # PostgreSQL default max_connections = 100
            exceeds = estimated_max > 100

        return PoolAnalysis(
            pool_size=pool_size if isinstance(pool_size, int) else None,
            max_overflow=max_overflow if isinstance(max_overflow, int) else None,
            pool_recycle=kwargs.get("pool_recycle") if isinstance(kwargs.get("pool_recycle"), int) else None,
            pool_pre_ping=kwargs.get("pool_pre_ping") if isinstance(kwargs.get("pool_pre_ping"), bool) else None,
            estimated_max_connections=estimated_max,
            exceeds_pg_max=exceeds,
        )

    return None


# ---------------------------------------------------------------------------
# Source-text detectors
# ---------------------------------------------------------------------------


def _check_lifespan(source: str) -> bool:
    """Check for asynccontextmanager + lifespan pattern."""
    has_acm = "asynccontextmanager" in source
    has_lifespan = "lifespan" in source
    return has_acm and has_lifespan


def _check_structured_logging(source: str) -> bool:
    """Check for structlog usage."""
    return "structlog" in source


def _check_correlation_id(source: str) -> bool:
    """Check for correlation ID pattern."""
    return "correlation" in source.lower()


def _check_health_level(source: str, level: HealthLevel) -> bool:
    """Check if any health endpoint pattern for *level* is present."""
    for pattern in _HEALTH_PATTERNS[level]:
        if pattern.search(source):
            return True
    return False


def _check_security_headers_in_source(source: str) -> bool:
    """Check for at least X-Content-Type-Options in source."""
    return "X-Content-Type-Options" in source


def _check_cors(source: str) -> tuple[bool, bool]:
    """Return (has_cors, cors_wildcard)."""
    has_cors = "CORSMiddleware" in source
    cors_wildcard = False
    if has_cors:
        # Look for allow_origins=["*"] patterns
        cors_wildcard = bool(
            re.search(r"""allow_origins\s*=\s*\[\s*["']\*["']\s*\]""", source)
        )
    return has_cors, cors_wildcard


def _check_graceful_shutdown(source: str, tree: ast.AST) -> bool:
    """
    Check for graceful shutdown independently (FP-004).

    Two valid signals:
    1. Explicit SIGTERM/signal handler
    2. Lifespan with teardown code (code after ``yield``)
    """
    # Check 1: SIGTERM / signal handler
    if "SIGTERM" in source or "signal.signal" in source:
        return True

    # Check 2: Lifespan with teardown code after yield
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        # Must be decorated with @asynccontextmanager AND have "lifespan" in name or body
        is_lifespan = "lifespan" in node.name
        if not is_lifespan:
            # Check if any decorator is asynccontextmanager
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name) and dec.id == "asynccontextmanager":
                    is_lifespan = True
                    break
                if isinstance(dec, ast.Attribute) and dec.attr == "asynccontextmanager":
                    is_lifespan = True
                    break
            if not is_lifespan:
                continue

        # Look for yield with statements after it (teardown code)
        found_yield = False
        for i, stmt in enumerate(node.body):
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Yield):
                found_yield = True
                # Check if there are statements after the yield
                if i < len(node.body) - 1:
                    return True
            # Also check for yield inside try/finally or async with
            if isinstance(stmt, ast.Try):
                for handler_body in [stmt.body, stmt.finalbody]:
                    for sub in handler_body:
                        if isinstance(sub, ast.Expr) and isinstance(sub.value, ast.Yield):
                            found_yield = True
                            # If there's a finally block with real code, that's teardown
                            if stmt.finalbody:
                                return True

    return False


def _check_pydantic_strict(source: str) -> bool | None:
    """Check for ConfigDict(strict=True) in Pydantic models."""
    if "ConfigDict" not in source:
        return None
    return bool(re.search(r"ConfigDict\s*\([^)]*strict\s*=\s*True", source))


def _extract_middleware_order(source: str) -> list[str]:
    """Extract middleware names in add_middleware order."""
    order: list[str] = []
    for m in re.finditer(r"add_middleware\s*\(\s*(\w+)", source):
        name = m.group(1)
        if name not in order:
            order.append(name)
    return order


# ---------------------------------------------------------------------------
# Findings generator
# ---------------------------------------------------------------------------


def _generate_findings(result: CoreAnalysisResult) -> list[Finding]:
    """Generate findings based on the analysis result."""
    findings: list[Finding] = []

    if not result.has_lifespan:
        findings.append(
            Finding(
                rule_id="CORE-001",
                severity=Severity.HIGH,
                title="Missing lifespan context manager",
                description=(
                    "No lifespan pattern found. Resources (DB pools, HTTP clients) "
                    "will leak on restart. Use @asynccontextmanager + lifespan=."
                ),
                fix_suggestion="Add lifespan context manager to FastAPI app initialization.",
            )
        )

    if not result.has_structured_logging:
        findings.append(
            Finding(
                rule_id="CORE-002",
                severity=Severity.MEDIUM,
                title="No structured logging (structlog)",
                description=(
                    "No structlog usage detected. Plain text logs are unusable in "
                    "production with multiple pods. Use structlog for JSON output."
                ),
                fix_suggestion="pip install structlog; configure structlog with JSON renderer.",
            )
        )

    if not result.has_correlation_id:
        findings.append(
            Finding(
                rule_id="CORE-003",
                severity=Severity.MEDIUM,
                title="No correlation ID",
                description=(
                    "No correlation ID middleware found. Impossible to trace requests "
                    "across services without a shared ID."
                ),
                fix_suggestion="Add CorrelationMiddleware that reads/generates X-Correlation-ID.",
            )
        )

    if not result.has_health_checks:
        findings.append(
            Finding(
                rule_id="CORE-004",
                severity=Severity.CRITICAL,
                title="No health check endpoints",
                description=(
                    "No health check endpoints found. Kubernetes cannot determine pod "
                    "health without /healthz, /readyz, /startupz endpoints."
                ),
                fix_suggestion="Add /healthz (liveness), /readyz (readiness), /startupz (startup).",
            )
        )
    else:
        missing_levels = {HealthLevel.LIVENESS, HealthLevel.READINESS, HealthLevel.STARTUP} - set(
            result.has_health_checks
        )
        if missing_levels:
            level_names = ", ".join(level.value for level in sorted(missing_levels, key=lambda l: l.value))
            findings.append(
                Finding(
                    rule_id="CORE-004a",
                    severity=Severity.MEDIUM,
                    title=f"Incomplete health checks (missing: {level_names})",
                    description=(
                        f"Health checks found but missing levels: {level_names}. "
                        "Kubernetes uses 3 different probes for 3 different failure modes."
                    ),
                    fix_suggestion=f"Add endpoints for missing levels: {level_names}.",
                )
            )

    if not result.has_security_headers:
        findings.append(
            Finding(
                rule_id="CORE-005",
                severity=Severity.HIGH,
                title="No security headers middleware",
                description=(
                    "No security headers detected. API is vulnerable to clickjacking, "
                    "MIME sniffing, and protocol downgrade attacks."
                ),
                fix_suggestion="Add SecurityHeadersMiddleware setting all 6 standard headers.",
            )
        )

    if result.cors_wildcard:
        findings.append(
            Finding(
                rule_id="CORE-006",
                severity=Severity.HIGH,
                title="CORS wildcard origin",
                description=(
                    'allow_origins=["*"] found. This disables CORS protection entirely '
                    "and is invalid with allow_credentials=True."
                ),
                fix_suggestion="Replace wildcard with specific origins list.",
            )
        )

    if not result.has_graceful_shutdown:
        findings.append(
            Finding(
                rule_id="CORE-007",
                severity=Severity.HIGH,
                title="No graceful shutdown handling",
                description=(
                    "No SIGTERM handler or lifespan teardown detected. In-flight "
                    "requests may be killed during deployment."
                ),
                fix_suggestion="Add SIGTERM signal handler or lifespan teardown (code after yield).",
            )
        )

    if result.pydantic_strict_inputs is False:
        findings.append(
            Finding(
                rule_id="CORE-008",
                severity=Severity.LOW,
                title="Pydantic models without strict mode",
                description=(
                    "Pydantic ConfigDict found but strict=True not set on input models. "
                    'Silent type coercion may accept "123" where int is expected.'
                ),
                fix_suggestion="Add ConfigDict(strict=True) to request/input models.",
            )
        )

    for violation in result.sync_in_async:
        findings.append(
            Finding(
                rule_id="CORE-009",
                severity=Severity.CRITICAL,
                title=f"Blocking call in async function: {violation.blocking_call}",
                description=(
                    f"{violation.blocking_call} in async def {violation.function_name} "
                    f"blocks the entire event loop. All concurrent requests stall."
                ),
                file_path=violation.file_path,
                line_number=violation.line_number,
                fix_suggestion=_SYNC_BLOCKING_CALLS.get(violation.blocking_call, "Use async alternative."),
            )
        )

    for dep in result.deprecated_patterns:
        findings.append(
            Finding(
                rule_id="CORE-010",
                severity=Severity.MEDIUM,
                title=f"Deprecated pattern: {dep.pattern}",
                description=(
                    f"{dep.pattern} is deprecated since FastAPI 0.93. "
                    "It will be removed in a future version."
                ),
                file_path=dep.file_path,
                line_number=dep.line_number,
                fix_suggestion=dep.replacement,
            )
        )

    if result.pool_config and result.pool_config.exceeds_pg_max:
        findings.append(
            Finding(
                rule_id="CORE-011",
                severity=Severity.HIGH,
                title="Connection pool may exceed PostgreSQL max_connections",
                description=(
                    f"pool_size={result.pool_config.pool_size} + "
                    f"max_overflow={result.pool_config.max_overflow} = "
                    f"{result.pool_config.estimated_max_connections} connections. "
                    "PostgreSQL default max_connections is 100."
                ),
                fix_suggestion="Reduce pool_size + max_overflow or increase pg max_connections.",
            )
        )

    if result.pool_config and result.pool_config.pool_pre_ping is not True:
        findings.append(
            Finding(
                rule_id="CORE-012",
                severity=Severity.MEDIUM,
                title="pool_pre_ping not enabled",
                description=(
                    "Without pool_pre_ping=True, stale connections from the pool "
                    "cause random query failures after DB restarts or network blips."
                ),
                fix_suggestion="Add pool_pre_ping=True to create_engine() call.",
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Score calculator
# ---------------------------------------------------------------------------

_SCORE_WEIGHTS: dict[str, int] = {
    "lifespan": 15,
    "structured_logging": 10,
    "correlation_id": 10,
    "health_checks": 15,
    "security_headers": 15,
    "cors_not_wildcard": 10,
    "graceful_shutdown": 15,
    "pydantic_strict": 5,
    "no_sync_in_async": 5,
}


def _calculate_score(result: CoreAnalysisResult) -> int:
    """Calculate a 0-100 production readiness score."""
    score = 0

    if result.has_lifespan:
        score += _SCORE_WEIGHTS["lifespan"]
    if result.has_structured_logging:
        score += _SCORE_WEIGHTS["structured_logging"]
    if result.has_correlation_id:
        score += _SCORE_WEIGHTS["correlation_id"]

    # Health checks: partial credit
    health_levels = len(result.has_health_checks)
    if health_levels >= 3:
        score += _SCORE_WEIGHTS["health_checks"]
    elif health_levels == 2:
        score += _SCORE_WEIGHTS["health_checks"] * 2 // 3
    elif health_levels == 1:
        score += _SCORE_WEIGHTS["health_checks"] // 3

    if result.has_security_headers:
        score += _SCORE_WEIGHTS["security_headers"]

    if result.has_cors and not result.cors_wildcard:
        score += _SCORE_WEIGHTS["cors_not_wildcard"]
    elif not result.has_cors:
        # No CORS at all — might be internal API, partial credit
        score += _SCORE_WEIGHTS["cors_not_wildcard"] // 2

    if result.has_graceful_shutdown:
        score += _SCORE_WEIGHTS["graceful_shutdown"]

    if result.pydantic_strict_inputs is True:
        score += _SCORE_WEIGHTS["pydantic_strict"]

    if not result.sync_in_async:
        score += _SCORE_WEIGHTS["no_sync_in_async"]

    return min(score, 100)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze_project(
    project_path: str,
    exclude_dirs: list[str] | None = None,
) -> CoreAnalysisResult:
    """
    Analyze a FastAPI project for production readiness.

    Scans all Python files (excluding non-production dirs for boolean flags)
    and returns a structured analysis result with score and findings.

    Args:
        project_path: Root directory of the FastAPI project.
        exclude_dirs: Additional directory names to exclude from scanning.

    Returns:
        CoreAnalysisResult with all detection results, score, and findings.
    """
    root = Path(project_path).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project path does not exist: {root}")

    excludes = _DEFAULT_EXCLUDE_DIRS.copy()
    if exclude_dirs:
        excludes.update(exclude_dirs)

    py_files = _collect_python_files(root, excludes)

    # Accumulators
    has_lifespan = False
    has_structured_logging = False
    has_correlation_id = False
    health_levels: set[HealthLevel] = set()
    has_security_headers = False
    has_cors = False
    cors_wildcard = False
    has_graceful_shutdown = False
    pydantic_strict: bool | None = None
    all_sync_violations: list[SyncInAsyncViolation] = []
    all_deprecated: list[DeprecatedPattern] = []
    pool_config: PoolAnalysis | None = None
    all_middleware_order: list[str] = []

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
            pass

        skip_for_flags = _should_skip_for_content(filepath, root)

        # --- AST-based detectors (always run, even in test files for violations) ---
        if tree is not None:
            # Sync-in-async: report everywhere (including tests — useful for examples)
            all_sync_violations.extend(_detect_sync_in_async(tree, filepath))

            # Deprecated: report everywhere
            all_deprecated.extend(_detect_deprecated_on_event(tree, filepath))

            # Pool config: only from production code
            if not skip_for_flags and pool_config is None:
                pool_config = _detect_pool_config(tree)

            # Graceful shutdown: only from production code (FP-004)
            if not skip_for_flags and not has_graceful_shutdown:
                has_graceful_shutdown = _check_graceful_shutdown(source, tree)

        # --- Source-text detectors (skip non-production for boolean flags, FP-003) ---
        if skip_for_flags:
            continue

        if not has_lifespan:
            has_lifespan = _check_lifespan(source)

        if not has_structured_logging:
            has_structured_logging = _check_structured_logging(source)

        if not has_correlation_id:
            has_correlation_id = _check_correlation_id(source)

        # Health checks — accumulate levels (FP-002: broader patterns)
        for level in HealthLevel:
            if level not in health_levels:
                if _check_health_level(source, level):
                    health_levels.add(level)

        if not has_security_headers:
            has_security_headers = _check_security_headers_in_source(source)

        file_cors, file_wildcard = _check_cors(source)
        if file_cors:
            has_cors = True
            if file_wildcard:
                cors_wildcard = True

        # Pydantic strict — track across all production files
        strict_check = _check_pydantic_strict(source)
        if strict_check is not None:
            if pydantic_strict is None:
                pydantic_strict = strict_check
            elif not strict_check:
                # At least one model without strict overrides
                pydantic_strict = False

        # Middleware order
        mw_order = _extract_middleware_order(source)
        if mw_order and not all_middleware_order:
            all_middleware_order = mw_order

    # Build result (without score/findings yet)
    result = CoreAnalysisResult(
        has_lifespan=has_lifespan,
        has_structured_logging=has_structured_logging,
        has_correlation_id=has_correlation_id,
        has_health_checks=sorted(health_levels, key=lambda l: l.value),
        has_security_headers=has_security_headers,
        has_cors=has_cors,
        cors_wildcard=cors_wildcard,
        has_graceful_shutdown=has_graceful_shutdown,
        sync_in_async=all_sync_violations,
        deprecated_patterns=all_deprecated,
        pool_config=pool_config,
        middleware_order=all_middleware_order,
        pydantic_strict_inputs=pydantic_strict,
        score=0,
        findings=[],
    )

    # Generate findings and score
    result.findings = _generate_findings(result)
    result.score = _calculate_score(result)

    return result


def mcp_fastapi_analyze_project_v2(project_path: str) -> dict:
    """MCP entry: [Legacy v2] AST-based analysis of 8 core patterns."""
    result = analyze_project(project_path)
    return result.model_dump(mode="json")
