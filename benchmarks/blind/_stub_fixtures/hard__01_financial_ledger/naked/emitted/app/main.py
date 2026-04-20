"""Naked-like reference emission — deliberately flawed.

Intentional failure modes:
  - Uses float for money (fails Layer E static + Layer B property)
  - No real concurrency guard (fails Layer C under load)
  - In-memory `seen = set()` idempotency (fails Layer E static)
  - No tamper-evident audit chain (fails Layer D chaos)

Passes Layer A smoke in the happy path to show harness discrimination.
"""
from __future__ import annotations

import threading
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Naive state — would not survive multi-worker.
_balances: dict[str, float] = {}      # float! bug on purpose
_audit: list[dict[str, Any]] = []
seen = set()                          # naive idempotency, flagged by static scan
_lock = threading.Lock()               # present but not enough for atomic transfer


class DepositBody(BaseModel):
    amount_cents: int


class WithdrawBody(BaseModel):
    amount_cents: int


class TransferBody(BaseModel):
    source_account_id: str
    destination_account_id: str
    amount_cents: int
    idempotency_key: str


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/accounts")
def open_account() -> dict:
    aid = str(uuid.uuid4())
    _balances[aid] = 0.0
    return {"id": aid, "balance_cents": 0.0}


@app.get("/accounts/{aid}")
def get_account(aid: str) -> dict:
    if aid not in _balances:
        raise HTTPException(404, "account not found")
    # Returns a float — Layer B detects.
    return {"id": aid, "balance_cents": _balances[aid]}


@app.post("/accounts/{aid}/deposit")
def deposit(aid: str, body: DepositBody) -> dict:
    if aid not in _balances:
        raise HTTPException(404)
    # float accumulator: accumulates rounding error on tricky sequences.
    _balances[aid] = _balances[aid] + float(body.amount_cents)
    _audit.append({"op": "deposit", "account": aid, "amount": body.amount_cents})
    return {"ok": True, "balance_cents": _balances[aid]}


@app.post("/accounts/{aid}/withdraw")
def withdraw(aid: str, body: WithdrawBody) -> dict:
    if aid not in _balances:
        raise HTTPException(404)
    if _balances[aid] < body.amount_cents:
        raise HTTPException(400, "insufficient funds")
    _balances[aid] -= float(body.amount_cents)
    _audit.append({"op": "withdraw", "account": aid, "amount": body.amount_cents})
    return {"ok": True, "balance_cents": _balances[aid]}


@app.post("/transfers")
def transfer(body: TransferBody) -> dict:
    # Idempotency via in-memory set — fails under multi-worker + restart.
    if body.idempotency_key in seen:
        return {"ok": True, "replayed": True}
    seen.add(body.idempotency_key)
    src, dst = body.source_account_id, body.destination_account_id
    if src not in _balances or dst not in _balances:
        raise HTTPException(404)
    # Intentional race: lock acquired per-leg, not per-transfer.
    with _lock:
        if _balances[src] < body.amount_cents:
            raise HTTPException(400, "insufficient")
        _balances[src] -= float(body.amount_cents)
    # Gap — another thread can interleave here on a naive solution.
    with _lock:
        _balances[dst] += float(body.amount_cents)
    _audit.append({"op": "transfer", "src": src, "dst": dst,
                   "amount": body.amount_cents, "key": body.idempotency_key})
    return {"ok": True}


@app.get("/audit/verify")
def verify() -> dict:
    # Naive: always reports OK (no hash chain). Layer D exposes this.
    return {"ok": True}
