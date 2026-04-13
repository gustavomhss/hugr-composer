## Tool: `refactor_model`

### Overview parameters
- Tool name: `fastapi_refactor_model`
- Category: EVOLVE
- Complexity: High
- Dependencies: existing FastAPI project, SQLAlchemy, Alembic, AST
- Signature: `refactor_model(project_dir: str, operation: str, target: str, new_name: str, update_schemas: bool = True, update_routes: bool = True, generate_migration: bool = True) -> dict`
- Parameters:
  - `project_dir`: project root
  - `operation`: `rename_model`, `rename_field`, `change_type`, `split_model`
  - `target`: dotted path to the target, e.g., `src.models.User.email`
  - `new_name`: new name (or new type name for `change_type`)
  - `update_schemas`: auto-update Pydantic schemas that reference the target
  - `update_routes`: auto-update route handlers that reference the target
  - `generate_migration`: generate Alembic migration for the schema change

### Purpose
Safely rename a model, field, or type across the entire codebase in a single atomic operation. Updates the SQLAlchemy model, all Pydantic schemas, all route handlers, all test files, generates a backward-compatible Alembic migration (rename column + optional temporary shim), and updates the OpenAPI snapshot. Catches the "I renamed a field and broke 40 consumers" failure. Implements the safe multi-phase pattern: add new → dual-write → migrate reads → drop old. Output is a git patch that the maintainer reviews before applying, so nothing changes without explicit approval.

### Performance SLOs
- Tool execution time < 5s for 100 files
- Files modified ≤ 30 (proportional to usage)
- Files created ≥ 7 (refactor engine, AST transformer, patch writer, CI gate, tests, docs, Makefile targets)
- AST walk < 2s
- Patch generation < 500 ms
- Zero impact on unmodified files

### Key technical decisions
1. **AST-based rewrite:** `ast` module parses, rewrites, unparses — preserves comments via `libcst`
2. **Reference discovery:** walks call sites, imports, type hints, strings (f-string column names)
3. **Multi-phase migration:** `add column new → backfill → dual-read → drop old`
4. **Schema update:** Pydantic `Field(alias="old_name")` added for compatibility
5. **Route update:** request/response models updated with alias preservation
6. **Alembic generation:** `op.alter_column()` with `new_column_name=`
7. **Patch mode:** generates git patch, never writes directly without `--apply`
8. **Dry-run:** lists affected files + counts without any changes
9. **Rollback:** patch includes `--reverse` metadata for undo
10. **Type change:** supports `Integer → BigInteger`, `String(50) → String(100)`, `Enum addition`

### Key invariants
1. Refactor is ALWAYS atomic (all or nothing via patch).
2. Comments and formatting are PRESERVED via libcst.
3. Pydantic `alias` is ALWAYS added for backward compat during rename.
4. Alembic migration is ALWAYS multi-phase safe.
5. Dry-run NEVER writes anywhere.
6. Patch is ALWAYS applicable via `git apply` (validated).
7. Test files are ALWAYS updated alongside production code.

### User story themes
- 9.1 Rename field (US-01..05): SQLAlchemy column, Pydantic schema, route handler, tests, migration
- 9.2 Rename model (US-06..10): class rename, imports, FK references, relationships, test factories
- 9.3 Change type (US-11..15): widen column, add enum value, narrow (blocker), patch generation
- 9.4 Multi-phase (US-16..20): add+backfill+drop, alias compat, dual-read, rollback
- 9.5 Edge cases (US-21..25): string references, dynamic getattr, tool idempotency, cycles

### Test plan categories
- 10.1 AST rewrite (T-01..06): field, model, type, import, string, comment preservation
- 10.2 Multi-phase (T-07..12): add, backfill, dual-read, drop, rollback
- 10.3 Patch (T-13..18): generation, application, reverse, dry-run
- 10.4 CI (T-19..24): gate, validation, block on unsafe
- 10.5 Edge cases (T-25..30): cycles, dynamic access, tool idempotency

### Edge cases (15)
1. Field referenced via `getattr` → flagged in patch notes, not auto-updated
2. Field name is SQL reserved word → quoted properly
3. Rename creates collision → error with clear message
4. Model has 100 references → all updated
5. Comments between field definitions → preserved
6. Tests importing from fixtures → updated
7. Migration runs out of disk → Alembic fails safely, patch not applied
8. Same refactor applied twice → second run is a no-op
9. Rename in `__init__.py` re-export → updated
10. String column name in raw SQL → flagged, not auto-updated
11. Dry-run then apply → identical results
12. Tool re-run idempotent
13. Circular import after rename → detected, flagged
14. Multi-package monorepo → cross-package references updated
15. Rename blocked by foreign key → two-phase plan generated

### Anti-patterns
- DO NOT use regex replace (misses scope, breaks strings)
- DO NOT skip alias preservation (breaks consumers)
- DO NOT write without dry-run first
- DO NOT mix schema and data migrations in the patch
- DO NOT forget string references in raw SQL
