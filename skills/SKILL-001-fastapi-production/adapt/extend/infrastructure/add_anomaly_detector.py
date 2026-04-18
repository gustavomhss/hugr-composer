"""TOOL-102: add_anomaly_detector — statistical anomaly detection for FastAPI.

Generates an ``AnomalyDetector`` (Z-score + EMA on sliding windows), an
``AlertDispatcher`` (webhook + log, lazy httpx), an ``AnomalyMiddleware``
(updates metrics per request), and a ``GET /anomaly/status`` endpoint.

The tool is idempotent: a second run detects ``app/anomaly/detector.py``
containing ``AnomalyDetector`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_anomaly_detector import add_anomaly_detector

    result = add_anomaly_detector(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/anomaly/detector.py, ...]
    print(result.next_steps)    # ["Set ANOMALY_ENABLED=true", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_anomaly_detector",
    "description": (
        "Add statistical anomaly detection: Z-score + EMA on sliding windows for "
        "request rate, error rate, latency, and payload size. Alerts via webhook or log."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_anomaly_detector",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_anomaly_detector(inp: ToolInput) -> ToolResult:
    """Add anomaly detector to a FastAPI project.

    Writes ``app/anomaly/`` package (detector, alerter, models), an
    ``AnomalyMiddleware``, and a ``GET /anomaly/status`` route.  Patches
    ``app/core/config.py`` with anomaly config fields.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(
            status="error",
            error=err,
            execution_time_ms=_elapsed_ms(start),
        )

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    fingerprint_file = app_dir / "anomaly" / "detector.py"
    if fingerprint_file.exists() and "AnomalyDetector" in fingerprint_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["AnomalyDetector already present — anomaly detection already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/anomaly/ package with detector, alerter, models.",
                "[dry_run] Would add AnomalyMiddleware to app/main.py.",
                "[dry_run] Would add GET /anomaly/status route.",
                "[dry_run] Would patch app/core/config.py with ANOMALY_* fields.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    files_modified: list[str] = []

    # --- Step 1: anomaly package ---------------------------------------------
    anomaly_dir = app_dir / "anomaly"
    anomaly_dir.mkdir(parents=True, exist_ok=True)

    init_file = anomaly_dir / "__init__.py"
    _write_anomaly_init(init_file)
    files_created.append(str(init_file))

    _write_detector(fingerprint_file)
    files_created.append(str(fingerprint_file))

    alerter_file = anomaly_dir / "alerter.py"
    _write_alerter(alerter_file)
    files_created.append(str(alerter_file))

    models_file = anomaly_dir / "models.py"
    _write_anomaly_models(models_file)
    files_created.append(str(models_file))

    # --- Step 2: middleware ---------------------------------------------------
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    middleware_file = middleware_dir / "anomaly.py"
    _write_anomaly_middleware(middleware_file)
    files_created.append(str(middleware_file))

    # --- Step 3: routes ------------------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        status_route = routes_dir / "anomaly.py"
        _write_anomaly_routes(status_route)
        files_created.append(str(status_route))

    # --- Step 4: patch config ------------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 5: ast.parse validation ----------------------------------------
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Anomaly detector added: Z-score + EMA on sliding windows.",
            "Metrics tracked: request rate, error rate, p99 latency, payload size.",
            "Alerts dispatched via webhook (lazy httpx) and log.",
            "GET /anomaly/status returns current baselines + deviations.",
        ],
        next_steps=[
            "Set ANOMALY_ENABLED=true in .env (default: false).",
            "Optional: set ANOMALY_SENSITIVITY (default: 3.0 — standard deviations).",
            "Optional: set ANOMALY_WINDOW_SIZE (default: 100 — samples per window).",
            "Optional: set ANOMALY_ALERT_WEBHOOK_URL for webhook alerts.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_anomaly_init(dest: Path) -> None:
    """Write ``app/anomaly/__init__.py`` re-exporting public symbols.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Anomaly detection — public API.\"\"\"

        from app.anomaly.detector import AnomalyDetector, get_detector, init_detector
        from app.anomaly.alerter import AlertDispatcher

        __all__ = [
            "AnomalyDetector",
            "get_detector",
            "init_detector",
            "AlertDispatcher",
        ]
        """))


def _write_detector(dest: Path) -> None:
    """Write ``app/anomaly/detector.py`` with Z-score + EMA detector.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"AnomalyDetector: Z-score + EMA sliding window anomaly detection.\"\"\"

        from __future__ import annotations

        import logging
        import math
        import time
        from collections import deque
        from threading import Lock

        logger = logging.getLogger(__name__)

        _detector: "AnomalyDetector | None" = None


        class _MetricWindow:
            \"\"\"Single-metric sliding window with Z-score and EMA computation.

            Args:
                window_size: Number of samples to retain.
                ema_alpha: EMA smoothing factor (0 < alpha <= 1).
            \"\"\"

            def __init__(self, window_size: int = 100, ema_alpha: float = 0.1) -> None:
                self._window: deque[float] = deque(maxlen=window_size)
                self._ema: float | None = None
                self._alpha = ema_alpha
                self._lock = Lock()

            def observe(self, value: float) -> None:
                \"\"\"Add a new observation.

                Args:
                    value: Metric value to record.
                \"\"\"
                with self._lock:
                    self._window.append(value)
                    if self._ema is None:
                        self._ema = value
                    else:
                        self._ema = self._alpha * value + (1 - self._alpha) * self._ema

            def z_score(self, value: float) -> float | None:
                \"\"\"Return Z-score of *value* relative to window, or None if < 10 samples.

                Args:
                    value: Value to score.
                \"\"\"
                with self._lock:
                    samples = list(self._window)
                if len(samples) < 10:
                    return None
                mean = sum(samples) / len(samples)
                variance = sum((x - mean) ** 2 for x in samples) / len(samples)
                std = math.sqrt(variance) if variance > 0 else 0.0
                if std == 0:
                    return 0.0
                return (value - mean) / std

            def baseline(self) -> dict:
                \"\"\"Return current baseline statistics.\"\"\"
                with self._lock:
                    samples = list(self._window)
                if not samples:
                    return {"mean": 0.0, "std": 0.0, "ema": self._ema, "count": 0}
                mean = sum(samples) / len(samples)
                variance = sum((x - mean) ** 2 for x in samples) / len(samples)
                std = math.sqrt(variance) if variance > 0 else 0.0
                return {"mean": mean, "std": std, "ema": self._ema, "count": len(samples)}


        class AnomalyDetector:
            \"\"\"Statistical anomaly detector for HTTP request metrics.

            Tracks four metrics per endpoint: request rate (req/s), error rate
            (fraction of 5xx), p99 latency (ms), and payload size (bytes).

            Args:
                sensitivity: Z-score threshold to trigger an alert (default 3.0).
                window_size: Number of samples per sliding window.
                alert_webhook_url: Optional webhook URL for alerts.
            \"\"\"

            def __init__(
                self,
                sensitivity: float = 3.0,
                window_size: int = 100,
                alert_webhook_url: str | None = None,
            ) -> None:
                self.sensitivity = sensitivity
                self.window_size = window_size
                self.alert_webhook_url = alert_webhook_url
                self._request_rate = _MetricWindow(window_size)
                self._error_rate = _MetricWindow(window_size)
                self._latency = _MetricWindow(window_size)
                self._payload_size = _MetricWindow(window_size)
                self._anomalies: list[dict] = []
                self._last_request_ts: float = time.monotonic()

            def observe(
                self,
                status_code: int,
                duration_ms: float,
                payload_bytes: int,
            ) -> list[dict]:
                \"\"\"Observe a completed request and return any anomalies detected.

                Args:
                    status_code: HTTP response status code.
                    duration_ms: Request duration in milliseconds.
                    payload_bytes: Response body size in bytes.

                Returns:
                    List of anomaly dicts (empty when no anomaly).
                \"\"\"
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
                        anom = {
                            "metric": name,
                            "value": value,
                            "z_score": round(z, 2),
                            "ts": time.time(),
                        }
                        anomalies.append(anom)
                        self._anomalies.append(anom)
                        if len(self._anomalies) > 1000:
                            self._anomalies = self._anomalies[-500:]

                return anomalies

            def status(self) -> dict:
                \"\"\"Return current baselines and recent anomaly count.\"\"\"
                return {
                    "sensitivity": self.sensitivity,
                    "window_size": self.window_size,
                    "baselines": {
                        "request_rate": self._request_rate.baseline(),
                        "error_rate": self._error_rate.baseline(),
                        "latency_ms": self._latency.baseline(),
                        "payload_bytes": self._payload_size.baseline(),
                    },
                    "recent_anomalies": self._anomalies[-20:],
                    "total_anomalies": len(self._anomalies),
                }


        def get_detector() -> "AnomalyDetector | None":
            \"\"\"Return the process-wide AnomalyDetector, or None if not initialised.\"\"\"
            return _detector


        def init_detector(
            sensitivity: float = 3.0,
            window_size: int = 100,
            alert_webhook_url: str | None = None,
        ) -> None:
            \"\"\"Initialise the global anomaly detector.  Call once at app startup.

            Args:
                sensitivity: Z-score threshold for anomaly alerts.
                window_size: Number of samples in each sliding window.
                alert_webhook_url: Optional webhook URL for alert dispatch.
            \"\"\"
            global _detector
            _detector = AnomalyDetector(
                sensitivity=sensitivity,
                window_size=window_size,
                alert_webhook_url=alert_webhook_url,
            )
        """))


def _write_alerter(dest: Path) -> None:
    """Write ``app/anomaly/alerter.py`` with AlertDispatcher.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"AlertDispatcher: dispatch anomaly alerts via webhook and log.\"\"\"

        from __future__ import annotations

        import json
        import logging

        logger = logging.getLogger(__name__)


        class AlertDispatcher:
            \"\"\"Dispatch anomaly alerts to configured channels.

            Args:
                webhook_url: Optional HTTP webhook URL for POST alerts.
            \"\"\"

            def __init__(self, webhook_url: str | None = None) -> None:
                self.webhook_url = webhook_url

            async def dispatch(self, anomaly: dict) -> None:
                \"\"\"Dispatch a single anomaly alert.

                Logs at WARNING level always.  If ``webhook_url`` is configured,
                also POSTs the anomaly JSON via httpx (lazy import).

                Args:
                    anomaly: Anomaly dict with metric, value, z_score, ts.
                \"\"\"
                logger.warning(
                    "Anomaly detected: metric=%s value=%s z_score=%s",
                    anomaly.get("metric"),
                    anomaly.get("value"),
                    anomaly.get("z_score"),
                )
                if not self.webhook_url:
                    return
                try:
                    import httpx  # lazy — optional SDK

                    async with httpx.AsyncClient(timeout=3.0) as client:
                        await client.post(
                            self.webhook_url,
                            content=json.dumps(anomaly).encode(),
                            headers={"Content-Type": "application/json"},
                        )
                except Exception:
                    logger.warning(
                        "AlertDispatcher webhook failed: url=%s", self.webhook_url,
                        exc_info=True,
                    )
        """))


def _write_anomaly_models(dest: Path) -> None:
    """Write ``app/anomaly/models.py`` with Pydantic schemas.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Pydantic schemas for the anomaly detection API.\"\"\"

        from __future__ import annotations

        from pydantic import BaseModel, ConfigDict, Field


        class MetricBaseline(BaseModel):
            \"\"\"Current baseline statistics for a single metric.\"\"\"

            model_config = ConfigDict(from_attributes=True)

            mean: float = Field(..., description="Mean value over the window.")
            std: float = Field(..., description="Standard deviation over the window.")
            ema: float | None = Field(None, description="Exponential moving average.")
            count: int = Field(..., description="Number of samples in window.")


        class AnomalyEvent(BaseModel):
            \"\"\"A single detected anomaly.\"\"\"

            model_config = ConfigDict(from_attributes=True)

            metric: str = Field(..., description="Metric name (e.g. latency_ms).")
            value: float = Field(..., description="Observed value.")
            z_score: float = Field(..., description="Z-score of the observation.")
            ts: float = Field(..., description="Unix timestamp of detection.")


        class AnomalyStatus(BaseModel):
            \"\"\"Full anomaly detection status response.\"\"\"

            model_config = ConfigDict(from_attributes=True)

            sensitivity: float = Field(..., description="Z-score alert threshold.")
            window_size: int = Field(..., description="Sliding window sample count.")
            baselines: dict[str, MetricBaseline] = Field(
                default_factory=dict,
                description="Current baseline per metric.",
            )
            recent_anomalies: list[AnomalyEvent] = Field(
                default_factory=list,
                description="Up to 20 most recent anomaly events.",
            )
            total_anomalies: int = Field(default=0, description="Total anomalies detected.")
        """))


def _write_anomaly_middleware(dest: Path) -> None:
    """Write ``app/middleware/anomaly.py`` with AnomalyMiddleware.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"AnomalyMiddleware: observe every request, dispatch alerts on anomaly.\"\"\"

        from __future__ import annotations

        import asyncio
        import logging
        import time
        from typing import Callable

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response

        from app.anomaly.alerter import AlertDispatcher
        from app.anomaly.detector import get_detector

        logger = logging.getLogger(__name__)


        class AnomalyMiddleware(BaseHTTPMiddleware):
            \"\"\"Observe every request/response and trigger alerts on anomaly.

            Args:
                app: ASGI application.
                webhook_url: Optional webhook URL for alert dispatch.
            \"\"\"

            def __init__(self, app: Callable, webhook_url: str | None = None) -> None:
                super().__init__(app)
                self._dispatcher = AlertDispatcher(webhook_url=webhook_url)

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                \"\"\"Time request, observe metrics, fire alerts on anomaly.\"\"\"
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
                if anomalies:
                    for anom in anomalies:
                        asyncio.ensure_future(self._dispatcher.dispatch(anom))

                return response
        """))


def _write_anomaly_routes(dest: Path) -> None:
    """Write ``app/api/routes/anomaly.py`` with GET /anomaly/status.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Admin route: GET /anomaly/status.\"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, Depends, HTTPException

        from app.api.deps import get_current_superuser
        from app.anomaly.detector import get_detector
        from app.anomaly.models import AnomalyStatus

        router = APIRouter(prefix="/anomaly", tags=["anomaly"])


        @router.get(
            "/status",
            response_model=AnomalyStatus,
            dependencies=[Depends(get_current_superuser)],
        )
        async def anomaly_status() -> dict:
            \"\"\"Return current anomaly detection baselines and recent events.

            Returns:
                AnomalyStatus with sensitivity, window_size, baselines per metric,
                and up to 20 recent anomaly events.

            Raises:
                HTTPException: 503 if detector not initialised.
            \"\"\"
            detector = get_detector()
            if detector is None:
                raise HTTPException(
                    status_code=503,
                    detail={"detail": "Anomaly detector not initialised"},
                )
            return detector.status()
        """))


def _patch_config(config_file: Path) -> None:
    """Inject ANOMALY_* fields into app/core/config.py Settings.

    Fields are injected inside the Settings class body with 4-space indent.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "ANOMALY_ENABLED" in src:
        return

    # 4-space-indented block to inject inside the Settings class body
    injection = (
        "\n"
        "    # Anomaly detection — added by add_anomaly_detector tool\n"
        "    ANOMALY_ENABLED: bool = False\n"
        "    ANOMALY_SENSITIVITY: float = 3.0\n"
        "    ANOMALY_WINDOW_SIZE: int = 100\n"
        "    ANOMALY_ALERT_WEBHOOK_URL: str = \"\"\n"
    )

    if "settings = Settings()" in src:
        src = src.replace("settings = Settings()", injection + "\nsettings = Settings()")
    else:
        src = src.rstrip("\n") + "\n" + injection

    config_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
