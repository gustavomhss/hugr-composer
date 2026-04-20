# InboundVerifier

`InboundVerifier` is the abstract extension point every inbound webhook
receiver plugs into: concrete subclasses (`StripeVerifier`, `GitHubVerifier`,
internal HMAC verifiers, etc.) each carry a stable `name` class attribute
(`INBOUND_VERIFIER_INV_02`) and implement `verify(body, headers) ->
VerifiedEvent`. The contract is intentionally exception-driven — the verifier
either produces a trusted `VerifiedEvent` built from the validated payload or
raises `HTTPException`; returning `None` or swallowing the error is
prohibited (`INBOUND_VERIFIER_INV_01`), which keeps the dispatcher's error
path uniform across providers.

Error classes are standardized: 400 for signature mismatch or malformed body,
401 for a missing required auth header (`INBOUND_VERIFIER_INV_03`), so
FastAPI's default exception handler emits the correct response without each
verifier re-inventing status codes. The verify signature is pure —
implementations MUST NOT mutate the input body or headers
(`INBOUND_VERIFIER_INV_04`) — which lets the caller log or replay the exact
bytes that failed verification. Extracted from
`adapt/extend/realtime/add_webhook_receiver.py` (lines 459–484).

## Compose with:

- **Vendor-specific webhook trust** → `SignatureVerifier` + `IdempotencyStore`
  Subclass delegates to SignatureVerifier with vendor's pinned key; the verified event id feeds the idempotency store — replay AND forgery are blocked in one pass.

- **Dispatcher seam** → `MiddlewarePipeline` + `AuditEvent`
  One middleware selects the verifier by endpoint; every rejection is audited with the vendor name — forensic trails are uniform across vendors.

- **Graceful-failure envelope** → `CircuitBreaker` + `RequestGuard`
  When a vendor key rotation is mid-flight, the breaker fails fast and the guard returns 401 — no ambiguous 500s during key overlap.
