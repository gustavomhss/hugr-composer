# Idempotent dataset export facade

## Background

The BI team requests nightly exports of datasets for their warehouse.
An export is identified by `(dataset, partition)`. The actual write
to blob storage is stubbed as an in-memory dictionary of
`export_key -> export_record`. Exports must be idempotent: retrying
the same `(dataset, partition)` MUST NOT overwrite the record unless
explicitly forced, and MUST return the existing record.

Dataset schema is fixed:

| dataset | allowed partitions     | row count |
|---------|-------------------------|-----------|
| orders  | `YYYY-MM-DD` strings    | 100        |
| users   | `YYYY-MM-DD` strings    | 50         |
| events  | `YYYY-MM-DD` strings    | 1000       |

Any other dataset → 400. A malformed partition (not `YYYY-MM-DD`) → 400.

## Requirements

1. `POST /exports` — body `{"dataset": "<string>", "partition":
   "<YYYY-MM-DD>"}`. Optional `force: true` for re-export.
   - First time for a `(dataset, partition)` → 200
     `{"status": "created", "export_id": "<uuid>",
     "rows": <int>, "bytes": <int>}`.
   - Retry without force → 200 `{"status": "already_exists",
     "export_id": "<same>", "rows": <same>, "bytes": <same>}`.
   - Retry with `force: true` → 200
     `{"status": "replaced", "export_id": "<new uuid>",
     "rows": ...}`.
   - Invalid dataset → 400, malformed partition → 400. MUST NOT
     create a record.
2. `GET /exports` — returns `{"exports": [...]}` — every export
   record.
3. `GET /exports/{dataset}/{partition}` — returns the record or 404.
4. `DELETE /exports/{dataset}/{partition}` → 204; 404 if missing.
5. Bytes size is deterministic: `bytes = rows * 64` (fake fixed-row
   size).
6. `GET /health` → 200.

## Acceptance criteria

- First /exports for (orders, 2026-04-01) → 200 `status: created`,
  rows=100, bytes=6400.
- Second call same pair → 200 `status: already_exists`, same
  export_id.
- With force → 200 `status: replaced`, different export_id.
- Invalid dataset → 400; after a failed call, `/exports` list is
  unchanged.
- Malformed partition (`2026-4-1`, `yesterday`, `""`) → 400.
- 50 concurrent /exports for the SAME pair → exactly one export_id
  persists (one created, rest already_exists).

## Non-requirements

- No real Parquet writing; bytes are counted via formula.
- No external blob storage.
- No auth.
