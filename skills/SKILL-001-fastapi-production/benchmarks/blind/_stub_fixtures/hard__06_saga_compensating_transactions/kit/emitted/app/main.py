"""Kit-like SOTA saga orchestrator."""
from __future__ import annotations

import threading
import uuid
from typing import Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()


class Leg(BaseModel):
    code: str
    fail: bool = False


class BookingBody(BaseModel):
    user_id: str
    flight: Leg
    hotel: Leg
    car: Leg


_reservations: dict[str, list[dict]] = {"flight": [], "hotel": [], "car": []}
_bookings: dict[str, dict] = {}
_lock = threading.Lock()


def _reserve(leg_name: str, code: str, booking_id: str) -> None:
    with _lock:
        _reservations[leg_name].append(
            {"code": code, "booking_id": booking_id, "active": True}
        )


def _compensate(leg_name: str, booking_id: str) -> None:
    with _lock:
        for r in _reservations[leg_name]:
            if r["booking_id"] == booking_id and r.get("active"):
                r["active"] = False


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/bookings")
def create_booking(body: BookingBody):
    from fastapi.responses import JSONResponse
    bid = str(uuid.uuid4())
    steps = [
        ("flight", body.flight),
        ("hotel", body.hotel),
        ("car", body.car),
    ]
    completed: list[str] = []
    for name, leg in steps:
        if leg.fail:
            # Compensate every completed leg in reverse order.
            for done in reversed(completed):
                _compensate(done, bid)
            resp = {
                "booking_id": bid, "status": "compensated",
                "failed_leg": name, "compensated_legs": completed,
            }
            with _lock:
                _bookings[bid] = resp
            return JSONResponse(resp, status_code=422)
        _reserve(name, leg.code, bid)
        completed.append(name)
    resp = {"booking_id": bid, "status": "confirmed",
            "legs": {"flight": "ok", "hotel": "ok", "car": "ok"}}
    with _lock:
        _bookings[bid] = resp
    return JSONResponse(resp, status_code=201)


@app.get("/bookings/{bid}")
def get_booking(bid: str) -> dict:
    with _lock:
        b = _bookings.get(bid)
        if not b:
            raise HTTPException(404)
        return b


@app.get("/reservations")
def get_reservations() -> dict:
    with _lock:
        return {k: list(v) for k, v in _reservations.items()}
