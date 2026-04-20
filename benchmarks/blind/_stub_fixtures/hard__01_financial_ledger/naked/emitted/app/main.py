"""Naked-like reference emission — deliberately flawed.

Intentional failure modes (every one a real anti-pattern you'd see from
a junior/naked agent):
  - Uses float for money (fails Layer E static + Layer B integer check)
  - No lock around transfer check-then-modify: real race that breaks
    conservation under parallelism (fails Layer C conservation)
  - Time gap inside idempotency check (fails Layer C replay-100x)
  - In-memory `seen = set()` module-level global (fails Layer E static)
  - No tamper-evident audit chain (fails Layer D chaos)
  - 1% random silent dropout mimicking partial-failure handling bugs
    (fails Layer B conservation property)

Expected discrimination against SOTA kit fixture:
  naked  ≈ 30-50%   kit = 100%   margin ≥ 50 pts
"""
from __future__ import annotations

import random
import threading
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Naive state — would not survive multi-worker.
_balances: dict[str, float] = {}      # float! bug on purpose
_audit: list[dict[str, Any]] = []
seen = set()                          # naive idempotency, flagged by static scan


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
    # No lock on withdraw either — real race exposure.
    if _balances[aid] < body.amount_cents:
        raise HTTPException(400, "insufficient funds")
    _balances[aid] -= float(body.amount_cents)
    _audit.append({"op": "withdraw", "account": aid, "amount": body.amount_cents})
    return {"ok": True, "balance_cents": _balances[aid]}


@app.post("/transfers")
def transfer(body: TransferBody) -> dict:
    # Idempotency via in-memory set with a time gap — races under replay.
    if body.idempotency_key in seen:
        return {"ok": True, "replayed": True}
    time.sleep(0.002)  # widens check-then-add window → replay race
    seen.add(body.idempotency_key)
    src, dst = body.source_account_id, body.destination_account_id
    if src not in _balances or dst not in _balances:
        raise HTTPException(404)
    # NO LOCK — naive read-then-write race under parallelism.
    if _balances[src] < body.amount_cents:
        raise HTTPException(400, "insufficient")
    _balances[src] -= float(body.amount_cents)
    # 1% silent dropout — second leg vanishes (simulates swallowed exception).
    if random.random() < 0.01:
        _audit.append({"op": "transfer_dropped", "src": src,
                       "amount": body.amount_cents, "key": body.idempotency_key})
        return {"ok": True}
    _balances[dst] += float(body.amount_cents)
    _audit.append({"op": "transfer", "src": src, "dst": dst,
                   "amount": body.amount_cents, "key": body.idempotency_key})
    return {"ok": True}


@app.get("/audit/verify")
def verify() -> dict:
    # Naive: always reports OK (no hash chain). Layer D exposes this.
    return {"ok": True}
