## Tool: `add_migration_data`

### Overview parameters
- Tool name: `fastapi_add_migration_data`
- Category: EVOLVE
- Complexity: High
- Dependencies: existing FastAPI project, Alembic, SQLAlchemy
- Signature: `add_migration_data(project_dir: str, name: str, batch_size: int = 1000, idempotent: bool = True, dry_run_default: bool = True, checkpoint_table: str = "data_migration_checkpoints") -> dict`
- Parameters:
  - `project_dir`: project root
  - `name`: human-readable migration name (e.g., `backfill_user_timezone`)
  - `batch_size`: rows processed per transaction
  - `idempotent`: must produce the same result if re-run on the same rows
  - `dry_run_default`: generated migration defaults to `--dry-run` mode
  - `checkpoint_table`: table tracking per-migration progress

### Purpose
Add infrastructure for **data migrations** (backfills, transforms, cleanups) that are distinct from schema migrations. Generates a templated data migration class with batching, checkpointing, dry-run mode, idempotency guarantees, and rollback support. Unlike Alembic schema migrations that run once and never again, data migrations must: resume after crashes, skip already-processed rows, support preview before execution, and complete in bounded batches to avoid locking large tables. Template includes logging, progress reporting, and verification queries to confirm the backfill worked.

### Performance SLOs
- Tool execution time < 2s (generation only)
- Files modified ≤ 3 (alembic/env.py, pyproject.toml, Makefile)
- Files created ≥ 9 (template module, checkpoint model, CLI, runner, tests, sample migration, docs, Makefile targets, config)
- Generated migration batch < 5s per 1000 rows (typical)
- Checkpoint write < 10 ms
- Zero impact on schema migrations

### Key technical decisions
1. **Batching:** `LIMIT + OFFSET` or cursor-based (`WHERE id > last_id`)
2. **Checkpoint table:** `(migration_name, last_processed_id, rows_processed, updated_at)`
3. **Dry-run mode:** logs what *would* change without executing writes
4. **Idempotency:** UPDATE-only on specific rows, or INSERT ... ON CONFLICT UPDATE
5. **Progress reporting:** stdout table every 100 batches + structured log events
6. **Transaction scope:** one transaction per batch (not per migration)
7. **Rollback:** each data migration must define an `undo()` method (may raise NotImplemented)
8. **CLI:** `python -m data_migrate run backfill_user_timezone --limit=10000`
9. **Verification:** pre-run count + post-run count + random sample assertion
10. **Separation:** data migrations live in `data_migrations/` directory, NOT `alembic/versions/`

### Key invariants
1. Dry-run mode NEVER writes to the database.
2. Checkpoints are ALWAYS written per batch, even on interrupt (via try/finally).
3. Batches are ALWAYS bounded (no "SELECT *" without limit).
4. Idempotent migrations are ALWAYS safe to re-run.
5. Data migrations NEVER mixed with schema migrations in `alembic/versions/`.
6. Progress logs ALWAYS include batch number, rows processed, elapsed time.
7. Rollback is DOCUMENTED even when not implemented (`NotImplementedError` with reason).

### User story themes
- 9.1 Basic migration (US-01..05): template generation, backfill, checkpoint, batch, verify
- 9.2 Dry-run (US-06..10): preview, no writes, log output, report, confirm before execute
- 9.3 Resume (US-11..15): crash mid-run, resume from checkpoint, skip done, finish
- 9.4 Idempotency (US-16..20): re-run safe, partial re-run, full re-run, upsert
- 9.5 Edge cases (US-21..25): zero rows, huge table, rollback, tool idempotency

### Test plan categories
- 10.1 Batching (T-01..06): cursor, offset, boundary, last batch, empty
- 10.2 Checkpoint (T-07..12): write, resume, crash, atomicity
- 10.3 Dry-run (T-13..18): no writes, log, count, exit code
- 10.4 Idempotency (T-19..24): re-run, upsert, partial, full
- 10.5 Edge cases (T-25..30): rollback, huge table, tool idempotency

### Edge cases (15)
1. Table with 0 rows → migration completes, logs "Nothing to process"
2. Table with 10M rows → batched, resumable, completes
3. Crash at batch 50/100 → resume from batch 51
4. Checkpoint corrupted → error with `--reset-checkpoint` hint
5. Same migration run twice → idempotent, only new rows processed
6. `--dry-run` executed → no writes, report printed
7. Rollback with `undo()` not implemented → clear error
8. Batch size 1 → still correct, slower
9. Batch size > table size → one batch, completes
10. Migration renamed → new checkpoint row, old one preserved
11. Column dropped after migration started → error with clear message
12. Concurrent writers modifying rows → lock hint (SELECT FOR UPDATE)
13. Tool re-run (generator) idempotent
14. Dry-run then real run → checkpoint from dry-run ignored
15. Migration with data_migrations/ missing → created automatically

### Anti-patterns
- DO NOT mix data and schema migrations
- DO NOT run without batching (locks large tables)
- DO NOT skip checkpointing (re-runs from scratch)
- DO NOT assume idempotency (verify with upsert or explicit check)
- DO NOT forget dry-run (safety net)
