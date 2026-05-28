"""Naked-like emission: mostly works, one subtle bug per spec requirement.

Deliberate flaws:
  - /health returns {"ok": "true"} (string) instead of boolean — fails
    Layer A test_health_returns_200_ok_true AND Layer B idempotency is
    fine (still deterministic). That alone costs ~1 test.
  - /ready endpoint missing → 404 instead of 200. Costs 1 A test.
  - /version present and correct.

Expected: passes 3/5 A + 3/3 B = 6/8 ~ 75%. In-band for calibration (75-95)
and well below kit's 100.
"""
from __future__ import annotations

from fastapi import FastAPI, Response

app = FastAPI()


@app.get("/health")
def health() -> Response:
    # Bug: returns text/plain content-type, naked agents sometimes do this
    # when manually building a Response. Trips content-type test.
    return Response(content='{"ok": true}', media_type="text/plain")


@app.get("/version")
def version() -> dict:
    # Bug: version is an integer, not a string. Trips Layer A type check.
    return {"service": "naked-service", "version": 1}


@app.get("/ready")
def ready() -> dict:
    return {"ready": True}

