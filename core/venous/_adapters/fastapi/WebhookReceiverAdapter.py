"""FastAPI adapter over `SignatureVerifier` + `IdempotentConsumer` + `AuditEvent`.

Wires three framework-agnostic primitives into a single inbound-webhook
endpoint in ≤ 30 lines of glue:

1. HMAC-verifies the raw body via :class:`DetachedSigner.verify_typed`
   BEFORE any other work (1 MiB body cap enforced up-front).
2. Deduplicates by ``X-Event-Id`` header through a
   :class:`BaseIdempotentConsumer` — redeliveries replay the cached
   outcome without re-running the handler body.
3. Appends a tamper-evident :class:`AuditEvent` for each delivery.

Usage::

    from fastapi import FastAPI
    from core.venous._adapters.fastapi.WebhookReceiverAdapter import install

    app = FastAPI()
    install(app, hmac_key=b"super-secret", key_id="default", path="/webhooks/in")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request

from core.venous.compliance.AuditEvent.AuditEvent import InMemoryAuditSink, build_event
from core.venous.events.IdempotentConsumer.IdempotentConsumer import BaseIdempotentConsumer
from core.venous.events.InboxDeduplicator.InboxDeduplicator import InMemoryInboxDeduplicator
from core.venous.events.TransactionalOutbox.TransactionalOutbox import InMemoryTransactionalOutbox
from core.venous.security.SignatureVerifier.SignatureVerifier import ALG_HMAC_SHA256, DetachedSigner, TrustAnchor

_MAX_BODY_BYTES = 1_048_576


def install(app: FastAPI, *, hmac_key: bytes, key_id: str = "default", path: str = "/webhooks/in") -> dict[str, Any]:
    """Wire verify → dedup → audit on *app*; return live components."""
    anchor = TrustAnchor(); anchor.register(key_id=key_id, algorithm=ALG_HMAC_SHA256, public_key=hmac_key, private_key=hmac_key)
    signer = DetachedSigner(anchor, default_msg_type="webhook")
    consumer: BaseIdempotentConsumer = _EchoAuditConsumer(inbox=InMemoryInboxDeduplicator(), outbox=InMemoryTransactionalOutbox(), audit=InMemoryAuditSink())
    router = APIRouter()

    @router.post(path)
    async def _receive(request: Request, x_signature: str = Header(...), x_event_id: str = Header(...)) -> dict:  # noqa: ANN001
        body = await request.body()
        if len(body) > _MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="payload too large")
        try:
            signer.verify_typed(body, bytes.fromhex(x_signature), key_id, msg_type="webhook")
        except Exception as exc:  # noqa: BLE001 — SignatureVerifier is the boundary
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        before = consumer.handle_calls
        consumer.handle({"id": x_event_id, "body": body})
        return {"received": True, "duplicate": consumer.handle_calls == before + 1 and consumer.duplicate_calls > 0}

    app.include_router(router)
    app.state.webhook_receiver = {"signer": signer, "consumer": consumer, "audit": consumer.audit}
    return app.state.webhook_receiver


class _EchoAuditConsumer(BaseIdempotentConsumer):
    """Subclass that emits an AuditEvent on every first-delivery effect."""

    def __init__(self, *, inbox, outbox, audit: InMemoryAuditSink) -> None:  # noqa: ANN001
        super().__init__(inbox=inbox, outbox=outbox, consumer_name="webhook_receiver")
        self.audit = audit
        self._tail = ""

    def _do_handle(self, message, enqueue):  # noqa: ANN001
        ev = build_event(event_id=str(message["id"]), actor_id="system", actor_type="webhook", action="CREATE", resource_type="webhook", resource_id=str(message["id"]), outcome="success", attributes={}, prev_hash=self._tail, occurred_at=datetime.now(timezone.utc))
        self.audit.emit(ev); self._tail = ev.event_hash
        return {"ok": True}
