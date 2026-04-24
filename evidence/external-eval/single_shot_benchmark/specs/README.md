# specs/ — 10 blind specs for single_shot_benchmark

## Authoring rules

- **Each spec is ~200 words, 3-5 acceptance criteria, 1-2 non-requirements.**
- **Blind:** author after the rubric + training corpus were frozen. Codex v6 B5 flagged that scoring on specs used for rubric authorship is self-grading; these MUST be outside that corpus.
- **Domain mix:** the 10 specs SHOULD span at least 6 distinct feature archetypes (CRUD, auth, realtime, background jobs, rate-limiting, event-sourced, RBAC, stripe-style billing, RAG, analytics-export). Repeating archetypes is allowed if the spec exercises a different primitive composition.
- **Acceptance criteria writing style:** imperative, each one checkable by a pytest. Example: "a DELETE on another tenant's row returns 404, not 403."

## File naming

`NN-title-slug.md` where `NN = 01..10`.

## Corpus hash

When the 10 specs are authored, record:

```
$ find specs -name '[0-9][0-9]-*.md' -print0 | sort -z | xargs -0 shasum | shasum
```

Commit the resulting hash to `run_manifest.json.corpus_hash` so a later auditor can confirm the benchmark corpus at run time matches what's committed now.

## Wave H status

At Wave H commit: 10 STUBS authored (title + 1-line premise only). Full specs land with Gustavo's pre-tag sign-off — that authoring is ~2-3h and depends on founder voice, not mechanical harness work.

## Stub list (placeholder, pre-tag)

| # | Archetype | Placeholder title |
|---|---|---|
| 01 | CRUD + owner-scoped reads | `01-notes-crud-owner-scoped.md` |
| 02 | Webhook ingestion + idempotency | `02-webhook-idempotent-ingest.md` |
| 03 | Token-bucket rate limiting | `03-rate-limited-search.md` |
| 04 | Websocket broadcast + reconnect | `04-live-cursor-broadcast.md` |
| 05 | RBAC + audit log | `05-rbac-audit-logged.md` |
| 06 | OAuth2 + 2FA challenge | `06-auth-oauth2-2fa.md` |
| 07 | Multi-tenant admin dashboard | `07-tenant-admin-dashboard.md` |
| 08 | Billing + invoice pagination | `08-billing-invoice-page.md` |
| 09 | Event-sourced order history | `09-orders-event-sourced.md` |
| 10 | LLM agent with tool-call logging | `10-agent-tool-call-log.md` |

Each stub is not yet a full spec — see Wave-H status above.
