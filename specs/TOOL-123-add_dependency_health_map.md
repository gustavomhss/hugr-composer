---
spec_id: "TOOL-123"
tool_name: "add_dependency_health_map"
generator: "generators/endpoints/health.py"
version: "1.0.0"
status: "draft"
invariants:
  - "INV-HMAP-001"
  - "INV-HMAP-002"
  - "INV-HMAP-003"
  - "INV-HMAP-004"
  - "INV-HMAP-005"
  - "INV-HMAP-006"
  - "INV-HMAP-007"
  - "INV-HMAP-008"
  - "INV-HMAP-009"
  - "INV-HMAP-010"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
  - "CC-21"
  - "CC-22"
  - "CC-23"
tags:
  - "performance"
  - "payments"
  - "data"
  - "resiliency"
  - "realtime"
---
# TOOL-123: add_dependency_health_map

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_dependency_health_map` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Dependencies | FastAPI, asyncio, os (stdlib); optional deferred: sqlalchemy, redis.asyncio, aiobotocore |
| Signature | `add_dependency_health_map(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_dependency_health_map", "description": "Add a visual dependency health map: HealthMapBuilder discovers all deps from config (DB, Redis, S3, Stripe), DependencyChecker async health check per dep with latency+status, GET /health/map (JSON graph), GET /health/map.html (self-contained SVG visualization). Config: HEALTH_MAP_ENABLED, HEALTH_MAP_CHECK_INTERVAL_S.", "tags": ["extend", "infrastructure"], "entry": "add_dependency_health_map"}` |
| Files created (typical) | 3 — `app/health_map/__init__.py`, `app/health_map/checker.py`, `app/api/routes/health_map.py` |
| Files modified (typical) | 2 — `app/core/config.py`, `app/main.py` |

---

## 2. Purpose

The `fastapi_add_dependency_health_map` tool installs a production-grade dependency health visualization layer into a FastAPI project. In on-call situations — a 3 AM PagerDuty alert, a staging deploy that is silently broken, a downstream outage whose blast radius is unclear — the most expensive question is *which dependency is the actual problem*. An application can have a healthy API pod while every downstream service it relies on is degraded or down; without a consolidated, visually scannable view, the on-call engineer must SSH into each pod, check individual healthchecks, and mentally aggregate the results under time pressure. This tool eliminates that sequence entirely by providing two endpoints that answer the question at a glance: `GET /health/map` returns the dependency graph as machine-readable JSON suitable for alerting rules and dashboards, and `GET /health/map.html` returns a self-contained SVG star-topology diagram where each dependency node is color-coded green (healthy), amber (degraded), or red (unhealthy) with its round-trip latency displayed below its label — no build step, no JavaScript framework, no external CDN, just a single HTTP response the on-call engineer can open in any browser.

The tool generates a `HealthMapBuilder` singleton in `app/health_map/__init__.py` that auto-discovers dependencies by inspecting environment variables: if `POSTGRES_SERVER` is set, the database appears in the map; if `REDIS_URL` is set, Redis appears; `AWS_S3_BUCKET` adds S3; `STRIPE_SECRET_KEY` adds Stripe. This means the map is always accurate to the current deployment's configuration — no manual registration required for the four standard dependency types. For non-standard dependencies (custom third-party APIs, internal microservices), `HealthMapBuilder.register(name, check_fn)` accepts an async callable returning a status dict, which is folded into the same graph. Each health check is performed by `DependencyChecker` in `app/health_map/checker.py`, which wraps every check in `asyncio.wait_for(..., timeout=5.0)` so a hung dependency cannot hold up the entire health map response. All optional SDK imports — `redis.asyncio`, `aiobotocore`, `stripe`, `sqlalchemy` — are deferred inside the check methods and never appear at module top level, ensuring the module loads cleanly even in environments where those packages are not installed.

The `build_graph()` method runs all checks concurrently via `asyncio.gather`, aggregates node statuses with a worst-case policy (any `error` or `unhealthy` node makes the overall graph `unhealthy`; any `degraded` without `unhealthy`/`error` yields `degraded`; otherwise `healthy`), and returns a JSON-serialisable dict with `status`, `nodes`, and `edges` keys. The HTML endpoint converts that graph into an SVG star topology: the API service sits at the centre, spokes radiate outward to each dependency node, and a `<pre>` block below the SVG shows the raw JSON so the page is simultaneously human-readable and copy-pasteable into a ticket. The HTML endpoint sets HTTP 503 when the overall status is `unhealthy`, so monitoring probes that simply check for non-2xx can integrate with it directly.

Config fields `HEALTH_MAP_ENABLED` (default `false`) and `HEALTH_MAP_CHECK_INTERVAL_S` (default `30`) are injected into `class Settings` with 4-space indent inside `app/core/config.py`. The router is registered in `app/main.py` automatically. The tool is idempotent: a second run detects `"HealthMapBuilder" in app/health_map/__init__.py` and returns `status="no_op"` without modifying any file.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (CC-17) |
| Files created | ≥ 3 | health_map package, checker, and routes file are always emitted (CC-04) |
| Files modified | ≥ 1 | config.py always patched with HEALTH_MAP_ENABLED field (CC-05) |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk over `app/health_map/` subtree (CC-07) |
| `GET /health/map` latency | < 5 s | Bounded by per-check `asyncio.wait_for` timeout of 5.0 s; all checks run concurrently (CC-20) |
| `GET /health/map.html` latency | < 5 s | Same concurrent check budget; SVG render is pure Python string ops (CC-13) |
| Health check timeout | = 5.0 s | `_TIMEOUT_S = 5.0` in checker.py; `asyncio.TimeoutError` returns `"unhealthy"` with `latency_ms = 5000` (CC-20) |
| Optional SDK import cost | 0 ms | All optional SDKs deferred inside check methods; never at module top level (CC-16) |
| Config patch idempotency | 0 modifications on second run | `_patch_config` short-circuits when `HEALTH_MAP_ENABLED` already present (CC-02) |
| Syntax correctness of all generated files | 100% | `ast.parse()` validation loop on all created `.py` files before returning success (CC-06) |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no health map router
│   ├── core/
│   │   └── config.py        # Settings class, no HEALTH_MAP_* fields
│   └── api/
│       └── routes/          # No health_map.py
└── requirements.txt
```

On-call engineer suspects Redis is degraded. Sequence: SSH to pod → `redis-cli ping` → check logs → check Datadog → file ticket. Mean time to dependency identification: 4–8 minutes under stress.

### 4.2 HealthMapBuilder singleton: AFTER

```python
# app/health_map/__init__.py

_KNOWN_DEPS = {
    "database": "POSTGRES_SERVER",
    "redis":    "REDIS_URL",
    "s3":       "AWS_S3_BUCKET",
    "stripe":   "STRIPE_SECRET_KEY",
}

class HealthMapBuilder:
    def __init__(self) -> None:
        self._extra: dict[str, Any] = {}

    def discover(self) -> list[str]:
        found = []
        for dep, env_key in _KNOWN_DEPS.items():
            if os.getenv(env_key, ""):
                found.append(dep)
        found.extend(self._extra.keys())
        return found

    def register(self, name: str, check_fn: Any) -> None:
        self._extra[name] = check_fn

    async def build_graph(self) -> dict[str, Any]:
        from app.health_map.checker import DependencyChecker
        checker = DependencyChecker()
        dep_names = self.discover()
        results = await asyncio.gather(
            *[checker.check(name) for name in dep_names],
            return_exceptions=True,
        )
        nodes = []
        for name, res in zip(dep_names, results):
            if isinstance(res, Exception):
                nodes.append({"name": name, "status": "error", "latency_ms": 0})
            else:
                nodes.append(res)
        edges = [{"from": "api", "to": n["name"]} for n in nodes]
        overall = _aggregate(nodes)
        return {"status": overall, "nodes": nodes, "edges": edges}

_builder: HealthMapBuilder | None = None

def get_health_map_builder() -> HealthMapBuilder:
    global _builder
    if _builder is None:
        _builder = HealthMapBuilder()
    return _builder
```

### 4.3 DependencyChecker with timeout: AFTER

```python
# app/health_map/checker.py

_TIMEOUT_S = 5.0

class DependencyChecker:
    async def check(self, name: str) -> dict[str, Any]:
        dispatch = {
            "database": self._check_database,
            "redis":    self._check_redis,
            "s3":       self._check_s3,
            "stripe":   self._check_stripe,
        }
        fn = dispatch.get(name, self._check_unknown)
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(fn(name), timeout=_TIMEOUT_S)
            result["latency_ms"] = int((time.monotonic() - t0) * 1000)
            return result
        except asyncio.TimeoutError:
            return {"name": name, "status": "unhealthy",
                    "latency_ms": int(_TIMEOUT_S * 1000), "detail": "timeout"}
        except Exception as exc:
            return {"name": name, "status": "unhealthy",
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                    "detail": str(exc)}

    async def _check_redis(self, name: str) -> dict[str, Any]:
        from redis.asyncio import Redis  # deferred — optional SDK
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = Redis.from_url(url, decode_responses=True)
        try:
            await client.ping()
        finally:
            await client.aclose()
        return {"name": name, "status": "healthy", "detail": "pong"}

    async def _check_s3(self, name: str) -> dict[str, Any]:
        import aiobotocore.session  # deferred — optional SDK
        bucket = os.getenv("AWS_S3_BUCKET", "")
        session = aiobotocore.session.get_session()
        async with session.create_client("s3") as client:
            await client.head_bucket(Bucket=bucket)
        return {"name": name, "status": "healthy", "detail": bucket}
```

### 4.4 JSON and HTML endpoints: AFTER

```python
# app/api/routes/health_map.py

router = APIRouter(prefix="/health", tags=["health-map"])

@router.get("/map", response_model=dict[str, Any])
async def dependency_map() -> dict[str, Any]:
    builder = get_health_map_builder()
    return await builder.build_graph()

@router.get("/map.html", response_class=HTMLResponse)
async def dependency_map_html(response: Response) -> HTMLResponse:
    builder = get_health_map_builder()
    graph = await builder.build_graph()
    if graph.get("status") == "unhealthy":
        response.status_code = 503
    nodes = graph.get("nodes", [])
    graph_json = json.dumps(graph, indent=2)
    html = _render_svg_page(nodes, graph_json)
    return HTMLResponse(content=html)
```

### 4.5 Config injection: AFTER

```python
# app/core/config.py (patch excerpt)

class Settings(BaseSettings):
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # ... existing fields ...

    # Dependency health map — added by add_dependency_health_map tool
    HEALTH_MAP_ENABLED: bool = False
    HEALTH_MAP_CHECK_INTERVAL_S: int = 30
```

---

## 5. Quality Standards

| Standard | Requirement |
|----------|-------------|
| Syntax | All generated `.py` files pass `ast.parse()` before `ToolResult` is returned |
| Function size | No generated function exceeds 50 LOC (AST walk over `app/health_map/`) |
| Lazy imports | `redis`, `aiobotocore`, `stripe`, `sqlalchemy` never imported at module top level in health_map files |
| Config indent | `HEALTH_MAP_ENABLED` and `HEALTH_MAP_CHECK_INTERVAL_S` start with 4 spaces (inside `class Settings`) |
| Idempotency | Second run returns `status="no_op"` with empty `files_created` and `files_modified` |
| Dry-run safety | `dry_run=True` writes zero bytes; project directory is unchanged |
| Timeout safety | Every per-dependency check wrapped in `asyncio.wait_for(..., timeout=_TIMEOUT_S)` |
| 503 on unhealthy | HTML endpoint sets `response.status_code = 503` when overall status is `"unhealthy"` |
| Graph contract | `build_graph()` always returns dict with `"status"`, `"nodes"`, and `"edges"` keys |
| Register API | `HealthMapBuilder.register(name, check_fn)` enables custom dependency injection |
| No forbidden external deps | Generated health_map files do not import `requests`, `boto3` (sync), or any other forbidden SDK at module level |
| Concurrent checks | All dep checks run via `asyncio.gather` — never sequential blocking calls |

---

## 6. Completeness Criteria

Each criterion maps to a test function in `adapt/extend/infrastructure/test_add_dependency_health_map.py`.

| ID | Criterion | Test function |
|----|-----------|---------------|
| CC-01 | Tool returns `status="success"` on a fresh fixture project | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with no `files_created` or `files_modified` | `test_idempotent` |
| CC-03 | `dry_run=True` returns success but writes no files; project directory is byte-for-byte identical before/after | `test_dry_run` |
| CC-04 | At least 3 files are created and all paths exist on disk | `test_files_created_count` |
| CC-05 | At least 1 file is modified and all paths exist on disk | `test_files_modified_count` |
| CC-06 | Every `.py` file in the project parses without `SyntaxError` (recursive `ast.parse`) | `test_all_py_parse` |
| CC-07 | No generated function in `app/health_map/` exceeds 50 LOC (AST walk via `ast.FunctionDef` / `ast.AsyncFunctionDef`) | `test_no_function_over_50_loc` |
| CC-08 | `HEALTH_MAP_ENABLED` and `HEALTH_MAP_CHECK_INTERVAL_S` are present in `app/core/config.py`, and the line containing `HEALTH_MAP_ENABLED` starts with 4 spaces | `test_config_fields_patched` |
| CC-09 | `app/health_map/__init__.py` exists and contains both `HealthMapBuilder` and `get_health_map_builder` | `test_health_map_builder_init` |
| CC-10 | `app/main.py` contains the string `"health_map"` confirming router registration | `test_routes_registered` |
| CC-11 | `app/health_map/checker.py` exists, contains `DependencyChecker`, and contains `async def check` | `test_dependency_checker_created` |
| CC-12 | `app/api/routes/health_map.py` exists and contains both `/map` and `map.html` endpoint definitions | `test_health_map_routes_file` |
| CC-13 | `app/api/routes/health_map.py` contains SVG markup (`<svg` or `svg`) for the visualization | `test_svg_visualization_present` |
| CC-14 | `app/health_map/__init__.py` uses `os.getenv` or `environ` and references `POSTGRES_SERVER` or `database` and `REDIS_URL` or `redis` | `test_discover_uses_env_vars` |
| CC-15 | `app/health_map/checker.py` contains all four dependency names: `database`, `redis`, `s3`, `stripe` | `test_checker_covers_known_deps` |
| CC-16 | No optional SDK (`redis`, `aiobotocore`, `stripe`) is imported at module top level in any health_map `.py` file (AST walk over `tree.body`) | `test_no_top_level_optional_sdk_imports` |
| CC-17 | `result.execution_time_ms` is a positive integer | `test_execution_time_recorded` |
| CC-18 | `result.next_steps` is non-empty and mentions `HEALTH_MAP_ENABLED` or `health` | `test_next_steps_present` |
| CC-19 | `HealthMapBuilder` has a `def register` method in `app/health_map/__init__.py` | `test_register_method_exists` |
| CC-20 | `app/health_map/__init__.py` contains both `nodes` and `edges` keys in `build_graph` implementation | `test_build_graph_structure` |
| CC-21 | `app/api/routes/health_map.py` contains the literal `"503"` confirming 503 response on unhealthy | `test_html_route_returns_503_on_unhealthy` |
| CC-22 | `app/health_map/checker.py` contains `wait_for` or `timeout` confirming timeout enforcement | `test_checker_has_timeout` |
| CC-23 | `result.notes` mentions `graph` or `dependency` AND mentions `html`, `visual`, or `svg` | `test_notes_mention_graph_and_svg` |
| CC-LAST | After two sequential runs all `.py` files in the project remain parseable | `test_idempotent_project_still_parses` |

---

## 7. Definition of Done

The tool is complete when:

1. `adapt/extend/infrastructure/test_add_dependency_health_map.py` — all 24 test functions (`CC-01` through `CC-LAST`) pass when run with `PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_dependency_health_map.py -v`.
2. `app/health_map/__init__.py` — contains `HealthMapBuilder` class with `discover()`, `register()`, `build_graph()` methods and `get_health_map_builder()` singleton; `discover()` uses `os.getenv` keyed on `_KNOWN_DEPS`; `build_graph()` uses `asyncio.gather` and returns `{"status": ..., "nodes": [...], "edges": [...]}`.
3. `app/health_map/checker.py` — contains `DependencyChecker` with `async def check(self, name)` dispatching to `_check_database`, `_check_redis`, `_check_s3`, `_check_stripe`, `_check_unknown`; all optional SDKs (`redis.asyncio`, `aiobotocore`, `sqlalchemy`) imported lazily inside their respective check methods; every check wrapped in `asyncio.wait_for(..., timeout=_TIMEOUT_S)`.
4. `app/api/routes/health_map.py` — contains `GET /health/map` returning JSON graph and `GET /health/map.html` returning `HTMLResponse` with inline SVG; HTML endpoint sets `response.status_code = 503` when `graph["status"] == "unhealthy"`.
5. `app/core/config.py` — `HEALTH_MAP_ENABLED: bool = False` and `HEALTH_MAP_CHECK_INTERVAL_S: int = 30` injected with 4-space indent inside `class Settings`.
6. `app/main.py` — imports and includes `health_map_router`.
7. All generated `.py` files pass `ast.parse()` with zero `SyntaxError`.
8. No generated function in `app/health_map/` exceeds 50 LOC.
9. Second run returns `status="no_op"` without modifying any file.
10. `dry_run=True` writes no bytes and returns `status="success"`.

---

## 8. Invariants

| ID | Invariant | Enforced by |
|----|-----------|-------------|
| INV-HMAP-001 | Idempotency fingerprint is `"HealthMapBuilder" in app/health_map/__init__.py` | Tool source; CC-02 |
| INV-HMAP-002 | `os.getenv` is the sole mechanism for dependency discovery; no hardcoded host strings | CC-14 |
| INV-HMAP-003 | Optional SDKs (`redis`, `aiobotocore`, `stripe`, `sqlalchemy`) are never imported at module top level | CC-16 |
| INV-HMAP-004 | All per-dependency checks use `asyncio.wait_for` with `_TIMEOUT_S = 5.0` | CC-22 |
| INV-HMAP-005 | `build_graph()` always returns a dict with `"status"`, `"nodes"`, and `"edges"` keys | CC-20 |
| INV-HMAP-006 | HTML endpoint (`GET /health/map.html`) sets HTTP 503 when overall status is `"unhealthy"` | CC-21 |
| INV-HMAP-007 | `_aggregate(nodes)` uses worst-case logic: `error`/`unhealthy` → `"unhealthy"`, then `"degraded"`, else `"healthy"` | Tool source |
| INV-HMAP-008 | Config fields are injected with 4-space indent inside `class Settings` | CC-08 |
| INV-HMAP-009 | `dry_run=True` writes zero bytes and returns `status="success"` | CC-03 |
| INV-HMAP-010 | All generated `.py` files pass `ast.parse()` before the tool returns `status="success"` | CC-06 |

---

## 9. User Stories

**Story 1 — On-call triage in 30 seconds**
As an SRE who just received a PagerDuty alert at 3 AM, I open `https://api.myapp.com/health/map.html` and immediately see that the Redis node is red with 5000 ms latency while the database node is green. I do not need to SSH anywhere. I know the blast radius in under 30 seconds.

**Story 2 — Automated alerting integration**
As a platform engineer, I configure my uptime monitor to `GET /health/map` every 30 seconds and alert on any non-`"healthy"` status in the `status` field. The endpoint also returns HTTP 503 on the HTML route, so a naive HTTP-status probe also works as a fallback.

**Story 3 — Custom microservice in the map**
As a backend developer, my application calls an internal payment orchestrator at `https://payments-internal/`. I register it with:
```python
builder = get_health_map_builder()
builder.register("payments-internal", check_payments_internal)
```
It appears in the SVG alongside database, Redis, and Stripe without any other changes.

**Story 4 — Zero-cost environments**
As a developer running the service locally without Redis or S3, `HealthMapBuilder.discover()` returns only the dependencies whose env vars are set. The health map renders correctly for the one or two deps I have configured, with no errors about missing optional SDK imports.

**Story 5 — Staging gate validation**
As a CI engineer, I run `curl -s https://staging-api/health/map | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d['status']=='healthy' else 1)"` as a post-deploy smoke test. A degraded Redis fails the deploy pipeline before it reaches production.

---

## 10. Design Decisions

### DD-01: Discovery via env vars rather than config file
Discovering dependencies from environment variables means the health map automatically reflects what is actually configured in each environment. A staging deploy without Stripe configured simply omits the Stripe node — there is no configuration drift between what the map shows and what the application actually connects to.

### DD-02: Concurrent checks via `asyncio.gather`
All dependency checks run concurrently rather than sequentially. A sequential implementation would multiply the worst-case response time by the number of dependencies — with four deps each timing out at 5 s, sequential would block for 20 s. `asyncio.gather` bounds the total response time at `max(check_latencies)`, not their sum.

### DD-03: Hard timeout of 5.0 s per check via `asyncio.wait_for`
Without a timeout, a hung network connection (e.g., TCP handshake to a crashed Redis node) would hold the health endpoint open indefinitely. `asyncio.wait_for` with `_TIMEOUT_S = 5.0` provides a hard bound; the check returns `{"status": "unhealthy", "latency_ms": 5000, "detail": "timeout"}` which is the correct semantics — a dependency that does not respond in 5 s is, for operational purposes, unhealthy.

### DD-04: Lazy optional SDK imports
`redis.asyncio`, `aiobotocore`, and `sqlalchemy` are imported inside their respective check methods. This means the `app/health_map/` package loads cleanly in any Python environment regardless of which optional SDKs are installed. An application that does not use Redis can still load the health map module; the Redis check will simply fail if invoked without the package (which it will not be, since `REDIS_URL` is not set and `discover()` will not include it).

### DD-05: Self-contained SVG — no build step
The HTML endpoint generates a self-contained SVG using pure Python string formatting. There is no JavaScript build step, no external CDN dependency, no webpack, no React. The page renders correctly in any browser from a single HTTP response. This is deliberately chosen over a richer interactive visualization (D3.js, Cytoscape) because those options require either a build pipeline or a CDN dependency, both of which fail silently when the network is unreliable — exactly the scenario where the health map is most needed.

### DD-06: 503 on unhealthy HTML endpoint
Returning HTTP 503 from `GET /health/map.html` when any dependency is unhealthy makes the endpoint compatible with monitoring systems that check only HTTP status codes. A Kubernetes liveness probe, an uptime robot, or a Pingdom check can all trigger on 503 without parsing JSON.

### DD-07: `_aggregate` uses worst-case semantics
Any `error` or `unhealthy` node makes the overall graph `unhealthy`; `degraded` bubbles up only if no node is `error`/`unhealthy`. This is conservative by design — a health map that reports `degraded` when a dependency is actually down is worse than no health map at all. False negatives in health checks are operationally more dangerous than false positives.

---

## 11. Dependencies

| Dependency | Version | Why |
|------------|---------|-----|
| fastapi | ≥ 0.100.0 | `APIRouter`, `HTMLResponse`, `Response` |
| asyncio | stdlib | `gather`, `wait_for` |
| os | stdlib | `os.getenv` for dependency discovery |
| math | stdlib | `math.cos`/`math.sin` for SVG polar layout |
| json | stdlib | JSON serialisation of graph for HTML page |
| redis[asyncio] | ≥ 5.0.0 | Optional; deferred in `_check_redis` |
| aiobotocore | ≥ 2.0.0 | Optional; deferred in `_check_s3` |
| sqlalchemy[asyncio] | ≥ 2.0.0 | Optional; deferred in `_check_database` |

No new entries are added to `requirements.txt` by this tool — all optional SDKs are expected to already be present if the corresponding env var is configured. The tool relies on deferred imports to avoid import-time failures.

---

## 12. Error Handling

| Scenario | Behaviour |
|----------|-----------|
| `validate_project_dir` fails | Return `ToolResult(status="error", error=<message>)` immediately |
| Prerequisites not met | Return `ToolResult(status="error", error="Prerequisites not met: ...")` with `notes` pointing to `fastapi_generate_project` |
| `app/core/config.py` does not exist | Skip config patch; `files_modified` remains empty for that file |
| `app/api/routes/` does not exist | Skip route file creation; `files_created` does not include the routes file |
| `app/main.py` does not exist | Skip main.py patch; router registration is skipped |
| Dependency check times out | `DependencyChecker.check()` catches `asyncio.TimeoutError` and returns `{"name": ..., "status": "unhealthy", "latency_ms": 5000, "detail": "timeout"}` |
| Dependency check throws any exception | Caught by bare `except Exception`; returns `{"name": ..., "status": "unhealthy", "latency_ms": ..., "detail": str(exc)}` |
| `asyncio.gather` returns `Exception` for a check | Top-level `isinstance(res, Exception)` guard in `build_graph()` maps it to `{"name": ..., "status": "error", "latency_ms": 0}` |
| Generated `.py` file has `SyntaxError` | Tool returns `ToolResult(status="error", error=f"Generated file has syntax error: {p}: {exc}")` |
| `_patch_config`: `HEALTH_MAP_ENABLED` already present | `_patch_config` short-circuits with no write |
| `_patch_main`: `"health_map"` already present | `_patch_main` short-circuits with no write |
| Idempotency guard triggers | Returns `ToolResult(status="no_op", notes=["HealthMapBuilder already present..."])` |

---

## 13. Security Considerations

| Concern | Mitigation |
|---------|------------|
| Health map endpoint leaks internal topology | `GET /health/map` and `GET /health/map.html` are unauthenticated by default; operators MUST add auth middleware (e.g., `require_dpop` or a shared-secret header) before exposing to the public internet |
| Stripe key presence check | `_check_stripe` only verifies that `STRIPE_SECRET_KEY` is set; it does not make a live Stripe API call and does not include the key value in any response |
| S3 bucket name in health response | `_check_s3` includes the bucket name in `"detail"` on success — operators handling PCI/HIPAA data SHOULD remove the `"detail"` field from the public `/health/map` response via a response filter |
| Redis URL in logs | `logger.warning("Redis health check failed: %s", exc)` logs the exception message which may include the Redis URL; use a redacting log handler in production |
| SVG injection | Dependency names used as SVG text labels are sourced from `_KNOWN_DEPS` keys (hardcoded) and `register()` calls (developer-controlled); user-supplied input never flows directly into SVG |
| Timeout prevents hanging on attacker-controlled endpoints | Custom `register()` check functions are wrapped by the same `asyncio.wait_for` timeout in `build_graph()` via the `asyncio.gather` contract |

---

## 14. Testing Guide

### Running the test file

```bash
# With pytest (recommended)
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_dependency_health_map.py -v

# Without pytest (standalone runner)
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_dependency_health_map.py
```

### Test file location

`adapt/extend/infrastructure/test_add_dependency_health_map.py`

### Test inventory

| Test function | CC | What it verifies |
|---------------|----|------------------|
| `test_success_status` | CC-01 | `result.status == "success"` on fresh project |
| `test_idempotent` | CC-02 | Second run → `status="no_op"`, zero files created/modified |
| `test_dry_run` | CC-03 | `dry_run=True` → no bytes written; project identical before/after |
| `test_files_created_count` | CC-04 | `len(files_created) >= 3`; all paths exist on disk |
| `test_files_modified_count` | CC-05 | `len(files_modified) >= 1`; all paths exist on disk |
| `test_all_py_parse` | CC-06 | All `.py` files under project root parse without `SyntaxError` |
| `test_no_function_over_50_loc` | CC-07 | AST walk over `app/health_map/`; no function > 50 LOC |
| `test_config_fields_patched` | CC-08 | `HEALTH_MAP_ENABLED` + `HEALTH_MAP_CHECK_INTERVAL_S` in config; 4-space indent |
| `test_health_map_builder_init` | CC-09 | `app/health_map/__init__.py` has `HealthMapBuilder` + `get_health_map_builder` |
| `test_routes_registered` | CC-10 | `"health_map"` present in `app/main.py` |
| `test_dependency_checker_created` | CC-11 | `checker.py` has `DependencyChecker` + `async def check` |
| `test_health_map_routes_file` | CC-12 | Routes file has `/map` and `map.html` endpoints |
| `test_svg_visualization_present` | CC-13 | Routes file contains SVG markup |
| `test_discover_uses_env_vars` | CC-14 | `__init__.py` uses `os.getenv`/`environ`; has `POSTGRES_SERVER`/`database` and `REDIS_URL`/`redis` |
| `test_checker_covers_known_deps` | CC-15 | `checker.py` contains all of: `database`, `redis`, `s3`, `stripe` |
| `test_no_top_level_optional_sdk_imports` | CC-16 | AST walk over `tree.body`; no `redis`/`aiobotocore`/`stripe` at module level |
| `test_execution_time_recorded` | CC-17 | `result.execution_time_ms > 0` |
| `test_next_steps_present` | CC-18 | `next_steps` non-empty; mentions `HEALTH_MAP_ENABLED` or `health` |
| `test_register_method_exists` | CC-19 | `def register` present in `__init__.py` |
| `test_build_graph_structure` | CC-20 | `__init__.py` contains `nodes` and `edges` |
| `test_html_route_returns_503_on_unhealthy` | CC-21 | Routes file contains `"503"` |
| `test_checker_has_timeout` | CC-22 | `checker.py` contains `wait_for` or `timeout` |
| `test_notes_mention_graph_and_svg` | CC-23 | Notes mention graph/dependency AND html/visual/svg |
| `test_idempotent_project_still_parses` | CC-LAST | Two runs → all `.py` files remain parseable |

### Manual verification checklist

- [ ] `GET /health/map` returns valid JSON with `status`, `nodes`, `edges`
- [ ] `GET /health/map.html` returns `text/html` with inline `<svg>`
- [ ] With all deps configured, SVG shows correct node count and color-coded status
- [ ] With Redis configured but unreachable, `/health/map` shows `status: "unhealthy"` for Redis node
- [ ] `/health/map.html` returns HTTP 503 when any dep is unhealthy
- [ ] `/health/map.html` returns HTTP 200 when all deps are healthy
- [ ] Custom dep registered via `register()` appears in both JSON and SVG
- [ ] No optional SDK import at module top level verified with `python3 -c "import app.health_map"`

---

## 15. Files Reference

| File | Role | Created/Modified |
|------|------|-----------------|
| `adapt/extend/infrastructure/add_dependency_health_map.py` | Tool entry point; orchestrates all writes and patches | Source (not generated) |
| `adapt/extend/infrastructure/test_add_dependency_health_map.py` | Test suite; 24 test functions CC-01…CC-LAST | Source (not generated) |
| `app/health_map/__init__.py` | `HealthMapBuilder` class; `discover()`, `register()`, `build_graph()`; `get_health_map_builder()` singleton | Created by tool |
| `app/health_map/checker.py` | `DependencyChecker` class; `async check(name)`; per-dep check methods with lazy imports | Created by tool |
| `app/api/routes/health_map.py` | `GET /health/map` JSON route; `GET /health/map.html` SVG route; `_render_svg_page()`; `_status_color()` | Created by tool |
| `app/core/config.py` | Receives `HEALTH_MAP_ENABLED: bool = False` and `HEALTH_MAP_CHECK_INTERVAL_S: int = 30` | Modified by tool |
| `app/main.py` | Receives `health_map_router` import and `app.include_router(health_map_router)` | Modified by tool |

---

## 16. Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-04-15 | Initial spec — 24 CCs, HealthMapBuilder discovery, DependencyChecker with asyncio.wait_for, JSON+SVG routes, 503 on unhealthy, lazy optional SDK imports |
