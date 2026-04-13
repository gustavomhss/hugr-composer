"""Benchmark analyzer for FastAPI production projects.

Checks generated code against the benchmark spec mechanically.
No bias — either the code has it or it doesn't.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Check:
    name: str
    category: str
    passed: bool
    detail: str = ""
    reference: str = ""


@dataclass
class BenchmarkResult:
    project_name: str
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def score(self) -> float:
        return (self.passed / self.total * 100) if self.total else 0

    def by_category(self) -> dict[str, tuple[int, int]]:
        cats: dict[str, list[bool]] = {}
        for c in self.checks:
            cats.setdefault(c.category, []).append(c.passed)
        return {k: (sum(v), len(v)) for k, v in cats.items()}

    def summary(self, show_references: bool = False) -> str:
        lines = [f"\n{'='*60}", f"  {self.project_name}", f"{'='*60}"]
        for cat, (p, t) in self.by_category().items():
            mark = "✅" if p == t else "⚠️" if p > 0 else "❌"
            lines.append(f"  {mark} {cat}: {p}/{t}")
        lines.append(f"{'─'*60}")
        lines.append(f"  TOTAL: {self.passed}/{self.total} ({self.score:.0f}%)")
        lines.append(f"{'='*60}")
        if show_references:
            lines.append(f"\n  {'REFERENCES':}")
            lines.append(f"  {'─'*56}")
            seen_refs: set[str] = set()
            for c in self.checks:
                if c.reference and c.reference not in seen_refs:
                    seen_refs.add(c.reference)
                    mark = "✅" if c.passed else "❌"
                    lines.append(f"  {mark} {c.reference}")
            lines.append("")
        else:
            lines.append("")
        return "\n".join(lines)

    def failures(self) -> str:
        fails = [c for c in self.checks if not c.passed]
        if not fails:
            return "  No failures.\n"
        lines = []
        for c in fails:
            lines.append(f"  ❌ [{c.category}] {c.name}")
            if c.detail:
                lines.append(f"     → {c.detail}")
            if c.reference:
                lines.append(f"     📖 {c.reference}")
        return "\n".join(lines) + "\n"


def _find_files(root: Path, ext: str = ".py") -> list[Path]:
    """Recursively find all files with given extension."""
    return sorted(root.rglob(f"*{ext}"))


def _read_all_py(root: Path) -> str:
    """Read all Python files into one big string."""
    content = ""
    for f in _find_files(root, ".py"):
        try:
            content += f.read_text() + "\n"
        except Exception:
            pass
    return content


def _read_all_files(root: Path) -> str:
    """Read ALL files into one string (for checking configs, YAML, etc.)."""
    content = ""
    for f in root.rglob("*"):
        if f.is_file() and f.stat().st_size < 100_000:
            try:
                content += f.read_text(errors="replace") + "\n"
            except Exception:
                pass
    return content


def _has_pattern(text: str, pattern: str) -> bool:
    """Case-insensitive, multiline regex search."""
    return bool(re.search(pattern, text, re.IGNORECASE | re.MULTILINE))


def analyze(root: str | Path) -> BenchmarkResult:
    """Run all benchmark checks against a project directory."""
    root = Path(root)
    result = BenchmarkResult(project_name=root.name)

    py_code = _read_all_py(root)
    all_code = _read_all_files(root)

    # ===================================================================
    # CATEGORY 1: Security (Auth)
    # ===================================================================

    # 1.1 Password hashing — must use modern algorithm
    uses_argon2 = _has_pattern(py_code, r"argon2|Argon2")
    uses_bcrypt = _has_pattern(py_code, r"bcrypt|CryptContext") and not uses_argon2
    uses_pwdlib = _has_pattern(py_code, r"pwdlib")
    uses_passlib = _has_pattern(py_code, r"passlib")

    result.checks.append(Check(
        "Modern password hashing (argon2id)",
        "Security",
        uses_argon2,
        "argon2id" if uses_argon2 else ("bcrypt (acceptable but not SOTA)" if uses_bcrypt else "no modern hasher found"),
        reference="OWASP Password Storage Cheat Sheet 2024: Use Argon2id with min 19 MiB memory, iteration count 2, parallelism 1",
    ))

    result.checks.append(Check(
        "Uses pwdlib (not deprecated passlib)",
        "Security",
        uses_pwdlib and not uses_passlib,
        "pwdlib" if uses_pwdlib else ("passlib (deprecated)" if uses_passlib else "neither"),
        reference="passlib last release 2020 (unmaintained). pwdlib is its maintained successor with same API",
    ))

    # 1.2 JWT — must use PyJWT, not python-jose (CVE-2024-33663)
    uses_pyjwt = _has_pattern(py_code, r"^import jwt\b|^from jwt ") or _has_pattern(py_code, r"^\s*import jwt\b")
    uses_jose = _has_pattern(py_code, r"from jose\b|import jose\b|from python_jose")

    result.checks.append(Check(
        "Uses PyJWT (not python-jose with CVE)",
        "Security",
        uses_pyjwt and not uses_jose,
        "PyJWT" if uses_pyjwt else ("python-jose (CVE-2024-33663)" if uses_jose else "no JWT lib"),
        reference="CVE-2024-33663: ECDSA signature validation bypass in python-jose allows forged tokens",
    ))

    # 1.3 Algorithm whitelist
    result.checks.append(Check(
        "JWT algorithm whitelist (algorithms=[...])",
        "Security",
        _has_pattern(py_code, r"algorithms\s*=\s*\["),
        "Found" if _has_pattern(py_code, r"algorithms\s*=\s*\[") else "Missing — vulnerable to algorithm confusion",
        reference="RFC 7515 Section 10.7: Require algorithm to be specified by application, not taken from header",
    ))

    # 1.4 Timing attack prevention
    has_dummy = _has_pattern(py_code, r"DUMMY_HASH|dummy.*hash|timing.*prevent|constant.time")
    result.checks.append(Check(
        "Timing attack prevention (DUMMY_HASH or constant-time)",
        "Security",
        has_dummy,
        "Found" if has_dummy else "Missing — login leaks user existence via response time",
        reference="CWE-208: Observable Timing Discrepancy. OWASP Authentication Cheat Sheet: prevent user enumeration via timing",
    ))

    # 1.5 Password field constraints
    has_pwd_min = _has_pattern(py_code, r"min_length\s*=\s*8")
    has_pwd_max = _has_pattern(py_code, r"max_length\s*=\s*128")
    result.checks.append(Check(
        "Password constraints (min=8, max=128)",
        "Security",
        has_pwd_min and has_pwd_max,
        f"min=8: {'✓' if has_pwd_min else '✗'}, max=128: {'✓' if has_pwd_max else '✗'}",
        reference="NIST SP 800-63B Section 5.1.1.2: min 8 chars. OWASP: max 128 to prevent long-password DoS",
    ))

    # 1.6 Secret key validation
    has_secret_validation = _has_pattern(py_code, r"changethis|change.this|default.*secret")
    result.checks.append(Check(
        "Secret key validation (reject defaults)",
        "Security",
        has_secret_validation,
        "Found" if has_secret_validation else "Missing — may accept default secrets in production",
        reference="OWASP Configuration Cheat Sheet: Never use default credentials in production",
    ))

    # 1.7 Password recovery doesn't leak existence
    has_recovery = _has_pattern(py_code, r"password.recovery|recover.password|reset.password")
    has_same_response = _has_pattern(py_code, r"same.*response|whether.*exists|enumeration")
    result.checks.append(Check(
        "Password recovery prevents email enumeration",
        "Security",
        has_recovery and has_same_response,
        "Safe" if has_same_response else "Recovery exists but may leak email existence" if has_recovery else "No recovery endpoint",
        reference="OWASP Authentication Cheat Sheet: Return a generic message for password recovery regardless of account existence",
    ))

    # 1.8 Security headers
    security_headers = [
        ("X-Content-Type-Options", r"x.content.type.options"),
        ("X-Frame-Options", r"x.frame.options"),
        ("Strict-Transport-Security", r"strict.transport.security|hsts"),
        ("Referrer-Policy", r"referrer.policy"),
        ("Content-Security-Policy", r"content.security.policy|csp"),
    ]
    header_count = sum(1 for _, pat in security_headers if _has_pattern(all_code, pat))
    result.checks.append(Check(
        f"Security headers ({header_count}/5)",
        "Security",
        header_count >= 4,
        ", ".join(name for name, pat in security_headers if _has_pattern(all_code, pat)),
        reference="OWASP Secure Headers Project: required response headers to prevent XSS, clickjacking, MIME sniffing",
    ))

    # 1.9 CORS not wildcard
    cors_present = _has_pattern(py_code, r"CORSMiddleware|cors")
    cors_wildcard = _has_pattern(py_code, r'allow_origins\s*=\s*\[\s*"\*"\s*\]')
    result.checks.append(Check(
        "CORS configured (not wildcard)",
        "Security",
        cors_present and not cors_wildcard,
        "Wildcard ✗" if cors_wildcard else ("Configured ✓" if cors_present else "No CORS"),
        reference="OWASP CORS Cheat Sheet: Never use wildcard origins with credentials; whitelist specific domains",
    ))

    # ===================================================================
    # CATEGORY 2: Database
    # ===================================================================

    # 2.1 Async engine
    has_async_engine = _has_pattern(py_code, r"create_async_engine")
    result.checks.append(Check(
        "Async database engine",
        "Database",
        has_async_engine,
        "create_async_engine" if has_async_engine else "sync or missing",
        reference="SQLAlchemy 2.0 docs: async engine required for non-blocking I/O in ASGI applications",
    ))

    # 2.2 Pool configuration
    has_pool_size = _has_pattern(py_code, r"pool_size\s*=")
    has_pool_recycle = _has_pattern(py_code, r"pool_recycle\s*=")
    has_pool_pre_ping = _has_pattern(py_code, r"pool_pre_ping\s*=\s*True")
    result.checks.append(Check(
        "Pool configuration (size + recycle + pre_ping)",
        "Database",
        has_pool_size and has_pool_pre_ping,
        f"pool_size: {'✓' if has_pool_size else '✗'}, recycle: {'✓' if has_pool_recycle else '✗'}, pre_ping: {'✓' if has_pool_pre_ping else '✗'}",
        reference="SQLAlchemy Connection Pooling docs: pool_pre_ping prevents stale connections, pool_recycle prevents firewall timeouts",
    ))

    # 2.3 UUID primary keys
    has_uuid_pk = _has_pattern(py_code, r"uuid4|UUID.*primary_key|uuid\.uuid4")
    result.checks.append(Check(
        "UUID primary keys",
        "Database",
        has_uuid_pk,
        "Found" if has_uuid_pk else "Missing",
        reference="OWASP: sequential integer IDs enable enumeration attacks (IDOR). UUIDs prevent resource guessing",
    ))

    # 2.4 Cascade deletes
    has_cascade = _has_pattern(py_code, r"CASCADE|cascade_delete")
    result.checks.append(Check(
        "Cascade deletes on relationships",
        "Database",
        has_cascade,
        "Found" if has_cascade else "Missing",
        reference="SQLAlchemy Relationship docs: cascade deletes prevent orphaned records and referential integrity violations",
    ))

    # 2.5 Alembic migrations
    has_alembic = any(root.rglob("alembic*")) or _has_pattern(all_code, r"alembic")
    result.checks.append(Check(
        "Alembic migrations configured",
        "Database",
        has_alembic,
        "Found" if has_alembic else "Missing",
        reference="SQLAlchemy migration best practice: version-controlled schema changes via Alembic for safe deployments",
    ))

    # 2.6 Session management
    has_session_dep = _has_pattern(py_code, r"async.*get_session|SessionDep|get_db|get_session")
    result.checks.append(Check(
        "Session dependency injection",
        "Database",
        has_session_dep,
        "Found" if has_session_dep else "Missing",
        reference="FastAPI dependency injection docs: proper session lifecycle management prevents connection leaks",
    ))

    # ===================================================================
    # CATEGORY 3: API Design
    # ===================================================================

    # 3.1 List response format {data, count}
    has_list_format = _has_pattern(py_code, r"data.*list|List\[.*Public\]") and _has_pattern(py_code, r"count.*int")
    result.checks.append(Check(
        "List responses use {data: [...], count: int}",
        "API Design",
        has_list_format,
        "Found" if has_list_format else "Missing standard format",
        reference="JSON:API specification pattern: paginated collections return {data, count} for client-side pagination",
    ))

    # 3.2 Response models on endpoints
    has_response_model = _has_pattern(py_code, r"response_model\s*=")
    result.checks.append(Check(
        "Response models defined on endpoints",
        "API Design",
        has_response_model,
        "Found" if has_response_model else "Missing — may expose internal fields",
        reference="FastAPI docs: response_model filters output fields, preventing accidental exposure of internal data",
    ))

    # 3.3 Pagination (skip/limit) — accept both single-line and split-line forms
    has_pagination = (
        _has_pattern(py_code, r"skip\s*:\s*int")
        and _has_pattern(py_code, r"limit\s*:\s*int")
    ) or _has_pattern(py_code, r"offset.*limit")
    result.checks.append(Check(
        "Pagination (skip/limit) on list endpoints",
        "API Design",
        has_pagination,
        "Found" if has_pagination else "Missing",
        reference="OWASP API Security Top 10 (API4:2023): Unrestricted Resource Consumption. Pagination prevents full-table dumps",
    ))

    # 3.4 Error handlers
    has_error_handlers = _has_pattern(py_code, r"HTTPException|exception_handler|RequestValidationError")
    result.checks.append(Check(
        "Error handlers (HTTPException + Validation)",
        "API Design",
        has_error_handlers,
        "Found" if has_error_handlers else "Missing",
        reference="RFC 7807: Problem Details for HTTP APIs. Structured error responses for consistent client handling",
    ))

    # ===================================================================
    # CATEGORY 4: Infrastructure
    # ===================================================================

    # 4.1 Lifespan (not on_event)
    has_lifespan = _has_pattern(py_code, r"lifespan|asynccontextmanager")
    has_on_event = _has_pattern(py_code, r'@app\.on_event|@.*on_event')
    result.checks.append(Check(
        "Lifespan pattern (not deprecated on_event)",
        "Infrastructure",
        has_lifespan and not has_on_event,
        "lifespan ✓" if has_lifespan and not has_on_event else ("on_event (deprecated)" if has_on_event else "neither"),
        reference="FastAPI 0.93+ docs: on_event is deprecated, use lifespan async context manager for startup/shutdown",
    ))

    # 4.2 Pydantic Settings
    has_pydantic_settings = _has_pattern(py_code, r"BaseSettings|pydantic.settings|pydantic_settings")
    result.checks.append(Check(
        "Pydantic Settings for config",
        "Infrastructure",
        has_pydantic_settings,
        "Found" if has_pydantic_settings else "Missing — config not env-driven",
        reference="12-Factor App (Factor III: Config): store config in environment, not code. Pydantic Settings validates at startup",
    ))

    # 4.3 Structlog or structured logging
    has_structlog = _has_pattern(py_code, r"structlog|structured.*log")
    result.checks.append(Check(
        "Structured logging (structlog)",
        "Infrastructure",
        has_structlog,
        "Found" if has_structlog else "Missing — using stdlib logging",
        reference="Structured logging best practice: machine-parseable JSON logs for production observability and log aggregation",
    ))

    # 4.4 Correlation ID
    has_correlation = _has_pattern(all_code, r"correlation.id|x.correlation|request.id|trace.id")
    result.checks.append(Check(
        "Correlation ID middleware",
        "Infrastructure",
        has_correlation,
        "Found" if has_correlation else "Missing — can't trace requests across services",
        reference="W3C Trace Context standard + OpenTelemetry: trace context propagation for distributed request tracing",
    ))

    # 4.5 Health checks
    has_liveness = _has_pattern(py_code, r"/healthz|/health|liveness")
    has_readiness = _has_pattern(py_code, r"/readyz|/ready|readiness")
    result.checks.append(Check(
        "Health checks (liveness + readiness)",
        "Infrastructure",
        has_liveness and has_readiness,
        f"liveness: {'✓' if has_liveness else '✗'}, readiness: {'✓' if has_readiness else '✗'}",
        reference="Kubernetes docs: liveness probes detect deadlocks, readiness probes gate traffic until dependencies are ready",
    ))

    # ===================================================================
    # CATEGORY 5: Deployment
    # ===================================================================

    # 5.1 Dockerfile
    has_dockerfile = any(root.rglob("Dockerfile*"))
    result.checks.append(Check(
        "Dockerfile present",
        "Deployment",
        has_dockerfile,
        "Found" if has_dockerfile else "Missing",
        reference="Container best practice: Dockerfile ensures reproducible, portable deployments across environments",
    ))

    # 5.2 Multi-stage build
    dockerfile_content = ""
    for df in root.rglob("Dockerfile"):
        try:
            dockerfile_content = df.read_text()
        except Exception:
            pass
    has_multistage = dockerfile_content.count("FROM ") >= 2
    result.checks.append(Check(
        "Multi-stage Docker build",
        "Deployment",
        has_multistage,
        "Found" if has_multistage else "Single stage or no Dockerfile",
        reference="Docker docs: multi-stage builds separate build deps from runtime, reducing final image size and attack surface",
    ))

    # 5.3 Non-root user
    has_nonroot = _has_pattern(dockerfile_content, r"USER\s+(?!root)\w+|useradd|adduser|runAsNonRoot")
    result.checks.append(Check(
        "Non-root container user",
        "Deployment",
        has_nonroot,
        "Found" if has_nonroot else "Running as root ✗",
        reference="CIS Docker Benchmark 4.1: Ensure a non-root user is created for the container to limit blast radius",
    ))

    # 5.4 Docker healthcheck
    has_docker_health = _has_pattern(dockerfile_content, r"HEALTHCHECK")
    result.checks.append(Check(
        "Docker HEALTHCHECK",
        "Deployment",
        has_docker_health,
        "Found" if has_docker_health else "Missing",
        reference="Docker docs: HEALTHCHECK instruction enables orchestrator to detect and restart unhealthy containers",
    ))

    # 5.5 requirements.txt or pyproject.toml
    has_deps = any(root.rglob("requirements*.txt")) or any(root.rglob("pyproject.toml"))
    result.checks.append(Check(
        "Dependency file (requirements.txt / pyproject.toml)",
        "Deployment",
        has_deps,
        "Found" if has_deps else "Missing",
        reference="Python Packaging: pinned dependencies in requirements.txt/pyproject.toml for reproducible installs",
    ))

    # ===================================================================
    # CATEGORY 6: Code Quality
    # ===================================================================

    # 6.1 No datetime.utcnow()
    has_utcnow = _has_pattern(py_code, r"\.utcnow\(\)")
    result.checks.append(Check(
        "No deprecated datetime.utcnow()",
        "Code Quality",
        not has_utcnow,
        "Clean ✓" if not has_utcnow else "Uses utcnow() (deprecated in 3.12)",
        reference="Python 3.12 deprecation: datetime.utcnow() returns naive UTC. Use datetime.now(timezone.utc) instead",
    ))

    # 6.2 Type hints
    has_type_hints = _has_pattern(py_code, r"def \w+\([^)]*:\s*\w+")
    result.checks.append(Check(
        "Type hints on functions",
        "Code Quality",
        has_type_hints,
        "Found" if has_type_hints else "Missing",
        reference="PEP 484 + mypy: static type checking catches bugs at development time, improves maintainability",
    ))

    # 6.3 max_length on string fields
    max_length_count = len(re.findall(r"max_length\s*=", py_code))
    result.checks.append(Check(
        f"max_length on string fields ({max_length_count} occurrences)",
        "Code Quality",
        max_length_count >= 3,
        f"{max_length_count} fields constrained" if max_length_count >= 3 else "Insufficient — DoS via unbounded strings",
        reference="CWE-400: Uncontrolled Resource Consumption. Unbounded string fields enable memory exhaustion DoS",
    ))

    # 6.4 hashed_password never in response
    # Check if any response/public schema includes hashed_password
    has_hashed_in_response = False
    for f in _find_files(root, ".py"):
        try:
            # Skip test files — they legitimately reference hashed_password in assertions
            if "test_" in f.name or "/tests/" in str(f):
                continue
            content = f.read_text()
            if "Public" in content and "hashed_password" in content:
                # Check if it's excluded
                if "exclude" not in content.lower():
                    has_hashed_in_response = True
        except Exception:
            pass
    result.checks.append(Check(
        "hashed_password never exposed in API responses",
        "Code Quality",
        not has_hashed_in_response,
        "Safe ✓" if not has_hashed_in_response else "DANGER: hashed_password may leak to API",
        reference="OWASP: never expose password hashes in API responses. Hashes enable offline brute-force attacks",
    ))

    # 6.5 No on_event decorator
    result.checks.append(Check(
        "No deprecated @app.on_event",
        "Code Quality",
        not has_on_event,
        "Clean ✓" if not has_on_event else "Uses deprecated on_event",
        reference="FastAPI 0.93+ deprecation notice: @app.on_event will be removed. Use lifespan context manager",
    ))

    return result


def compare_results(*results: BenchmarkResult, show_references: bool = False) -> str:
    """Generate a comparison table across multiple results."""
    if not results:
        return ""

    # Collect all unique checks (and their references)
    all_check_names: list[str] = []
    check_refs: dict[str, str] = {}
    seen: set[str] = set()
    for r in results:
        for c in r.checks:
            key = f"{c.category}|{c.name}"
            if key not in seen:
                seen.add(key)
                all_check_names.append(key)
                if c.reference:
                    check_refs[key] = c.reference

    # Header
    names = [r.project_name for r in results]
    col_width = max(18, max(len(n) for n in names) + 2)
    header = f"{'Check':<50}" + "".join(f"{n:^{col_width}}" for n in names)
    sep = "─" * len(header)

    lines = ["\n" + sep, header, sep]

    current_cat = ""
    for key in all_check_names:
        cat, name = key.split("|", 1)
        if cat != current_cat:
            current_cat = cat
            lines.append(f"\n  {cat.upper()}")

        row = f"  {name:<48}"
        for r in results:
            check = next((c for c in r.checks if f"{c.category}|{c.name}" == key), None)
            if check is None:
                row += f"{'—':^{col_width}}"
            elif check.passed:
                row += f"{'✅':^{col_width}}"
            else:
                row += f"{'❌':^{col_width}}"
        lines.append(row)
        if show_references and key in check_refs:
            lines.append(f"    📖 {check_refs[key]}")

    lines.append(sep)
    score_row = f"  {'SCORE':<48}"
    for r in results:
        score_row += f"{f'{r.passed}/{r.total} ({r.score:.0f}%)':^{col_width}}"
    lines.append(score_row)
    lines.append(sep + "\n")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python analyzer.py <project_dir> [project_dir2 ...]")
        sys.exit(1)

    results = []
    for path in sys.argv[1:]:
        r = analyze(path)
        print(r.summary())
        if any(not c.passed for c in r.checks):
            print("FAILURES:")
            print(r.failures())
        results.append(r)

    if len(results) > 1:
        print(compare_results(*results))
