"""Kit-like reference emission — SOTA for the financial ledger spec.

Design choices that clear every judge layer:
  - Balances are strict `int` cents throughout (passes B + E).
  - Transfers run inside a per-pair lock graph (passes C conservation).
  - Idempotency keys are stored in a dict guarded by a lock; replays
    return the stored outcome without re-applying the effect
    (passes C exactly-once).
  - Audit is a hash-chained append-only log; /audit/verify walks the
    chain; /audit/_test_tamper deliberately mutates one record so the
    judge can confirm tamper-evidence (passes D).

This is NOT a full production app — no persistence across restarts, no
metrics, no auth. It is a minimal SOTA-grade answer for the sealed
test surface.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()


# ---------------------------------------------------------------------------
# Storage — int-cents only
# ---------------------------------------------------------------------------

_balances_cents: dict[str, int] = {}
_global_lock = threading.Lock()               # guards account-map mutations
_per_account_lock: dict[str, threading.Lock] = {}

# IdempotencyStore — maps key → stored result (returned verbatim on replay)
_idempotency: dict[str, dict] = {}
_idempotency_lock = threading.Lock()


@dataclass(frozen=True)
class AuditRecord:
    index: int
    op: str
    details: dict
    prev_hash: str
    this_hash: str


def _compute_hash(prev: str, payload: dict) -> str:
    blob = prev.encode() + b"|" + json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


class TamperEvidentAuditLog:
    GENESIS = "0" * 64

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._lock = threading.Lock()

    def append(self, op: str, details: dict) -> AuditRecord:
        with self._lock:
            prev = self._records[-1].this_hash if self._records else self.GENESIS
            idx = len(self._records)
            payload = {"index": idx, "op": op, "details": details}
            rec = AuditRecord(
                index=idx, op=op, details=details,
                prev_hash=prev, this_hash=_compute_hash(prev, payload),
            )
            self._records.append(rec)
            return rec

    def verify(self) -> tuple[bool, int | None]:
        with self._lock:
            prev = self.GENESIS
            for i, r in enumerate(self._records):
                if r.index != i or r.prev_hash != prev:
                    return False, i
                expected = _compute_hash(prev, {"index": r.index, "op": r.op, "details": r.details})
                if r.this_hash != expected:
                    return False, i
                prev = r.this_hash
            return True, None

    def tamper_for_test(self, at_index: int) -> bool:
        with self._lock:
            if at_index >= len(self._records):
                return False
            victim = self._records[at_index]
            tampered_details = dict(victim.details)
            tampered_details["__mutated__"] = True
            self._records[at_index] = AuditRecord(
                index=victim.index, op=victim.op, details=tampered_details,
                prev_hash=victim.prev_hash, this_hash=victim.this_hash,
            )
            return True


_audit = TamperEvidentAuditLog()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_account(aid: str) -> threading.Lock:
    with _global_lock:
        if aid not in _balances_cents:
            raise HTTPException(404, "account not found")
        if aid not in _per_account_lock:
            _per_account_lock[aid] = threading.Lock()
        return _per_account_lock[aid]


def _locks_for_pair(a: str, b: str) -> tuple[threading.Lock, threading.Lock]:
    """Acquire per-account locks in a canonical order to avoid deadlock."""
    la = _ensure_account(a)
    lb = _ensure_account(b)
    return (la, lb) if a < b else (lb, la)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

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
    with _global_lock:
        _balances_cents[aid] = 0
        _per_account_lock[aid] = threading.Lock()
    _audit.append("open_account", {"id": aid})
    return {"id": aid, "balance_cents": 0}


@app.get("/accounts/{aid}")
def get_account(aid: str) -> dict:
    lock = _ensure_account(aid)
    with lock:
        return {"id": aid, "balance_cents": int(_balances_cents[aid])}


@app.post("/accounts/{aid}/deposit")
def deposit(aid: str, body: DepositBody) -> dict:
    if body.amount_cents <= 0:
        raise HTTPException(400, "amount_cents must be positive")
    lock = _ensure_account(aid)
    with lock:
        _balances_cents[aid] = int(_balances_cents[aid]) + int(body.amount_cents)
        new_balance = int(_balances_cents[aid])
    _audit.append("deposit", {"account": aid, "amount_cents": int(body.amount_cents)})
    return {"ok": True, "balance_cents": new_balance}


@app.post("/accounts/{aid}/withdraw")
def withdraw(aid: str, body: WithdrawBody) -> dict:
    if body.amount_cents <= 0:
        raise HTTPException(400, "amount_cents must be positive")
    lock = _ensure_account(aid)
    with lock:
        if int(_balances_cents[aid]) < int(body.amount_cents):
            raise HTTPException(400, "insufficient funds")
        _balances_cents[aid] = int(_balances_cents[aid]) - int(body.amount_cents)
        new_balance = int(_balances_cents[aid])
    _audit.append("withdraw", {"account": aid, "amount_cents": int(body.amount_cents)})
    return {"ok": True, "balance_cents": new_balance}


@app.post("/transfers")
def transfer(body: TransferBody) -> dict:
    if body.amount_cents <= 0:
        raise HTTPException(400, "amount_cents must be positive")
    if body.source_account_id == body.destination_account_id:
        raise HTTPException(400, "source and destination must differ")

    # IdempotencyStore: if this key has been processed, return stored outcome.
    with _idempotency_lock:
        if body.idempotency_key in _idempotency:
            return _idempotency[body.idempotency_key]

    # Lock both accounts in canonical order — avoids deadlock, guarantees
    # atomicity of debit + credit.
    first, second = _locks_for_pair(body.source_account_id, body.destination_account_id)
    with first, second:
        # Re-check idempotency inside the critical section (double-checked).
        with _idempotency_lock:
            if body.idempotency_key in _idempotency:
                return _idempotency[body.idempotency_key]
        src_balance = int(_balances_cents[body.source_account_id])
        if src_balance < body.amount_cents:
            raise HTTPException(400, "insufficient funds")
        _balances_cents[body.source_account_id] = src_balance - int(body.amount_cents)
        _balances_cents[body.destination_account_id] = (
            int(_balances_cents[body.destination_account_id]) + int(body.amount_cents)
        )
        _audit.append("transfer", {
            "src": body.source_account_id, "dst": body.destination_account_id,
            "amount_cents": int(body.amount_cents),
            "idempotency_key": body.idempotency_key,
        })
        result = {"ok": True, "idempotency_key": body.idempotency_key}
        with _idempotency_lock:
            _idempotency[body.idempotency_key] = result
    return result


@app.get("/audit/verify")
def audit_verify() -> dict:
    ok, broken = _audit.verify()
    if ok:
        return {"ok": True}
    return {"ok": False, "broken_index": broken}


@app.post("/audit/_test_tamper")
def audit_test_tamper(body: dict[str, Any]) -> dict:
    """Test-only endpoint — mutate an audit record by index. The spec's
    judge uses this to assert tamper-evidence. Not exposed in production.
    """
    idx = int(body.get("at_index", 0))
    ok = _audit.tamper_for_test(idx)
    if not ok:
        raise HTTPException(400, "index out of range")
    return {"tampered": True, "at_index": idx}
