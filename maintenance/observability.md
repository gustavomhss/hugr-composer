# Observability Domain — Maintenance Skill

> **Crates**: 15 | **Status**: Production-ready | **Owner**: Platform Team | **Last Updated**: 2026-09-04

> **Purpose**: Full-stack observability — logging, metrics, tracing, alerting, and health checks.

---

## Crate Inventory

| Crate | Purpose | Complexity | Maturity |
|-------|---------|------------|----------|
| `AccessLog` | Structured access logging | Low | Production |
| `CardinalityGuard` | Prometheus label cardinality protection | Medium | Production |
| `CorrelationContext` | Correlation ID propagation | Low | Production |
| `CorrelationId` | Request correlation ID generation | Low | Production |
| `ErrorSink` | Centralized error capture | Medium | Production |
| `EventBus` | In-process event bus | Low | Production |
| `HealthProbe` | Liveness/readiness/startup probes | Low | Production |
| `HistogramBuckets` | Prometheus histogram bucket optimization | Low | Production |
| `LifecycleHook` | Application lifecycle management | Low | Production |
| `LlmTrace` | LLM request/response tracing | Medium | Production |
| `MetricMeter` | Prometheus metrics abstraction | Low | Production |
| `ResourceDescriptor` | OpenTelemetry resource attributes | Low | Production |
| `SamplingPolicy` | Trace sampling strategies | Medium | Production |
| `SemanticAttributes` | OpenTelemetry semantic conventions | Low | Production |
| `StructuredLogger` | Structured JSON logging | Low | Production |
| `TelemetryExporter` | OTLP/Jaeger/Prometheus exporters | Medium | Production |
| `Tracer` | OpenTelemetry tracer wrapper | Medium | Production |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      OBSERVABILITY                          │
├─────────────────────────────────────────────────────────────┤
│  Request → CorrelationId → StructuredLogger → Logs         │
│       ↓                                                      │
│  Tracer → Spans → Traces → OTLP Exporter → Jaeger/Tempo    │
│       ↓                                                      │
│  MetricMeter → Metrics → Prometheus Exporter → Prometheus   │
│       ↓                                                      │
│  HealthProbe → Liveness/Readiness → Kubernetes              │
│       ↓                                                      │
│  ErrorSink → Alerting → PagerDuty/Slack                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Structured Logging

```python
# In your app entry point
from generators.observability.structured_logger import StructuredLogger

logger = StructuredLogger(
    service_name="my-service",
    environment="production",
    level="INFO",
)

# Usage
logger.info("User logged in", user_id=user.id, email=user.email)
logger.error("Payment failed", error=str(e), order_id=order_id)
logger.warning("Rate limit exceeded", user_id=user.id, endpoint="/api/pay")
```

**Output** (JSON):
```json
{
  "timestamp": "2026-09-04T10:30:00.123Z",
  "level": "ERROR",
  "message": "Payment failed",
  "service": "my-service",
  "environment": "production",
  "trace_id": "abc123",
  "span_id": "def456",
  "error": "Insufficient funds",
  "order_id": "ord_123"
}
```

---

### 2. Correlation ID Propagation

```python
# Middleware (automatic)
from generators.middleware.correlation import CorrelationMiddleware

app.add_middleware(CorrelationMiddleware)

# In your code - automatically available
from generators.observability.correlation_id import get_correlation_id

@app.get("/api/users/{user_id}")
async def get_user(user_id: str):
    correlation_id = get_correlation_id()  # Auto-propagated
    logger.info("Fetching user", user_id=user_id)
    # All downstream calls inherit correlation_id
```

---

### 3. Metrics (RED Pattern)

```python
from generators.observability.metric_meter import MetricMeter

meter = MetricMeter(service_name="my-service")

# Counter
requests_total = meter.counter(
    "http_requests_total",
    "Total HTTP requests",
    labels=["method", "endpoint", "status"],
)

# Histogram
request_duration = meter.histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    labels=["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# Gauge
active_connections = meter.gauge(
    "active_connections",
    "Current active connections",
)

# Usage
requests_total.inc(labels={"method": "GET", "endpoint": "/api/users", "status": "200"})
request_duration.observe(0.123, labels={"method": "GET", "endpoint": "/api/users"})
active_connections.set(42)
```

---

### 4. Distributed Tracing

```python
from generators.observability.tracer import Tracer

tracer = Tracer(service_name="my-service")

# Automatic instrumentation
@app.get("/api/users/{user_id}")
async def get_user(user_id: str):
    with tracer.start_span("get_user", attributes={"user_id": user_id}) as span:
        user = await user_repo.get(user_id)
        span.set_attribute("user.found", user is not None)
        return user

# Or use decorator
@tracer.trace("get_user")
async def get_user(user_id: str) -> User:
    return await user_repo.get(user_id)
```

---

### 5. Health Probes

```python
from generators.observability.health_probe import HealthProbe, HealthStatus

probe = HealthProbe()

# Liveness - process is alive
@probe.liveness
async def liveness():
    return HealthStatus(
        status="healthy",
        checks={"process": "alive"},
    )

# Readiness - ready to serve traffic
@probe.readiness
async def readiness():
    checks = {
        "database": await db.health_check(),
        "redis": await redis.ping(),
        "dependencies": await check_external_services(),
    }
    return HealthStatus(
        status="healthy" if all(c["healthy"] for c in checks.values()) else "degraded",
        checks=checks,
    )

# Startup - initialization complete
@probe.startup
async def startup():
    await db.migrate()
    await cache.warmup()
    return HealthStatus(status="healthy", checks={})

# Mount in FastAPI
app.include_router(probe.router)
```

---

### 6. OpenTelemetry Export

```python
from generators.observability.otel import generate_otel_setup

# In your scaffold
result = await generate_otel_setup(
    output_dir="/tmp/my-app",
    service_name="my-service",
    exporter="otlp_grpc",  # or "otlp_http", "console"
    with_structlog=True,
)

# Generated files:
# - observability/telemetry.py (TracerProvider, MeterProvider)
# - observability/trace_middleware.py (auto-instrumentation)
# - observability/structlog_processor.py (log enrichment)
```

---

## Common Operations

### 1. Adding Custom Metrics

```python
# In your service
class PaymentService:
    def __init__(self, meter: MetricMeter):
        self.payments_total = meter.counter(
            "payments_total",
            "Total payments processed",
            labels=["status", "provider"],
        )
        self.payment_duration = meter.histogram(
            "payment_duration_seconds",
            "Payment processing duration",
            labels=["provider"],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
        )
    
    async def charge(self, payment: PaymentRequest) -> PaymentResult:
        start = time.time()
        try:
            result = await self.gateway.charge(payment)
            self.payments_total.inc(labels={"status": "success", "provider": "stripe"})
            return result
        except Exception as e:
            self.payments_total.inc(labels={"status": "failed", "provider": "stripe"})
            raise
        finally:
            duration = time.time() - start
            self.payment_duration.observe(duration, labels={"provider": "stripe"})
```

---

### 2. Custom Span Attributes

```python
from generators.observability.semantic_attributes import SemanticAttributes

with tracer.start_span("db.query", kind=SpanKind.CLIENT) as span:
    span.set_attribute(SemanticAttributes.DB_SYSTEM, "postgresql")
    span.set_attribute(SemanticAttributes.DB_OPERATION, "SELECT")
    span.set_attribute(SemanticAttributes.DB_STATEMENT, "SELECT * FROM users WHERE id = ?")
    span.set_attribute(SemanticAttributes.DB_PARAMETER, user_id)
    
    result = await db.execute("SELECT * FROM users WHERE id = ?", user_id)
    
    span.set_attribute(SemanticAttributes.DB_ROWS_RETURNED, len(result))
```

---

### 3. Cardinality Guard

```python
from generators.observability.cardinality_guard import CardinalityGuard

guard = CardinalityGuard(
    max_cardinality=1000,
    on_violation="warn",  # or "drop", "reject"
)

# Use in metric creation
counter = meter.counter(
    "custom_metric",
    "Description",
    labels=["user_id"],  # HIGH CARDINALITY!
)

# Guard will warn if cardinality exceeds threshold
with guard:
    counter.inc(labels={"user_id": user_id})
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **High cardinality labels** | Prometheus OOM | Use `CardinalityGuard`; avoid user_id, request_id as labels |
| **Missing correlation ID** | Can't trace request | Add `CorrelationMiddleware` early |
| **No structured logging** | Unsearchable logs | Use `StructuredLogger` everywhere |
| **Missing health probes** | K8s kills healthy pods | Add liveness/readiness/startup |
| **No tracing** | Can't debug latency | Add `Tracer` + OTLP exporter |
| **High cardinality metrics** | Prometheus OOM | Use `CardinalityGuard`; aggregate labels |
| **No error tracking** | Silent failures | Use `ErrorSink` + alerting |
| **No structured logs** | Can't query logs | Use `StructuredLogger` + JSON output |

---

## Evolution Without Breaking Contracts

### Adding a New Metric

```python
# Non-breaking: add new metric
new_metric = meter.counter(
    "new_metric_total",
    "Description",
    labels=["label1"],
)

# Existing metrics unchanged
```

### Adding a Span Attribute

```python
# Non-breaking: add optional attribute
span.set_attribute("new_attribute", value)
# Consumers ignore unknown attributes
```

---

