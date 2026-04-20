"""Generator for k6 load test scripts with per-endpoint scenarios.

Produces a ``loadtest.js`` k6 JavaScript file.  Three built-in presets cover
the most common CI use-cases:

Presets
-------
smoke  (default)
    1 VU, 10 s sustained.  Validates the service is reachable after a deploy.
    Strict thresholds: p95 < 200 ms, 0 % errors.

load
    50 VUs, 5 m (300 s) sustained with 30 s ramp-up / 15 s ramp-down.
    Standard SLA thresholds: p95 < 500 ms, p99 < 1 000 ms, < 1 % errors.

stress
    200 VUs, 10 m (600 s) with 60 s ramp-up / 30 s ramp-down.
    Relaxed thresholds (p95 < 2 000 ms, < 10 % errors) — goal is to find the
    breaking point, not to enforce strict SLAs.

Per-endpoint strategy
---------------------
Each entry in ``endpoints`` becomes its own named k6 request with a tag so
per-endpoint latency percentiles are visible in the k6 summary.  A per-endpoint
``http_req_duration{name:<endpoint_name>}: ['p(95)<...']`` threshold is also
emitted automatically.

``handleSummary()`` exports ``summary.json`` alongside the stdout table, making
results CI-parseable (e.g. for Grafana annotations or Datadog events).
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_generate_loadtest',
    'description': 'Generate k6 load test with ramp/spike/recovery stages and SLA thresholds.',
    'tags': ['deployment', 'generator'],
    'entry': 'generate_k6_loadtest',
}

import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

_PRESETS: dict[str, dict] = {
    "smoke": {
        "max_vus": 1,
        "ramp_up_s": 5,
        "sustain_s": 10,
        "ramp_down_s": 5,
        "p95_ms": 200,
        "p99_ms": 500,
        "error_rate": 0.0,
        "think_s": 1.0,
    },
    "load": {
        "max_vus": 50,
        "ramp_up_s": 30,
        "sustain_s": 300,
        "ramp_down_s": 15,
        "p95_ms": 500,
        "p99_ms": 1000,
        "error_rate": 0.01,
        "think_s": 1.0,
    },
    "stress": {
        "max_vus": 200,
        "ramp_up_s": 60,
        "sustain_s": 600,
        "ramp_down_s": 30,
        "p95_ms": 2000,
        "p99_ms": 5000,
        "error_rate": 0.10,
        "think_s": 0.5,
    },
}

_DEFAULT_ENDPOINTS: list[dict] = [
    {"method": "GET", "path": "/healthz", "name": "health_check", "expected_status": "200"},
    {"method": "GET", "path": "/readyz", "name": "ready_check", "expected_status": "200"},
]


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def generate_k6_loadtest(
    output_dir: str,
    endpoints: list[dict] | None = None,
    preset: str = "smoke",
    base_url: str = "http://localhost:8000",
) -> dict:
    """Generate a production-grade k6 load test script.

    Writes ``loadtest.js`` (k6 JavaScript) to *output_dir*.

    Args:
        output_dir: Directory where ``loadtest.js`` will be written.
        endpoints: List of endpoint dicts.  Each dict may contain:
            ``method`` (default ``"GET"``), ``path`` (default ``"/"``),
            ``name`` (default ``"endpoint_N"``), ``body`` (optional JSON
            string for POST/PUT/PATCH), ``expected_status`` (default ``"200"``).
            Falls back to health + readiness probes when *None*.
        preset: One of ``"smoke"``, ``"load"``, or ``"stress"``.
            See module docstring for threshold details.
        base_url: Base URL of the application under test.

    Returns:
        Dict with ``files_created`` (list of absolute paths) and ``notes``
        (list of human-readable strings describing what was generated).

    Raises:
        ValueError: If *preset* is not one of the three recognised names.
    """
    if preset not in _PRESETS:
        raise ValueError(f"Unknown preset {preset!r}. Choose from: {list(_PRESETS)}")

    resolved_endpoints = endpoints if endpoints is not None else _DEFAULT_ENDPOINTS
    cfg = _PRESETS[preset]

    js_content = _build_js(base_url, resolved_endpoints, cfg)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    file_path = out / "loadtest.js"
    file_path.write_text(js_content)

    return {
        "files_created": [str(file_path)],
        "notes": _build_notes(base_url, preset, cfg, resolved_endpoints),
    }


# ---------------------------------------------------------------------------
# JS assembly helpers
# ---------------------------------------------------------------------------


def _build_js(base_url: str, endpoints: list[dict], cfg: dict) -> str:
    """Assemble the complete k6 JavaScript file from component templates."""
    options_block = _options_block(cfg, endpoints)
    requests_block = _requests_block(endpoints, cfg["p95_ms"])
    summary_block = _handle_summary_block()
    url = base_url.rstrip("/")

    header = textwrap.dedent("""\
        // =============================================================================
        // k6 Load Test Script — Generated by SKILL-001-fastapi-production
        // =============================================================================
        // Run:    k6 run loadtest.js
        // Custom: k6 run --vus 10 --duration 30s loadtest.js
        // CI:     k6 run loadtest.js --out json=results.json
        // Exit code 99 = threshold breach — use in CI to gate deploys.
        // =============================================================================

        import http from 'k6/http';
        import { check, sleep } from 'k6';
        import { textSummary } from 'https://jslib.k6.io/k6-summary/0.1.0/index.js';
    """)

    return (
        f"{header}\n"
        f"const BASE_URL = __ENV.BASE_URL || '{url}';\n\n"
        f"{options_block}\n\n"
        f"export default function () {{\n"
        f"{requests_block}\n\n"
        f"  sleep({cfg['think_s']});\n"
        f"}}\n\n"
        f"{summary_block}\n"
    )


def _options_block(cfg: dict, endpoints: list[dict]) -> str:
    """Return the complete k6 export const options block."""
    stages = _stages_block(cfg)
    thresholds = _thresholds_block(cfg, endpoints)
    return (
        "export const options = {\n"
        "  stages: [\n"
        f"{stages}\n"
        "  ],\n"
        "  thresholds: {\n"
        f"{thresholds}\n"
        "  },\n"
        "};"
    )


def _stages_block(cfg: dict) -> str:
    """Return the indented stages array lines for the k6 options block."""
    lines = [
        f"    {{ duration: '{cfg['ramp_up_s']}s', target: {cfg['max_vus']} }},   // ramp up",
        f"    {{ duration: '{cfg['sustain_s']}s', target: {cfg['max_vus']} }},   // sustain",
        f"    {{ duration: '{cfg['ramp_down_s']}s', target: 0 }},              // ramp down",
    ]
    return "\n".join(lines)


def _thresholds_block(cfg: dict, endpoints: list[dict]) -> str:
    """Return the indented threshold lines for the k6 options block."""
    lines = [
        f"    http_req_duration: ['p(95)<{cfg['p95_ms']}', 'p(99)<{cfg['p99_ms']}'],",
        f"    http_req_failed: ['rate<{cfg['error_rate']}'],",
        "    checks: ['rate>0.99'],",
    ]
    p95 = cfg["p95_ms"]
    for i, ep in enumerate(endpoints):
        name = ep.get("name", f"endpoint_{i}")
        lines.append(
            f"    'http_req_duration{{name:{name}}}': ['p(95)<{p95}'],"
        )
    return "\n".join(lines)


def _requests_block(endpoints: list[dict], p95_ms: int) -> str:
    """Return the indented per-endpoint request + check blocks."""
    blocks: list[str] = []
    for i, ep in enumerate(endpoints):
        blocks.append(_single_request_block(ep, i, p95_ms))
    return "\n\n".join(blocks)


def _single_request_block(ep: dict, index: int, p95_ms: int) -> str:
    """Return the JS snippet for one endpoint: request line + check block."""
    method = ep.get("method", "GET").upper()
    path = ep.get("path", "/")
    name = ep.get("name", f"endpoint_{index}")
    body = ep.get("body")
    expected_status = ep.get("expected_status", "200")

    tag_param = f"{{ tags: {{ name: '{name}' }} }}"
    request_line = _request_line(method, path, name, body, tag_param)

    check_block = (
        f"  check(res_{name}, {{\n"
        f"    '{name}: status is {expected_status}': (r) => r.status === {expected_status},\n"
        f"    '{name}: p95 < {p95_ms}ms': (r) => r.timings.duration < {p95_ms},\n"
        f"  }});"
    )
    return f"{request_line}\n{check_block}"


def _request_line(
    method: str,
    path: str,
    name: str,
    body: str | None,
    tag_param: str,
) -> str:
    """Return the JS http.* call for a single endpoint."""
    if method == "GET":
        return f"  const res_{name} = http.get(`${{BASE_URL}}{path}`, {tag_param});"
    if method == "DELETE":
        return f"  const res_{name} = http.del(`${{BASE_URL}}{path}`, null, {tag_param});"
    if method in ("POST", "PUT", "PATCH"):
        return _mutation_request_line(method, path, name, body, tag_param)
    # Fallback: treat unknown methods as GET
    return f"  const res_{name} = http.get(`${{BASE_URL}}{path}`, {tag_param});"


def _mutation_request_line(
    method: str,
    path: str,
    name: str,
    body: str | None,
    tag_param: str,
) -> str:
    """Return the JS http.post/put/patch call, with or without a JSON body."""
    m = method.lower()
    if body:
        return (
            f"  const res_{name} = http.{m}(\n"
            f"    `${{BASE_URL}}{path}`,\n"
            f"    JSON.stringify({body}),\n"
            f"    {{ headers: {{ 'Content-Type': 'application/json' }}, tags: {{ name: '{name}' }} }},\n"
            f"  );"
        )
    return (
        f"  const res_{name} = http.{m}(\n"
        f"    `${{BASE_URL}}{path}`,\n"
        f"    null,\n"
        f"    {tag_param},\n"
        f"  );"
    )


def _handle_summary_block() -> str:
    """Return the handleSummary JS function that exports summary.json."""
    return textwrap.dedent("""\
        export function handleSummary(data) {
          return {
            stdout: textSummary(data, { indent: ' ', enableColors: true }),
            'summary.json': JSON.stringify(data, null, 2),
          };
        }""")


# ---------------------------------------------------------------------------
# Notes helper
# ---------------------------------------------------------------------------


def _build_notes(
    base_url: str,
    preset: str,
    cfg: dict,
    endpoints: list[dict],
) -> list[str]:
    """Return human-readable notes describing the generated script."""
    endpoint_names = [ep.get("name", ep.get("path", "?")) for ep in endpoints]
    return [
        f"Preset '{preset}': {cfg['max_vus']} VUs, "
        f"ramp-up {cfg['ramp_up_s']}s / sustain {cfg['sustain_s']}s / ramp-down {cfg['ramp_down_s']}s.",
        f"Thresholds: p95 < {cfg['p95_ms']} ms, p99 < {cfg['p99_ms']} ms, "
        f"error rate < {cfg['error_rate'] * 100:.0f}%.",
        f"Endpoints ({len(endpoints)}): {', '.join(endpoint_names)}.",
        "Per-endpoint http_req_duration thresholds emitted for each named request.",
        "handleSummary() writes summary.json for CI/Grafana/Datadog integration.",
        f"Target: {base_url}  —  override at runtime with BASE_URL env var.",
    ]
