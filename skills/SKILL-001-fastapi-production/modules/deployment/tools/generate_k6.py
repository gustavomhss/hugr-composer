"""
SKILL-001 Deployment Tool: Generate k6 load testing scripts.

Creates production-grade k6 JavaScript load test scripts with:
  - Configurable ramping stages (ramp-up, sustain, ramp-down)
  - Per-endpoint checks (status, response time, body validation)
  - Thresholds with p95/p99 latency gates and error rate limits
  - handleSummary for JSON export (CI integration, Grafana, Datadog)
  - Tagged requests for per-endpoint metric breakdown
  - Realistic think time between iterations

Generated script can be run directly: k6 run loadtest.js
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_deployment_generate_k6',
    'description': 'Generate k6 load test scripts with ramping stages, per-endpoint checks, p95/p99 thresholds, handleSummary JSON export.',
    'tags': ['deployment', 'generator'],
    'entry': 'generate_k6_script',
    'annotations': {'readOnlyHint': False, 'destructiveHint': False},
}

import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity


# ---------------------------------------------------------------------------
# k6 script generator
# ---------------------------------------------------------------------------


def generate_k6_script(
    base_url: str,
    endpoints: list[dict[str, str]],
    max_vus: int = 50,
    duration_seconds: int = 60,
    *,
    ramp_up_seconds: int = 30,
    ramp_down_seconds: int = 15,
    p95_threshold_ms: int = 500,
    p99_threshold_ms: int = 1000,
    error_rate_threshold: float = 0.01,
    think_time_seconds: float = 1.0,
) -> str:
    """
    Generate a k6 load testing script for a FastAPI application.

    Creates a JavaScript file with ramping VU stages, per-endpoint checks,
    pass/fail thresholds, and JSON summary export. The script follows SOTA
    k6 patterns: tagged requests for metric breakdown, realistic think time,
    graceful ramp-down, and handleSummary for CI integration.

    Args:
        base_url: Base URL of the target service (e.g., "http://localhost:8000").
        endpoints: List of endpoint dicts with keys:
            - method: HTTP method ("GET", "POST", "PUT", "DELETE")
            - path: URL path (e.g., "/healthz", "/api/v1/items")
            - name: Human-readable name for metrics/tags (e.g., "health_check")
            - body: Optional JSON body string for POST/PUT (default: None)
            - expected_status: Expected HTTP status code (default: "200")
        max_vus: Maximum virtual users during sustained load (default: 50).
        duration_seconds: Duration of sustained load phase in seconds (default: 60).
        ramp_up_seconds: Seconds to ramp from 0 to max_vus (default: 30).
        ramp_down_seconds: Seconds to ramp from max_vus to 0 (default: 15).
        p95_threshold_ms: p95 latency threshold in ms — test fails if exceeded
            (default: 500).
        p99_threshold_ms: p99 latency threshold in ms — test fails if exceeded
            (default: 1000).
        error_rate_threshold: Maximum allowed error rate as decimal (default: 0.01 = 1%).
        think_time_seconds: Sleep between iterations to simulate real users
            (default: 1.0). Without this, VUs fire as fast as possible.

    Returns:
        String containing the complete k6 JavaScript test script.

    Example::

        script = generate_k6_script(
            base_url="http://localhost:8000",
            endpoints=[
                {"method": "GET", "path": "/healthz", "name": "health"},
                {"method": "GET", "path": "/api/v1/items", "name": "list_items"},
                {"method": "POST", "path": "/api/v1/items", "name": "create_item",
                 "body": '{"name": "test", "price": 9.99}'},
            ],
            max_vus=100,
            duration_seconds=120,
        )
        Path("loadtest.js").write_text(script)
        # Run: k6 run loadtest.js
    """
    # Build endpoint request blocks
    request_blocks: list[str] = []

    for i, ep in enumerate(endpoints):
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "/")
        name = ep.get("name", f"endpoint_{i}")
        body = ep.get("body")
        expected_status = ep.get("expected_status", "200")

        tag_param = f"{{ tags: {{ name: '{name}' }} }}"

        if method == "GET":
            request_line = f"  const res_{name} = http.get(`${{BASE_URL}}{path}`, {tag_param});"
        elif method in ("POST", "PUT", "PATCH"):
            if body:
                # Body provided — send as JSON
                request_line = (
                    f"  const res_{name} = http.{method.lower()}(\n"
                    f"    `${{BASE_URL}}{path}`,\n"
                    f"    JSON.stringify({body}),\n"
                    f"    {{ headers: {{ 'Content-Type': 'application/json' }}, tags: {{ name: '{name}' }} }},\n"
                    f"  );"
                )
            else:
                request_line = (
                    f"  const res_{name} = http.{method.lower()}(\n"
                    f"    `${{BASE_URL}}{path}`,\n"
                    f"    null,\n"
                    f"    {tag_param},\n"
                    f"  );"
                )
        elif method == "DELETE":
            request_line = f"  const res_{name} = http.del(`${{BASE_URL}}{path}`, null, {tag_param});"
        else:
            request_line = f"  const res_{name} = http.get(`${{BASE_URL}}{path}`, {tag_param});"

        check_block = (
            f"  check(res_{name}, {{\n"
            f"    '{name}: status is {expected_status}': (r) => r.status === {expected_status},\n"
            f"    '{name}: duration < {p95_threshold_ms}ms': (r) => r.timings.duration < {p95_threshold_ms},\n"
            f"  }});"
        )

        request_blocks.append(f"{request_line}\n{check_block}")

    requests_code = "\n\n".join(request_blocks)

    # Build thresholds with per-endpoint breakdown
    threshold_lines = [
        f"    http_req_duration: ['p(95)<{p95_threshold_ms}', 'p(99)<{p99_threshold_ms}'],",
        f"    http_req_failed: ['rate<{error_rate_threshold}'],",
        f"    checks: ['rate>0.99'],",
    ]

    # Add per-endpoint duration thresholds
    for ep in endpoints:
        name = ep.get("name", "unknown")
        threshold_lines.append(
            f"    'http_req_duration{{name:{name}}}': ['p(95)<{p95_threshold_ms}'],"
        )

    thresholds_code = "\n".join(threshold_lines)

    return textwrap.dedent(f"""\
        // =============================================================================
        // k6 Load Test Script
        // Generated by SKILL-001 Deployment Module
        // =============================================================================
        //
        // Run:     k6 run loadtest.js
        // Custom:  k6 run --vus 100 --duration 5m loadtest.js
        // CI:      k6 run loadtest.js --out json=results.json
        // Cloud:   k6 cloud loadtest.js
        //
        // Thresholds cause k6 to exit with code 99 on failure — use in CI to gate deploys.
        // =============================================================================

        import http from 'k6/http';
        import {{ check, sleep }} from 'k6';
        import {{ textSummary }} from 'https://jslib.k6.io/k6-summary/0.1.0/index.js';

        // ---------------------------------------------------------------------------
        // Configuration
        // ---------------------------------------------------------------------------

        const BASE_URL = __ENV.BASE_URL || '{base_url.rstrip("/")}';

        export const options = {{
          // Ramping stages: ramp-up -> sustain -> ramp-down
          stages: [
            {{ duration: '{ramp_up_seconds}s', target: {max_vus} }},    // Ramp up to {max_vus} VUs
            {{ duration: '{duration_seconds}s', target: {max_vus} }},   // Sustain at {max_vus} VUs
            {{ duration: '{ramp_down_seconds}s', target: 0 }},          // Graceful ramp-down
          ],

          // Pass/fail thresholds — k6 exits with code 99 if ANY threshold is breached
          thresholds: {{
        {thresholds_code}
          }},
        }};

        // ---------------------------------------------------------------------------
        // Test scenario
        // ---------------------------------------------------------------------------

        export default function () {{
        {requests_code}

          // Think time: simulate real user behavior.
          // Without this, VUs fire as fast as possible — unrealistic and misleading.
          sleep({think_time_seconds});
        }}

        // ---------------------------------------------------------------------------
        // Custom summary (JSON export for CI/Grafana/Datadog)
        // ---------------------------------------------------------------------------

        export function handleSummary(data) {{
          return {{
            stdout: textSummary(data, {{ indent: ' ', enableColors: true }}),
            'k6-summary.json': JSON.stringify(data, null, 2),
          }};
        }}
    """)


# ---------------------------------------------------------------------------
# Quick preset generators
# ---------------------------------------------------------------------------


def generate_smoke_test(base_url: str, health_path: str = "/healthz") -> str:
    """
    Generate a minimal k6 smoke test (1 VU, 10s, health endpoint only).

    Use as a deploy gate: runs in <15s, validates the app is reachable
    and responding correctly after deployment.

    Args:
        base_url: Base URL of the target service.
        health_path: Health check endpoint path (default: "/healthz").

    Returns:
        String containing a minimal k6 smoke test script.

    Example::

        script = generate_smoke_test("http://localhost:8000")
        Path("smoke.js").write_text(script)
        # Run: k6 run smoke.js
    """
    return generate_k6_script(
        base_url=base_url,
        endpoints=[
            {"method": "GET", "path": health_path, "name": "smoke_health"},
        ],
        max_vus=1,
        duration_seconds=10,
        ramp_up_seconds=1,
        ramp_down_seconds=1,
        p95_threshold_ms=200,
        p99_threshold_ms=500,
        error_rate_threshold=0.0,
        think_time_seconds=1.0,
    )


def generate_stress_test(
    base_url: str,
    endpoints: list[dict[str, str]],
    breaking_point_vus: int = 200,
) -> str:
    """
    Generate a k6 stress test that ramps beyond expected capacity.

    Gradually increases load to find the breaking point. The test has
    5 stages: warmup, normal load, stress load, spike, and recovery.
    Thresholds are relaxed compared to normal load tests — the goal
    is to find WHERE things break, not to pass/fail.

    Args:
        base_url: Base URL of the target service.
        endpoints: List of endpoint dicts (same format as generate_k6_script).
        breaking_point_vus: Maximum VUs to reach during spike (default: 200).

    Returns:
        String containing the k6 stress test script.

    Example::

        script = generate_stress_test(
            "http://localhost:8000",
            [{"method": "GET", "path": "/api/v1/items", "name": "list"}],
            breaking_point_vus=500,
        )
    """
    return generate_k6_script(
        base_url=base_url,
        endpoints=endpoints,
        max_vus=breaking_point_vus,
        duration_seconds=120,
        ramp_up_seconds=60,
        ramp_down_seconds=30,
        p95_threshold_ms=2000,
        p99_threshold_ms=5000,
        error_rate_threshold=0.10,  # Accept up to 10% errors during stress
        think_time_seconds=0.5,
    )
