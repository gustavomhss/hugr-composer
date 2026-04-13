"""
SKILL-001 Security Tool: Static analysis of security configuration.

Performs AST-based and regex-based analysis on a FastAPI project to detect
10 security anti-patterns: CORS wildcard with credentials, missing security
headers, no rate limiting, unbounded string fields, raw SQL, secrets in code,
no body size limit, debug mode in production, missing HTTPS/HSTS, and
exception details exposed to clients.
"""

from __future__ import annotations

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
    "site-packages", ".tox", "htmlcov",
}

# Security headers that MUST be present (OWASP 2025)
_REQUIRED_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=",
    "Content-Security-Policy": "default-src",
    "Referrer-Policy": "strict-origin",
    "Permissions-Policy": "camera=()",
    "X-XSS-Protection": "1",
}

# Patterns that indicate secrets hardcoded in source
_SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"""(?:api[_-]?key|apikey)\s*[=:]\s*['"][A-Za-z0-9_\-]{16,}['"]""", "API key literal"),
    (r"""(?:secret|password|passwd|pwd)\s*[=:]\s*['"][^'"]{8,}['"]""", "Secret/password literal"),
    (r"""(?:sk_live_|sk_test_|pk_live_|pk_test_)[A-Za-z0-9]{20,}""", "Stripe key"),
    (r"""(?:ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9]{36,}""", "GitHub token"),
    (r"""AKIA[0-9A-Z]{16}""", "AWS Access Key ID"),
    (r"""(?:postgres|mysql|mongodb)://[^'"{\s]+:[^'"{\s]+@""", "Database connection string with credentials"),
    (r"""Bearer\s+[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}""", "Hardcoded JWT"),
]

# SQL keywords for raw SQL detection
_SQL_KEYWORDS: set[str] = {
    "SELECT", "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "EXEC", "EXECUTE", "UNION", "WHERE", "FROM",
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


def _read_file_safe(filepath: Path) -> str:
    """Read file content, returning empty string on error."""
    try:
        return filepath.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return ""


def _parse_ast_safe(source: str, filepath: Path) -> ast.AST | None:
    """Parse source to AST, returning None on syntax errors."""
    try:
        return ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return None


def _resolve_call_name(node: ast.Call) -> str | None:
    """Resolve a dotted call name like ``app.add_middleware``."""
    func = node.func
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name):
            return f"{func.value.id}.{func.attr}"
        if isinstance(func.value, ast.Attribute) and isinstance(func.value.value, ast.Name):
            return f"{func.value.value.id}.{func.value.attr}.{func.attr}"
    if isinstance(func, ast.Name):
        return func.id
    return None


def _get_keyword_value(node: ast.Call, name: str) -> ast.expr | None:
    """Get the value of a keyword argument from a Call node."""
    for kw in node.keywords:
        if kw.arg == name:
            return kw.value
    return None


# ---------------------------------------------------------------------------
# SEC-01: CORS wildcard with credentials
# ---------------------------------------------------------------------------

def _check_sec01_cors_wildcard(
    tree: ast.AST, source: str, filepath: Path,
) -> list[Finding]:
    """SEC-01: Detect CORS wildcard origin with credentials enabled."""
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolve_call_name(node)

        # Check CORSMiddleware or add_middleware(CORSMiddleware, ...)
        is_cors = False
        if call_name == "CORSMiddleware":
            is_cors = True
        elif call_name and call_name.endswith(".add_middleware"):
            if node.args and isinstance(node.args[0], ast.Name):
                if node.args[0].id == "CORSMiddleware":
                    is_cors = True

        if not is_cors:
            continue

        # Check allow_origins for wildcard
        origins_node = _get_keyword_value(node, "allow_origins")
        has_wildcard = False
        if isinstance(origins_node, ast.List):
            for elt in origins_node.elts:
                if isinstance(elt, ast.Constant) and elt.value == "*":
                    has_wildcard = True
                    break

        # Check allow_credentials
        creds_node = _get_keyword_value(node, "allow_credentials")
        has_credentials = False
        if isinstance(creds_node, ast.Constant) and creds_node.value is True:
            has_credentials = True

        if has_wildcard and has_credentials:
            findings.append(Finding(
                rule_id="SEC-01",
                severity=Severity.CRITICAL,
                title="CORS wildcard origin with credentials enabled",
                description=(
                    "CORSMiddleware is configured with allow_origins=['*'] AND "
                    "allow_credentials=True. While browsers block this combination, "
                    "it signals a misconfiguration. Some frameworks silently fall back "
                    "to reflecting the Origin header, which allows any site to steal "
                    "credentials via cross-origin requests."
                ),
                file_path=str(filepath),
                line_number=node.lineno,
                fix_suggestion=(
                    "Replace allow_origins=['*'] with an explicit list of allowed "
                    "origins: allow_origins=['https://myapp.com']. Never use '*' "
                    "when allow_credentials=True."
                ),
            ))
        elif has_wildcard:
            findings.append(Finding(
                rule_id="SEC-01",
                severity=Severity.HIGH,
                title="CORS wildcard origin — consider restricting",
                description=(
                    "CORSMiddleware uses allow_origins=['*']. While credentials "
                    "are not enabled, this allows any website to make requests "
                    "to your API. This is acceptable only for truly public APIs "
                    "with no authentication."
                ),
                file_path=str(filepath),
                line_number=node.lineno,
                fix_suggestion=(
                    "If this API requires authentication or handles sensitive "
                    "data, replace '*' with explicit allowed origins."
                ),
            ))

        # Check for dynamic origin reflection pattern
        for line_no, line in enumerate(source.splitlines(), 1):
            if re.search(
                r'headers?\[.*["\']Access-Control-Allow-Origin["\'].*\]'
                r'\s*=\s*.*(?:request|req)\.',
                line,
            ):
                findings.append(Finding(
                    rule_id="SEC-01",
                    severity=Severity.CRITICAL,
                    title="Dynamic CORS origin reflection detected",
                    description=(
                        "The Origin header from the request is reflected directly "
                        "into Access-Control-Allow-Origin. This is functionally "
                        "equivalent to allow_origins=['*'] with credentials and "
                        "allows any website to steal user data."
                    ),
                    file_path=str(filepath),
                    line_number=line_no,
                    fix_suggestion=(
                        "Validate the Origin against an explicit allowlist before "
                        "reflecting it. Better: use CORSMiddleware with a fixed "
                        "allow_origins list."
                    ),
                ))

    return findings


# ---------------------------------------------------------------------------
# SEC-02: Missing security headers
# ---------------------------------------------------------------------------

def _check_sec02_missing_headers(
    tree: ast.AST, source: str, filepath: Path,
) -> list[Finding]:
    """SEC-02: Check each required security header is set."""
    findings: list[Finding] = []

    # Only check files that look like they contain middleware or app config
    source_lower = source.lower()
    is_relevant = any(kw in source_lower for kw in [
        "middleware", "securityheader", "response.headers", "x-content-type",
        "x-frame-options", "strict-transport", "content-security-policy",
    ])

    if not is_relevant:
        return findings

    for header_name, expected_fragment in _REQUIRED_HEADERS.items():
        # Check if the header is set anywhere in the file
        if header_name.lower() not in source_lower:
            findings.append(Finding(
                rule_id="SEC-02",
                severity=Severity.HIGH if header_name in (
                    "Strict-Transport-Security", "Content-Security-Policy",
                ) else Severity.MEDIUM,
                title=f"Missing security header: {header_name}",
                description=(
                    f"Security header '{header_name}' is not set in this middleware. "
                    f"Expected value containing: '{expected_fragment}'. "
                    f"Without this header, your API is vulnerable to the class of "
                    f"attacks this header prevents."
                ),
                file_path=str(filepath),
                fix_suggestion=(
                    f'Add: response.headers["{header_name}"] = "{expected_fragment}..."'
                ),
            ))

    return findings


# ---------------------------------------------------------------------------
# SEC-03: No rate limiting
# ---------------------------------------------------------------------------

def _check_sec03_no_rate_limiting(
    all_sources: dict[Path, str],
) -> list[Finding]:
    """SEC-03: Project-wide check for rate limiting presence."""
    has_rate_limiting = False
    rate_limit_indicators = [
        "slowapi", "SlowAPI", "Limiter", "limiter.limit",
        "fastapi_limiter", "RateLimitExceeded", "rate_limit",
        "throttle", "Throttle",
    ]

    for filepath, source in all_sources.items():
        for indicator in rate_limit_indicators:
            if indicator in source:
                has_rate_limiting = True
                break
        if has_rate_limiting:
            break

    if not has_rate_limiting:
        return [Finding(
            rule_id="SEC-03",
            severity=Severity.HIGH,
            title="No rate limiting detected in project",
            description=(
                "No rate limiting library or middleware was found in any project "
                "file. Without rate limiting, your API is vulnerable to brute "
                "force attacks, credential stuffing, and application-layer DoS. "
                "OWASP API Security #4: Unrestricted Resource Consumption."
            ),
            fix_suggestion=(
                "Install slowapi (pip install slowapi) and add rate limits: "
                "@limiter.limit('5/minute') on auth endpoints, "
                "default_limits=['200/minute'] globally. Use Redis backend "
                "for multi-worker deployments."
            ),
        )]

    return []


# ---------------------------------------------------------------------------
# SEC-04: String fields without max_length
# ---------------------------------------------------------------------------

def _check_sec04_unbounded_strings(
    tree: ast.AST, source: str, filepath: Path,
) -> list[Finding]:
    """SEC-04: Detect Pydantic string fields without max_length."""
    findings: list[Finding] = []

    # Quick check: only scan files that use Pydantic
    if "BaseModel" not in source and "pydantic" not in source:
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Check if class inherits from BaseModel
        is_model = any(
            (isinstance(base, ast.Name) and base.id == "BaseModel")
            or (isinstance(base, ast.Attribute) and base.attr == "BaseModel")
            for base in node.bases
        )
        if not is_model:
            continue

        for item in node.body:
            if not isinstance(item, ast.AnnAssign):
                continue
            if not item.annotation:
                continue

            # Check if annotation is str
            is_str = False
            ann = item.annotation
            if isinstance(ann, ast.Name) and ann.id == "str":
                is_str = True
            elif isinstance(ann, ast.Constant) and ann.value == "str":
                is_str = True
            # str | None
            elif isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
                if isinstance(ann.left, ast.Name) and ann.left.id == "str":
                    is_str = True

            if not is_str:
                continue

            # Check if Field() is used with max_length
            has_max_length = False
            if item.value and isinstance(item.value, ast.Call):
                call_name = _resolve_call_name(item.value)
                if call_name == "Field" or (call_name and call_name.endswith(".Field")):
                    for kw in item.value.keywords:
                        if kw.arg == "max_length":
                            has_max_length = True
                            break

            if not has_max_length:
                field_name = ""
                if isinstance(item.target, ast.Name):
                    field_name = item.target.id

                findings.append(Finding(
                    rule_id="SEC-04",
                    severity=Severity.MEDIUM,
                    title=f"String field without max_length: {node.name}.{field_name}",
                    description=(
                        f"Field '{field_name}' in model '{node.name}' is type str "
                        f"without max_length constraint. An attacker can send megabytes "
                        f"of data in this field, causing memory exhaustion, log bloat, "
                        f"and database storage abuse."
                    ),
                    file_path=str(filepath),
                    line_number=item.lineno,
                    fix_suggestion=(
                        f"Add max_length: {field_name}: str = Field(max_length=N). "
                        f"Common limits: name=200, email=254, description=5000, "
                        f"slug=100, bio=1000."
                    ),
                ))

    return findings


# ---------------------------------------------------------------------------
# SEC-05: Raw SQL (f-string with SQL keywords)
# ---------------------------------------------------------------------------

def _check_sec05_raw_sql(
    tree: ast.AST, source: str, filepath: Path,
) -> list[Finding]:
    """SEC-05: Detect f-strings or string concatenation containing SQL keywords."""
    findings: list[Finding] = []

    for node in ast.walk(tree):
        # Check f-strings (JoinedStr in AST)
        if isinstance(node, ast.JoinedStr):
            # Reconstruct parts to check for SQL
            static_parts = []
            has_variables = False
            for val in node.values:
                if isinstance(val, ast.Constant):
                    static_parts.append(str(val.value))
                elif isinstance(val, ast.FormattedValue):
                    has_variables = True

            if has_variables:
                combined = " ".join(static_parts).upper()
                found_keywords = [kw for kw in _SQL_KEYWORDS if kw in combined]
                if len(found_keywords) >= 2:
                    findings.append(Finding(
                        rule_id="SEC-05",
                        severity=Severity.CRITICAL,
                        title="Raw SQL with f-string interpolation",
                        description=(
                            f"f-string contains SQL keywords ({', '.join(found_keywords[:4])}) "
                            f"with variable interpolation. This is a SQL injection "
                            f"vulnerability. Any user input in the variables becomes "
                            f"executable SQL."
                        ),
                        file_path=str(filepath),
                        line_number=getattr(node, "lineno", 0),
                        fix_suggestion=(
                            "Use parameterised queries: "
                            'text("SELECT * FROM t WHERE id = :id"), {"id": val}. '
                            "Never use f-strings, .format(), or concatenation with SQL."
                        ),
                    ))

        # Check string.format() with SQL
        if isinstance(node, ast.Call):
            call_name = _resolve_call_name(node)
            if call_name and call_name.endswith(".format"):
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Constant):
                    template = str(node.func.value.value).upper()
                    found_keywords = [kw for kw in _SQL_KEYWORDS if kw in template]
                    if len(found_keywords) >= 2:
                        findings.append(Finding(
                            rule_id="SEC-05",
                            severity=Severity.CRITICAL,
                            title="Raw SQL with .format() interpolation",
                            description=(
                                f"String.format() contains SQL keywords "
                                f"({', '.join(found_keywords[:4])}). This is a SQL "
                                f"injection vulnerability."
                            ),
                            file_path=str(filepath),
                            line_number=node.lineno,
                            fix_suggestion=(
                                "Use parameterised queries with bind parameters. "
                                "Never use .format() with SQL strings."
                            ),
                        ))

    # Also check for string concatenation patterns with SQL keywords via regex
    for line_no, line in enumerate(source.splitlines(), 1):
        # Pattern: "SELECT..." + variable or f"SELECT...{var}"
        if re.search(
            r'''['"](?:\s*(?:SELECT|INSERT|UPDATE|DELETE|DROP)\s).*['"]\s*\+\s*\w''',
            line,
            re.IGNORECASE,
        ):
            findings.append(Finding(
                rule_id="SEC-05",
                severity=Severity.CRITICAL,
                title="SQL string concatenation detected",
                description=(
                    "A SQL string is concatenated with a variable using +. "
                    "This is a classic SQL injection vector."
                ),
                file_path=str(filepath),
                line_number=line_no,
                fix_suggestion=(
                    "Use parameterised queries: "
                    'text("SELECT ... WHERE id = :id"), {"id": val}'
                ),
            ))

    return findings


# ---------------------------------------------------------------------------
# SEC-06: Secrets in code
# ---------------------------------------------------------------------------

def _check_sec06_secrets_in_code(
    source: str, filepath: Path,
) -> list[Finding]:
    """SEC-06: Detect hardcoded secrets, API keys, and connection strings."""
    findings: list[Finding] = []

    # Skip test files and config examples
    fname = filepath.name.lower()
    if fname.startswith("test_") or fname.endswith("_test.py"):
        return findings
    if "example" in fname or "sample" in fname or "fixture" in fname:
        return findings

    for line_no, line in enumerate(source.splitlines(), 1):
        # Skip comments
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        for pattern, description in _SECRET_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                # Mask the actual value in the finding
                masked_line = re.sub(
                    r"""['"][A-Za-z0-9_\-/:.@]{10,}['"]""",
                    '"***REDACTED***"',
                    line.strip(),
                )
                findings.append(Finding(
                    rule_id="SEC-06",
                    severity=Severity.CRITICAL,
                    title=f"Possible secret in source code: {description}",
                    description=(
                        f"Line appears to contain a hardcoded {description}. "
                        f"Secrets in source code are exposed to anyone with "
                        f"repository access and persist in git history forever. "
                        f"Masked line: {masked_line[:200]}"
                    ),
                    file_path=str(filepath),
                    line_number=line_no,
                    fix_suggestion=(
                        "Move to environment variable via pydantic-settings. "
                        "Use: settings.api_key loaded from .env (not committed). "
                        "In production, inject via Kubernetes Secrets or Vault."
                    ),
                ))
                break  # One finding per line is enough

    return findings


# ---------------------------------------------------------------------------
# SEC-07: No request body size limit
# ---------------------------------------------------------------------------

def _check_sec07_no_body_limit(
    all_sources: dict[Path, str],
) -> list[Finding]:
    """SEC-07: Project-wide check for request body size limiting."""
    has_body_limit = False
    indicators = [
        "RequestSizeLimitMiddleware", "content-length", "Content-Length",
        "max_body_size", "body_limit", "client_max_body_size",
        "LimitRequestBody", "413",
    ]

    for filepath, source in all_sources.items():
        for indicator in indicators:
            if indicator in source:
                has_body_limit = True
                break
        if has_body_limit:
            break

    if not has_body_limit:
        return [Finding(
            rule_id="SEC-07",
            severity=Severity.HIGH,
            title="No request body size limit detected",
            description=(
                "No middleware or configuration was found to limit request body "
                "size. FastAPI reads the entire body into memory by default. "
                "An attacker can send gigabytes of data to cause OOM crash. "
                "Uvicorn has no built-in body size limit."
            ),
            fix_suggestion=(
                "Add a RequestSizeLimitMiddleware that checks Content-Length "
                "and returns 413 for oversized requests. Default: 1MB for JSON "
                "APIs, 10MB for file upload endpoints. Alternatively, configure "
                "Nginx with: client_max_body_size 1m;"
            ),
        )]

    return []


# ---------------------------------------------------------------------------
# SEC-08: Debug mode in production config
# ---------------------------------------------------------------------------

def _check_sec08_debug_mode(
    tree: ast.AST, source: str, filepath: Path,
) -> list[Finding]:
    """SEC-08: Detect debug=True without environment guard."""
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolve_call_name(node)

        # Check FastAPI(debug=True) or App(debug=True)
        if call_name in ("FastAPI", "Starlette"):
            debug_node = _get_keyword_value(node, "debug")
            if isinstance(debug_node, ast.Constant) and debug_node.value is True:
                findings.append(Finding(
                    rule_id="SEC-08",
                    severity=Severity.CRITICAL,
                    title="Debug mode hardcoded to True",
                    description=(
                        "FastAPI is initialised with debug=True as a constant. "
                        "In production, this exposes full stack traces to clients "
                        "and may enable the interactive debugger (code execution). "
                        "Debug mode must be controlled by environment variable."
                    ),
                    file_path=str(filepath),
                    line_number=node.lineno,
                    fix_suggestion=(
                        'Use: debug=os.getenv("DEBUG", "false").lower() == "true" '
                        "or debug=settings.debug with pydantic-settings."
                    ),
                ))

        # Check docs/redoc/openapi exposed unconditionally
        if call_name in ("FastAPI",):
            for attr in ("docs_url", "redoc_url", "openapi_url"):
                val = _get_keyword_value(node, attr)
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    # Docs are exposed — check if there's an environment guard
                    # Look for environment/settings reference in same scope
                    source_lines = source.splitlines()
                    start = max(0, node.lineno - 10)
                    end = min(len(source_lines), node.end_lineno + 5 if node.end_lineno else node.lineno + 10)
                    context = "\n".join(source_lines[start:end])
                    if "environment" not in context.lower() and "production" not in context.lower():
                        findings.append(Finding(
                            rule_id="SEC-08",
                            severity=Severity.MEDIUM,
                            title=f"API docs ({attr}) exposed without environment guard",
                            description=(
                                f"'{attr}' is set to a string constant without checking "
                                f"the environment. In production, API documentation "
                                f"exposes your entire API surface to attackers for "
                                f"reconnaissance."
                            ),
                            file_path=str(filepath),
                            line_number=node.lineno,
                            fix_suggestion=(
                                f"Set {attr}=None in production: "
                                f'{attr}="/docs" if ENVIRONMENT != "production" else None'
                            ),
                        ))

    return findings


# ---------------------------------------------------------------------------
# SEC-09: Missing HTTPS redirect / HSTS
# ---------------------------------------------------------------------------

def _check_sec09_no_https(
    all_sources: dict[Path, str],
) -> list[Finding]:
    """SEC-09: Project-wide check for HTTPS enforcement."""
    has_https_redirect = False
    has_hsts = False

    indicators_redirect = [
        "HTTPSRedirectMiddleware", "https_redirect", "force_https",
        "redirect_http", "ssl_redirect",
    ]
    indicators_hsts = [
        "Strict-Transport-Security", "strict-transport-security",
        "hsts", "HSTS",
    ]

    for filepath, source in all_sources.items():
        for indicator in indicators_redirect:
            if indicator in source:
                has_https_redirect = True
        for indicator in indicators_hsts:
            if indicator in source:
                has_hsts = True

    findings: list[Finding] = []

    if not has_hsts:
        findings.append(Finding(
            rule_id="SEC-09",
            severity=Severity.HIGH,
            title="No HSTS header detected in project",
            description=(
                "No Strict-Transport-Security header was found. Without HSTS, "
                "browsers allow HTTP connections to your domain, enabling SSL "
                "stripping attacks on the first request. After the first HTTPS "
                "visit, HSTS forces all subsequent connections to use HTTPS."
            ),
            fix_suggestion=(
                "Add to your security headers middleware: "
                'response.headers["Strict-Transport-Security"] = '
                '"max-age=31536000; includeSubDomains; preload"'
            ),
        ))

    return findings


# ---------------------------------------------------------------------------
# SEC-10: Exception details exposed to client
# ---------------------------------------------------------------------------

def _check_sec10_exception_exposure(
    tree: ast.AST, source: str, filepath: Path,
) -> list[Finding]:
    """SEC-10: Detect patterns where exception details leak to responses."""
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolve_call_name(node)

        if call_name != "HTTPException":
            continue

        # Check detail= keyword
        detail_node = _get_keyword_value(node, "detail")
        if detail_node is None and len(node.args) >= 2:
            detail_node = node.args[1]

        if detail_node is None:
            continue

        # Detect str(exc), repr(exc), str(e), repr(e), traceback.format_exc()
        is_leaking = False
        leak_description = ""

        if isinstance(detail_node, ast.Call):
            inner_name = _resolve_call_name(detail_node)
            if inner_name in ("str", "repr"):
                # str(e) or repr(exc)
                if detail_node.args and isinstance(detail_node.args[0], ast.Name):
                    is_leaking = True
                    leak_description = f"{inner_name}({detail_node.args[0].id})"
            elif inner_name in ("traceback.format_exc", "format_exc"):
                is_leaking = True
                leak_description = "traceback.format_exc()"

        # Check f-string with exception variable: f"Error: {e}"
        if isinstance(detail_node, ast.JoinedStr):
            for val in detail_node.values:
                if isinstance(val, ast.FormattedValue):
                    if isinstance(val.value, ast.Name):
                        # Check if the variable name looks like an exception
                        if val.value.id in ("e", "exc", "err", "error", "exception"):
                            is_leaking = True
                            leak_description = f"f-string with {{{val.value.id}}}"

        if is_leaking:
            # Check if this is inside an except handler (expected context)
            # The finding is about RETURNING the details to client, not catching
            findings.append(Finding(
                rule_id="SEC-10",
                severity=Severity.HIGH,
                title="Exception details exposed in HTTP response",
                description=(
                    f"HTTPException detail contains {leak_description}. "
                    f"This leaks internal information (table names, file paths, "
                    f"library versions, stack traces) to the client. Attackers use "
                    f"this for reconnaissance to target specific vulnerabilities."
                ),
                file_path=str(filepath),
                line_number=node.lineno,
                fix_suggestion=(
                    "Return a generic message to the client: "
                    'detail="Internal server error". '
                    "Log the actual error with an error_id for correlation: "
                    'logger.error("Error [%s]: %s", error_id, str(exc), exc_info=True)'
                ),
            ))

    return findings


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def verify_security_config(
    project_path: str,
    skip_rules: list[str] | None = None,
) -> list[Finding]:
    """
    Run all 10 security checks against a FastAPI project.

    Performs AST-based and regex-based static analysis to detect security
    misconfigurations and vulnerabilities. Each check corresponds to a rule
    ID (SEC-01 through SEC-10).

    Rules:
        SEC-01: CORS wildcard with credentials / origin reflection
        SEC-02: Missing security headers (7 OWASP recommended headers)
        SEC-03: No rate limiting in the entire project
        SEC-04: Pydantic string fields without max_length
        SEC-05: Raw SQL via f-string, .format(), or concatenation
        SEC-06: Hardcoded secrets (API keys, passwords, tokens)
        SEC-07: No request body size limit middleware
        SEC-08: Debug mode enabled without environment guard
        SEC-09: Missing HTTPS redirect or HSTS header
        SEC-10: Exception details (str(e), traceback) exposed to client

    Args:
        project_path: Root directory of the FastAPI project.
        skip_rules: List of rule IDs to skip (e.g. ["SEC-04", "SEC-06"]).

    Returns:
        List of Finding objects, sorted by severity (critical first).

    Example::

        findings = verify_security_config("/path/to/myproject")
        critical = [f for f in findings if f.severity == Severity.CRITICAL]
        print(f"{len(critical)} critical issues found")
        for f in findings:
            print(f"[{f.rule_id}] {f.severity.value}: {f.title}")
    """
    root = Path(project_path)
    if not root.is_dir():
        return [Finding(
            rule_id="SEC-00",
            severity=Severity.CRITICAL,
            title="Project path does not exist",
            description=f"The path '{project_path}' is not a valid directory.",
            fix_suggestion="Provide a valid directory path to a FastAPI project.",
        )]

    skip = set(skip_rules or [])
    python_files = _collect_python_files(root)

    if not python_files:
        return [Finding(
            rule_id="SEC-00",
            severity=Severity.LOW,
            title="No Python files found",
            description=f"No .py files found in '{project_path}'.",
            fix_suggestion="Check the project path.",
        )]

    # Read and parse all files
    all_sources: dict[Path, str] = {}
    parsed: dict[Path, ast.AST] = {}
    for fp in python_files:
        source = _read_file_safe(fp)
        if source:
            all_sources[fp] = source
            tree = _parse_ast_safe(source, fp)
            if tree:
                parsed[fp] = tree

    findings: list[Finding] = []

    # Per-file checks
    for filepath, source in all_sources.items():
        tree = parsed.get(filepath)
        if not tree:
            continue

        if "SEC-01" not in skip:
            findings.extend(_check_sec01_cors_wildcard(tree, source, filepath))
        if "SEC-02" not in skip:
            findings.extend(_check_sec02_missing_headers(tree, source, filepath))
        if "SEC-04" not in skip:
            findings.extend(_check_sec04_unbounded_strings(tree, source, filepath))
        if "SEC-05" not in skip:
            findings.extend(_check_sec05_raw_sql(tree, source, filepath))
        if "SEC-06" not in skip:
            findings.extend(_check_sec06_secrets_in_code(source, filepath))
        if "SEC-08" not in skip:
            findings.extend(_check_sec08_debug_mode(tree, source, filepath))
        if "SEC-10" not in skip:
            findings.extend(_check_sec10_exception_exposure(tree, source, filepath))

    # Project-wide checks
    if "SEC-03" not in skip:
        findings.extend(_check_sec03_no_rate_limiting(all_sources))
    if "SEC-07" not in skip:
        findings.extend(_check_sec07_no_body_limit(all_sources))
    if "SEC-09" not in skip:
        findings.extend(_check_sec09_no_https(all_sources))

    # Sort by severity: CRITICAL > HIGH > MEDIUM > LOW
    severity_order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
    }
    findings.sort(key=lambda f: (severity_order.get(f.severity, 99), f.rule_id))

    return findings
