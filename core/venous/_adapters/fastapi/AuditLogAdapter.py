"""FastAPI adapter over `TamperEvidentAuditLog` + `AuditEvent`.

Wires an :class:`InMemoryTamperEvidentAuditLog` (backed by the reference
HMAC signer) behind a small router that exposes append, verify-chain, and
since-seq export.

Every route requires an injected ``auth_dependency`` (R5-S1-F1): the
``/audit-logs`` surface is administrative — appending forged entries or
exporting the whole tamper-evident chain must never be anonymous. The
``actor`` recorded on append is derived from the authenticated principal,
NOT a client-supplied value (R5-S1-F2): a caller can only ever attribute an
audit entry to itself. The in-process application records entries by calling
``log.append(...)`` directly (no HTTP, no auth); these routes are the
admin-facing management/inspection interface.

Usage::

    from fastapi import FastAPI
    from app.api.deps import get_current_superuser
    from core.venous._adapters.fastapi.AuditLogAdapter import install

    app = FastAPI()
    log = install(app, hmac_secret=b"signer-secret", auth_dependency=get_current_superuser)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response

from core.venous.compliance.TamperEvidentAuditLog.TamperEvidentAuditLog import (
    HmacReferenceSigner,
    InMemoryTamperEvidentAuditLog,
    TamperEvidentAuditLogError,
)


def _resolve_actor(principal: object) -> str:
    """Derive a stable actor string from the authenticated principal.

    The actor is NEVER read from the request (R5-S1-F2). We prefer a human
    identifier (email/username) and fall back to the opaque id.
    """
    for attr in ("email", "username", "id"):
        value = getattr(principal, attr, None)
        if value:
            return str(value)
    return "unknown"


def install(
    app: FastAPI,
    *,
    auth_dependency: Callable[..., Any],
    hmac_secret: bytes = b"change-me-to-a-real-kms-key-xxxx",
    prefix: str = "/audit-logs",
    log: Any = None,
) -> Any:
    """Attach a tamper-evident audit log + auth-gated router to *app*; return log.

    Args:
        app: The FastAPI application.
        auth_dependency: A FastAPI dependency guarding every route (e.g. the
            app's ``get_current_superuser``). REQUIRED — there is no anonymous
            access to the audit surface.
        hmac_secret: Signing key for the tamper-evident chain (used only when
            *log* is not supplied).
        prefix: Router mount prefix.
        log: An optional pre-built ``TamperEvidentAuditLog`` implementation
            (e.g. the durable ``SqlTamperEvidentAuditLog``). When omitted, an
            in-memory reference log is created — NON-durable, lost on restart.
    """
    if log is None:
        log = InMemoryTamperEvidentAuditLog(HmacReferenceSigner(hmac_secret))
    router = APIRouter(prefix=prefix, tags=["audit"])

    @router.post("/")
    def _append(
        action: str,
        resource: str,
        outcome: str,
        attributes: dict | None = None,
        principal: object = Depends(auth_dependency),
    ) -> dict:
        actor = _resolve_actor(principal)
        try:
            entry_hash = log.append(
                actor=actor,
                action=action,
                resource=resource,
                outcome=outcome,
                attributes=attributes or {},
            )
        except TamperEvidentAuditLogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"entry_hash": entry_hash}

    @router.post("/verify")
    def _verify(principal: object = Depends(auth_dependency)) -> dict:
        return {"valid": log.verify_chain()}

    @router.get("/export")
    def _export(
        since_seq: int = 1,
        principal: object = Depends(auth_dependency),
    ) -> Response:
        # since_seq is 1-based; the store rejects < 1. Default to the valid
        # minimum so the documented bare GET /export does not 500, and map a
        # bad explicit value to 400 rather than letting it escape as 500.
        try:
            body = log.export(since_seq)
        except TamperEvidentAuditLogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(content=body, media_type="application/x-ndjson")

    app.include_router(router)
    app.state.audit_log = log
    return log
