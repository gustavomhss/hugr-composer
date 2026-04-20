"""FastAPI adapter over `TamperEvidentAuditLog` + `AuditEvent`.

Wires an :class:`InMemoryTamperEvidentAuditLog` (backed by the reference
HMAC signer) behind a small read router that exposes append, verify-
chain, and since-seq export in ≤ 30 lines of glue.

Usage::

    from fastapi import FastAPI
    from core.venous._adapters.fastapi.AuditLogAdapter import install

    app = FastAPI()
    log = install(app, hmac_secret=b"signer-secret")
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException, Response

from core.venous.compliance.TamperEvidentAuditLog.TamperEvidentAuditLog import (
    HmacReferenceSigner,
    InMemoryTamperEvidentAuditLog,
    TamperEvidentAuditLogError,
)


def install(app: FastAPI, *, hmac_secret: bytes = b"change-me-to-a-real-kms-key-xxxx", prefix: str = "/audit-logs") -> InMemoryTamperEvidentAuditLog:
    """Attach a tamper-evident audit log + REST router to *app*; return log."""
    log = InMemoryTamperEvidentAuditLog(HmacReferenceSigner(hmac_secret))
    router = APIRouter(prefix=prefix, tags=["audit"])

    @router.post("/")
    def _append(actor: str, action: str, resource: str, outcome: str, attributes: dict | None = None) -> dict:
        try:
            entry_hash = log.append(actor=actor, action=action, resource=resource, outcome=outcome, attributes=attributes or {})
        except TamperEvidentAuditLogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"entry_hash": entry_hash}

    @router.post("/verify")
    def _verify() -> dict:
        return {"valid": log.verify_chain()}

    @router.get("/export")
    def _export(since_seq: int = 0) -> Response:
        return Response(content=log.export(since_seq), media_type="application/x-ndjson")

    app.include_router(router)
    app.state.audit_log = log
    return log
