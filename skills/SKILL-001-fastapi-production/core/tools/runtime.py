"""
SKILL-001 Core Tool: Runtime checks against a running FastAPI instance.

Performs live HTTP probes for health check endpoints and security headers.
Uses httpx for async HTTP. All connection errors are handled gracefully.
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_check_health',
    'description': 'Check 3-level health endpoints (/healthz, /readyz, /startupz) of a running instance.',
    'tags': ['runtime', 'verify'],
    'entry': 'mcp_fastapi_check_health',
    'annotations': {'readOnlyHint': True},
}

import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.models import (
    Finding,
    HealthCheckResult,
    HealthLevel,
    SecurityHeadersResult,
    Severity,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Health endpoints to probe, mapped to their level
_HEALTH_ENDPOINTS: list[tuple[HealthLevel, str]] = [
    (HealthLevel.LIVENESS, "/healthz"),
    (HealthLevel.READINESS, "/readyz"),
    (HealthLevel.STARTUP, "/startupz"),
]

# Security headers expected on responses
_EXPECTED_SECURITY_HEADERS: list[str] = [
    "X-Content-Type-Options",
    "X-Frame-Options",
    "X-XSS-Protection",
    "Strict-Transport-Security",
    "Referrer-Policy",
    "Permissions-Policy",
]

_DEFAULT_TIMEOUT: float = 5.0


# ---------------------------------------------------------------------------
# Health check probes
# ---------------------------------------------------------------------------


async def check_health(
    base_url: str,
    timeout: float = _DEFAULT_TIMEOUT,
) -> list[HealthCheckResult]:
    """
    Probe health check endpoints on a running FastAPI instance.

    Hits /healthz, /readyz, and /startupz. Returns a result per endpoint
    with status code, response time, body, and pass/fail.

    Args:
        base_url: Base URL of the running service (e.g. "http://localhost:8000").
        timeout: HTTP request timeout in seconds.

    Returns:
        List of HealthCheckResult, one per endpoint probed.
    """
    base = base_url.rstrip("/")
    results: list[HealthCheckResult] = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for level, path in _HEALTH_ENDPOINTS:
            url = f"{base}{path}"
            start = time.perf_counter()

            try:
                response = await client.get(url)
                elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

                # Try to parse body as JSON, fall back to text
                body: dict | str | None = None
                try:
                    body = response.json()
                except Exception:
                    text = response.text.strip()
                    body = text if text else None

                passed = response.status_code < 400

                results.append(
                    HealthCheckResult(
                        level=level,
                        endpoint=path,
                        status_code=response.status_code,
                        response_time_ms=elapsed_ms,
                        body=body,
                        passed=passed,
                    )
                )

            except httpx.ConnectError:
                elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
                results.append(
                    HealthCheckResult(
                        level=level,
                        endpoint=path,
                        status_code=0,
                        response_time_ms=elapsed_ms,
                        body={"error": "connection_refused"},
                        passed=False,
                    )
                )

            except httpx.TimeoutException:
                elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
                results.append(
                    HealthCheckResult(
                        level=level,
                        endpoint=path,
                        status_code=0,
                        response_time_ms=elapsed_ms,
                        body={"error": "timeout"},
                        passed=False,
                    )
                )

            except httpx.HTTPError as exc:
                elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
                results.append(
                    HealthCheckResult(
                        level=level,
                        endpoint=path,
                        status_code=0,
                        response_time_ms=elapsed_ms,
                        body={"error": str(type(exc).__name__)},
                        passed=False,
                    )
                )

    return results


# ---------------------------------------------------------------------------
# Security headers check
# ---------------------------------------------------------------------------


async def check_security_headers(
    base_url: str,
    timeout: float = _DEFAULT_TIMEOUT,
) -> SecurityHeadersResult:
    """
    Check security headers on a running FastAPI instance.

    Makes a GET to the base URL and an OPTIONS preflight request,
    then checks for all 6 expected security headers.

    Args:
        base_url: Base URL of the running service.
        timeout: HTTP request timeout in seconds.

    Returns:
        SecurityHeadersResult with present/missing headers, score, and findings.
    """
    base = base_url.rstrip("/")
    headers_present: dict[str, str] = {}
    headers_missing: list[str] = []
    findings: list[Finding] = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        # GET request to inspect response headers
        try:
            response = await client.get(base)
        except httpx.ConnectError:
            return SecurityHeadersResult(
                url=base,
                headers_present={},
                headers_missing=list(_EXPECTED_SECURITY_HEADERS),
                score=0,
                findings=[
                    Finding(
                        rule_id="RT-SEC-001",
                        severity=Severity.CRITICAL,
                        title="Cannot connect to service",
                        description=f"Connection refused at {base}. Service may not be running.",
                    )
                ],
            )
        except httpx.HTTPError as exc:
            return SecurityHeadersResult(
                url=base,
                headers_present={},
                headers_missing=list(_EXPECTED_SECURITY_HEADERS),
                score=0,
                findings=[
                    Finding(
                        rule_id="RT-SEC-002",
                        severity=Severity.CRITICAL,
                        title="HTTP error connecting to service",
                        description=f"{type(exc).__name__} when connecting to {base}.",
                    )
                ],
            )

        # Check each expected header
        for header_name in _EXPECTED_SECURITY_HEADERS:
            value = response.headers.get(header_name)
            if value:
                headers_present[header_name] = value
            else:
                headers_missing.append(header_name)

        # CORS preflight check (OPTIONS)
        try:
            preflight = await client.options(
                base,
                headers={
                    "Origin": "https://attacker.example.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
            acao = preflight.headers.get("Access-Control-Allow-Origin", "")
            if acao == "*":
                findings.append(
                    Finding(
                        rule_id="RT-SEC-010",
                        severity=Severity.HIGH,
                        title="CORS allows wildcard origin",
                        description=(
                            "Access-Control-Allow-Origin: * returned on preflight. "
                            "Any origin can make cross-origin requests."
                        ),
                        fix_suggestion="Configure specific allowed origins instead of wildcard.",
                    )
                )
            elif acao == "https://attacker.example.com":
                findings.append(
                    Finding(
                        rule_id="RT-SEC-011",
                        severity=Severity.CRITICAL,
                        title="CORS reflects arbitrary origin",
                        description=(
                            "Server reflects attacker origin in Access-Control-Allow-Origin. "
                            "This defeats CORS protection entirely."
                        ),
                        fix_suggestion="Use a strict allowlist of origins, do not reflect the Origin header.",
                    )
                )
        except httpx.HTTPError:
            # Preflight check is best-effort
            pass

    # Generate findings for missing headers
    _header_severity: dict[str, Severity] = {
        "X-Content-Type-Options": Severity.HIGH,
        "X-Frame-Options": Severity.HIGH,
        "X-XSS-Protection": Severity.LOW,
        "Strict-Transport-Security": Severity.HIGH,
        "Referrer-Policy": Severity.MEDIUM,
        "Permissions-Policy": Severity.MEDIUM,
    }

    _header_descriptions: dict[str, str] = {
        "X-Content-Type-Options": "Prevents MIME type sniffing. Should be 'nosniff'.",
        "X-Frame-Options": "Prevents clickjacking. Should be 'DENY' or 'SAMEORIGIN'.",
        "X-XSS-Protection": "Legacy XSS filter. Should be '1; mode=block'.",
        "Strict-Transport-Security": "Enforces HTTPS. Should include max-age and includeSubDomains.",
        "Referrer-Policy": "Controls referrer leakage. Should be 'strict-origin-when-cross-origin'.",
        "Permissions-Policy": "Restricts browser features. Should disable camera, microphone, etc.",
    }

    for header in headers_missing:
        findings.append(
            Finding(
                rule_id=f"RT-SEC-{_EXPECTED_SECURITY_HEADERS.index(header) + 3:03d}",
                severity=_header_severity.get(header, Severity.MEDIUM),
                title=f"Missing security header: {header}",
                description=_header_descriptions.get(header, f"{header} is not set."),
                fix_suggestion=f"Add {header} header via SecurityHeadersMiddleware.",
            )
        )

    # Score: percentage of headers present
    total = len(_EXPECTED_SECURITY_HEADERS)
    score = round((len(headers_present) / total) * 100) if total else 0

    return SecurityHeadersResult(
        url=base,
        headers_present=headers_present,
        headers_missing=headers_missing,
        score=score,
        findings=findings,
    )


def mcp_fastapi_check_health(base_url: str) -> list[dict]:
    """MCP entry: check 3-level health endpoints (/healthz, /readyz, /startupz) of a running instance."""
    import asyncio as _asyncio
    results = _asyncio.run(check_health(base_url))
    return [r.model_dump(mode="json") for r in results]


def mcp_fastapi_check_headers(base_url: str) -> dict:
    """MCP entry: check security headers and CORS of a running instance."""
    import asyncio as _asyncio
    result = _asyncio.run(check_security_headers(base_url))
    return result.model_dump(mode="json")
