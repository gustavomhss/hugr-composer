"""Kit-like SOTA emission for the calibration health endpoint spec."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

SERVICE_NAME = "calibration-health"
SERVICE_VERSION = "1.0.0"


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/version")
def version() -> dict:
    return {"service": SERVICE_NAME, "version": SERVICE_VERSION}


@app.get("/ready")
def ready() -> dict:
    return {"ready": True}


# FastAPI already returns JSON 404s by default, but we add an explicit handler
# to guarantee {"detail": "not found"} even if middleware changes.
@app.exception_handler(404)
async def not_found_handler(request, exc):  # noqa: ARG001, ANN001
    return JSONResponse({"detail": "not found"}, status_code=404)
