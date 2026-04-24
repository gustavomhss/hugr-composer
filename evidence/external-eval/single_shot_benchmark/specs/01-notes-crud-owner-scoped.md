# notes-crud-owner-scoped

> **Status:** STUB — content authoring deferred to Gustavo pre-tag (Wave I-2 per LAUNCH.md §2.0). The runner will fail fast with `len(specs) < 10` until all 10 are filled.

## Requirements

[Gustavo: 200-word spec body. Build a notes CRUD where each user owns
their notes. Cross-owner reads MUST return 404 (not 403) to prevent
existence enumeration. Pagination uses keyset over (created_at, id).]

## Acceptance criteria

- [Gustavo: each criterion as one imperative sentence checkable by a pytest assertion]
- A POST `/notes` with no auth returns 401.
- A GET `/notes/{id}` for a note owned by another user returns 404, not 403.
- Listing returns at most page_size items per call; cursor advances stably under concurrent inserts.

## Non-requirements

- No notes sharing / collaboration features at v1.
- No full-text search.
