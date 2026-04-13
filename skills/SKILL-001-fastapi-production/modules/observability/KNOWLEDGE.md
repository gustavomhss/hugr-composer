# Module: Observability — Production Telemetry for FastAPI

> The LLM generates: print() debugging, logging.info() with string formatting, no metrics, no tracing.
> The staff engineer ships: OpenTelemetry traces with context propagation, Prometheus RED metrics, structlog with trace correlation, SLO-based alerting, and Grafana dashboards that answer "is the service healthy?" in under 5 seconds.

---

## 1. OpenTelemetry Setup — TracerProvider + BatchSpanProcessor + OTLP

### WHY
Without distributed tracing, debugging a slow request across 3+ services means grepping logs on each host and manually correlating timestamps. OpenTelemetry is the CNCF standard (graduated 2024) — every major backend (Jaeger, Tempo, Datadog, Honeycomb) speaks OTLP natively. Setting up TracerProvider with BatchSpanProcessor and OTLP exporter is the foundation that enables all other observability.

### HOW
```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

def setup_telemetry(service_name: str, otlp_endpoint: str = "http://localhost:4317") -> None:
    """Initialize OpenTelemetry with OTLP exporter. Call ONCE at startup."""
    resource = Resource.create({
        SERVICE_NAME: service_name,
        "service.version": os.getenv("SERVICE_VERSION", "0.1.0"),
        "deployment.environment": os.getenv("ENVIRONMENT", "development"),
    })

    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,
        insecure=True,  # Use TLS in production via OTEL_EXPORTER_OTLP_INSECURE=false
    )

    # BatchSpanProcessor batches spans and exports them asynchronously.
    # Defaults: max_queue_size=2048, max_export_batch_size=512,
    #           schedule_delay_millis=5000, export_timeout_millis=30000
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
```

### GOTCHA
`TracerProvider` must be set BEFORE any auto-instrumentors run. If you call `FastAPIInstrumentor.instrument_app(app)` before `trace.set_tracer_provider(provider)`, spans go to the no-op provider and vanish silently. Initialize telemetry in your lifespan handler BEFORE yielding, or at module scope before the app object is created.

---

## 2. FastAPI Auto-Instrumentation — FastAPIInstrumentor

### WHY
Manual `tracer.start_as_current_span()` on every route is error-prone and misses middleware spans. `FastAPIInstrumentor` automatically creates spans for every HTTP request with method, route, status code, and latency — zero code changes to your routes. It also propagates W3C `traceparent` headers for cross-service correlation.

### HOW
```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# After setting up TracerProvider and creating the FastAPI app:
FastAPIInstrumentor.instrument_app(app,
    excluded_urls="healthz,readyz,startupz,metrics",  # Don't trace probes
)

# To uninstrument (useful in tests):
# FastAPIInstrumentor.uninstrument_app(app)
```

### GOTCHA
With uvicorn `--workers N`, each worker process gets its own TracerProvider. This works correctly. But `--reload` mode forks differently and can cause duplicate spans or lost context. Use `--reload` only in development, never with OTel in production. For multi-worker production, use `gunicorn` with `uvicorn.workers.UvicornWorker` and call `setup_telemetry()` in a `post_fork` hook.

---

## 3. SQLAlchemy Auto-Instrumentation — SQLAlchemyInstrumentor

### WHY
Without DB tracing, a slow endpoint shows 500ms latency but you cannot tell if 450ms was the query or 450ms was serialization. SQLAlchemy instrumentation creates child spans for every query with the SQL statement (sanitized), execution time, and DB connection pool metrics. Instantly reveals N+1 queries, missing indexes, and connection pool exhaustion.

### HOW
```python
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

# Option A: Instrument a specific engine (recommended)
SQLAlchemyInstrumentor().instrument(
    engine=engine,
    enable_commenter=True,   # Adds traceparent as SQL comment for DB-side correlation
)

# Option B: Instrument ALL engines globally
SQLAlchemyInstrumentor().instrument(enable_commenter=True)
```

### GOTCHA
`enable_commenter=True` appends `/* traceparent=... */` as a SQL comment to every query. This is powerful for correlating slow query logs in PostgreSQL with traces. But it increases query string length — if you have a query length limit in your DB proxy or WAF, this can cause truncation. Test with your infrastructure first.

---

## 4. HTTPX Auto-Instrumentation — HTTPXClientInstrumentor

### WHY
If your service calls external APIs, you need to see those calls as child spans in your trace. Without HTTPX instrumentation, outbound HTTP calls are invisible black boxes. The instrumentor automatically creates spans with the target URL, HTTP method, status code, and propagates `traceparent` headers to downstream services.

### HOW
```python
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

# Instrument all httpx clients globally
HTTPXClientInstrumentor().instrument()

# Now any httpx.AsyncClient() call automatically creates spans:
async with httpx.AsyncClient() as client:
    response = await client.get("https://api.example.com/data")
    # ^ This creates a span: HTTP GET api.example.com/data [200] 45ms
```

### GOTCHA
The instrumentor captures the full URL by default, including query parameters. If your URLs contain PII or tokens (e.g., `?api_key=secret`), these appear in your trace backend. Set `OTEL_PYTHON_HTTPX_EXCLUDED_URLS` to exclude sensitive paths, or use a custom `url_filter` hook to sanitize URLs before they become span attributes.

---

## 5. Custom Spans — Business Logic Tracing

### WHY
Auto-instrumentation covers HTTP requests and DB queries, but your business logic is a black box. "The payment took 2 seconds" — was it validation, fraud check, or the gateway call? Custom spans break business operations into measurable steps. They are the difference between "it's slow" and "the fraud check API is slow."

### HOW
```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def process_payment(order_id: str, amount: float) -> PaymentResult:
    with tracer.start_as_current_span("process_payment",
        attributes={"order.id": order_id, "payment.amount": amount},
    ) as span:
        # Step 1: Validate
        with tracer.start_as_current_span("validate_payment"):
            validate(order_id, amount)

        # Step 2: Fraud check
        with tracer.start_as_current_span("fraud_check") as fraud_span:
            risk = await check_fraud(order_id)
            fraud_span.set_attribute("fraud.risk_score", risk.score)
            if risk.blocked:
                span.set_status(trace.StatusCode.ERROR, "Blocked by fraud check")
                raise PaymentBlockedError(order_id)

        # Step 3: Charge
        with tracer.start_as_current_span("gateway_charge"):
            result = await gateway.charge(amount)
            span.set_attribute("payment.gateway_id", result.transaction_id)

        return result
```

### GOTCHA
Span attribute values must be str, bool, int, float, or sequences thereof. Passing a dict or Pydantic model as an attribute silently drops it. Convert to string first: `span.set_attribute("order.data", json.dumps(order.dict()))`. Also, keep attribute count under 128 per span (OTel SDK default limit) — exceeding it silently drops attributes.

---

## 6. Prometheus Metrics — RED Method (Rate, Errors, Duration)

### WHY
Traces tell you WHY a request was slow. Metrics tell you WHAT is happening right now. The RED method (Rate, Errors, Duration) is the standard for request-driven services. Three metrics answer the three critical questions: How much traffic? (Rate), How many failures? (Errors), How fast? (Duration). These feed directly into SLOs and alerting.

### HOW
```python
from prometheus_client import Counter, Gauge, Histogram, Info

# Rate: requests per second (counter, use rate() in PromQL)
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    labelnames=["method", "endpoint", "status"],
)

# Duration: request latency distribution (histogram with percentiles)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    labelnames=["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Saturation: concurrent requests (gauge)
REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Number of HTTP requests currently being processed",
    labelnames=["method"],
)

# Service info (static metadata)
SERVICE_INFO = Info("service", "Service metadata")
SERVICE_INFO.info({"version": "1.0.0", "environment": "production"})
```

### GOTCHA
NEVER use high-cardinality labels like `user_id`, `request_id`, or full URL paths on Prometheus metrics. Each unique label combination creates a new time series. 1000 endpoints x 5 methods x 5 status codes = 25,000 series — manageable. Add `user_id` = millions of series = Prometheus OOM. Use normalized route templates (`/users/{id}`) not actual paths (`/users/12345`).

---

## 7. Structured Logging with OTel Trace Correlation

### WHY
Logs and traces are two views of the same event. Without correlation, you see a trace with a slow span but cannot find the corresponding log line, or vice versa. Injecting `trace_id` and `span_id` into every log line enables one-click navigation from trace to logs and from logs to trace in Grafana/Datadog.

### HOW
```python
import structlog
from opentelemetry import trace

def add_otel_context(logger, method_name, event_dict):
    """structlog processor that injects OTel trace context into every log."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
        event_dict["trace_flags"] = ctx.trace_flags
    return event_dict

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        add_otel_context,                         # <-- inject trace context
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()            # JSONRenderer() in production
        # Use structlog.processors.JSONRenderer() for production
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
```

Output in production (JSON):
```json
{
  "event": "payment_processed",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "trace_flags": 1,
  "order_id": "ORD-123",
  "amount": 99.99,
  "level": "info",
  "timestamp": "2026-04-07T10:30:00Z"
}
```

### GOTCHA
`trace.get_current_span()` returns a `NonRecordingSpan` when no span is active (e.g., background tasks, startup code). The span context `is_valid` check prevents logging invalid zeros. Also, `format(ctx.trace_id, "032x")` produces the W3C-standard 32-char hex string — do NOT use `str(ctx.trace_id)` which gives a Python int representation that no tool can correlate.

---

## 8. SLO Definition — Availability, Latency, Error Rate

### WHY
"The service seems fine" is not engineering. SLOs turn gut feeling into math. A 99.9% availability SLO means you have a 43.2-minute monthly error budget. When the budget is exhausted, you stop feature work and fix reliability. Without SLOs, you argue about priority. With SLOs, the budget decides.

### HOW
```yaml
# slo.yaml — Service Level Objectives
service: my-api
slos:
  - name: availability
    description: "Proportion of successful (non-5xx) requests"
    sli: |
      sum(rate(http_requests_total{status!~"5.."}[5m]))
      / sum(rate(http_requests_total[5m]))
    target: 0.999           # 99.9%
    window: 30d             # Rolling 30-day window
    error_budget: 0.001     # 0.1% of requests can fail
    # Budget: 43.2 min/month, 8.64 hours/year

  - name: latency_p99
    description: "99th percentile request latency under 500ms"
    sli: |
      histogram_quantile(0.99,
        sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
      ) < 0.5
    target: 0.99            # 99% of time, p99 is under 500ms
    window: 30d

  - name: error_rate
    description: "Error rate (5xx) stays below 0.1%"
    sli: |
      sum(rate(http_requests_total{status=~"5.."}[5m]))
      / sum(rate(http_requests_total[5m]))
    target_max: 0.001       # < 0.1% errors
    window: 30d
```

### GOTCHA
SLOs are meaningless without excluding health checks. `/healthz` gets hit every 10 seconds by Kubernetes — that is 8,640 requests/day of artificial "100% success." Always exclude probe endpoints from SLI calculations: `http_requests_total{endpoint!~"/healthz|/readyz|/startupz|/metrics"}`. Also, choose your denominator carefully: do you count 404s as errors? Usually no — 404 is a valid response to an invalid path.

---

## 9. Alerting Rules — Burn Rate Multi-Window Alerts

### WHY
Threshold alerts ("error rate > 1%") fire too late or too often. A 1-minute spike of errors is not an incident — it is noise. A sustained 0.5% error rate for 6 hours burns 10% of your monthly budget — that IS an incident. Multi-window burn rate alerts based on the Google SRE Workbook fire only when error budget consumption threatens your SLO.

### HOW
```yaml
# prometheus_rules.yaml
groups:
  - name: slo_burn_rate
    rules:
      # --- Recording rules: pre-compute error ratios ---
      - record: slo:error_ratio:5m
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m]))
          / sum(rate(http_requests_total[5m]))

      - record: slo:error_ratio:1h
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[1h]))
          / sum(rate(http_requests_total[1h]))

      - record: slo:error_ratio:6h
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[6h]))
          / sum(rate(http_requests_total[6h]))

      # --- PAGE: Fast burn (2% budget in 1 hour) ---
      # burn_rate = error_ratio / error_budget = error_ratio / 0.001
      # 14.4x burn = 100% budget in ~1 hour
      - alert: SLOFastBurn
        expr: |
          slo:error_ratio:1h / 0.001 > 14.4
          and
          slo:error_ratio:5m / 0.001 > 14.4
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "High error burn rate — paging"
          description: "Burning error budget at 14.4x. Will exhaust 30-day budget in ~50 hours."

      # --- TICKET: Slow burn (10% budget in 3 days) ---
      # 1x burn = 100% budget in 30 days. We alert at slightly above 1x.
      - alert: SLOSlowBurn
        expr: |
          slo:error_ratio:6h / 0.001 > 1.0
          and
          slo:error_ratio:1h / 0.001 > 1.0
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Elevated error burn rate — ticket"
          description: "Sustained error rate above SLO budget. Will exhaust budget before window end."
```

### GOTCHA
The short window (`5m`, `1h`) prevents stale alerts from historical spikes. Without the short window, a 1-hour outage that was resolved 5 hours ago still fires the alert because the 6h window remembers it. Always pair a long window with a short window: `long_window AND short_window`. Google SRE recommends `short = long / 12`.

---

## 10. Grafana Dashboard — Essential Panels

### WHY
A Grafana dashboard is not decoration — it is the first thing an on-call engineer looks at during an incident. The wrong dashboard wastes 15 minutes of an outage. The right dashboard has 4 panels matching the Four Golden Signals: Latency, Traffic, Errors, Saturation. Each panel answers one question in under 5 seconds.

### HOW
Essential panels for an API service:

| Panel | Type | PromQL | Purpose |
|-------|------|--------|---------|
| Request Rate | Time series | `sum(rate(http_requests_total[5m])) by (endpoint)` | Traffic volume, detect spikes/drops |
| Error Rate % | Time series | `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) * 100` | Error budget consumption |
| Latency p50/p95/p99 | Time series | `histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))` | Tail latency — where users feel pain |
| Active Requests | Time series | `http_requests_in_progress` | Saturation — is the service overloaded? |
| Latency Heatmap | Heatmap | `sum(increase(http_request_duration_seconds_bucket[5m])) by (le)` | Distribution — reveals bimodal latency |
| Error Budget Remaining | Gauge | `1 - (sum(increase(http_requests_total{status=~"5.."}[30d])) / sum(increase(http_requests_total[30d]))) / 0.001` | SLO burn — how much budget is left |

### GOTCHA
Template variables (`$service`, `$environment`) prevent dashboard sprawl. One dashboard for all services, filtered by dropdown. But do NOT use `$endpoint` as a variable with `=~"$endpoint"` regex match — an attacker who controls route names could inject PromQL. Use exact match `="$endpoint"` or a predefined allowlist. Also, set a reasonable refresh interval (15-30s) — 5s refresh with heavy PromQL causes Prometheus to spend all CPU on dashboard queries instead of scraping.

---

## 11. Health Check Observability — Separate Probe Metrics

### WHY
Health check endpoints (`/healthz`, `/readyz`) are hit every 10 seconds by Kubernetes. If counted in your RED metrics, they inflate request rate by 8,640 requests/day, deflate average latency (they are instant), and mask real error rates. Health checks need their OWN metrics, separate from business traffic.

### HOW
```python
from prometheus_client import Gauge, Histogram

# Separate metrics for probes — NOT counted in http_requests_total
HEALTH_CHECK_DURATION = Histogram(
    "health_check_duration_seconds",
    "Health check response time",
    labelnames=["probe"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1),
)

HEALTH_CHECK_STATUS = Gauge(
    "health_check_up",
    "Health check status (1=healthy, 0=unhealthy)",
    labelnames=["probe"],
)

# In your metrics middleware, SKIP health endpoints:
EXCLUDED_PATHS = {"/healthz", "/readyz", "/startupz", "/metrics"}

class MetricsMiddleware:
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path not in EXCLUDED_PATHS:
                # Record RED metrics for business traffic only
                ...
```

### GOTCHA
Excluding `/metrics` from metrics recording prevents a recursion-like effect where scraping the metrics endpoint creates metrics about scraping. Also, if your readiness check queries the database, add a `health_check_db_duration_seconds` histogram — a slow readiness check can reveal DB connection pool exhaustion before business requests fail.

---

## 12. Cost Optimization — Sampling Strategies

### WHY
At 1000 RPS, full tracing generates ~86 million spans/day. At $0.50/million spans (typical SaaS pricing), that is $43/day or $1,300/month for ONE service. Head-based sampling at 10% cuts this to $130/month with minimal visibility loss. Tail-based sampling keeps 100% of errors and slow requests while dropping 90% of healthy fast requests.

### HOW
```python
from opentelemetry.sdk.trace.sampling import (
    TraceIdRatioBased,
    ParentBasedTraceIdRatio,
)

# Head-based: Sample 10% of traces, but ALWAYS sample if parent was sampled
sampler = ParentBasedTraceIdRatio(0.1)

provider = TracerProvider(resource=resource, sampler=sampler)

# Or via environment variable (no code change):
# OTEL_TRACES_SAMPLER=parentbased_traceidratio
# OTEL_TRACES_SAMPLER_ARG=0.1
```

For tail-based sampling (requires OTel Collector):
```yaml
# otel-collector-config.yaml
processors:
  tail_sampling:
    decision_wait: 10s
    policies:
      # Always keep errors
      - name: errors
        type: status_code
        status_code: { status_codes: [ERROR] }
      # Always keep slow requests (> 1s)
      - name: slow-requests
        type: latency
        latency: { threshold_ms: 1000 }
      # Sample 10% of everything else
      - name: probabilistic
        type: probabilistic
        probabilistic: { sampling_percentage: 10 }
```

### GOTCHA
Head-based sampling makes the decision at trace START — if a trace is dropped, ALL its spans are dropped, including the one that would have revealed the error. This is why tail-based sampling exists: it waits to see the complete trace before deciding. But tail-based requires a stateful OTel Collector that buffers traces, which adds infrastructure complexity. Start with head-based at 10-50%, add tail-based when you hit cost issues with full error/latency capture.

---

## Metrics Middleware — Complete Implementation

Not a separate technique — this ties RED metrics and health check separation together:

```python
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

EXCLUDED_PATHS = frozenset({"/healthz", "/readyz", "/startupz", "/metrics"})

class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record RED metrics for all non-probe requests."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path in EXCLUDED_PATHS:
            return await call_next(request)

        method = request.method

        # Resolve to route template (/users/{id}) not actual path (/users/123)
        route = self._get_route_template(request) or path

        REQUESTS_IN_PROGRESS.labels(method=method).inc()
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = str(response.status_code)
        except Exception:
            status = "500"
            raise
        finally:
            duration = time.perf_counter() - start
            REQUEST_COUNT.labels(method=method, endpoint=route, status=status).inc()
            REQUEST_DURATION.labels(method=method, endpoint=route).observe(duration)
            REQUESTS_IN_PROGRESS.labels(method=method).dec()

        return response

    @staticmethod
    def _get_route_template(request: Request) -> str | None:
        """Extract the route template string, e.g., '/users/{id}'."""
        app = request.app
        for route in getattr(app, "routes", []):
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                return getattr(route, "path", None)
        return None
```

This middleware gives you the exact route template as the label — `/users/{id}` instead of `/users/12345` — preventing cardinality explosion.

---

## Metrics Endpoint — Exposing /metrics for Scraping

Not a separate technique — necessary plumbing for Prometheus to work:

```python
from prometheus_client import REGISTRY, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response as FastAPIResponse

@app.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus scrape endpoint. Excluded from OpenAPI docs."""
    return FastAPIResponse(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )
```

Alternatively, use `prometheus_client.make_asgi_app()` mounted as a sub-application, which is more efficient for high-frequency scraping.
