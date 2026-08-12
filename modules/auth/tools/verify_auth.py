"""
SKILL-001 Auth Tool: Static analysis of auth code for security issues.

Performs AST-based analysis on a FastAPI project to detect 8 common auth
security anti-patterns: hardcoded JWT secrets, excessive token expiry,
missing refresh rotation, timing attack vulnerability, weak hashing,
missing rate limiting, no logout endpoint, and unbounded password length.
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_auth_verify_config',
    'description': 'AST-based static analysis of FastAPI auth code for 8 common security anti-patterns (hardcoded secrets, weak hashing, etc).',
    'tags': ['auth', 'security', 'verify'],
    'entry': 'verify_auth_config',
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
    "site-packages",
}

# Weak hashing algorithms that should never be used for passwords
_WEAK_HASH_PATTERNS: list[str] = [
    "md5", "sha1", "sha256", "sha512", "hashlib.md5", "hashlib.sha1",
    "hashlib.sha256", "hashlib.sha512",
]

# Safe hashing libraries/algorithms
_SAFE_HASH_PATTERNS: list[str] = [
    "argon2", "bcrypt", "scrypt", "pwdlib", "passlib",
]


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
    """Resolve a dotted call name like ``jwt.encode``."""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute):
        # e.g. hashlib.md5
        if isinstance(func.value.value, ast.Name):
            return f"{func.value.value.id}.{func.value.attr}.{func.attr}"
    if isinstance(func, ast.Name):
        return func.id
    return None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_auth01_hardcoded_secret(
    tree: ast.AST, source: str, filepath: Path,
) -> Finding | None:
    """AUTH-01: JWT secret not hardcoded (string literals in jwt.encode calls)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolve_call_name(node)
        if call_name not in ("jwt.encode", "encode"):
            continue

        # Check positional args and keyword args for string literal secrets
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if len(arg.value) > 0 and arg.value not in ("", "HS256", "RS256"):
                    return Finding(
                        rule_id="AUTH-01",
                        severity=Severity.CRITICAL,
                        title="Hardcoded JWT secret in jwt.encode() call",
                        description=(
                            "A string literal is passed directly to jwt.encode(). "
                            "Secrets must come from environment variables via settings, "
                            "never hardcoded in source code."
                        ),
                        file_path=str(filepath),
                        line_number=node.lineno,
                        fix_suggestion=(
                            "Use settings.jwt_secret from pydantic-settings. "
                            "Load via os.getenv('JWT_SECRET') in config.py."
                        ),
                    )

        for kw in node.keywords:
            if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str) and kw.value.value not in ("", "HS256"):
                    return Finding(
                        rule_id="AUTH-01",
                        severity=Severity.CRITICAL,
                        title="Hardcoded JWT secret in jwt.encode(key=...)",
                        description=(
                            "A string literal is passed as key= to jwt.encode(). "
                            "Secrets must come from environment variables."
                        ),
                        file_path=str(filepath),
                        line_number=node.lineno,
                        fix_suggestion="Use settings.jwt_secret from pydantic-settings.",
                    )

    # Also check for common hardcoded secret assignment patterns
    hardcoded_re = re.compile(
        r"""(?:SECRET_KEY|JWT_SECRET|jwt_secret)\s*[:=]\s*["']([^"']{4,})["']""",
        re.IGNORECASE,
    )
    for i, line in enumerate(source.splitlines(), 1):
        m = hardcoded_re.search(line)
        if m:
            value = m.group(1)
            # Allow template/placeholder values
            if value.upper() in ("CHANGE-ME-IN-PRODUCTION", "CHANGE-ME", ""):
                continue
            # Allow os.getenv patterns
            if "getenv" in line or "environ" in line or "settings." in line:
                continue
            return Finding(
                rule_id="AUTH-01",
                severity=Severity.CRITICAL,
                title="Hardcoded JWT secret in variable assignment",
                description=(
                    f"JWT secret appears to be hardcoded (line {i}). "
                    f"This secret will be visible in version control."
                ),
                file_path=str(filepath),
                line_number=i,
                fix_suggestion="Load from environment: os.getenv('JWT_SECRET').",
            )

    return None


def _check_auth02_token_expiry(
    tree: ast.AST, source: str, filepath: Path,
) -> Finding | None:
    """AUTH-02: Access token expiry <= 30 min."""
    # Look for timedelta assignments related to access tokens
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue

        # Check if this is an access token expiry assignment
        for target in node.targets:
            target_name = ""
            if isinstance(target, ast.Name):
                target_name = target.name if hasattr(target, "name") else target.id
            if not target_name:
                continue

            is_access_expiry = any(
                kw in target_name.upper()
                for kw in ("ACCESS", "TOKEN_EXPIRE", "TOKEN_EXPIRY", "ACCESS_EXPIRE")
            )
            if not is_access_expiry:
                continue

            # Check if it's a timedelta call
            if isinstance(node.value, ast.Call):
                call_name = _resolve_call_name(node.value)
                if call_name and "timedelta" in call_name.lower():
                    for kw in node.value.keywords:
                        if isinstance(kw.value, ast.Constant):
                            val = kw.value.value
                            if not isinstance(val, (int, float)):
                                continue
                            if kw.arg == "minutes" and val > 30:
                                return Finding(
                                    rule_id="AUTH-02",
                                    severity=Severity.HIGH,
                                    title=f"Access token expiry too long: {val} minutes",
                                    description=(
                                        f"Access token expires in {val} minutes. "
                                        f"OWASP recommends <= 30 minutes for access tokens. "
                                        f"Longer expiry increases the window of attack if "
                                        f"a token is leaked."
                                    ),
                                    file_path=str(filepath),
                                    line_number=node.lineno,
                                    fix_suggestion="Set access token expiry to 15-30 minutes.",
                                )
                            if kw.arg == "hours" and val >= 1:
                                return Finding(
                                    rule_id="AUTH-02",
                                    severity=Severity.HIGH,
                                    title=f"Access token expiry too long: {val} hours",
                                    description=(
                                        f"Access token expires in {val} hour(s). "
                                        f"OWASP recommends <= 30 minutes."
                                    ),
                                    file_path=str(filepath),
                                    line_number=node.lineno,
                                    fix_suggestion="Set access token expiry to 15-30 minutes.",
                                )
                            if kw.arg == "days" and val >= 1:
                                return Finding(
                                    rule_id="AUTH-02",
                                    severity=Severity.CRITICAL,
                                    title=f"Access token expiry dangerously long: {val} days",
                                    description=(
                                        f"Access token expires in {val} day(s). "
                                        f"This effectively disables token rotation."
                                    ),
                                    file_path=str(filepath),
                                    line_number=node.lineno,
                                    fix_suggestion="Set access token expiry to 15-30 minutes.",
                                )
    return None


def _check_auth03_refresh_rotation(source: str, filepath: Path) -> Finding | None:
    """AUTH-03: Refresh token rotation implemented (jti in token payload)."""
    has_refresh = "refresh" in source.lower()
    if not has_refresh:
        # No refresh tokens at all — separate concern, not flagged here
        return None

    has_jti = "jti" in source
    if not has_jti:
        return Finding(
            rule_id="AUTH-03",
            severity=Severity.HIGH,
            title="Refresh tokens without jti (no rotation support)",
            description=(
                "Refresh token logic found but no 'jti' (JWT ID) in token payload. "
                "Without jti, you cannot implement token rotation or detect token "
                "reuse after theft."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Add 'jti': str(uuid.uuid4()) to refresh token payload. "
                "Track used jtis in Redis/DB blocklist."
            ),
        )
    return None


def _check_auth04_timing_attack(source: str, filepath: Path) -> Finding | None:
    """AUTH-04: Timing attack prevention (DUMMY_HASH or constant-time compare)."""
    has_login = bool(re.search(r"def\s+(login|authenticate)", source, re.IGNORECASE))
    if not has_login:
        return None

    has_dummy = "DUMMY_HASH" in source or "dummy" in source.lower()
    has_constant_time = "hmac.compare_digest" in source or "secrets.compare_digest" in source
    has_verify_on_miss = bool(
        re.search(r"(user\s*(is\s*None|==\s*None|not\s)).*verify", source, re.DOTALL)
    )

    if has_dummy or has_constant_time or has_verify_on_miss:
        return None

    return Finding(
        rule_id="AUTH-04",
        severity=Severity.HIGH,
        title="No timing attack prevention in login",
        description=(
            "Login function found but no DUMMY_HASH or constant-time comparison. "
            "An attacker can enumerate valid emails by measuring response times: "
            "missing user returns fast, wrong password returns slow (due to hashing)."
        ),
        file_path=str(filepath),
        fix_suggestion=(
            "Create DUMMY_HASH = password_hash.hash('dummy') and run "
            "password_hash.verify(password, DUMMY_HASH) when user is None."
        ),
    )


def _check_auth05_password_hashing(source: str, filepath: Path) -> Finding | None:
    """AUTH-05: Password hashing uses argon2id or bcrypt (not MD5/SHA)."""
    # Check for weak hashing used in password context
    has_password_context = bool(
        re.search(r"password|passwd|pwd|hash", source, re.IGNORECASE)
    )
    if not has_password_context:
        return None

    source_lower = source.lower()

    # Check for weak algorithms in password context
    for weak in _WEAK_HASH_PATTERNS:
        if weak.lower() in source_lower:
            # Make sure it's actually used for passwords, not for checksums/IDs
            # Look for password-related usage near the weak hash
            for i, line in enumerate(source.splitlines(), 1):
                line_lower = line.lower()
                if weak.lower() in line_lower and any(
                    kw in line_lower for kw in ("password", "passwd", "pwd")
                ):
                    return Finding(
                        rule_id="AUTH-05",
                        severity=Severity.CRITICAL,
                        title=f"Weak hash algorithm for passwords: {weak}",
                        description=(
                            f"{weak} is not suitable for password hashing. "
                            f"It is fast by design, making brute force trivial. "
                            f"Use argon2id (via pwdlib) or bcrypt."
                        ),
                        file_path=str(filepath),
                        line_number=i,
                        fix_suggestion=(
                            "Use pwdlib: from pwdlib import PasswordHash; "
                            "ph = PasswordHash.recommended(); ph.hash(password)"
                        ),
                    )

    # Check that at least one safe hashing library is used
    has_safe = any(safe in source_lower for safe in _SAFE_HASH_PATTERNS)
    if not has_safe and has_password_context:
        # Only flag if there's actual hashing logic (not just a 'password' field)
        has_hash_call = bool(re.search(r"\.(hash|verify)\s*\(", source))
        if has_hash_call:
            return Finding(
                rule_id="AUTH-05",
                severity=Severity.HIGH,
                title="No recognized password hashing library",
                description=(
                    "Password hashing logic found but no recognized library "
                    "(argon2, bcrypt, scrypt, pwdlib, passlib) is imported."
                ),
                file_path=str(filepath),
                fix_suggestion=(
                    "Use pwdlib[argon2]: pip install pwdlib[argon2]; "
                    "from pwdlib import PasswordHash; ph = PasswordHash.recommended()"
                ),
            )

    return None


def _check_auth06_rate_limiting(source: str, filepath: Path) -> Finding | None:
    """AUTH-06: Rate limiting on login endpoint."""
    has_login_route = bool(re.search(r"""["']/auth/login["']""", source))
    if not has_login_route:
        return None

    has_limiter = (
        "limiter.limit" in source
        or "@limiter" in source
        or "RateLimiter" in source
        or "rate_limit" in source.lower()
        or "slowapi" in source.lower()
        or "throttle" in source.lower()
    )

    if not has_limiter:
        return Finding(
            rule_id="AUTH-06",
            severity=Severity.HIGH,
            title="No rate limiting on login endpoint",
            description=(
                "Login endpoint found but no rate limiting decorator or middleware. "
                "Without rate limiting, an attacker can perform brute force attacks "
                "at thousands of requests per minute."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Use slowapi: from slowapi import Limiter; "
                '@limiter.limit("5/minute") on the login route.'
            ),
        )
    return None


def _check_auth07_logout(all_sources: str) -> Finding | None:
    """AUTH-07: Logout/revocation endpoint exists."""
    has_logout = bool(re.search(r"""["']/auth/logout["']""", all_sources))
    has_revoke = bool(re.search(r"""["']/auth/revoke["']""", all_sources))
    has_signout = bool(re.search(r"""["']/auth/sign-?out["']""", all_sources))

    if has_logout or has_revoke or has_signout:
        return None

    # Only flag if there's actual auth logic present
    has_auth = "jwt" in all_sources.lower() or "oauth" in all_sources.lower()
    if not has_auth:
        return None

    return Finding(
        rule_id="AUTH-07",
        severity=Severity.MEDIUM,
        title="No logout or token revocation endpoint",
        description=(
            "JWT auth found but no logout/revoke endpoint. Users cannot "
            "invalidate their sessions. A leaked token remains valid until expiry."
        ),
        fix_suggestion=(
            "Add POST /auth/logout that adds the token jti to a blocklist. "
            "Use Redis with TTL matching the token's remaining lifetime."
        ),
    )


def _check_auth08_password_maxlength(
    tree: ast.AST, source: str, filepath: Path,
) -> Finding | None:
    """AUTH-08: Password max_length set (<= 128, prevents hash DoS)."""
    # Look for password Field definitions without max_length
    has_password_field = bool(re.search(r"password.*Field\s*\(", source, re.IGNORECASE))
    if not has_password_field:
        return None

    # Check if max_length is set on password fields
    has_maxlen = bool(
        re.search(r"password.*max_length\s*=", source, re.IGNORECASE)
    )

    if not has_maxlen:
        return Finding(
            rule_id="AUTH-08",
            severity=Severity.MEDIUM,
            title="No max_length on password field",
            description=(
                "Password field uses Field() but no max_length constraint. "
                "Without a cap, an attacker can send a 1MB password and argon2id "
                "will spend minutes hashing it — effective DoS."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Add max_length=128 to password fields: "
                "password: str = Field(min_length=8, max_length=128)"
            ),
        )

    # Check if max_length is too high
    maxlen_match = re.search(
        r"password.*max_length\s*=\s*(\d+)", source, re.IGNORECASE,
    )
    if maxlen_match:
        maxlen = int(maxlen_match.group(1))
        if maxlen > 128:
            return Finding(
                rule_id="AUTH-08",
                severity=Severity.MEDIUM,
                title=f"Password max_length too high: {maxlen}",
                description=(
                    f"Password max_length is {maxlen}. OWASP recommends <= 128. "
                    f"Higher values increase hash computation time without adding "
                    f"meaningful security."
                ),
                file_path=str(filepath),
                fix_suggestion="Set max_length=128 (OWASP 2024 recommendation).",
            )

    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def verify_auth_config(project_path: str) -> list[Finding]:
    """
    Statically analyze a FastAPI project for auth security issues.

    Scans all Python files for 8 common auth anti-patterns using AST
    analysis and regex matching. Returns a list of Finding objects, one
    per detected issue, sorted by severity (critical first).

    Args:
        project_path: Root directory of the FastAPI project to analyze.

    Returns:
        List of Finding objects for each detected auth security issue.

    Example::

        findings = verify_auth_config("/path/to/my-fastapi-project")
        for f in findings:
            print(f"[{f.severity.value}] {f.rule_id}: {f.title}")
        # [critical] AUTH-01: Hardcoded JWT secret in jwt.encode() call
        # [high] AUTH-06: No rate limiting on login endpoint
    """
    root = Path(project_path).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project path does not exist: {root}")

    py_files = _collect_python_files(root)
    findings: list[Finding] = []

    # Concatenated source for project-wide checks (AUTH-07)
    all_sources_parts: list[str] = []

    for filepath in py_files:
        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue

        all_sources_parts.append(source)

        # Parse AST (best-effort)
        tree: ast.AST | None = None
        try:
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError:
            pass

        # --- Per-file checks ---

        # AUTH-01: Hardcoded JWT secret
        if tree is not None:
            finding = _check_auth01_hardcoded_secret(tree, source, filepath)
            if finding:
                findings.append(finding)

        # AUTH-02: Access token expiry
        if tree is not None:
            finding = _check_auth02_token_expiry(tree, source, filepath)
            if finding:
                findings.append(finding)

        # AUTH-03: Refresh token rotation (jti)
        finding = _check_auth03_refresh_rotation(source, filepath)
        if finding:
            findings.append(finding)

        # AUTH-04: Timing attack prevention
        finding = _check_auth04_timing_attack(source, filepath)
        if finding:
            findings.append(finding)

        # AUTH-05: Password hashing algorithm
        finding = _check_auth05_password_hashing(source, filepath)
        if finding:
            findings.append(finding)

        # AUTH-06: Rate limiting on auth endpoints
        finding = _check_auth06_rate_limiting(source, filepath)
        if finding:
            findings.append(finding)

        # AUTH-08: Password max_length
        if tree is not None:
            finding = _check_auth08_password_maxlength(tree, source, filepath)
            if finding:
                findings.append(finding)

    # --- Project-wide checks ---

    # AUTH-07: Logout endpoint exists
    all_sources = "\n".join(all_sources_parts)
    finding = _check_auth07_logout(all_sources)
    if finding:
        findings.append(finding)

    # Sort by severity (critical first)
    severity_order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
    }
    findings.sort(key=lambda f: severity_order.get(f.severity, 99))

    return findings
