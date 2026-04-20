# Maestro session — 02-webhook-sink

Plan-level transcript mirroring the v3 best-of run that scored 100 on
`baseline/03_webhook_sink.md`.

## Requirement → kit mapping

1. **HMAC signature + timestamp window.**
   → `SignatureVerifier` primitive; rejects before body parse.
2. **Exactly-once on duplicate deliveries.**
   → `IdempotentConsumer` + `InboxDeduplicator`. Key = `(provider, event_id)`.
3. **Persist every accepted event.**
   → `AuditEvent` + a raw-body column on the inbox record.
4. **Concurrent duplicates — exactly one wins.**
   → The `IdempotentConsumer` uses a conditional insert (`INSERT … ON CONFLICT DO NOTHING`)
     so the race collapses to a single winner at the DB.

## Tool call sequence

```
1. fastapi_generate_project(name="webhook_sink")
2. fastapi_add_webhook_receiver(provider="*", signing="hmac_sha256", ts_window_s=300)
3. fastapi_add_idempotency(on="webhook_event", key="provider,event_id")
4. fastapi_add_audit_log(on="webhook_event", redact=["authorization"])
```

## Out of scope (per spec)

- Outbound webhooks, admin UI for replay, per-tenant signing keys.

## Benchmark outcome

- Scaffold completeness: 25/25
- Test suite pass:       25/25
- Primitive gate pass:   25/25
- Hand editability:      25/25
- **Total:               100**
