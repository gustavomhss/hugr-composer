"""FastAPI adapter over `LoadShedder`.

Wires an :class:`InMemoryLoadShedder` to FastAPI through an HTTP
middleware that rejects requests with 503 + ``Retry-After`` when the
current cutoff would not admit their priority class (read from the
``X-Priority`` header, defaulting to ``normal``).

Usage::

    from fastapi import FastAPI
    from core.venous._adapters.fastapi.LoadShedderAdapter import install

    app = FastAPI()
    shedder = install(app)
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from core.venous.resiliency.LoadShedder.LoadShedder import InMemoryLoadShedder


def install(app: FastAPI, *, shedder: InMemoryLoadShedder | None = None) -> InMemoryLoadShedder:
    """Install admission-control middleware on *app*; return live shedder."""
    ls = shedder or InMemoryLoadShedder()

    @app.middleware("http")
    async def _shed(request: Request, call_next):  # noqa: ANN001 — FastAPI callable
        prio = request.headers.get("X-Priority", "normal")
        if prio not in {"critical", "normal", "sheddable_plus", "sheddable"}:
            prio = "normal"
        depth = int(request.headers.get("X-Queue-Depth", "0") or 0)
        cpu = float(request.headers.get("X-Cpu-Ewma", "0") or 0.0)
        if not ls.admit(prio, depth, cpu):  # type: ignore[arg-type]
            return JSONResponse({"detail": "overloaded", "cutoff": ls.current_cutoff()}, status_code=503, headers={"Retry-After": "1"})
        return await call_next(request)

    app.state.load_shedder = ls
    return ls
