# RBAC with tamper-evident audit log

## Background

An internal admin tool exposes document CRUD operations. Access is
role-based:

- `reader`  — may GET documents only.
- `editor`  — may GET and PUT documents.
- `admin`   — may GET, PUT, and DELETE documents.

Every privileged operation (PUT, DELETE) MUST be recorded in a
hash-chained, tamper-evident audit log.

Identity is passed via `X-User: <username>`. The user registry is
hard-coded:

```
alice   → admin
bob     → editor
carol   → reader
mallory → (none)
```

## Requirements

1. `GET /docs/{id}` — allowed for reader / editor / admin. 404 if the
   doc does not exist.
2. `PUT /docs/{id}` — allowed for editor / admin only. Body `{"body": "<string>"}`.
   - Returns 200 with `{"id": "...", "body": "..."}`.
   - Emits an audit event with `actor`, `action: "update"`, `target`.
3. `DELETE /docs/{id}` — admin only. Emits an audit event.
4. Missing `X-User` header → 401.
5. Unknown user → 401.
6. User whose role lacks permission → 403 (NOT 401; it IS a known
   user).
7. `GET /audit` — admin only. Returns `{"events": [...]}` with every
   audit event. Each event MUST carry `actor`, `action`, `target`,
   and the `prev_hash` + `this_hash` of the chain.
8. `GET /audit/verify` — admin only. Walks the chain; returns
   `{"ok": true}` on intact, `{"ok": false, "broken_index": N}` on
   tampering.
9. `POST /audit/_test_tamper` — admin only (test hook). Body
   `{"at_index": N}` — mutates that audit entry. Returns
   `{"tampered": true}`.
10. `GET /health` → 200 `{"ok": true}`.

## Acceptance criteria

- reader PUT → 403; carol (reader) GET → 200.
- mallory (unknown) → 401 on any endpoint.
- missing X-User → 401.
- After 5 successful admin PUTs, `/audit` has 5 events and
  `/audit/verify` → ok.
- After `POST /audit/_test_tamper` at index 2, `/audit/verify` →
  `{"ok": false, "broken_index": 2}`.
- Non-admin cannot call `/audit`, `/audit/verify`, `/audit/_test_tamper`
  → 403.

## Non-requirements

- No persistence.
- No sessions; identity via header only.
- No secret; audit chain uses SHA-256.
