"""Naked-like billing — real dumb mistakes.

Flaws:
  - Every /bill call calls the stub (no dedup) → fails A already_charged,
    B property, C exactly-one.
  - No retry on simulated error → 500 sometimes.
  - No lock around (customer, cycle) → duplicates under concurrency.
"""
from __future__ import annotations

import secrets
import time

from fastapi import FastAPI, HTTPException

app = FastAPI()

_charges: list[dict] = []
_stub_count = 0


@app.get("/health")
def health() -> dict:
    return {"ok": True}


def _stripe_charge(amount_cents: int) -> dict:
    global _stub_count
    _stub_count += 1
    # BUG: naked doesn't retry; leaks error as 500 via exception.
    return {"stripe_charge_id": f"ch_{secrets.token_hex(8)}", "amount_cents": amount_cents}


@app.post("/bill")
def bill(body: dict):
    if not isinstance(body, dict):
        raise HTTPException(400)
    cust = body.get("customer_id")
    cyc = body.get("cycle_id")
    amt = body.get("amount_cents")
    if not cust or not cyc or not isinstance(amt, int) or amt <= 0:
        raise HTTPException(422)
    # BUG: no dedup — every call re-charges.
    time.sleep(0.001)
    result = _stripe_charge(amt)
    # BUG: drops cycle_id from stored entry → charges_list_contains_unique_pairs fails
    entry = {"customer_id": cust,
             "stripe_charge_id": result["stripe_charge_id"],
             "amount_cents": amt}
    _charges.append(entry)
    return {"status": "charged", **result}


@app.get("/charges")
def list_charges() -> dict:
    return {"charges": list(_charges)}


@app.get("/_stripe/calls")
def stub_calls() -> dict:
    return {"count": _stub_count}


@app.post("/_stripe/charge")
def stub_charge(body: dict):
    amt = body.get("amount_cents", 0)
    return _stripe_charge(amt)
