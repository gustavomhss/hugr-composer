# BI export service

## Requirements

- Daily job that snapshots several tables and writes them to object storage (CSV or Parquet) for analytics.
- Each export is versioned by date and is idempotent: re-running the same day's export overwrites atomically.
- Exports never block OLTP — read-only queries must run against a snapshot view, not live rows under locks.
- Export progress and last-successful timestamp are surfaced on a health endpoint.
- Failed exports retry up to 3 times with backoff before paging oncall.

## Acceptance criteria

- Running today's export twice in the same hour produces the same output bytes (idempotent).
- A read-write load generator hitting the OLTP tables during export sees no lock contention on rows being exported.
- If the third retry fails, the health endpoint reports `last_success: <yesterday>` and the alerting channel receives one page (not four).
- An operator can trigger an ad-hoc export for an older date without blocking the scheduled one.

## Non-requirements

- No incremental / CDC export — full-day snapshot is fine.
- No UI for downloading; consumers use signed URLs from object storage.
- No schema evolution migration.
- No multi-region export targets.
