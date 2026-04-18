# TOOL-102: add_anomaly_detector

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_anomaly_detector` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, pydantic-settings, httpx (lazy import only) |
| Signature | `add_anomaly_detector(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and optional `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_anomaly_detector", "description": "Add per-request statistical anomaly detection (Z-score + EMA) with webhook alerting for FastAPI services.", "tags": ["extend", "infrastructure"], "entry": "add_anomaly_detector"}` |
| Files created (typical) | 6 — `app/anomaly/__init__.py`, `app/anomaly/detector.py`, `app/anomaly/alerter.py`, `app/anomaly/models.py`, `app/middleware/anomaly.py`, `app/api/routes/anomaly.py` |
| Files modified (typical) | 1 — `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_anomaly_detector` tool installs a statistical anomaly detection system into a FastAPI project that surfaces unusual traffic patterns, error spikes, and latency shifts in real time without requiring an external APM agent. APM agents are excellent for historical analysis but present three problems at service launch: they require sidecar processes or vendor SDK initialisation; they add per-request latency for metric shipping; and they use static thresholds that are almost always wrong because there is no historical baseline when the service is new. The generated system learns its own baseline from observed traffic and triggers alerts relative to that baseline rather than to hand-coded thresholds.

The core algorithm combines two techniques. **Z-score detection**: for each of four metrics — `request_rate` (requests/second since previous request), `error_rate` (1.0 for 5xx, 0.0 otherwise), `latency_ms` (request duration), `payload_bytes` (response `Content-Length`) — the detector maintains a `_MetricWindow` backed by a `deque(maxlen=window_size)`. The window computes population mean `μ` and standard deviation `σ` across its samples, then `z_score(value) = (value - μ) / max(1e-9, σ)`. If `|z_score| > sensitivity` (default 3.0 — three standard deviations), the value is flagged as an anomaly. A warm-up guard prevents false positives: Z-score returns `None` when fewer than 10 samples have been collected. **EMA tracking**: alongside the Z-score, each window tracks an exponential moving average using `ema = alpha * value + (1 - alpha) * ema` (default `alpha=0.1`). The EMA provides a smoothed trend line that is exposed in the `baseline()` response for dashboard visualization. Both computations use stdlib `math` only — no `numpy`, no `scipy`, zero additional dependency footprint.

`AnomalyDetector.observe(status_code, duration_ms, payload_bytes)` computes all four metrics, runs Z-score detection, and for each breach appends an `AnomalyEvent` dict to a rolling store (maximum 1 000 events; pruned to 500 on overflow). `AlertDispatcher.dispatch(anomaly)` always logs at `WARNING` level and, if `ANOMALY_ALERT_WEBHOOK_URL` is configured, POSTs the anomaly JSON via `httpx.AsyncClient` (imported lazily inside `dispatch()` — the module does not import httpx at the top level). `AnomalyMiddleware` calls `asyncio.ensure_future(dispatcher.dispatch(anom))` for each detected anomaly, ensuring alert delivery never blocks the response. `GET /anomaly/status` exposes current baselines (mean, std, ema, count) for all four metrics and the last 20 anomaly events.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget |
| Files created | ≥ 5 | anomaly package (4 files) + middleware + route (CC-04) |
| Files modified | ≥ 1 | Config patch (CC-05) |
| Max function LOC | ≤ 50 | AST walk enforced |
| Per-request observation overhead | < 0.5 ms | In-process deque append + Z-score; no I/O synchronously |
| Webhook dispatch | Non-blocking | `asyncio.ensure_future()` in middleware |
| Z-score computation | < 0.1 ms | Bounded deque + linear scan with `sum()`/`math.sqrt()` |
| External dependencies for Z-score | 0 | stdlib `math` + `collections.deque` only |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
app/
├── main.py
├── core/config.py    # No ANOMALY_* settings
├── api/routes/       # No /anomaly routes
└── middleware/       # No AnomalyMiddleware
```

No anomaly detection. A sudden 10× error rate spike goes unnoticed until a user files a support ticket. A latency cliff from a degraded dependency goes unreported for 20 minutes.

### 4.2 `_MetricWindow` (Z-score + EMA): AFTER

```python
# app/anomaly/detector.py (excerpt)
import math
from collections import deque
from threading import Lock


class _MetricWindow:
    """Single-metric sliding window with Z-score and EMA computation."""

    def __init__(self, window_size: int = 100, ema_alpha: float = 0.1) -> None:
        self._window: deque[float] = deque(maxlen=window_size)
        self._ema: float | None = None
        self._alpha = ema_alpha
        self._lock = Lock()

    def observe(self, value: float) -> None:
        with self._lock:
            self._window.append(value)
            if self._ema is None:
                self._ema = value
            else:
                self._ema = self._alpha * value + (1 - self._alpha) * self._ema

    def z_score(self, value: float) -> float | None:
        """Return Z-score, or None if fewer than 10 samples collected."""
        with self._lock:
            samples = list(self._window)
        if len(samples) < 10:
            return None  # warm-up guard — prevents false positives
        mean = sum(samples) / len(samples)
        variance = sum((x - mean) ** 2 for x in samples) / len(samples)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std == 0:
            return 0.0
        return (value - mean) / std

    def baseline(self) -> dict:
        with self._lock:
            samples = list(self._window)
        if not samples:
            return {"mean": 0.0, "std": 0.0, "ema": self._ema, "count": 0}
        mean = sum(samples) / len(samples)
        variance = sum((x - mean) ** 2 for x in samples) / len(samples)
        std = math.sqrt(variance) if variance > 0 else 0.0
        return {"mean": mean, "std": std, "ema": self._ema, "count": len(samples)}
```

### 4.3 `AnomalyDetector.observe()` — four metrics: AFTER

```python
class AnomalyDetector:
    """Statistical anomaly detector for HTTP request metrics."""

    def __init__(self, sensitivity: float = 3.0, window_size: int = 100,
                 alert_webhook_url: str | None = None) -> None:
        self.sensitivity = sensitivity
        self.window_size = window_size
        self._request_rate = _MetricWindow(window_size)
        self._error_rate = _MetricWindow(window_size)
        self._latency = _MetricWindow(window_size)
        self._payload_size = _MetricWindow(window_size)
        self._anomalies: list[dict] = []
        self._last_request_ts: float = time.monotonic()

    def observe(self, status_code: int, duration_ms: float, payload_bytes: int) -> list[dict]:
        """Observe a completed request and return detected anomalies."""
        now = time.monotonic()
        elapsed = max(now - self._last_request_ts, 0.001)
        self._last_request_ts = now
        req_rate = 1.0 / elapsed
        err_flag = 1.0 if status_code >= 500 else 0.0

        anomalies: list[dict] = []
        metrics = {
            "request_rate": (self._request_rate, req_rate),
            "error_rate": (self._error_rate, err_flag),
            "latency_ms": (self._latency, duration_ms),
            "payload_bytes": (self._payload_size, float(payload_bytes)),
        }
        for name, (window, value) in metrics.items():
            z = window.z_score(value)
            window.observe(value)
            if z is not None and abs(z) > self.sensitivity:
                anom = {"metric": name, "value": value, "z_score": round(z, 2),
                        "ts": time.time()}
                anomalies.append(anom)
                self._anomalies.append(anom)
                if len(self._anomalies) > 1000:
                    self._anomalies = self._anomalies[-500:]
        return anomalies
```

### 4.4 `AlertDispatcher` (lazy httpx): AFTER

```python
# app/anomaly/alerter.py
import logging
import json

logger = logging.getLogger(__name__)


class AlertDispatcher:
    """Dispatch anomaly alerts via webhook and log."""

    def __init__(self, webhook_url: str | None = None) -> None:
        self.webhook_url = webhook_url

    async def dispatch(self, anomaly: dict) -> None:
        """Always logs. POSTs to webhook if configured (httpx lazy import)."""
        logger.warning(
            "Anomaly detected: metric=%s value=%s z_score=%s",
            anomaly.get("metric"), anomaly.get("value"), anomaly.get("z_score"),
        )
        if not self.webhook_url:
            return
        try:
            import httpx  # lazy — not imported at module top-level
            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.post(
                    self.webhook_url,
                    content=json.dumps(anomaly).encode(),
                    headers={"Content-Type": "application/json"},
                )
        except Exception:
            logger.warning("AlertDispatcher webhook failed: url=%s", self.webhook_url,
                           exc_info=True)
```

### 4.5 `AnomalyMiddleware` (non-blocking dispatch): AFTER

```python
# app/middleware/anomaly.py
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from app.anomaly.alerter import AlertDispatcher
from app.anomaly.detector import get_detector
import asyncio
import time


class AnomalyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, webhook_url: str | None = None) -> None:
        super().__init__(app)
        self._dispatcher = AlertDispatcher(webhook_url=webhook_url)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        detector = get_detector()
        if detector is None:
            return await call_next(request)
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        content_length = int(response.headers.get("content-length", 0))
        anomalies = detector.observe(
            status_code=response.status_code,
            duration_ms=duration_ms,
            payload_bytes=content_length,
        )
        for anom in anomalies:
            asyncio.ensure_future(self._dispatcher.dispatch(anom))
        return response
```

### 4.6 Pydantic schemas: AFTER

```python
# app/anomaly/models.py
from pydantic import BaseModel, ConfigDict, Field


class MetricBaseline(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    mean: float = Field(...)
    std: float = Field(...)
    ema: float | None = Field(None)
    count: int = Field(...)


class AnomalyEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    metric: str
    value: float
    z_score: float
    ts: float


class AnomalyStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    sensitivity: float
    window_size: int
    baselines: dict[str, MetricBaseline] = Field(default_factory=dict)
    recent_anomalies: list[AnomalyEvent] = Field(default_factory=list)
    total_anomalies: int = 0
```

### 4.7 Config patch: AFTER

```python
# app/core/config.py (fragment)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Anomaly detection — added by add_anomaly_detector tool
    ANOMALY_ENABLED: bool = False
    ANOMALY_SENSITIVITY: float = 3.0
    ANOMALY_WINDOW_SIZE: int = 100
    ANOMALY_ALERT_WEBHOOK_URL: str = ""
```

### 4.8 Initialisation in FastAPI lifespan (caller pattern)

```python
# app/main.py (after tool runs)
import os
from contextlib import asynccontextmanager
from app.anomaly.detector import init_detector
from app.middleware.anomaly import AnomalyMiddleware

@asynccontextmanager
async def lifespan(app):
    if os.getenv("ANOMALY_ENABLED", "false").lower() == "true":
        init_detector(
            sensitivity=float(os.getenv("ANOMALY_SENSITIVITY", "3.0")),
            window_size=int(os.getenv("ANOMALY_WINDOW_SIZE", "100")),
            alert_webhook_url=os.getenv("ANOMALY_ALERT_WEBHOOK_URL") or None,
        )
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(AnomalyMiddleware,
                  webhook_url=os.getenv("ANOMALY_ALERT_WEBHOOK_URL"))
```

### 4.9 Verifying the baseline after warmup

```python
# After 10+ requests have been processed:
import httpx, json

with httpx.Client() as c:
    r = c.get("http://localhost:8000/anomaly/status",
              headers={"Authorization": "Bearer <superuser-token>"})
    status = r.json()
    print(status["baselines"]["latency_ms"]["mean"])   # e.g. 12.4
    print(status["baselines"]["error_rate"]["count"])  # e.g. 100
    print(status["recent_anomalies"])                  # [] if no spikes
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Idempotent on second run | `"AnomalyDetector" in anomaly/detector.py` → `no_op` |
| QS-2 | `dry_run=True` zero writes | Early return before any `Path.write_text()` |
| QS-3 | All `.py` AST-parse clean | `_assert_parses` loop after creation |
| QS-4 | No function > 50 LOC | AST walk over all generated files |
| QS-5 | Z-score uses stdlib `math` only | No `import numpy` or `import scipy` at any level |
| QS-6 | `httpx` imported lazily inside `dispatch()` | No `import httpx` at module scope in `alerter.py` |
| QS-7 | Webhook dispatch non-blocking | `asyncio.ensure_future()` in `AnomalyMiddleware` |
| QS-8 | Warm-up guard: minimum 10 samples before Z-score fires | `len(samples) < 10 → return None` |
| QS-9 | Config 4-space indent | `_patch_config` anchored on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-10 | `execution_time_ms` positive | `_elapsed_ms(start)` with `time.monotonic()` |
| QS-11 | Anomaly store pruned at 1 000 events | `if len > 1000: list = list[-500:]` |
| QS-12 | `GET /anomaly/status` requires superuser auth | `Depends(get_current_superuser)` on route |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | `status="success"` on fresh project | `result.status == "success"` | T-01 |
| CC-02 | Second run → `no_op` | `r2.status == "no_op"` | T-02 |
| CC-03 | `dry_run=True` → zero writes | `before_tree == after_tree` | T-03 |
| CC-04 | ≥ 5 files created | `len(files_created) >= 5` | T-04 |
| CC-05 | ≥ 1 file modified | `len(files_modified) >= 1` | T-05 |
| CC-06 | All `.py` in `app/anomaly/` parse | `ast.parse` loop | T-06 |
| CC-07 | No function > 50 LOC | AST walk | T-07 |
| CC-08 | `ANOMALY_ENABLED` in config, 4-space indent | Substring + indent check | T-08 |
| CC-09 | Models in existing context not broken | `models/__init__.py` still parseable | T-09 |
| CC-10 | `anomaly.py` route uses `APIRouter` + `/anomaly` prefix | File + symbol check | T-10 |
| CC-11 | `AnomalyDetector`, `z_score`, `sensitivity` in `detector.py` | Symbol search | T-11 |
| CC-12 | EMA (`ema` or `alpha`) in `detector.py` | Pattern check | T-12 |
| CC-13 | All four metric names present: `request_rate`, `error_rate`, `latency_ms`, `payload_bytes` | All four substrings | T-13 |
| CC-14 | `AlertDispatcher`, `webhook`, `logger.warning` in `alerter.py` | Symbols in alerter | T-14 |
| CC-15 | `httpx` NOT at top-level in `alerter.py` | No `import httpx` at module scope | T-15 |
| CC-16 | `AnomalyMiddleware`, `observe`, `get_detector` in middleware | Symbol search | T-16 |
| CC-17 | `/status` route or `anomaly_status` in `routes/anomaly.py` | Route pattern | T-17 |
| CC-18 | `AnomalyStatus`, `BaseModel` in `models.py` | Pydantic schema symbols | T-18 |
| CC-19 | `init_detector`, `get_detector` in `detector.py` | Factory function symbols | T-19 |
| CC-20 | All four `ANOMALY_*` config fields present | All four substring checks | T-20 |
| CC-21 | `app/anomaly/__init__.py` exports `AnomalyDetector`, `AlertDispatcher` | Both symbols | T-21 |
| CC-22 | `notes` describe Z-score and EMA | `"z-score"` or `"ema"` token in `notes` | T-22 |
| CC-23 | `execution_time_ms > 0` | Positive integer check | T-23 |
| CC-24 | `next_steps` contains "anomaly" token | Token in joined string | T-24 |
| CC-25 | Second run leaves all `.py` parseable | `ast.parse` on all anomaly + middleware files | T-25 |

---

## 7. Definition of Done (DoD)

- [ ] All CC-01 through CC-25 verified by `test_add_anomaly_detector.py`
- [ ] `_MetricWindow.z_score` uses `math.sqrt()` and `sum()` — no numpy/scipy
- [ ] EMA updated on every `observe()` call with `alpha * value + (1 - alpha) * ema`
- [ ] Four metrics tracked: `request_rate`, `error_rate`, `latency_ms`, `payload_bytes`
- [ ] Minimum 10-sample warm-up guard: `z_score()` returns `None` until 10 samples
- [ ] `httpx` imported lazily inside `AlertDispatcher.dispatch()` body only
- [ ] `AnomalyMiddleware` uses `asyncio.ensure_future()` for non-blocking dispatch
- [ ] `AnomalyStatus` Pydantic model with `sensitivity`, `window_size`, `baselines`, `recent_anomalies`, `total_anomalies`
- [ ] `GET /anomaly/status` returns 503 if detector not initialised; else `AnomalyStatus`
- [ ] Config fields use 4-space indent inside `class Settings` body
- [ ] `execution_time_ms` is a positive integer
- [ ] `MCP_TOOL` descriptor present in source module

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-AD-01 | Idempotent on re-run | Fingerprint `"AnomalyDetector"` in `anomaly/detector.py` → `no_op` | T-02, T-25 |
| INV-AD-02 | `dry_run=True` never writes | Early return before `Path.write_text()` | T-03 |
| INV-AD-03 | All generated `.py` pass `ast.parse` | `_assert_parses` loop | T-06, T-25 |
| INV-AD-04 | Z-score uses stdlib only — no numpy/scipy | No `import numpy` or `import scipy` | T-15, B-08 |
| INV-AD-05 | `httpx` NOT at module top-level in alerter | Lazy import inside `dispatch()` | T-15, B-05 |
| INV-AD-06 | Webhook dispatch MUST be non-blocking | `asyncio.ensure_future()` in middleware | T-16 |
| INV-AD-07 | Config fields inside `class Settings` body | 4-space indent | T-08 |
| INV-AD-08 | `execution_time_ms` MUST be positive | `_elapsed_ms(start)` | T-23 |
| INV-AD-09 | Warm-up guard prevents false positives | `len(samples) < 10 → return None` | T-11, B-09 |
| INV-AD-10 | Anomaly store pruned at 1 000 entries | Prune to 500 on overflow | T-11 |

---

## 9. User Stories

### 9.1 Core installation (US-01 .. US-05)

**US-01: Successful install on fresh project**
- **Given:** A valid FastAPI project without anomaly detection
- **When:** `add_anomaly_detector(ToolInput(project_dir="/path"))` is called
- **Then:** `result.status == "success"`, `len(result.files_created) >= 5` (CC-01, CC-04)

**US-02: Idempotent CI re-run**
- **Given:** Anomaly detector already installed (first run succeeded)
- **When:** The tool is called a second time
- **Then:** `result.status == "no_op"`, no files modified (INV-AD-01)

**US-03: Dry-run preview**
- **Given:** A valid project
- **When:** `add_anomaly_detector(ToolInput(project_dir="/path", dry_run=True))` is called
- **Then:** `result.status == "success"`, filesystem is unchanged (INV-AD-02)

**US-04: All generated files are syntactically valid**
- **Given:** A tool run that returns `status="success"`
- **When:** Each `files_created` path is loaded with `ast.parse()`
- **Then:** No `SyntaxError` is raised (INV-AD-03)

**US-05: Z-score importable without numpy installed**
- **Given:** `numpy` not installed in the Python environment
- **When:** `from app.anomaly.detector import AnomalyDetector` is executed
- **Then:** No `ImportError` — Z-score uses only `math`, `collections.deque`, `threading.Lock` (INV-AD-04)

### 9.2 Z-score and EMA detection (US-06 .. US-10)

**US-06: Error rate spike detected after warmup**
- **Given:** 100 requests at 0% error rate (window warmed up)
- **When:** A request with `status_code=500` is observed
- **Then:** `z_score("error_rate", 1.0)` >> 3.0 → `AnomalyEvent` appended; `AlertDispatcher.dispatch()` called (CC-11, CC-13)

**US-07: Warm-up guard prevents false positives**
- **Given:** Only 5 observations in the window (below threshold)
- **When:** `z_score(value)` is called
- **Then:** Returns `None` — no anomaly fired (INV-AD-09)

**US-08: EMA tracks gradual latency drift**
- **Given:** 50 requests at 100 ms, then gradual drift toward 200 ms
- **When:** EMA updated after each observation
- **Then:** EMA rises smoothly toward 200 ms without being distorted by individual spike outliers (CC-12)

**US-09: `ANOMALY_SENSITIVITY=3.0` — only genuine outliers trigger alerts**
- **Given:** 100 requests with normally distributed latency
- **When:** All are observed
- **Then:** ≈ 0.3% of observations flagged (matches 3σ statistical expectation)

**US-10: `ANOMALY_SENSITIVITY=0.0` — every request triggers alert**
- **Given:** `sensitivity=0.0` (test-only configuration)
- **When:** Any request is observed after warmup
- **Then:** Every `|z_score|` > 0 → anomaly fired for all requests

### 9.3 Alert dispatch (US-11 .. US-15)

**US-11: WARNING log always dispatched on anomaly**
- **Given:** Anomaly detected
- **When:** `AlertDispatcher.dispatch(anomaly)` is called
- **Then:** `logger.warning(...)` is called with `metric`, `value`, `z_score` (CC-14)

**US-12: Webhook POST dispatched asynchronously**
- **Given:** `ANOMALY_ALERT_WEBHOOK_URL` configured
- **When:** Anomaly detected
- **Then:** `asyncio.ensure_future(dispatcher.dispatch(event))` fires non-blocking (INV-AD-06)

**US-13: Webhook failure does not propagate to request**
- **Given:** Webhook server is down (connection refused)
- **When:** `dispatch()` attempts POST
- **Then:** Exception caught; `logger.warning` logged; request completes normally (CC-14)

**US-14: No HTTP call when webhook URL is empty**
- **Given:** `ANOMALY_ALERT_WEBHOOK_URL=""` (default)
- **When:** Anomaly detected
- **Then:** `dispatch()` logs at WARNING and returns immediately — no HTTP call made

**US-15: `httpx` not importable at module load time**
- **Given:** `httpx` not installed in the Python environment
- **When:** `from app.anomaly.alerter import AlertDispatcher` is executed
- **Then:** No `ImportError` — httpx only imported inside `dispatch()` if webhook is configured (INV-AD-05)

### 9.4 Status endpoint and observability (US-16 .. US-20)

**US-16: `GET /anomaly/status` returns baselines after warmup**
- **Given:** 10+ requests have been observed
- **When:** `GET /anomaly/status` is called with superuser auth
- **Then:** Response contains `baselines` dict with non-zero `count` for all four metrics (CC-17)

**US-17: `GET /anomaly/status` returns 503 before `init_detector()`**
- **Given:** `ANOMALY_ENABLED=false` — `init_detector()` never called
- **When:** `GET /anomaly/status` is called
- **Then:** Returns `503 Service Unavailable` — `get_detector()` returns `None` (CC-17)

**US-18: `recent_anomalies` lists last 20 events**
- **Given:** 25 anomaly events have been recorded
- **When:** `detector.status()` is called
- **Then:** `recent_anomalies` contains the 20 most recent events (CC-17)

**US-19: Anomaly store pruned at 1 000 events**
- **Given:** 1 001 anomaly events have been recorded
- **When:** The 1 001st event is recorded
- **Then:** Internal store is pruned to last 500 events (INV-AD-10)

**US-20: Baselines exposed per metric in status response**
- **Given:** Detector warmed up with traffic
- **When:** `GET /anomaly/status`
- **Then:** `baselines` contains keys `request_rate`, `error_rate`, `latency_ms`, `payload_bytes` each with `mean`, `std`, `ema`, `count` (CC-13, CC-18)

### 9.5 Ops and integration (US-21 .. US-25)

**US-21: Chaos testing generates detectable anomalies**
- **Given:** `ChaosMiddleware` and `AnomalyMiddleware` both active
- **When:** Chaos injects `error_rate=0.5` for 20 requests
- **Then:** `error_rate` metric breaches sensitivity; `AnomalyEvent` logged and dispatched

**US-22: API replay debugger references anomaly `rec_id` for investigation**
- **Given:** `AnomalyMiddleware` detects anomalous request at path `/api/v1/items`
- **When:** Operator queries `GET /anomaly/status`
- **Then:** `recent_anomalies` shows metric and value; operator uses `GET /debug/requests` to find matching request by timestamp

**US-23: `add_load_shedding` thresholds informed by anomaly baselines**
- **Given:** `GET /anomaly/status` shows `latency_ms.mean = 50` with `std = 10`
- **When:** Operator configures load shedding
- **Then:** Sets `LOAD_SHEDDING_P99_THRESHOLD` to `mean + 3*std = 80 ms`

**US-24: Second run is idempotent and leaves all files parseable**
- **Given:** First run succeeded
- **When:** Tool runs a second time (no_op), then all `.py` re-parsed
- **Then:** All anomaly and middleware files pass `ast.parse()` (INV-AD-01, INV-AD-03)

**US-25: `execution_time_ms` positive in all outcomes**
- **Given:** Tool called in any mode (success, no_op, dry_run, error)
- **When:** `result.execution_time_ms` is read
- **Then:** Value is an integer > 0 (INV-AD-08)

---

## 10. Test Plan

### 10.1 Structural tests (`test_add_anomaly_detector.py`)

| # | Test ID | Test name | Expected |
|---|---------|-----------|----------|
| T-01 | CC-01 | `test_success_on_fresh_project` | `status="success"` |
| T-02 | CC-02 | `test_idempotent_second_run` | `status="no_op"` |
| T-03 | CC-03 | `test_dry_run_zero_writes` | Filesystem unchanged |
| T-04 | CC-04 | `test_files_created_count` | `len(files_created) >= 5` |
| T-05 | CC-05 | `test_files_modified_count` | `len(files_modified) >= 1` |
| T-06 | CC-06 | `test_anomaly_py_files_parse` | All `.py` in `app/anomaly/` parse |
| T-07 | CC-07 | `test_no_function_exceeds_50_loc` | AST walk: max function body ≤ 50 |
| T-08 | CC-08 | `test_anomaly_config_fields_4space` | `ANOMALY_ENABLED` present, 4-space indent |
| T-09 | CC-09 | `test_models_init_not_broken` | `models/__init__.py` still parseable |
| T-10 | CC-10 | `test_anomaly_route_file` | `APIRouter` + `/anomaly` prefix |
| T-11 | CC-11 | `test_detector_symbols` | `AnomalyDetector`, `z_score`, `sensitivity` |
| T-12 | CC-12 | `test_detector_has_ema` | `ema` or `alpha` in `detector.py` |
| T-13 | CC-13 | `test_four_metrics_present` | All four metric name strings |
| T-14 | CC-14 | `test_alerter_symbols` | `AlertDispatcher`, `webhook`, `logger.warning` |
| T-15 | CC-15 | `test_httpx_lazy_in_alerter` | No top-level `import httpx` in `alerter.py` |
| T-16 | CC-16 | `test_middleware_symbols` | `AnomalyMiddleware`, `observe`, `get_detector` |
| T-17 | CC-17 | `test_status_route` | `/status` or `anomaly_status` in routes |
| T-18 | CC-18 | `test_anomaly_models_pydantic` | `AnomalyStatus`, `BaseModel` in `models.py` |
| T-19 | CC-19 | `test_detector_init_function` | `init_detector`, `get_detector` in `detector.py` |
| T-20 | CC-20 | `test_config_has_all_anomaly_fields` | All four `ANOMALY_*` fields |
| T-21 | CC-21 | `test_anomaly_init_exports` | Both `AnomalyDetector` and `AlertDispatcher` in `__init__` |
| T-22 | CC-22 | `test_notes_mention_zscore_and_ema` | `"z-score"` or `"ema"` in joined `notes` |
| T-23 | CC-23 | `test_execution_time_positive` | `execution_time_ms > 0` |
| T-24 | CC-24 | `test_next_steps_mention_anomaly` | "anomaly" or "ANOMALY" in `next_steps` |
| T-25 | CC-25 | `test_second_run_files_still_parse` | All anomaly + middleware `.py` parse after second run |

### 10.2 Behavior tests (`test_add_anomaly_detector_behavior.py`)

| # | Test ID | Test name | Assertion |
|---|---------|-----------|-----------|
| B-01 | QS-1 | `test_healthz_returns_200` | `GET /healthz` → 200 OK |
| B-02 | CC-11 | `test_detector_symbols_importable` | `AnomalyDetector`, `get_detector`, `init_detector` importable |
| B-03 | CC-14 | `test_alerter_importable` | `AlertDispatcher` importable |
| B-04 | CC-20 | `test_anomaly_enabled_in_config` | `ANOMALY_ENABLED` in config source |
| B-05 | INV-AD-05 | `test_httpx_not_at_top_level` | No `import httpx` at module scope in alerter |
| B-06 | CC-07 | `test_no_function_exceeds_50_loc` | AST walk on all generated files |
| B-07 | CC-08 | `test_config_4space_indent` | Fields inside `class Settings` body |
| B-08 | INV-AD-04 | `test_no_numpy_scipy` | No `import numpy` or `import scipy` anywhere |
| B-09 | INV-AD-09 | `test_warmup_guard_10_samples` | `z_score()` returns `None` when `len(samples) < 10` |
| B-10 | INV-AD-10 | `test_anomaly_store_prune` | Store pruned to 500 after exceeding 1 000 |

---

## 11. Interaction Matrix

| Other tool | Interaction type | Notes |
|------------|-----------------|-------|
| `add_chaos_testing` (TOOL-099) | ✅ Complementary | Chaos errors + latency deliberately trigger anomalies; validates alert calibration |
| `add_load_shedding` (TOOL-095) | ✅ Complementary | Anomaly baselines inform load shedding p99 thresholds |
| `add_api_replay_debugger` (TOOL-101) | ✅ Complementary | Anomalous requests surfaced for replay-based root cause investigation |
| `add_adaptive_timeouts` (TOOL-096) | ✅ Complementary | Latency anomalies may coincide with adaptive timeout adjustments |
| `add_graceful_shutdown` (TOOL-100) | ✅ Neutral | Both use middleware pattern; register `AnomalyMiddleware` before `ShutdownMiddleware` |
| `add_request_fingerprint` (TOOL-103) | ✅ Neutral | Both use middleware; no Redis dependency overlap |
| `add_bulkhead_isolation` (TOOL-097) | ✅ Complementary | Bulkhead 503 spikes detected as `error_rate` anomalies |
| `add_retry_budget` (TOOL-098) | ✅ Complementary | Retry storms appear as `request_rate` anomalies |
| External APM (Datadog, etc.) | ⚠️ Caveat | Webhook can feed APM custom events; avoid double-alerting on same signal |
| `generate_project` | ✅ Prerequisite | Requires `app/core/config.py` with `class Settings` |
| Second `add_anomaly_detector` call | ✅ Idempotent | `no_op` — `AnomalyDetector` already in `detector.py` |

---

## 12. Rollback Procedure

### 12.1 Remove anomaly package

```bash
rm -rf app/anomaly/
```

### 12.2 Remove anomaly middleware

```bash
rm -f app/middleware/anomaly.py
```

### 12.3 Remove anomaly routes

```bash
rm -f app/api/routes/anomaly.py
```

### 12.4 Restore config

```bash
git checkout HEAD -- app/core/config.py
```

Or manually remove all four `ANOMALY_*` fields from `app/core/config.py`.

### 12.5 Remove wiring from `main.py`

```bash
git checkout HEAD -- app/main.py
```

Or manually remove:
- `from app.anomaly.detector import init_detector`
- `from app.middleware.anomaly import AnomalyMiddleware`
- `app.add_middleware(AnomalyMiddleware, ...)`
- `init_detector(...)` call in lifespan

### 12.6 Verify rollback

```bash
python -c "from app.main import app; print('OK')"
pytest tests/ -x --tb=short
```

---

## 13. Edge Cases

| # | Scenario | Expected behaviour |
|---|----------|--------------------|
| EC-01 | `"AnomalyDetector"` already in `app/anomaly/detector.py` | `status="no_op"`, no files modified |
| EC-02 | `dry_run=True` on any valid project | `status="success"`, zero writes |
| EC-03 | Fewer than 10 samples in window | `z_score()` returns `None`; no anomaly fired (warm-up guard) |
| EC-04 | `ANOMALY_ALERT_WEBHOOK_URL=""` (default) | `dispatch()` logs at WARNING; no HTTP call made |
| EC-05 | Webhook POST fails with exception | Exception caught; warning logged; request unaffected |
| EC-06 | Anomaly store reaches 1 000 entries | Pruned to 500 (last 500 retained) — prevents unbounded memory growth |
| EC-07 | `ANOMALY_SENSITIVITY=0.0` | Every request with ≥ 10 samples in window triggers anomaly — useful only for testing |
| EC-08 | All responses have `status_code < 500` | `error_rate` window accumulates zeros; Z-score near 0 for all observations |
| EC-09 | `content-length` header absent | `int(response.headers.get("content-length", 0))` → 0 bytes |
| EC-10 | `app/api/routes/` directory absent | Routes file skipped; tool succeeds with 5 files instead of 6 |
| EC-11 | `app/core/config.py` absent | Config patch skipped; `files_modified` is empty |
| EC-12 | `get_detector()` returns `None` in middleware | Middleware passes all requests through unchanged — no anomaly detection |
| EC-13 | Two requests arrive at same millisecond | `max(now - last_ts, 0.001)` guard prevents division by zero in `request_rate` |
| EC-14 | All samples identical (σ = 0) | `std = 0.0` → returns `0.0` (no anomaly) rather than `NaN` or division error |
| EC-15 | `ANOMALY_WINDOW_SIZE=1` | Window holds 1 sample; Z-score always returns `None` (warm-up guard) |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All CC-01 through CC-25 pass in `test_add_anomaly_detector.py`
2. ✅ `_MetricWindow.z_score()` uses `math.sqrt()` and `sum()` — no numpy/scipy
3. ✅ EMA updated on every `observe()` call: `ema = alpha * value + (1 - alpha) * ema`
4. ✅ Four metrics tracked: `request_rate`, `error_rate`, `latency_ms`, `payload_bytes`
5. ✅ Minimum 10-sample warm-up guard: `len(samples) < 10 → return None`
6. ✅ `httpx` imported lazily inside `AlertDispatcher.dispatch()` only
7. ✅ `AnomalyMiddleware` uses `asyncio.ensure_future()` — non-blocking dispatch
8. ✅ `AnomalyStatus` Pydantic model with all five fields
9. ✅ `GET /anomaly/status` returns 503 if `get_detector()` returns `None`
10. ✅ All generated `.py` files pass `ast.parse()` with no `SyntaxError`
11. ✅ No generated function exceeds 50 LOC (AST walk)
12. ✅ Config fields have 4-space indent inside `class Settings` body
13. ✅ `execution_time_ms` is a positive integer in all result types
14. ✅ Second run returns `no_op` without modifying files

---

## 15. Implementation Checklist

### 15.1 Pre-flight checks

- [ ] Validate `project_dir` with `validate_project_dir()` — return error if invalid
- [ ] Run `ensure_prerequisites(Prereq.CONFIG_SETTINGS, Prereq.REQUIREMENTS_TXT)` — return error if not met
- [ ] Check idempotency: `"AnomalyDetector" in (app/anomaly/detector.py)` → return `no_op` if true
- [ ] If `dry_run=True`, return early success with notes about all 4 would-be changes

### 15.2 Anomaly package creation

- [ ] Create `app/anomaly/` directory with `mkdir(parents=True, exist_ok=True)`
- [ ] Write `app/anomaly/__init__.py` via `_write_anomaly_init()`: re-export `AnomalyDetector`, `AlertDispatcher`, `get_detector`, `init_detector`
- [ ] Write `app/anomaly/detector.py` via `_write_detector()`:
  - [ ] `_MetricWindow` with `deque(maxlen=window_size)`, `Lock`, `observe()`, `z_score()` (warm-up guard), `baseline()`
  - [ ] `AnomalyDetector` with 4 `_MetricWindow` instances, `observe()` computing all 4 metrics, `status()`
  - [ ] `get_detector()` returning module-level `_detector`
  - [ ] `init_detector()` factory function
- [ ] Write `app/anomaly/alerter.py` via `_write_alerter()`:
  - [ ] `AlertDispatcher` with `webhook_url` attribute
  - [ ] `dispatch()` with `logger.warning(...)` and lazy `import httpx`
- [ ] Write `app/anomaly/models.py` via `_write_anomaly_models()`:
  - [ ] `MetricBaseline(BaseModel)` with `mean`, `std`, `ema`, `count`
  - [ ] `AnomalyEvent(BaseModel)` with `metric`, `value`, `z_score`, `ts`
  - [ ] `AnomalyStatus(BaseModel)` with `sensitivity`, `window_size`, `baselines`, `recent_anomalies`, `total_anomalies`

### 15.3 Middleware

- [ ] Create `app/middleware/` if not exists
- [ ] Write `app/middleware/anomaly.py` via `_write_anomaly_middleware()`:
  - [ ] `AnomalyMiddleware(BaseHTTPMiddleware)` with `_dispatcher = AlertDispatcher(webhook_url)`
  - [ ] `dispatch()` with timing, `detector.observe(status_code, duration_ms, payload_bytes)`
  - [ ] `asyncio.ensure_future(dispatcher.dispatch(anom))` for each anomaly

### 15.4 Routes

- [ ] Write `app/api/routes/anomaly.py` via `_write_anomaly_routes()` (only if `routes_dir.exists()`):
  - [ ] `router = APIRouter(prefix="/anomaly", tags=["anomaly"])`
  - [ ] `GET /status` with `Depends(get_current_superuser)`, 503 when `get_detector()` is `None`

### 15.5 Config and main.py

- [ ] Patch `app/core/config.py` via `_patch_config()`:
  - [ ] Skip if `"ANOMALY_ENABLED"` already in file
  - [ ] Inject 4 fields with 4-space indent
- [ ] Return `ToolResult` with `status="success"`, `notes` mentioning "z-score" and "ema", `next_steps` mentioning "ANOMALY", `execution_time_ms`

### 15.6 Validation

- [ ] Loop over `files_created`: `ast.parse(path.read_text())` — return error on `SyntaxError`

---

## 16. Documentation Output

### 16.1 Success (fresh project)

```json
{
  "status": "success",
  "files_created": [
    "/project/app/anomaly/__init__.py",
    "/project/app/anomaly/detector.py",
    "/project/app/anomaly/alerter.py",
    "/project/app/anomaly/models.py",
    "/project/app/middleware/anomaly.py",
    "/project/app/api/routes/anomaly.py"
  ],
  "files_modified": ["/project/app/core/config.py"],
  "notes": [
    "Anomaly detector added: Z-score + EMA on sliding windows.",
    "Metrics tracked: request_rate, error_rate, latency_ms, payload_bytes.",
    "Sensitivity=3.0 (z-score threshold), window_size=100, EMA alpha=0.1.",
    "AlertDispatcher: WARNING log always + optional webhook POST (httpx lazy)."
  ],
  "next_steps": [
    "Set ANOMALY_ENABLED=true in .env (default: false).",
    "Optional: set ANOMALY_SENSITIVITY (default: 3.0 — standard deviations).",
    "Optional: set ANOMALY_WINDOW_SIZE (default: 100 — samples per window).",
    "Optional: set ANOMALY_ALERT_WEBHOOK_URL for webhook alerts."
  ],
  "execution_time_ms": 112
}
```

### 16.2 No-op (already installed)

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "AnomalyDetector already present — anomaly detection already enabled, skipped."
  ],
  "next_steps": [],
  "execution_time_ms": 3
}
```

### 16.3 Dry run

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create app/anomaly/ package with detector, alerter, models.",
    "[dry_run] Would add AnomalyMiddleware to app/main.py.",
    "[dry_run] Would add GET /anomaly/status route.",
    "[dry_run] Would patch app/core/config.py with ANOMALY_* fields."
  ],
  "next_steps": [
    "Re-run without dry_run=True to apply changes."
  ],
  "execution_time_ms": 2
}
```

### 16.4 Error (invalid project directory)

```json
{
  "status": "error",
  "error": "project_dir '/nonexistent/path' does not exist or is not a directory.",
  "files_created": [],
  "files_modified": [],
  "notes": [],
  "next_steps": [],
  "execution_time_ms": 1
}
```

---
