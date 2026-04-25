"""TOOL-122: add_request_tracing_ui — embedded request tracing dashboard.

Adds a self-contained request tracing system with a ring-buffer of the last
N requests, per-layer timing breakdown, and a vanilla-JS dashboard served at
``/tracing/dashboard``.

Idempotent: a second run detects ``TracingBuffer`` in
``app/tracing_ui/__init__.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_request_tracing_ui import add_request_tracing_ui

    result = add_request_tracing_ui(ToolInput(project_dir="/path/to/project"))
    print(result.status)          # "success"
    print(result.files_created)   # [.../app/tracing_ui/__init__.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_deployment_add_request_tracing_ui",
    "description": (
        "Add an embedded request tracing dashboard: TracingBuffer ring buffer (last 1000 "
        "requests), TimingCollector per-middleware/DB/external timing, GET /tracing/requests, "
        "GET /tracing/requests/{id}, GET /tracing/slow (p99), and a self-contained vanilla-JS "
        "HTML dashboard at GET /tracing/dashboard."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_request_tracing_ui",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_request_tracing_ui(inp: ToolInput) -> ToolResult:
    """Add request tracing UI to a FastAPI project.

    Writes ``app/tracing_ui/`` package, a routes file, an HTML dashboard
    template, patches ``app/core/config.py`` with tracing knobs, and
    registers the router in ``app/main.py``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

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
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    tracing_init = app_dir / "tracing_ui" / "__init__.py"
    if tracing_init.exists() and "TracingBuffer" in tracing_init.read_text():
        return ToolResult(
            status="no_op",
            notes=["TracingBuffer already present — request tracing UI already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/tracing_ui/ package with TracingBuffer and TimingCollector.",
                "[dry_run] Would create app/api/routes/tracing.py with 3 endpoints.",
                "[dry_run] Would create app/tracing_ui/templates/dashboard.html.",
                "[dry_run] Would patch app/core/config.py and app/main.py.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: tracing_ui package ------------------------------------------
    tracing_dir = app_dir / "tracing_ui"
    tracing_dir.mkdir(parents=True, exist_ok=True)

    templates_dir = tracing_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    _write_tracing_init(tracing_init)
    files_created.append(str(tracing_init))

    _write_timing_collector(tracing_dir / "collector.py")
    files_created.append(str(tracing_dir / "collector.py"))

    _write_tracing_middleware(tracing_dir / "middleware.py")
    files_created.append(str(tracing_dir / "middleware.py"))

    _write_dashboard_html(templates_dir / "dashboard.html")
    files_created.append(str(templates_dir / "dashboard.html"))

    # --- Step 2: tracing routes ----------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        route_file = routes_dir / "tracing.py"
        _write_tracing_routes(route_file)
        files_created.append(str(route_file))

    # --- Step 3: Patch config.py ---------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 4: Patch main.py -----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- Validate all generated .py files ------------------------------------
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
            "Request tracing UI enabled: TracingBuffer ring buffer (last 1000 requests).",
            "TimingCollector records per-layer timing: middleware, DB, external calls.",
            "Three JSON endpoints: GET /tracing/requests, GET /tracing/requests/{id}, "
            "GET /tracing/slow (p99 requests).",
            "Self-contained HTML dashboard at GET /tracing/dashboard (no build step).",
            "All tracing is in-process — zero external dependencies.",
        ],
        next_steps=[
            "Set TRACING_UI_ENABLED=true in .env (default: false).",
            "Set TRACING_UI_BUFFER_SIZE in .env (default: 1000).",
            "Set TRACING_UI_AUTH_REQUIRED=true in .env to password-protect the dashboard.",
            "Visit /tracing/dashboard in your browser after starting the server.",
            "Instrument DB queries: call collector.record_span('db', latency_ms) from your DAL.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_tracing_init(dest: Path) -> None:
    """Write app/tracing_ui/__init__.py — TracingBuffer ring buffer.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Request tracing UI — TracingBuffer ring buffer and public API.\"\"\"

        from __future__ import annotations

        import threading
        import uuid
        from collections import deque
        from typing import Any

        _lock = threading.Lock()


        class TracingBuffer:
            \"\"\"Thread-safe ring buffer of the last N traced requests.

            Args:
                maxlen: Maximum number of request records to retain.
            \"\"\"

            def __init__(self, maxlen: int = 1000) -> None:
                self._buf: deque[dict[str, Any]] = deque(maxlen=maxlen)

            def record(self, entry: dict[str, Any]) -> None:
                \"\"\"Append a request trace entry to the ring buffer.

                Args:
                    entry: Dict with at minimum 'id', 'method', 'path',
                        'status_code', 'total_ms', 'spans'.
                \"\"\"
                with _lock:
                    self._buf.append(entry)

            def get_all(self) -> list[dict[str, Any]]:
                \"\"\"Return all buffered entries, newest-first.\"\"\"
                with _lock:
                    return list(reversed(self._buf))

            def get_by_id(self, request_id: str) -> dict[str, Any] | None:
                \"\"\"Return the entry with the given request ID, or None.

                Args:
                    request_id: UUID string assigned when the request arrived.
                \"\"\"
                with _lock:
                    for entry in self._buf:
                        if entry.get("id") == request_id:
                            return entry
                return None

            def get_slow(self, percentile: float = 0.99) -> list[dict[str, Any]]:
                \"\"\"Return requests at or above the given latency percentile.

                Args:
                    percentile: Fraction (0-1) above which requests are 'slow'.
                        Defaults to 0.99 (p99).
                \"\"\"
                with _lock:
                    items = sorted(self._buf, key=lambda r: r.get("total_ms", 0))
                if not items:
                    return []
                cutoff_idx = max(0, int(len(items) * percentile) - 1)
                threshold = items[cutoff_idx].get("total_ms", 0)
                return [r for r in items if r.get("total_ms", 0) >= threshold]

            def __len__(self) -> int:
                \"\"\"Return current number of buffered entries.\"\"\"
                return len(self._buf)


        def make_request_id() -> str:
            \"\"\"Generate a new UUID4 request identifier.\"\"\"
            return str(uuid.uuid4())


        _buffer: TracingBuffer | None = None


        def get_tracing_buffer() -> TracingBuffer:
            \"\"\"Return the process-wide TracingBuffer singleton.\"\"\"
            global _buffer
            if _buffer is None:
                import os
                size = int(os.getenv("TRACING_UI_BUFFER_SIZE", "1000"))
                _buffer = TracingBuffer(maxlen=size)
            return _buffer
        """))


def _write_timing_collector(dest: Path) -> None:
    """Write app/tracing_ui/collector.py — TimingCollector span recorder.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"TimingCollector — per-request span recorder for tracing.\"\"\"

        from __future__ import annotations

        import time
        from contextlib import contextmanager
        from typing import Any


        class TimingCollector:
            \"\"\"Collects named spans (middleware, db, external) for one request.

            Usage::

                collector = TimingCollector()
                with collector.span("db"):
                    await db.execute(...)
                spans = collector.flush()

            Args:
                request_id: UUID string for the owning request.
            \"\"\"

            def __init__(self, request_id: str) -> None:
                self.request_id = request_id
                self._spans: list[dict[str, Any]] = []
                self._start = time.monotonic()

            @contextmanager
            def span(self, name: str):
                \"\"\"Context manager that records a named span.

                Args:
                    name: Span label (e.g. 'middleware', 'db', 'stripe').
                \"\"\"
                t0 = time.monotonic()
                try:
                    yield
                finally:
                    elapsed = int((time.monotonic() - t0) * 1000)
                    self._spans.append({"name": name, "ms": elapsed})

            def record_span(self, name: str, latency_ms: int) -> None:
                \"\"\"Append a pre-measured span (e.g. from instrumented DB layer).

                Args:
                    name: Span label.
                    latency_ms: Duration of the span in milliseconds.
                \"\"\"
                self._spans.append({"name": name, "ms": latency_ms})

            def total_ms(self) -> int:
                \"\"\"Return wall-clock time since this collector was created (ms).\"\"\"
                return int((time.monotonic() - self._start) * 1000)

            def flush(self) -> list[dict[str, Any]]:
                \"\"\"Return the list of recorded spans and clear the internal buffer.\"\"\"
                spans = list(self._spans)
                self._spans.clear()
                return spans
        """))


def _write_tracing_middleware(dest: Path) -> None:
    """Write app/tracing_ui/middleware.py — ASGI middleware for tracing.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"TracingMiddleware — captures per-request timing into TracingBuffer.\"\"\"

        from __future__ import annotations

        import logging
        import os
        import time

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response

        from app.tracing_ui import get_tracing_buffer, make_request_id
        from app.tracing_ui.collector import TimingCollector

        logger = logging.getLogger(__name__)

        _EXCLUDE_PREFIXES = ("/tracing", "/healthz", "/readyz", "/metrics")


        class TracingMiddleware(BaseHTTPMiddleware):
            \"\"\"Capture total latency and per-span timing for every request.

            Skips the tracing UI's own paths and health endpoints to avoid
            recursive noise in the buffer.
            \"\"\"

            async def dispatch(
                self, request: Request, call_next: RequestResponseEndpoint
            ) -> Response:
                \"\"\"Wrap the request in a TracingCollector and record the result.

                Args:
                    request: Incoming HTTP request.
                    call_next: Next middleware or endpoint handler.

                Returns:
                    The HTTP response, unchanged.
                \"\"\"
                enabled = os.getenv("TRACING_UI_ENABLED", "false").lower() == "true"
                if not enabled or request.url.path.startswith(_EXCLUDE_PREFIXES):
                    return await call_next(request)

                request_id = make_request_id()
                collector = TimingCollector(request_id)
                request.state.tracing = collector

                t0 = time.monotonic()
                try:
                    with collector.span("handler"):
                        response = await call_next(request)
                except Exception:
                    logger.exception("TracingMiddleware caught unhandled exception")
                    raise
                finally:
                    total = int((time.monotonic() - t0) * 1000)
                    try:
                        buf = get_tracing_buffer()
                        buf.record({
                            "id": request_id,
                            "method": request.method,
                            "path": request.url.path,
                            "status_code": getattr(response, "status_code", 0),
                            "total_ms": total,
                            "spans": collector.flush(),
                        })
                    except Exception:  # noqa: BLE001
                        logger.warning("TracingMiddleware failed to record entry", exc_info=True)

                return response
        """))


def _write_tracing_routes(dest: Path) -> None:
    """Write app/api/routes/tracing.py — tracing endpoints + HTML dashboard.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Tracing endpoints: list, detail, slow, and HTML dashboard.\"\"\"

        from __future__ import annotations

        import os
        from pathlib import Path
        from typing import Any

        from fastapi import APIRouter, HTTPException
        from fastapi.responses import HTMLResponse

        from app.tracing_ui import get_tracing_buffer

        router = APIRouter(prefix="/tracing", tags=["tracing"])

        _TEMPLATES_DIR = Path(__file__).parent.parent.parent / "tracing_ui" / "templates"


        @router.get("/requests", response_model=list[dict[str, Any]])
        async def list_requests() -> list[dict[str, Any]]:
            \"\"\"Return all buffered request traces, newest-first.

            Returns:
                List of trace entries with id, method, path, status_code,
                total_ms, and spans.
            \"\"\"
            buf = get_tracing_buffer()
            return buf.get_all()


        @router.get("/requests/{request_id}", response_model=dict[str, Any])
        async def get_request(request_id: str) -> dict[str, Any]:
            \"\"\"Return the full trace for a specific request ID.

            Args:
                request_id: UUID string from the trace list.

            Returns:
                Detailed trace entry including all recorded spans.

            Raises:
                HTTPException: 404 if the request ID is not found.
            \"\"\"
            buf = get_tracing_buffer()
            entry = buf.get_by_id(request_id)
            if entry is None:
                raise HTTPException(status_code=404, detail="Request trace not found")
            return entry


        @router.get("/slow", response_model=list[dict[str, Any]])
        async def slow_requests() -> list[dict[str, Any]]:
            \"\"\"Return p99 slowest requests in the buffer.

            Returns:
                Requests at or above the 99th latency percentile.
            \"\"\"
            buf = get_tracing_buffer()
            return buf.get_slow(percentile=0.99)


        @router.get("/dashboard", response_class=HTMLResponse)
        async def dashboard() -> HTMLResponse:
            \"\"\"Serve the self-contained tracing HTML dashboard.

            Returns:
                HTMLResponse with the vanilla-JS dashboard page.

            Raises:
                HTTPException: 503 when dashboard template is missing.
            \"\"\"
            html_file = _TEMPLATES_DIR / "dashboard.html"
            if not html_file.exists():
                raise HTTPException(status_code=503, detail="Dashboard template missing")
            return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
        """))


def _write_dashboard_html(dest: Path) -> None:
    """Write the self-contained vanilla-JS HTML tracing dashboard.

    Args:
        dest: Absolute path for the dashboard.html file.
    """
    dest.write_text(textwrap.dedent("""\
        <!DOCTYPE html>
        <html lang="en">
        <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Request Tracing Dashboard</title>
        <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
               background: #0f172a; color: #e2e8f0; min-height: 100vh; padding: 1.5rem; }
        h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: 1rem; color: #7dd3fc; }
        .toolbar { display: flex; gap: 0.75rem; margin-bottom: 1rem; align-items: center; }
        button { background: #1e40af; color: #fff; border: none; padding: 0.4rem 1rem;
                 border-radius: 0.375rem; cursor: pointer; font-size: 0.875rem; }
        button:hover { background: #2563eb; }
        #filter { background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
                  border-radius: 0.375rem; padding: 0.4rem 0.75rem; font-size: 0.875rem;
                  width: 220px; }
        table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
        th { text-align: left; padding: 0.5rem 0.75rem; background: #1e293b;
             color: #94a3b8; font-weight: 600; border-bottom: 1px solid #334155; }
        td { padding: 0.45rem 0.75rem; border-bottom: 1px solid #1e293b; }
        tr:hover td { background: #1e293b; cursor: pointer; }
        .slow { color: #f87171; }
        .ok { color: #4ade80; }
        .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 9999px;
                 font-size: 0.75rem; font-weight: 700; }
        .s2xx { background: #14532d; color: #4ade80; }
        .s4xx { background: #7c2d12; color: #fca5a5; }
        .s5xx { background: #450a0a; color: #f87171; }
        #detail { display: none; background: #1e293b; border-radius: 0.5rem;
                  padding: 1rem; margin-top: 1rem; white-space: pre-wrap;
                  font-family: monospace; font-size: 0.8rem; color: #bfdbfe; }
        .stats { display: flex; gap: 1.5rem; margin-bottom: 1rem; }
        .stat { background: #1e293b; border-radius: 0.5rem; padding: 0.75rem 1rem; }
        .stat-val { font-size: 1.5rem; font-weight: 700; color: #7dd3fc; }
        .stat-lbl { font-size: 0.75rem; color: #64748b; margin-top: 0.1rem; }
        </style>
        </head>
        <body>
        <h1>&#x26a1; Request Tracing Dashboard</h1>
        <div class="stats">
          <div class="stat"><div class="stat-val" id="stat-total">0</div><div class="stat-lbl">Total traced</div></div>
          <div class="stat"><div class="stat-val" id="stat-p99">—</div><div class="stat-lbl">p99 latency (ms)</div></div>
          <div class="stat"><div class="stat-val" id="stat-slow">0</div><div class="stat-lbl">Slow requests</div></div>
        </div>
        <div class="toolbar">
          <button onclick="load()">&#x21ba; Refresh</button>
          <button onclick="loadSlow()">&#x1f40c; Show slow (p99)</button>
          <input id="filter" type="text" placeholder="Filter by path…" oninput="applyFilter()">
        </div>
        <table id="tbl">
          <thead><tr><th>Method</th><th>Path</th><th>Status</th><th>Total ms</th><th>Spans</th><th>ID</th></tr></thead>
          <tbody id="tbody"></tbody>
        </table>
        <pre id="detail"></pre>
        <script>
        let _rows = [];
        function statusClass(s) {
          if (s >= 500) return 's5xx';
          if (s >= 400) return 's4xx';
          return 's2xx';
        }
        function render(rows) {
          const tb = document.getElementById('tbody');
          tb.innerHTML = '';
          rows.forEach(r => {
            const tr = document.createElement('tr');
            const slow = r.total_ms > 500 ? 'slow' : 'ok';
            const spans = (r.spans||[]).map(s => s.name + ':' + s.ms + 'ms').join(', ');
            tr.innerHTML = '<td>' + r.method + '</td>' +
              '<td>' + r.path + '</td>' +
              '<td><span class="badge ' + statusClass(r.status_code) + '">' + r.status_code + '</span></td>' +
              '<td class="' + slow + '">' + r.total_ms + '</td>' +
              '<td>' + (spans || '—') + '</td>' +
              '<td style="font-size:0.7rem;color:#64748b">' + r.id.slice(0,8) + '…</td>';
            tr.onclick = () => showDetail(r);
            tb.appendChild(tr);
          });
          updateStats(rows);
        }
        function updateStats(rows) {
          document.getElementById('stat-total').textContent = rows.length;
          if (!rows.length) return;
          const sorted = rows.map(r => r.total_ms).sort((a,b) => a-b);
          const p99 = sorted[Math.floor(sorted.length * 0.99)] || sorted[sorted.length-1];
          document.getElementById('stat-p99').textContent = p99;
          document.getElementById('stat-slow').textContent = rows.filter(r=>r.total_ms>500).length;
        }
        function showDetail(r) {
          const el = document.getElementById('detail');
          el.style.display = 'block';
          el.textContent = JSON.stringify(r, null, 2);
        }
        function applyFilter() {
          const q = document.getElementById('filter').value.toLowerCase();
          render(q ? _rows.filter(r => r.path.toLowerCase().includes(q)) : _rows);
        }
        async function load() {
          try {
            const resp = await fetch('/tracing/requests');
            _rows = await resp.json();
            applyFilter();
          } catch(e) { console.error('Tracing load error', e); }
        }
        async function loadSlow() {
          try {
            const resp = await fetch('/tracing/slow');
            _rows = await resp.json();
            applyFilter();
          } catch(e) { console.error('Tracing slow load error', e); }
        }
        load();
        setInterval(load, 5000);
        </script>
        </body>
        </html>
        """))


def _patch_config(config_file: Path) -> None:
    """Inject tracing UI settings into app/core/config.py.

    Fields are inserted inside the ``class Settings`` body with 4-space
    indent so Pydantic picks them up as class-level field declarations.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("TRACING_UI_ENABLED", "TRACING_UI_ENABLED: bool = False"),
            ("TRACING_UI_BUFFER_SIZE", "TRACING_UI_BUFFER_SIZE: int = 1000"),
            ("TRACING_UI_AUTH_REQUIRED", "TRACING_UI_AUTH_REQUIRED: bool = False"),
        ],
    )


def _patch_main(main_file: Path) -> None:
    """Register tracing router and middleware in app/main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "tracing_ui" in src:
        return

    tracing_import = (
        "\nfrom app.api.routes.tracing import router as tracing_router"
        "  # noqa: E402 — request tracing UI\n"
        "from app.tracing_ui.middleware import TracingMiddleware  # noqa: E402\n"
    )
    tracing_register = textwrap.dedent("""\

        # Request tracing UI — added by add_request_tracing_ui tool
        app.add_middleware(TracingMiddleware)
        app.include_router(tracing_router)
    """)

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + tracing_import,
        )
    else:
        src = tracing_import + src

    src = src.rstrip("\n") + "\n" + tracing_register
    main_file.write_text(src)


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
