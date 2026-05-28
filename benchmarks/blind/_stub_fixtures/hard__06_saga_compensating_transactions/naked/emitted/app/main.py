"""Naked-like saga — partial compensation.

Flaws:
  - Rollback only compensates the previous leg (not all of them).
    → Fails A car-fails-both-rolled-back, C concurrency no-leftovers.
  - Doesn't include "compensated_legs" in error body.
  - 500 on malformed body because uses body.get() without validation.
"""
from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException

app = FastAPI()

_reservations: dict[str, list[dict]] = {"flight": [], "hotel": [], "car": []}
_bookings: dict[str, dict] = {}


@app.get("/health")
def health() -> dict:
    return {"ok": True}


def _reserve(leg: str, code: str, bid: str) -> None:
    _reservations[leg].append({"code": code, "booking_id": bid, "active": True})


def _rollback_last(leg: str, bid: str) -> None:
    for r in _reservations[leg]:
        if r["booking_id"] == bid:
            r["active"] = False
            return


@app.post("/bookings")
def create_booking(body: dict):
    from fastapi.responses import JSONResponse
    bid = str(uuid.uuid4())
    try:
        flight = body["flight"]
        hotel = body["hotel"]
        car = body["car"]
    except (KeyError, TypeError):
        raise HTTPException(400, "bad body")

    previous = None
    for name, leg in (("flight", flight), ("hotel", hotel), ("car", car)):
        if not isinstance(leg, dict) or "fail" not in leg or "code" not in leg:
            raise HTTPException(422)
        if leg["fail"]:
            # Only compensate the IMMEDIATELY previous leg (BUG).
            if previous:
                _rollback_last(previous, bid)
            resp = {
                "booking_id": bid, "status": "compensated",
                "failed_leg": name,
                # BUG: missing compensated_legs field
            }
            _bookings[bid] = resp
            return JSONResponse(resp, status_code=422)
        _reserve(name, leg["code"], bid)
        previous = name
    # BUG: "legs" uses code not "ok" — doesn't match spec.
    resp = {"booking_id": bid, "status": "confirmed",
            "legs": {"flight": flight["code"], "hotel": hotel["code"], "car": car["code"]}}
    _bookings[bid] = resp
    return JSONResponse(resp, status_code=201)


@app.get("/bookings/{bid}")
def get_booking(bid: str) -> dict:
    b = _bookings.get(bid)
    if not b:
        raise HTTPException(404)
    return b


@app.get("/reservations")
def get_reservations() -> dict:
    return {k: list(v) for k, v in _reservations.items()}
